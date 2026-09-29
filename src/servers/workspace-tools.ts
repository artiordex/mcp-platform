import { promises as fs } from 'node:fs';
import path from 'node:path';

import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import * as z from 'zod/v4';

const workspaceRoot = path.resolve(
  process.env.MCP_WORKSPACE_ROOT ?? process.cwd(),
);
const maxReadBytes = 256 * 1024;
const ignoredDirectories = new Set([
  '.git',
  '.venv',
  'node_modules',
  '__pycache__',
  '.cache',
]);

function resolveWorkspacePath(relativePath: string): string {
  if (relativePath.includes('\0')) {
    throw new Error('The path contains a null byte.');
  }

  const resolved = path.resolve(workspaceRoot, relativePath);
  const relativeToRoot = path.relative(workspaceRoot, resolved);
  if (
    relativeToRoot.startsWith('..') ||
    path.isAbsolute(relativeToRoot)
  ) {
    throw new Error('The requested path is outside the workspace.');
  }

  return resolved;
}

function assertVisiblePath(relativePath: string): void {
  const segments = relativePath.split(path.sep).filter(Boolean);
  if (segments.some((segment) => segment.startsWith('.') || ignoredDirectories.has(segment))) {
    throw new Error('Hidden files and dependency directories are not accessible.');
  }
}

async function resolveAccessiblePath(
  relativePath: string,
): Promise<{ absolutePath: string; relativePath: string }> {
  const requestedPath = resolveWorkspacePath(relativePath);
  const requestedRelativePath = path.relative(workspaceRoot, requestedPath);
  assertVisiblePath(requestedRelativePath);

  const [realWorkspaceRoot, realPath] = await Promise.all([
    fs.realpath(workspaceRoot),
    fs.realpath(requestedPath),
  ]);
  const realRelativePath = path.relative(realWorkspaceRoot, realPath);
  if (realRelativePath.startsWith('..') || path.isAbsolute(realRelativePath)) {
    throw new Error('The requested path resolves outside the workspace.');
  }
  assertVisiblePath(realRelativePath);

  return { absolutePath: realPath, relativePath: realRelativePath };
}

async function collectFiles(
  directory: string,
  realWorkspaceRoot: string,
  maxDepth: number,
  currentDepth = 0,
): Promise<string[]> {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const files: string[] = [];

  for (const entry of entries.sort((left, right) =>
    left.name.localeCompare(right.name),
  )) {
    if (entry.name.startsWith('.') || ignoredDirectories.has(entry.name)) {
      continue;
    }

    const entryPath = path.join(directory, entry.name);
    if (entry.isFile()) {
      files.push(path.relative(realWorkspaceRoot, entryPath));
      continue;
    }

    if (entry.isDirectory() && currentDepth < maxDepth) {
      files.push(
        ...(await collectFiles(entryPath, realWorkspaceRoot, maxDepth, currentDepth + 1)),
      );
    }
  }

  return files;
}

function createServer(): McpServer {
  const server = new McpServer({
    name: 'workspace-tools',
    version: '0.1.0',
  });

  server.registerTool(
    'workspace_status',
    {
      description:
        'Return basic information about the configured workspace root. This tool is read-only.',
      inputSchema: z.object({}),
    },
    async () => {
      const entries = await fs.readdir(workspaceRoot, { withFileTypes: true });
      const visibleEntries = entries
        .filter(
          (entry) =>
            !entry.name.startsWith('.') &&
            !ignoredDirectories.has(entry.name),
        )
        .sort((left, right) => left.name.localeCompare(right.name))
        .map((entry) => `${entry.isDirectory() ? 'dir ' : 'file'} ${entry.name}`);

      return {
        content: [
          {
            type: 'text',
            text: [
              `workspace_root: ${workspaceRoot}`,
              `entries: ${visibleEntries.length}`,
              ...visibleEntries,
            ].join('\n'),
          },
        ],
      };
    },
  );

  server.registerTool(
    'list_project_files',
    {
      description:
        'List visible files under a workspace-relative directory. The tool is read-only and skips hidden, dependency, and virtual-environment directories.',
      inputSchema: z.object({
        path: z.string().default('.').describe('Workspace-relative directory'),
        maxDepth: z
          .number()
          .int()
          .min(0)
          .max(4)
          .default(2)
          .describe('Maximum directory depth to traverse'),
      }),
    },
    async ({ path: relativePath, maxDepth }) => {
      const { absolutePath: directory } = await resolveAccessiblePath(relativePath);
      const realWorkspaceRoot = await fs.realpath(workspaceRoot);
      const stats = await fs.stat(directory);
      if (!stats.isDirectory()) {
        return {
          content: [{ type: 'text', text: 'The requested path is not a directory.' }],
          isError: true,
        };
      }

      const files = await collectFiles(directory, realWorkspaceRoot, maxDepth);
      return {
        content: [
          {
            type: 'text',
            text: files.length > 0 ? files.join('\n') : '(no visible files)',
          },
        ],
      };
    },
  );

  server.registerTool(
    'read_project_file',
    {
      description:
        'Read a visible UTF-8 text file using a workspace-relative path. Hidden files, dependency directories, and paths that resolve outside the workspace are blocked. Reads are limited to 256 KiB.',
      inputSchema: z.object({
        path: z.string().min(1).describe('Workspace-relative file path'),
      }),
    },
    async ({ path: relativePath }) => {
      const { absolutePath: filePath, relativePath: visibleRelativePath } =
        await resolveAccessiblePath(relativePath);
      const stats = await fs.stat(filePath);
      if (!stats.isFile()) {
        return {
          content: [{ type: 'text', text: 'The requested path is not a file.' }],
          isError: true,
        };
      }

      const contents = await fs.readFile(filePath);
      if (contents.includes(0)) {
        return {
          content: [{ type: 'text', text: 'Binary files are not supported.' }],
          isError: true,
        };
      }

      const truncated = contents.length > maxReadBytes;
      const text = contents.subarray(0, maxReadBytes).toString('utf8');
      return {
        content: [
          {
            type: 'text',
            text: [
              `# ${visibleRelativePath}`,
              truncated ? '(truncated at 256 KiB)' : '',
              '',
              text,
            ].join('\n'),
          },
        ],
      };
    },
  );

  return server;
}

void serveStdio(createServer);
console.error('workspace-tools MCP server running on stdio');
