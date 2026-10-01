/**
 * 파일명: http-gateway.ts
 * 경로: src/servers/http-gateway.ts
 * 목적: 표준 MCP Streamable HTTP 전송(/mcp) 및 사내 포털 연동용 REST API(/api/*)를 제공함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

import { execFile } from 'node:child_process';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { promises as fs } from 'node:fs';
import http from 'node:http';
import { isIP } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

import {
  WebStandardStreamableHTTPServerTransport,
  localhostAllowedHostnames,
  localhostAllowedOrigins,
  validateHostHeader,
  validateOriginHeader,
} from '@modelcontextprotocol/server';
import * as z from 'zod/v4';

import type { ChildMcpClient } from '../clients/child-mcp-client.js';
import { createGateway, type GatewayToolSummary } from './mcp-gateway.js';

const execFileAsync = promisify(execFile);
const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../..',
);

function readIntegerSetting(
  name: string,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const raw = process.env[name];
  if (raw === undefined) return fallback;
  if (!/^\d+$/.test(raw)) {
    throw new Error(`${name} 값은 ${minimum}에서 ${maximum} 사이의 정수여야 함`);
  }
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} 값은 ${minimum}에서 ${maximum} 사이의 정수여야 함`);
  }
  return value;
}

// 1. 네트워크 및 보안 기본 설정
const defaultPort =
  process.env.PORT === undefined ? 8120 : readIntegerSetting('PORT', 8120, 0, 65535);
const PORT = readIntegerSetting('MCP_HTTP_PORT', defaultPort, 0, 65535);
const HOST = process.env.MCP_HTTP_HOST ?? '127.0.0.1';
const bearerToken = process.env.MCP_HTTP_BEARER_TOKEN;
const adminToken = process.env.MCP_ADMIN_TOKEN ?? bearerToken;
const enableWorkspaceHttp = process.env.MCP_ENABLE_WORKSPACE_HTTP === 'true';
const RATE_LIMIT_PER_SEC = readIntegerSetting('MCP_HTTP_RATE_LIMIT', 120, 1, 100_000);

const MAX_BODY_BYTES = 1024 * 1024; // 1 MB
const REQUEST_TIMEOUT_MS = 30_000; // 요청 헤더와 본문 수신 제한

/**
 * IP/호스트명이 루프백 주소인지 판별함
 */
function isLoopbackAddress(host: string): boolean {
  const normalized = host.replace(/^\[|\]$/g, '').toLowerCase();
  if (normalized === 'localhost') return true;
  const version = isIP(normalized);
  if (version === 4) return normalized.split('.')[0] === '127';
  return version === 6 && normalized === '::1';
}

// 비루프백 주소 바인딩 시 인증 토큰 강제 검증
if (!isLoopbackAddress(HOST) && !bearerToken) {
  console.error(
    `[mcp-platform] 보안 오류: 비루프백 주소(${HOST})로 바인딩 시 MCP_HTTP_BEARER_TOKEN 환경변수가 반드시 설정되어야 함`,
  );
  process.exit(1);
}
if (!HOST.trim()) {
  throw new Error('MCP_HTTP_HOST 값이 비어 있음');
}

// Host 및 Origin 허용 목록 구성
const customAllowedHosts = process.env.MCP_ALLOWED_HOSTS?.split(',')
  .map((h) => h.trim())
  .filter(Boolean);
const allowedHostnames =
  customAllowedHosts && customAllowedHosts.length > 0
    ? customAllowedHosts
    : localhostAllowedHostnames();

const customAllowedOrigins = process.env.MCP_ALLOWED_ORIGINS?.split(',')
  .map((o) => o.trim())
  .filter(Boolean);
const allowedOriginHostnames =
  customAllowedOrigins && customAllowedOrigins.length > 0
    ? customAllowedOrigins
    : localhostAllowedOrigins();

// 2. 워크스페이스 샌드박스 설정
const workspaceRoot = path.resolve(
  process.env.MCP_WORKSPACE_ROOT ?? process.cwd(),
);
const maxReadBytes = 256 * 1024;
const maxGrepFileBytes = 1024 * 1024;
const maxGrepTotalBytes = 16 * 1024 * 1024;
const maxGrepFiles = 100;
const maxGrepPatternChars = 256;
const maxGrepResultChars = 64 * 1024;
const maxGrepLineChars = 500;
const maxListedFiles = 2_000;
const maxSummaryFiles = 5_000;
const maxDirectoryEntries = 20_000;
const maxVisibleRootEntries = 1_000;
const ignoredDirectories = new Set([
  '.git',
  '.venv',
  'node_modules',
  '__pycache__',
  '.cache',
]);

