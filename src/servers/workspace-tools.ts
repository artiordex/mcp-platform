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
    entries.push(`${entry.isDirectory() ? 'dir ' : 'file'} ${entry.name}`);
  }
  entries.sort((left, right) => left.localeCompare(right));
  return { entries, truncated };
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
      const { entries: visibleEntries, truncated } = await listVisibleRootEntries(workspaceRoot);

      return {
        content: [
          {
            type: 'text',
            text: [
              `workspace_root: ${workspaceRoot}`,
              `entries: ${visibleEntries.length}`,
              ...(truncated ? ['(표시 항목이 1,000개로 제한됨)'] : []),
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

      const collection = await collectFiles(
        directory,
        realWorkspaceRoot,
        maxDepth,
        createFileCollection(maxListedFiles + 1),
      );
      const files = collection.files.slice(0, maxListedFiles);
      return {
        content: [
          {
            type: 'text',
            text: [
              ...(files.length > 0 ? files : ['(표시 가능한 파일 없음)']),
              ...(collection.truncated || collection.files.length > maxListedFiles
                ? ['(파일 목록이 2,000개로 제한됨)']
                : []),
            ].join('\n'),
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

      const contents = await readFilePrefix(filePath, maxReadBytes);
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

  server.registerTool(
    'grep_workspace_files',
    {
      description:
        '워크스페이스 내 가시 텍스트 파일에서 리터럴 문자열을 검색함 (정규표현식은 지원하지 않음)',
      inputSchema: z.object({
        pattern: z
          .string()
          .min(1)
          .max(maxGrepPatternChars)
          .describe('검색할 리터럴 문자열임 (정규표현식은 지원하지 않음)'),
        path: z.string().default('.').describe('검색을 시작할 상대 경로임'),
        maxMatches: z.number().int().min(1).max(100).default(30).describe('반환할 최대 일치 건수임'),
      }),
    },
    async ({ pattern, path: relativePath, maxMatches }) => {
      const { absolutePath: directory } = await resolveAccessiblePath(relativePath);
      const realWorkspaceRoot = await fs.realpath(workspaceRoot);
      const collection = await collectFiles(
        directory,
        realWorkspaceRoot,
        3,
        createFileCollection(maxGrepFiles + 1),
      );
      const needle = pattern.toLowerCase();
      const matches: string[] = [];
      let scannedBytes = 0;
      let resultChars = 0;
      let truncated = collection.truncated || collection.files.length > maxGrepFiles;
      for (const relFile of collection.files.slice(0, maxGrepFiles)) {
        if (matches.length >= maxMatches) break;
        const fullPath = path.join(realWorkspaceRoot, relFile);
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
          if (content.includes(0)) continue; // 바이너리 제외
          const text = content.toString('utf8');
          let lineStart = 0;
          let lineNumber = 1;
          while (lineStart <= text.length) {
            const newline = text.indexOf('\n', lineStart);
            const lineEnd = newline === -1 ? text.length : newline;
            const line = text.slice(lineStart, lineEnd);
            if (line.toLowerCase().includes(needle)) {
              const excerpt = line.trim().slice(0, maxGrepLineChars);
              const match = `${relFile}:${lineNumber}: ${excerpt}${line.trim().length > maxGrepLineChars ? '…' : ''}`;
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
          // 읽기 실패 파일 건너뜀
        }
      }

      return {
        content: [
          {
            type: 'text',
            text:
              matches.length > 0
                ? [
                    `검색 결과 (최대 ${matches.length}건 표시함):`,
                    ...matches,
                    ...(truncated ? ['(검색량 또는 응답 크기 제한으로 결과가 일부 생략됨)'] : []),
                  ].join('\n')
                : truncated
                  ? '검색량 제한에 도달해 결과가 일부 생략됨'
                  : '일치하는 내용을 찾지 못함',
          },
        ],
      };
    },
  );

  server.registerTool(
    'workspace_project_summary',
    {
      description:
        '워크스페이스 내 가시 파일들의 확장자별 분포 및 요약 통계를 산출함',
      inputSchema: z.object({
        path: z.string().default('.').describe('분석할 기준 상대 디렉터리 경로임'),
      }),
    },
    async ({ path: relativePath }) => {
      const { absolutePath: directory } = await resolveAccessiblePath(relativePath);
      const realWorkspaceRoot = await fs.realpath(workspaceRoot);
      const collection = await collectFiles(
        directory,
        realWorkspaceRoot,
        4,
        createFileCollection(maxSummaryFiles + 1),
      );
      const files = collection.files.slice(0, maxSummaryFiles);

      const extCount: Record<string, number> = {};
      for (const file of files) {
        const ext = path.extname(file) || '(확장자 없음)';
        extCount[ext] = (extCount[ext] ?? 0) + 1;
      }

      const sorted = Object.entries(extCount).sort((a, b) => b[1] - a[1]);
      const lines = [
        `# 워크스페이스 요약 보고서 (${relativePath})`,
        `총 가시 파일 수: ${files.length}개`,
        ...(collection.truncated || collection.files.length > maxSummaryFiles
          ? ['(파일 수집이 5,000개로 제한됨)']
          : []),
        '',
        '## 파일 확장자별 통계:',
        ...sorted.map(([ext, cnt]) => `- ${ext}: ${cnt}개`),
      ];

      return {
        content: [{ type: 'text', text: lines.join('\n') }],
      };
    },
  );

  return server;
}

void serveStdio(createServer);
console.error('workspace-tools MCP server running on stdio');
