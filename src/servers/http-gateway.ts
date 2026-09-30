/**
 * 파일명: http-gateway.ts
 * 경로: src/servers/http-gateway.ts
 * 목적: 사내 웹 포털(8080/mcp) 및 외부 HTTP 클라이언트 연동용 REST/JSON 게이트웨이를 제공함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

import { execFile } from 'node:child_process';
import { promises as fs } from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../..',
);

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

/**
 * 상대경로를 워크스페이스 절대경로로 변환하고 상위 경로 탈출을 차단함
 */
function resolveWorkspacePath(relativePath: string): string {
  if (relativePath.includes('\0')) {
    throw new Error('경로에 널 바이트가 포함됨');
  }

  const resolved = path.resolve(workspaceRoot, relativePath);
  const relativeToRoot = path.relative(workspaceRoot, resolved);
  if (relativeToRoot.startsWith('..') || path.isAbsolute(relativeToRoot)) {
    throw new Error('요청한 경로가 워크스페이스 범위를 벗어남');
  }

  return resolved;
}

/**
 * 숨김 및 의존성 디렉터리 접근 여부를 검증함
 */
function assertVisiblePath(relativePath: string): void {
  const segments = relativePath.split(path.sep).filter(Boolean);
  if (segments.some((segment) => segment.startsWith('.') || ignoredDirectories.has(segment))) {
    throw new Error('숨김 파일 및 의존성 디렉터리는 접근할 수 없음');
  }
}

/**
 * 실제 물리 경로가 워크스페이스 내부인지 검증함
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
 * 디렉터리를 재귀 탐색하여 가시 파일 목록을 수집함
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

// HTTP 게이트웨이 노출 도구 목록 정의
const TOOLS = [
  {
    name: 'workspace_status',
    description: '설정된 워크스페이스 루트의 기본 정보를 반환함 (읽기 전용임)',
    parameters: {},
  },
  {
    name: 'list_project_files',
    description: '워크스페이스 상대 디렉터리의 가시 파일 목록을 반환함 (읽기 전용임)',
    parameters: {
      path: { type: 'string', default: '.', description: '워크스페이스 기준 상대 디렉터리 경로임' },
      maxDepth: { type: 'number', default: 2, description: '최대 탐색 깊이임' },
    },
  },
  {
    name: 'read_project_file',
    description: '워크스페이스 상대경로의 텍스트 파일 내용을 읽음 (최대 256KB 제한함)',
    parameters: {
      path: { type: 'string', required: true, description: '워크스페이스 기준 상대 파일 경로임' },
    },
  },
  {
    name: 'grep_workspace_files',
    description: '워크스페이스 내 텍스트 파일에서 문자열 또는 정규표현식 일치 항목을 검색함',
    parameters: {
      pattern: { type: 'string', required: true, description: '검색할 정규표현식 또는 문자열임' },
      path: { type: 'string', default: '.', description: '검색을 시작할 상대 경로임' },
      maxMatches: { type: 'number', default: 30, description: '최대 반환 일치 건수임' },
    },
  },
  {
    name: 'workspace_project_summary',
    description: '워크스페이스 내 가시 파일들의 확장자별 분포 및 요약 통계를 산출함',
    parameters: {
      path: { type: 'string', default: '.', description: '분석할 상대 디렉터리 경로임' },
    },
  },
];

/**
 * 도구 호출 요청을 처리하고 결과를 반환함
 */
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
      throw new Error('요청한 경로가 디렉터리가 아님');
    }
    const files = await collectFiles(directory, realRoot, depth);
    return { count: files.length, files };
  }

  if (name === 'read_project_file') {
    const relPath = args.path;
    if (!relPath) throw new Error('path 매개변수가 필수임');
    const { absolutePath: filePath, relativePath: visiblePath } = await resolveAccessiblePath(relPath);
    const stats = await fs.stat(filePath);
    if (!stats.isFile()) throw new Error('요청한 경로가 일반 파일이 아님');
    const contents = await fs.readFile(filePath);
    if (contents.includes(0)) throw new Error('바이너리 파일은 읽을 수 없음');
    const text = contents.subarray(0, maxReadBytes).toString('utf8');
    return {
      file: visiblePath,
      size_bytes: stats.size,
      truncated: stats.size > maxReadBytes,
      content: text,
    };
  }

  if (name === 'grep_workspace_files') {
    const pattern = String(args.pattern || '');
    if (!pattern) throw new Error('pattern 매개변수가 필수임');
    const relPath = args.path || '.';
    const maxMatches = Number(args.maxMatches ?? 30);
    const { absolutePath: directory } = await resolveAccessiblePath(relPath);
    const realRoot = await fs.realpath(workspaceRoot);
    const files = await collectFiles(directory, realRoot, 3);

    const regex = new RegExp(pattern, 'i');
    const matches: string[] = [];
    for (const file of files) {
      if (matches.length >= maxMatches) break;
      const fullPath = path.join(realRoot, file);
      try {
        const content = await fs.readFile(fullPath);
        if (content.includes(0)) continue;
        const lines = content.toString('utf8').split('\n');
        for (let i = 0; i < lines.length; i++) {
          if (regex.test(lines[i])) {
            matches.push(`${file}:${i + 1}: ${lines[i].trim()}`);
            if (matches.length >= maxMatches) break;
          }
        }
      } catch {
        // 무시
      }
    }
    return { count: matches.length, matches };
  }

  if (name === 'workspace_project_summary') {
    const relPath = args.path || '.';
    const { absolutePath: directory } = await resolveAccessiblePath(relPath);
    const realRoot = await fs.realpath(workspaceRoot);
    const files = await collectFiles(directory, realRoot, 4);

    const extCount: Record<string, number> = {};
    for (const file of files) {
      const ext = path.extname(file) || '(확장자 없음)';
      extCount[ext] = (extCount[ext] ?? 0) + 1;
    }
    return {
      workspace_path: relPath,
      total_files: files.length,
      extensions: extCount,
    };
  }

  throw new Error(`알 수 없는 도구명임: ${name}`);
}