/**
 * 상대경로를 워크스페이스 절대경로로 변환하고 상위 탈출을 차단함
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
type FileCollection = {
  files: string[];
  visitedEntries: number;
  maxFiles: number;
  truncated: boolean;
};

function createFileCollection(maxFiles: number): FileCollection {
  return { files: [], visitedEntries: 0, maxFiles, truncated: false };
}

async function collectFiles(
  directory: string,
  realWorkspaceRoot: string,
  maxDepth: number,
  collection: FileCollection,
  currentDepth = 0,
): Promise<FileCollection> {
  if (collection.files.length >= collection.maxFiles) {
    collection.truncated = true;
    return collection;
  }

  const handle = await fs.opendir(directory);
  const entries = [];
  for await (const entry of handle) {
    collection.visitedEntries++;
    if (collection.visitedEntries > maxDirectoryEntries) {
      collection.truncated = true;
      break;
    }
    entries.push(entry);
  }

  entries.sort((left, right) => left.name.localeCompare(right.name));
  for (const entry of entries) {
    if (collection.files.length >= collection.maxFiles) {
      collection.truncated = true;
      break;
    }
    if (entry.name.startsWith('.') || ignoredDirectories.has(entry.name)) {
      continue;
    }

    const entryPath = path.join(directory, entry.name);
    if (entry.isFile()) {
      collection.files.push(path.relative(realWorkspaceRoot, entryPath));
      continue;
    }

    if (entry.isDirectory() && currentDepth < maxDepth) {
      await collectFiles(
        entryPath,
        realWorkspaceRoot,
        maxDepth,
        collection,
        currentDepth + 1,
      );
      if (collection.truncated) break;
    }
  }

  return collection;
}

async function listVisibleRootEntries(
  directory: string,
): Promise<{ entries: string[]; truncated: boolean }> {
  const handle = await fs.opendir(directory);
  const entries: string[] = [];
  let truncated = false;
  for await (const entry of handle) {
    if (entry.name.startsWith('.') || ignoredDirectories.has(entry.name)) continue;
    if (entries.length >= maxVisibleRootEntries) {
      truncated = true;
      break;
    }
    entries.push(`${entry.isDirectory() ? 'dir' : 'file'}: ${entry.name}`);
  }
  entries.sort((left, right) => left.localeCompare(right));
  return { entries, truncated };
}

function boundedInteger(value: unknown, fallback: number, minimum: number, maximum: number): number {
  const parsed = value === undefined ? fallback : Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`정수 매개변수는 ${minimum}에서 ${maximum} 사이여야 함`);
  }
  return parsed;
}

async function readFilePrefix(filePath: string, maxBytes: number): Promise<Buffer> {
  const file = await fs.open(filePath, 'r');
  try {
    const buffer = Buffer.alloc(maxBytes + 1);
    let totalBytes = 0;
    while (totalBytes < buffer.length) {
      const { bytesRead } = await file.read(
        buffer,
        totalBytes,
        buffer.length - totalBytes,
        totalBytes,
      );
      if (bytesRead === 0) break;
      totalBytes += bytesRead;
    }
    return buffer.subarray(0, totalBytes);
  } finally {
    await file.close();
  }
}

/**
 * 워크스페이스 도구 실행 핸들러임
 */
