/**
 * 파일명: workspace-tools.ts
 * 경로: src/servers/workspace-tools.ts
 * 목적: 로컬 워크스페이스 내 프로젝트 파일 구조 탐색 및 안전한 읽기 전용 도구를 제공함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

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

/**
 * 상대경로를 워크스페이스 절대경로로 해석하고 상위 탈출을 차단함
 */
function resolveWorkspacePath(relativePath: string): string {
  if (relativePath.includes('\0')) {
    throw new Error('경로에 널 바이트가 포함됨');
  }

  const resolved = path.resolve(workspaceRoot, relativePath);
  const relativeToRoot = path.relative(workspaceRoot, resolved);
  if (
    relativeToRoot.startsWith('..') ||
    path.isAbsolute(relativeToRoot)
  ) {
    throw new Error('요청한 경로가 워크스페이스 범위를 벗어남');
  }

  return resolved;
}

/**
 * 숨김 파일 및 의존성 디렉터리 접근 여부를 검증함
 */
function assertVisiblePath(relativePath: string): void {
  const segments = relativePath.split(path.sep).filter(Boolean);
  if (segments.some((segment) => segment.startsWith('.') || ignoredDirectories.has(segment))) {
    throw new Error('숨김 파일 및 의존성 디렉터리는 접근할 수 없음');
  }
}

/**
 * 심볼릭 링크를 해제하고 실제 워크스페이스 내부의 안전한 경로인지 검증함
 */
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
    throw new Error('해석된 실제 경로가 워크스페이스 범위를 벗어남');
  }
  assertVisiblePath(realRelativePath);

  return { absolutePath: realPath, relativePath: realRelativePath };
}

/**
 * 디렉터리를 재귀 탐색하여 숨김 제외 가시 파일 목록을 수집함
 */
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

/**
 * 워크스페이스 도구 MCP 서버 인스턴스를 생성함
 */
function createServer(): McpServer {
  const server = new McpServer({
    name: 'workspace-tools',
    version: '0.1.0',
  });

  server.registerTool(
    'workspace_status',
    {
      description:
        '설정된 워크스페이스 루트의 기본 상태와 최상위 항목 목록을 반환함 (읽기 전용임)',
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
        '지정한 워크스페이스 상대 디렉터리의 가시 파일 목록을 반환함 (읽기 전용이며 숨김 폴더 및 의존성 제외함)',
      inputSchema: z.object({
        path: z.string().default('.').describe('워크스페이스 기준 상대 디렉터리 경로임'),
        maxDepth: z
          .number()
          .int()
          .min(0)
          .max(4)
          .default(2)
          .describe('탐색할 최대 하위 디렉터리 깊이임'),
      }),
    },
    async ({ path: relativePath, maxDepth }) => {
      const { absolutePath: directory } = await resolveAccessiblePath(relativePath);
      const realWorkspaceRoot = await fs.realpath(workspaceRoot);
      const stats = await fs.stat(directory);
      if (!stats.isDirectory()) {
        return {
          content: [{ type: 'text', text: '요청한 경로가 디렉터리가 아님' }],
          isError: true,
        };
      }

      const files = await collectFiles(directory, realWorkspaceRoot, maxDepth);
      return {
        content: [
          {
            type: 'text',
            text: files.length > 0 ? files.join('\n') : '(표시 가능한 파일 없음)',
          },
        ],
      };
    },
  );

  server.registerTool(
    'read_project_file',
    {
      description:
        '워크스페이스 상대경로를 이용해 UTF-8 텍스트 파일 내용을 읽어옴 (최대 256 KiB 제한함)',
      inputSchema: z.object({
        path: z.string().min(1).describe('워크스페이스 기준 상대 파일 경로임'),
      }),
    },
    async ({ path: relativePath }) => {
      const { absolutePath: filePath, relativePath: visibleRelativePath } =
        await resolveAccessiblePath(relativePath);
      const stats = await fs.stat(filePath);
      if (!stats.isFile()) {
        return {
          content: [{ type: 'text', text: '요청한 경로가 일반 파일이 아님' }],
          isError: true,
        };
      }

      const contents = await fs.readFile(filePath);
      if (contents.includes(0)) {
        return {
          content: [{ type: 'text', text: '바이너리 파일은 읽을 수 없음' }],
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
              truncated ? '(256 KiB 초과로 축약됨)' : '',
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