const server = http.createServer(async (req, res) => {
  // CORS 헤더 설정
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

  if (req.method === 'GET' && pathname === '/servers') {
    const cliScript = path.resolve(projectRoot, 'scripts/mcp-cli.sh');
    try {
      const { stdout } = await execFileAsync(cliScript, ['servers']);
      const servers = JSON.parse(stdout);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, count: servers.length, servers }, null, 2));
    } catch (err: any) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: false, error: err.message || String(err) }));
    }
    return;
  }

  if (req.method === 'GET' && pathname === '/cache/stats') {
    const cliScript = path.resolve(projectRoot, 'scripts/mcp-cli.sh');
    try {
      const { stdout } = await execFileAsync(cliScript, ['cache', 'stats']);
      const stats = JSON.parse(stdout);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, stats }, null, 2));
    } catch (err: any) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: false, error: err.message || String(err) }));
    }
    return;
  }

  if (req.method === 'POST' && pathname === '/cache/clear') {
    const cliScript = path.resolve(projectRoot, 'scripts/mcp-cli.sh');
    try {
      const { stdout } = await execFileAsync(cliScript, ['cache', 'clear']);
      const result = JSON.parse(stdout);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, result }, null, 2));
    } catch (err: any) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: false, error: err.message || String(err) }));
    }
    return;
  }

  if (req.method === 'GET' && pathname === '/doctor') {
    const doctorScript = path.resolve(projectRoot, 'scripts/doctor.sh');
    try {
      const { stdout } = await execFileAsync(doctorScript, []);
      res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(stdout);
    } catch (err: any) {
      res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(err.stdout || err.message || String(err));
    }
    return;
  }

  if (req.method === 'GET' && pathname === '/openapi.json') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      openapi: '3.0.0',
      info: { title: 'MCP Platform HTTP Gateway', version: '0.1.0' },
      paths: {
        '/mcp/tools': { get: { summary: '등록 도구 목록 조회', responses: { '200': { description: '성공' } } } },
        '/call': {
          post: {
            summary: '도구 호출 실행',
            requestBody: {
              content: {
                'application/json': {
                  schema: {
                    type: 'object',
                    required: ['tool'],
                    properties: { tool: { type: 'string' }, arguments: { type: 'object' } },
                  },
                },
              },
            },
            responses: { '200': { description: '실행 성공' } },
          },
        },
      },
    }, null, 2));
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

  if (req.method === 'GET' && (pathname === '/mcp/events' || pathname === '/events')) {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    });
    res.write(`data: ${JSON.stringify({ event: 'connected', service: 'mcp-platform-http-gateway', timestamp: new Date().toISOString() })}\n\n`);

    const intervalId = setInterval(() => {
      res.write(`: ping ${Date.now()}\n\n`);
    }, 15000);

    req.on('close', () => {
      clearInterval(intervalId);
    });
    return;
  }

  if (req.method === 'POST' && (pathname === '/call' || pathname === '/mcp/call' || pathname === '/mcp')) {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', async () => {
      try {
        const payload = JSON.parse(body || '{}');

        // JSON-RPC 2.0 지원 호환성 처리
        let toolName = payload.tool || payload.name;
        let toolArgs = payload.arguments || payload.args || {};
        let requestId = payload.id;

        if (payload.method === 'tools/call' && payload.params) {
          toolName = payload.params.name;
          toolArgs = payload.params.arguments || {};
        }

        if (!toolName) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({
            jsonrpc: requestId ? '2.0' : undefined,
            id: requestId,
            error: { code: -32600, message: '요청 본문에 tool 또는 name 항목이 누락됨' },
          }));
          return;
        }

        const result = await handleToolCall(toolName, toolArgs);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        if (requestId !== undefined) {
          res.end(JSON.stringify({
            jsonrpc: '2.0',
            id: requestId,
            result: { content: [{ type: 'text', text: typeof result === 'string' ? result : JSON.stringify(result) }] },
          }));
        } else {
          res.end(JSON.stringify({ success: true, tool: toolName, result }));
        }
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
  console.log(`[mcp-platform] HTTP 게이트웨이가 http://0.0.0.0:${PORT} 에서 대기 중임`);
});