async function handleWorkspaceToolCall(
  name: string,
  args: Record<string, any>,
): Promise<unknown> {
  if (!enableWorkspaceHttp) {
    throw new Error(
      'HTTP 워크스페이스 파일 접근이 비활성화됨. MCP_ENABLE_WORKSPACE_HTTP=true 설정 필요함',
    );
  }

  if (name === 'workspace_status') {
    const { entries: visibleEntries, truncated } = await listVisibleRootEntries(workspaceRoot);

    return {
      workspace_root: workspaceRoot,
      total_entries: visibleEntries.length,
      truncated,
      entries: visibleEntries,
    };
  }

  if (name === 'list_project_files') {
    const relPath = args.path || '.';
    const depth = boundedInteger(args.maxDepth, 2, 0, 4);
    const { absolutePath: directory } = await resolveAccessiblePath(relPath);
    const realRoot = await fs.realpath(workspaceRoot);
    const stats = await fs.stat(directory);
    if (!stats.isDirectory()) {
      throw new Error('요청한 경로가 디렉터리가 아님');
    }
    const collection = await collectFiles(
      directory,
      realRoot,
      depth,
      createFileCollection(maxListedFiles + 1),
    );
    const files = collection.files.slice(0, maxListedFiles);
    return {
      count: files.length,
      files,
      truncated: collection.truncated || collection.files.length > maxListedFiles,
    };
  }

  if (name === 'read_project_file') {
    const relPath = args.path;
    if (!relPath) throw new Error('path 매개변수가 필수임');
    const { absolutePath: filePath, relativePath: visiblePath } = await resolveAccessiblePath(relPath);
    const stats = await fs.stat(filePath);
    if (!stats.isFile()) throw new Error('요청한 경로가 일반 파일이 아님');
    const contents = await readFilePrefix(filePath, maxReadBytes);
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
    if (pattern.length > maxGrepPatternChars) {
      throw new Error(`검색 문자열은 ${maxGrepPatternChars}자 이하여야 함`);
    }
    const relPath = args.path || '.';
    const maxMatches = boundedInteger(args.maxMatches, 30, 1, 100);
    const { absolutePath: directory } = await resolveAccessiblePath(relPath);
    const realRoot = await fs.realpath(workspaceRoot);
    const collection = await collectFiles(
      directory,
      realRoot,
      3,
      createFileCollection(maxGrepFiles + 1),
    );
    const needle = pattern.toLowerCase();
    const matches: string[] = [];
    let scannedBytes = 0;
    let resultChars = 0;
    let truncated = collection.truncated || collection.files.length > maxGrepFiles;
    for (const file of collection.files.slice(0, maxGrepFiles)) {
      if (matches.length >= maxMatches) break;
      const fullPath = path.join(realRoot, file);
      try {
        const stats = await fs.stat(fullPath);
        if (!stats.isFile()) continue;
        if (stats.size > maxGrepFileBytes) {
          truncated = true;
          continue;
        }
        const bytesRemaining = maxGrepTotalBytes - scannedBytes;
        if (bytesRemaining <= 0) {
          truncated = true;
          break;
        }
        const readLimit = Math.min(maxGrepFileBytes, bytesRemaining);
        const content = await readFilePrefix(fullPath, readLimit);
        scannedBytes += content.length;
        if (stats.size > content.length) truncated = true;
        if (content.includes(0)) continue;
        const text = content.toString('utf8');
        let lineStart = 0;
        let lineNumber = 1;
        while (lineStart <= text.length) {
          const newline = text.indexOf('\n', lineStart);
          const lineEnd = newline === -1 ? text.length : newline;
          const line = text.slice(lineStart, lineEnd);
          if (line.toLowerCase().includes(needle)) {
            const trimmedLine = line.trim();
            const match = `${file}:${lineNumber}: ${trimmedLine.slice(0, maxGrepLineChars)}${trimmedLine.length > maxGrepLineChars ? '…' : ''}`;
            if (resultChars + match.length + 1 > maxGrepResultChars) {
              truncated = true;
              break;
            }
            matches.push(match);
            resultChars += match.length + 1;
            if (matches.length >= maxMatches) break;
          }
          if (newline === -1) break;
          lineStart = newline + 1;
          lineNumber++;
        }
        if (resultChars >= maxGrepResultChars || scannedBytes >= maxGrepTotalBytes) break;
      } catch {
        // 무시
      }
    }
    return { count: matches.length, matches, truncated };
  }

  if (name === 'workspace_project_summary') {
    const relPath = args.path || '.';
    const { absolutePath: directory } = await resolveAccessiblePath(relPath);
    const realRoot = await fs.realpath(workspaceRoot);
    const collection = await collectFiles(
      directory,
      realRoot,
      4,
      createFileCollection(maxSummaryFiles + 1),
    );
    const files = collection.files.slice(0, maxSummaryFiles);

    const extCount: Record<string, number> = {};
    for (const file of files) {
      const ext = path.extname(file) || '(확장자 없음)';
      extCount[ext] = (extCount[ext] ?? 0) + 1;
    }
    return {
      workspace_path: relPath,
      total_files: files.length,
      truncated: collection.truncated || collection.files.length > maxSummaryFiles,
      extensions: extCount,
    };
  }

  throw new Error(`알 수 없는 도구명임: ${name}`);
}

const WORKSPACE_TOOLS_DEFINITION = [
  {
    name: 'workspace_status',
    description: '설정된 워크스페이스 루트의 기본 정보를 반환함 (읽기 전용임)',
    parameters: {},
    enabled: enableWorkspaceHttp,
  },
  {
    name: 'list_project_files',
    description: '워크스페이스 상대 디렉터리의 가시 파일 목록을 반환함 (읽기 전용임)',
    parameters: {
      path: { type: 'string', default: '.', description: '워크스페이스 기준 상대 디렉터리 경로임' },
      maxDepth: { type: 'number', default: 2, description: '최대 탐색 깊이임' },
    },
    enabled: enableWorkspaceHttp,
  },
  {
    name: 'read_project_file',
    description: '워크스페이스 상대경로의 텍스트 파일 내용을 읽음 (최대 256KB 제한함)',
    parameters: {
      path: { type: 'string', required: true, description: '워크스페이스 기준 상대 파일 경로임' },
    },
    enabled: enableWorkspaceHttp,
  },
  {
    name: 'grep_workspace_files',
    description: '워크스페이스 내 텍스트 파일에서 리터럴 문자열을 검색함 (정규표현식은 지원하지 않음)',
    parameters: {
      pattern: { type: 'string', required: true, description: '검색할 리터럴 문자열임 (최대 256자)' },
      path: { type: 'string', default: '.', description: '검색을 시작할 상대 경로임' },
      maxMatches: { type: 'number', default: 30, description: '최대 반환 일치 건수임' },
    },
    enabled: enableWorkspaceHttp,
  },
  {
    name: 'workspace_project_summary',
    description: '워크스페이스 내 가시 파일들의 확장자별 분포 및 요약 통계를 산출함',
    parameters: {
      path: { type: 'string', default: '.', description: '분석할 상대 디렉터리 경로임' },
    },
    enabled: enableWorkspaceHttp,
  },
];

