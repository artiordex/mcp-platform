import { promises as fs } from 'node:fs';
import http from 'node:http';
import path from 'node:path';

const PORT = Number(process.env.MCP_HTTP_PORT ?? process.env.PORT ?? 8120);
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
  if (relativeToRoot.startsWith('..') || path.isAbsolute(relativeToRoot)) {
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

// Tool definitions
const TOOLS = [
  {
    name: 'workspace_status',
    description: 'Return basic information about the configured workspace root.',
    parameters: {},
  },
  {
    name: 'list_project_files',
    description: 'List visible files under a workspace-relative directory.',
    parameters: {
      path: { type: 'string', default: '.', description: 'Workspace-relative directory' },
      maxDepth: { type: 'number', default: 2, description: 'Maximum directory depth' },
    },
  },
  {
    name: 'read_project_file',
    description: 'Read a visible UTF-8 text file using a workspace-relative path (max 256KB).',
    parameters: {
      path: { type: 'string', required: true, description: 'Workspace-relative file path' },
    },
  },
];

async function handleToolCall(name: string, args: Record<string, any>): Promise<any> {
  if (name === 'workspace_status') {
    const entries = await fs.readdir(workspaceRoot, { withFileTypes: true });
    const visibleEntries = entries
      .filter((entry) => !entry.name.startsWith('.') && !ignoredDirectories.has(entry.name))
      .sort((left, right) => left.name.localeCompare(right.name))
      .map((entry) => `${entry.isDirectory() ? 'dir' : 'file'}: ${entry.name}`);

    return {
      workspace_root: workspaceRoot,
      total_entries: visibleEntries.length,
      entries: visibleEntries,
    };
  }

  if (name === 'list_project_files') {
    const relPath = args.path || '.';
    const depth = Number(args.maxDepth ?? 2);
    const { absolutePath: directory } = await resolveAccessiblePath(relPath);
    const realRoot = await fs.realpath(workspaceRoot);
    const stats = await fs.stat(directory);
    if (!stats.isDirectory()) {
      throw new Error('Path is not a directory');
    }
    const files = await collectFiles(directory, realRoot, depth);
    return { count: files.length, files };
  }

  if (name === 'read_project_file') {
    const relPath = args.path;
    if (!relPath) throw new Error('Path parameter is required');
    const { absolutePath: filePath, relativePath: visiblePath } = await resolveAccessiblePath(relPath);
    const stats = await fs.stat(filePath);
    if (!stats.isFile()) throw new Error('Path is not a file');
    const contents = await fs.readFile(filePath);
    if (contents.includes(0)) throw new Error('Binary files are not supported');
    const text = contents.subarray(0, maxReadBytes).toString('utf8');
    return {
      file: visiblePath,
      size_bytes: stats.size,
      truncated: stats.size > maxReadBytes,
      content: text,
    };
  }

  throw new Error(`Unknown tool: ${name}`);
}

const server = http.createServer(async (req, res) => {
  // CORS Headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
  const pathname = url.pathname;

  if (req.method === 'GET' && (pathname === '/health' || pathname === '/healthz')) {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', service: 'mcp-platform', port: PORT, uptime: process.uptime() }));
    return;
  }

  if (req.method === 'GET' && (pathname === '/' || pathname === '/mcp' || pathname === '/mcp/tools' || pathname === '/tools')) {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      service: 'mcp-platform-http-gateway',
      version: '0.1.0',
      workspace_root: workspaceRoot,
      tools: TOOLS,
    }, null, 2));
    return;
  }

  if (req.method === 'POST' && (pathname === '/call' || pathname === '/mcp/call')) {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', async () => {
      try {
        const payload = JSON.parse(body || '{}');
        const toolName = payload.tool || payload.name;
        const toolArgs = payload.arguments || payload.args || {};
        if (!toolName) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Missing "tool" or "name" in JSON body' }));
          return;
        }

        const result = await handleToolCall(toolName, toolArgs);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: true, tool: toolName, result }));
      } catch (err: any) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: err.message || String(err) }));
      }
    });
    return;
  }

  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not Found', path: pathname }));
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[mcp-platform] HTTP Gateway listening on http://0.0.0.0:${PORT}`);
});