// 3. 표준 Streamable HTTP MCP 서버 및 트랜스포트 구성
const httpTransport = new WebStandardStreamableHTTPServerTransport({
  sessionIdGenerator: () => randomUUID(),
});

const forwardedTools: GatewayToolSummary[] = [];
const httpGatewayClients: ChildMcpClient[] = [];
const httpMcpServer = await createGateway(
  httpGatewayClients,
  (tool) => forwardedTools.push(tool),
).catch(async (error: unknown) => {
  await Promise.allSettled(httpGatewayClients.map((client) => client.close()));
  throw error;
});

// 워크스페이스 도구가 명시적으로 활성화된 경우에만 MCP 서버에 등록함
if (enableWorkspaceHttp) {
  httpMcpServer.registerTool(
    'workspace_status',
    {
      description: '설정된 워크스페이스 루트의 기본 정보를 반환함 (읽기 전용임)',
      annotations: { readOnlyHint: true, idempotentHint: true },
    },
    async () => {
      const res = await handleWorkspaceToolCall('workspace_status', {});
      return { content: [{ type: 'text', text: JSON.stringify(res, null, 2) }] };
    },
  );

  httpMcpServer.registerTool(
    'list_project_files',
    {
      description: '워크스페이스 상대 디렉터리의 가시 파일 목록을 반환함 (읽기 전용임)',
      inputSchema: {
        path: z.string().optional().describe('상대 디렉터리 경로임'),
        maxDepth: z.number().int().min(0).max(4).optional().describe('최대 탐색 깊이임'),
      },
      annotations: { readOnlyHint: true, idempotentHint: true },
    },
    async (args) => {
      const res = await handleWorkspaceToolCall('list_project_files', args);
      return { content: [{ type: 'text', text: JSON.stringify(res, null, 2) }] };
    },
  );

  httpMcpServer.registerTool(
    'read_project_file',
    {
      description: '워크스페이스 상대경로의 텍스트 파일 내용을 읽음 (최대 256KB 제한함)',
      inputSchema: {
        path: z.string().describe('상대 파일 경로임'),
      },
      annotations: { readOnlyHint: true, idempotentHint: true },
    },
    async (args) => {
      const res = await handleWorkspaceToolCall('read_project_file', args);
      return { content: [{ type: 'text', text: JSON.stringify(res, null, 2) }] };
    },
  );

  httpMcpServer.registerTool(
    'grep_workspace_files',
    {
      description: '워크스페이스 내 텍스트 파일에서 리터럴 문자열을 검색함 (정규표현식은 지원하지 않음)',
      inputSchema: {
        pattern: z.string().min(1).max(maxGrepPatternChars).describe('검색할 리터럴 문자열임'),
        path: z.string().optional().describe('검색 경로임'),
        maxMatches: z.number().int().min(1).max(100).optional().describe('최대 일치 건수임'),
      },
      annotations: { readOnlyHint: true, idempotentHint: true },
    },
    async (args) => {
      const res = await handleWorkspaceToolCall('grep_workspace_files', args);
      return { content: [{ type: 'text', text: JSON.stringify(res, null, 2) }] };
    },
  );

  httpMcpServer.registerTool(
    'workspace_project_summary',
    {
      description: '워크스페이스 내 가시 파일들의 확장자별 분포 및 요약 통계를 산출함',
      inputSchema: {
        path: z.string().optional().describe('분석할 상대 디렉터리 경로임'),
      },
      annotations: { readOnlyHint: true, idempotentHint: true },
    },
    async (args) => {
      const res = await handleWorkspaceToolCall('workspace_project_summary', args);
      return { content: [{ type: 'text', text: JSON.stringify(res, null, 2) }] };
    },
  );
}

// 플랫폼 공통 상태 확인 도구 등록
httpMcpServer.registerTool(
  'platform_status',
  {
    description: 'mcp-platform HTTP 게이트웨이의 가동 상태 및 보안 설정 요약을 반환함',
    annotations: { readOnlyHint: true, idempotentHint: true },
  },
  async () => ({
    content: [
      {
        type: 'text',
        text: JSON.stringify(
          {
            service: 'mcp-platform-http-gateway',
            version: '0.1.0',
            workspace_files_enabled: enableWorkspaceHttp,
            uptime_seconds: process.uptime(),
          },
          null,
          2,
        ),
      },
    ],
  }),
);

// MCP 서버와 HTTP 트랜스포트 바인딩 완료
try {
  await httpMcpServer.connect(httpTransport);
} catch (error) {
  await httpMcpServer.close();
  throw error;
}

// 3. 메트릭 및 레이트 리미터 정의
interface GatewayMetrics {
  totalRequests: number;
  statusCodes: Record<string, number>;
  endpoints: Record<string, number>;
  totalLatencyMs: number;
  maxLatencyMs: number;
  startedAt: string;
}

const metrics: GatewayMetrics = {
  totalRequests: 0,
  statusCodes: {},
  endpoints: {},
  totalLatencyMs: 0,
  maxLatencyMs: 0,
  startedAt: new Date().toISOString(),
};

// IP별 고정 1초 요청 카운터. 클라이언트 수와 상태 메모리를 제한함.
type RateLimitState = { windowStartedAt: number; requestCount: number };
const rateLimitMap = new Map<string, RateLimitState>();
const MAX_RATE_LIMIT_CLIENTS = 10_000;
let lastRateLimitCleanupAt = 0;

function checkRateLimit(clientIp: string): boolean {
  const now = Date.now();
  let state = rateLimitMap.get(clientIp);
  if (!state) {
    if (rateLimitMap.size >= MAX_RATE_LIMIT_CLIENTS) {
      if (now - lastRateLimitCleanupAt >= 1000) {
        for (const [ip, entry] of rateLimitMap) {
          if (now - entry.windowStartedAt >= 1000) rateLimitMap.delete(ip);
        }
        lastRateLimitCleanupAt = now;
      }
      if (rateLimitMap.size >= MAX_RATE_LIMIT_CLIENTS) return false;
    }
    state = { windowStartedAt: now, requestCount: 0 };
    rateLimitMap.set(clientIp, state);
  }
  if (now - state.windowStartedAt >= 1000) {
    state.windowStartedAt = now;
    state.requestCount = 0;
  }
  if (state.requestCount >= RATE_LIMIT_PER_SEC) return false;
  state.requestCount++;
  return true;
}

function waitForResponseDrain(res: http.ServerResponse): Promise<void> {
  return new Promise((resolve) => {
    const cleanup = () => {
      res.off('drain', onDrain);
      res.off('close', onClose);
    };
    const onDrain = () => {
      cleanup();
      resolve();
    };
    const onClose = () => {
      cleanup();
      resolve();
    };
    res.once('drain', onDrain);
    res.once('close', onClose);
  });
}

// 4. HTTP 요청 디스패처 및 보안 미들웨어
const server = http.createServer((req, res) => {
  const requestId = (req.headers['x-request-id'] as string) || randomUUID();
  res.setHeader('X-Request-Id', requestId);
  void dispatchRequest(req, res, requestId).catch((error: unknown) => {
    try {
      const kind = error instanceof Error ? error.name : typeof error;
      console.error(`[mcp-platform] HTTP 요청 처리 실패함 (${requestId}, ${kind})`);
      if (res.destroyed || res.writableEnded) return;
      res.shouldKeepAlive = false;
      if (res.headersSent) {
        res.destroy();
        return;
      }
      res.writeHead(500, {
        'Content-Type': 'application/json',
        Connection: 'close',
      });
      res.end(JSON.stringify({ error: 'Internal Server Error', requestId }));
    } catch {
      res.destroy();
    }
  });
});

async function dispatchRequest(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  requestId: string,
): Promise<void> {
  const startTime = Date.now();

  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
  const pathname = url.pathname;

  // 응답 완료 시 메트릭 집계
  res.on('finish', () => {
    const duration = Date.now() - startTime;
    metrics.totalRequests++;
    metrics.totalLatencyMs += duration;
    if (duration > metrics.maxLatencyMs) {
      metrics.maxLatencyMs = duration;
    }
    const statusGroup = `${Math.floor(res.statusCode / 100)}xx`;
    metrics.statusCodes[statusGroup] = (metrics.statusCodes[statusGroup] ?? 0) + 1;
    const endpointKey =
      metrics.endpoints[pathname] !== undefined
        ? pathname
        : Object.keys(metrics.endpoints).length < 255 && pathname.length <= 256
          ? pathname
          : '__other__';
    metrics.endpoints[endpointKey] = (metrics.endpoints[endpointKey] ?? 0) + 1;
  });

  // Host 헤더 유효성 검증
  const hostValidation = validateHostHeader(req.headers.host, allowedHostnames);
  if (!hostValidation.ok) {
    res.writeHead(403, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: hostValidation.message }));
    return;
  }

  // Origin 헤더 유효성 검증 (제공된 경우)
  const originHeader = req.headers.origin;
  if (originHeader) {
    const originValidation = validateOriginHeader(originHeader, allowedOriginHostnames);
    if (!originValidation.ok) {
      res.writeHead(403, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: originValidation.message }));
      return;
    }
    res.setHeader('Access-Control-Allow-Origin', originHeader);
    res.setHeader('Vary', 'Origin');
  }

  // 레이트 리미트 검증
  const clientIp = req.socket.remoteAddress ?? '127.0.0.1';
  if (!checkRateLimit(clientIp)) {
    res.writeHead(429, {
      'Content-Type': 'application/json',
      'Retry-After': '1',
    });
    res.end(JSON.stringify({ error: '요청 한도 초과됨 (초당 최대 요청 제한)', retryAfter: 1 }));
    return;
  }

  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, Accept, X-Requested-With');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const authorization = req.headers.authorization;
  const matchesBearer = (expected: string | undefined): boolean => {
    if (!expected || !authorization) return false;
    const match = /^Bearer\s+(\S+)$/i.exec(authorization);
    if (!match) return false;
    const supplied = Buffer.from(match[1]);
    const configured = Buffer.from(expected);
    return supplied.length === configured.length && timingSafeEqual(supplied, configured);
  };
  const bearerAuthenticated = matchesBearer(bearerToken);
  const managementAuthenticated = bearerAuthenticated || matchesBearer(adminToken);
  const publicHealthPaths = new Set(['/api/health', '/api/healthz', '/health', '/healthz']);

  if (
    pathname !== '/mcp' &&
    !publicHealthPaths.has(pathname) &&
    (bearerToken || adminToken) &&
    !managementAuthenticated
  ) {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: '관리 API 인증 토큰이 필요함' }));
    return;
  }

  // -------------------------------------------------------------------------
  // 4.1 표준 MCP Streamable HTTP 전송 엔드포인트 (/mcp)
  // -------------------------------------------------------------------------
  if (pathname === '/mcp') {
    if (bearerToken && !bearerAuthenticated) {
      res.writeHead(401, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          jsonrpc: '2.0',
          error: { code: -32001, message: 'Unauthorized: MCP_HTTP_BEARER_TOKEN이 일치하지 않음' },
          id: null,
        }),
      );
      return;
    }

    const chunks: Buffer[] = [];
    let totalBytes = 0;
    let bodyTooLarge = false;

    for await (const chunk of req) {
      totalBytes += (chunk as Buffer).length;
      if (totalBytes > MAX_BODY_BYTES) {
        bodyTooLarge = true;
        break;
      }
      chunks.push(chunk as Buffer);
    }

    if (bodyTooLarge) {
      res.writeHead(413, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          jsonrpc: '2.0',
          error: { code: -32000, message: 'Payload Too Large: 요청 본문이 1MB 제한을 초과함' },
          id: null,
        }),
      );
      return;
    }

    const bodyBuffer = chunks.length > 0 ? Buffer.concat(chunks) : undefined;
    const headers = new Headers();
    for (const [key, val] of Object.entries(req.headers)) {
      if (Array.isArray(val)) {
        val.forEach((v) => headers.append(key, v));
      } else if (val !== undefined) {
        headers.set(key, val);
      }
    }

    const webReq = new Request(url, {
      method: req.method,
      headers,
      body:
        req.method !== 'GET' && req.method !== 'HEAD' && bodyBuffer && bodyBuffer.length > 0
          ? bodyBuffer
          : undefined,
      duplex: 'half',
    } as any);

    const webRes = await httpTransport.handleRequest(webReq);
    res.writeHead(webRes.status, Object.fromEntries(webRes.headers.entries()));
    if (webRes.body) {
      const reader = webRes.body.getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!res.write(value)) {
          await waitForResponseDrain(res);
          if (res.destroyed) {
            await reader.cancel().catch(() => undefined);
            return;
          }
        }
      }
    }
    res.end();
    return;
  }

  // -------------------------------------------------------------------------
  // 4.2 REST 관리 API 엔드포인트 (/api/* 및 호환성 경로)
  // -------------------------------------------------------------------------

  // 헬스체크
  if (req.method === 'GET' && (pathname === '/api/health' || pathname === '/api/healthz' || pathname === '/health' || pathname === '/healthz')) {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify({
        status: 'ok',
        service: 'mcp-platform',
        host: HOST,
        port: PORT,
        uptime: process.uptime(),
        workspace_tools_enabled: enableWorkspaceHttp,
      }),
    );
    return;
  }

  // 시스템 및 HTTP 통계 메트릭 엔드포인트 (JSON 및 Prometheus 텍스트 포맷 지원)
  if (req.method === 'GET' && (pathname === '/api/metrics' || pathname === '/metrics')) {
    const accept = req.headers.accept ?? '';
    const format = url.searchParams.get('format');
    if (format === 'prometheus' || accept.includes('text/plain')) {
      const avgLatency = metrics.totalRequests > 0 ? (metrics.totalLatencyMs / metrics.totalRequests).toFixed(2) : '0';
      let prom = `# HELP mcp_http_requests_total 총 HTTP 요청 처리 건수임\n`;
      prom += `# TYPE mcp_http_requests_total counter\n`;
      prom += `mcp_http_requests_total ${metrics.totalRequests}\n\n`;
      prom += `# HELP mcp_http_request_duration_ms_avg 평균 요청 처리 지연시간(ms)임\n`;
      prom += `# TYPE mcp_http_request_duration_ms_avg gauge\n`;
      prom += `mcp_http_request_duration_ms_avg ${avgLatency}\n\n`;
      prom += `# HELP mcp_http_request_duration_ms_max 최대 요청 처리 지연시간(ms)임\n`;
      prom += `# TYPE mcp_http_request_duration_ms_max gauge\n`;
      prom += `mcp_http_request_duration_ms_max ${metrics.maxLatencyMs}\n\n`;
      for (const [code, count] of Object.entries(metrics.statusCodes)) {
        prom += `mcp_http_responses_total{status_group="${code}"} ${count}\n`;
      }
      res.writeHead(200, { 'Content-Type': 'text/plain; version=0.0.4; charset=utf-8' });
      res.end(prom);
      return;
    }

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify(
        {
          service: 'mcp-platform',
          totalRequests: metrics.totalRequests,
          statusCodes: metrics.statusCodes,
          endpoints: metrics.endpoints,
          avgLatencyMs:
            metrics.totalRequests > 0
              ? Number((metrics.totalLatencyMs / metrics.totalRequests).toFixed(2))
              : 0,
          maxLatencyMs: metrics.maxLatencyMs,
          startedAt: metrics.startedAt,
          uptimeSeconds: process.uptime(),
        },
        null,
        2,
      ),
    );
    return;
  }

  // 등록 서버 목록 조회
  if (req.method === 'GET' && (pathname === '/api/servers' || pathname === '/servers')) {
    const cliScript = path.resolve(projectRoot, 'scripts/mcp-cli.sh');
    try {
      const { stdout } = await execFileAsync(cliScript, ['servers'], { timeout: REQUEST_TIMEOUT_MS });
      const servers = JSON.parse(stdout);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, count: servers.length, servers }, null, 2));
    } catch (err: any) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: false, error: err.message || String(err) }));
    }
    return;
  }

  // 캐시 통계 조회
  if (req.method === 'GET' && (pathname === '/api/cache/stats' || pathname === '/cache/stats')) {
    const cliScript = path.resolve(projectRoot, 'scripts/mcp-cli.sh');
    try {
      const { stdout } = await execFileAsync(cliScript, ['cache', 'stats'], { timeout: REQUEST_TIMEOUT_MS });
      const stats = JSON.parse(stdout);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, stats }, null, 2));
    } catch (err: any) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: false, error: err.message || String(err) }));
    }
    return;
  }

  // 관리자 전용 영속 캐시 초기화 (원격 기본 비활성화, 인증 필수임)
  if (req.method === 'POST' && (pathname === '/api/admin/cache/clear' || pathname === '/cache/clear')) {
    if (pathname === '/cache/clear') {
      res.writeHead(410, { 'Content-Type': 'application/json' });
      res.end(
        JSON.stringify({
          success: false,
          error: '/cache/clear 경로는 폐기됨. /api/admin/cache/clear를 사용해야 함',
        }),
      );
      return;
    }

    const authHeader = req.headers.authorization;
    const isAuthorizedAdmin = Boolean(adminToken && authHeader && matchesBearer(adminToken));

    if (!isAuthorizedAdmin) {
      res.writeHead(401, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: false, error: '관리자 인증 토큰이 필요함' }));
      return;
    }

    const cliScript = path.resolve(projectRoot, 'scripts/mcp-cli.sh');
    try {
      const { stdout } = await execFileAsync(cliScript, ['cache', 'clear'], { timeout: REQUEST_TIMEOUT_MS });
      const result = JSON.parse(stdout);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: true, result }, null, 2));
    } catch (err: any) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ success: false, error: err.message || String(err) }));
    }
    return;
  }

  // 시스템 종합 진단 리포트
  if (req.method === 'GET' && (pathname === '/api/doctor' || pathname === '/doctor')) {
    const doctorScript = path.resolve(projectRoot, 'scripts/doctor.sh');
    try {
      const { stdout } = await execFileAsync(doctorScript, [], { timeout: REQUEST_TIMEOUT_MS });
      res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(stdout);
    } catch (err: any) {
      res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(err.stdout || err.message || String(err));
    }
    return;
  }

  // OpenAPI 3.0 명세
  if (req.method === 'GET' && (pathname === '/api/openapi.json' || pathname === '/openapi.json')) {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify(
        {
          openapi: '3.0.0',
          info: {
            title: 'MCP Platform HTTP & REST Gateway',
            version: '0.1.0',
            description: 'MCP Streamable HTTP(/mcp) 및 시스템 관리 REST API(/api/*)',
          },
          paths: {
            '/mcp': {
              post: { summary: '표준 MCP Streamable HTTP JSON-RPC 전송 엔드포인트' },
              get: { summary: '표준 MCP SSE 이벤트 스트림 핸드셰이크' },
              delete: { summary: '표준 MCP 세션 종료' },
            },
            '/api/health': { get: { summary: '서비스 가동 상태 확인' } },
            '/api/servers': { get: { summary: '등록된 MCP 서버 목록 조회' } },
            '/api/tools': { get: { summary: 'HTTP 게이트웨이 도구 명세 조회' } },
            '/api/cache/stats': { get: { summary: '2계층 영속 캐시 적재 통계 조회' } },
            '/api/admin/cache/clear': { post: { summary: '관리자 전용 영속 캐시 즉시 초기화' } },
            '/api/doctor': { get: { summary: '시스템 종합 진단 텍스트 리포트' } },
          },
        },
        null,
        2,
      ),
    );
    return;
  }

  // 도구 명세 목록 조회
  if (req.method === 'GET' && (pathname === '/' || pathname === '/api/tools' || pathname === '/tools')) {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify(
        {
          service: 'mcp-platform-http-gateway',
          version: '0.1.0',
          mcp_endpoint: '/mcp',
          workspace_files_enabled: enableWorkspaceHttp,
          tools: [
            {
              name: 'platform_status',
              description: 'mcp-platform HTTP 게이트웨이의 상태를 반환함',
            },
            ...forwardedTools,
            ...WORKSPACE_TOOLS_DEFINITION.filter((tool) => tool.enabled),
          ],
        },
        null,
        2,
      ),
    );
    return;
  }

  // 하트비트 SSE 스트림 (기존 /mcp/events 대신 분리된 경로)
  if (req.method === 'GET' && (pathname === '/api/heartbeat-stream' || pathname === '/heartbeat')) {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    });
    res.write(
      `data: ${JSON.stringify({ event: 'connected', service: 'mcp-platform-http-gateway', timestamp: new Date().toISOString() })}\n\n`,
    );

    const intervalId = setInterval(() => {
      if (!res.write(`: ping ${Date.now()}\n\n`)) {
        clearInterval(intervalId);
        res.end();
      }
    }, 15000);

    res.on('close', () => {
      clearInterval(intervalId);
    });
    return;
  }

  // 폐기된 /mcp/events 접근 처리
  if (pathname === '/mcp/events') {
    res.writeHead(410, { 'Content-Type': 'application/json' });
    res.end(
      JSON.stringify({
        error: '/mcp/events 경로는 폐기됨. 표준 MCP 전송은 /mcp를 사용하고 단순 핑은 /api/heartbeat-stream을 사용해야 함',
      }),
    );
    return;
  }

  // 404 미지원 경로
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not Found', path: pathname }));
}

server.requestTimeout = REQUEST_TIMEOUT_MS;
server.headersTimeout = 10_000;
server.keepAliveTimeout = 5_000;

let shutdownPromise: Promise<void> | undefined;
const shutdown = (): Promise<void> => {
  if (shutdownPromise) return shutdownPromise;
  shutdownPromise = (async () => {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) =>
      server.close((error) => {
        if (error && (error as NodeJS.ErrnoException).code !== 'ERR_SERVER_NOT_RUNNING') {
          reject(error);
        } else {
          resolve();
        }
      }),
    );
    await httpMcpServer.close();
  })();
  return shutdownPromise;
};

const reportShutdownError = (error: unknown) => {
  const kind = error instanceof Error ? error.name : typeof error;
  console.error(`[mcp-platform] 종료 처리 실패함 (${kind})`);
  process.exitCode = 1;
};

process.once('SIGINT', () => void shutdown().catch(reportShutdownError));
process.once('SIGTERM', () => void shutdown().catch(reportShutdownError));
server.on('error', (error) => {
  const kind = error instanceof Error ? error.name : typeof error;
  console.error(`[mcp-platform] HTTP 리스너 실행 실패함 (${kind})`);
  void shutdown().catch(reportShutdownError).finally(() => {
    process.exitCode = 1;
  });
});

server.listen(PORT, HOST, () => {
  console.log(`[mcp-platform] HTTP 게이트웨이가 http://${HOST}:${PORT} 에서 대기 중임`);
  console.log(`[mcp-platform] MCP 표준 엔드포인트: http://${HOST}:${PORT}/mcp`);
  console.log(`[mcp-platform] REST 관리 엔드포인트: http://${HOST}:${PORT}/api/health`);
});
