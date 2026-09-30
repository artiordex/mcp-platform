/**
 * 파일명: mcp-gateway.ts
 * 경로: src/servers/mcp-gateway.ts
 * 목적: 설정 파일에 정의된 복수 MCP 서버(stdio/HTTP)를 단일 MCP 게이트웨이로 통합 제공함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { fromJsonSchema, McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import * as z from 'zod/v4';

import {
  ChildMcpClient,
  describeError,
  type ChildMcpServerConfig,
  type ChildTool,
} from '../clients/child-mcp-client.js';
import { namespacedToolName } from './tool-name.js';

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../..',
);

const CommonServerFields = {
  id: z.string().regex(/^[A-Za-z0-9_-]+$/).max(32),
  label: z.string().trim().min(1).max(100),
  enabled: z.boolean().default(true),
  requestTimeoutMs: z.number().int().min(1_000).max(600_000).default(30_000),
};

const StdioServerDefinitionSchema = z.object({
  ...CommonServerFields,
  transport: z.literal('stdio'),
  command: z.string().trim().min(1),
  args: z.array(z.string()).default([]),
  cwd: z.string().optional(),
  envPassthrough: z
    .array(z.string().regex(/^[A-Za-z_][A-Za-z0-9_]*$/))
    .default([]),
  maxBufferSize: z.number().int().min(1_024).max(100 * 1024 * 1024).optional(),
}).strict();

const StreamableHttpServerDefinitionSchema = z.object({
  ...CommonServerFields,
  transport: z.literal('streamable-http'),
  url: z
    .string()
    .url()
    .refine((value) => {
      const url = new URL(value);
      return (
        ['http:', 'https:'].includes(url.protocol) &&
        url.username.length === 0 &&
        url.password.length === 0 &&
        url.search.length === 0 &&
        url.hash.length === 0
      );
    }, '자격증명, 쿼리, 프래그먼트가 없는 안전한 HTTP(S) URL이어야 함'),
  headersFromEnv: z
    .record(
      z.string().regex(/^[A-Za-z0-9!#$%&'*+.^_`|~-]+$/),
      z.string().regex(/^[A-Za-z_][A-Za-z0-9_]*$/),
    )
    .default({}),
}).strict();

const ServerDefinitionSchema = z.discriminatedUnion('transport', [
  StdioServerDefinitionSchema,
  StreamableHttpServerDefinitionSchema,
]);

const GatewayConfigSchema = z.object({
  name: z.string().trim().min(1).max(100).default('mcp-platform-gateway'),
  servers: z.array(ServerDefinitionSchema).min(1),
});

type ServerDefinition = z.infer<typeof ServerDefinitionSchema>;
type GatewayConfig = z.infer<typeof GatewayConfigSchema>;

/**
 * 게이트웨이 설정 파일 경로를 계산함
 */
function configPath(): string {
  const configuredPath = process.env.MCP_SERVERS_CONFIG ?? 'config/mcp-servers.json';
  return path.resolve(projectRoot, configuredPath);
}

/**
 * mcp-servers.json 설정을 읽고 유효성을 검증함
 */
async function loadGatewayConfig(): Promise<GatewayConfig> {
  const filename = configPath();
  let contents: string;
  try {
    contents = await fs.readFile(filename, 'utf8');
  } catch (error) {
    throw new Error(
      `설정 파일(${filename})을 읽을 수 없음. config/mcp-servers.example.json 파일을 복사하여 준비해야 함`,
      { cause: error },
    );
  }

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(contents) as unknown;
  } catch (error) {
    throw new Error(`MCP 서버 설정 파일이 올바른 JSON 형식이 아님: ${describeError(error)}`, {
      cause: error,
    });
  }

  const config = GatewayConfigSchema.safeParse(parsedJson);
  if (!config.success) {
    throw new Error(`MCP 서버 설정 유효성 검증 실패함: ${config.error.message}`);
  }

  const seenIds = new Set<string>();
  for (const server of config.data.servers) {
    if (seenIds.has(server.id)) {
      throw new Error(`중복된 서버 식별자가 존재함: ${server.id}`);
    }
    seenIds.add(server.id);
  }

  return config.data;
}

/**
 * 개별 서버 정의를 자식 클라이언트 실행 설정으로 변환함
 */
function childConfig(server: ServerDefinition): ChildMcpServerConfig {
  if (server.transport === 'streamable-http') {
    return {
      transport: server.transport,
      url: server.url,
      headersFromEnv: server.headersFromEnv,
      requestTimeoutMs: server.requestTimeoutMs,
    };
  }
  return {
    transport: server.transport,
    command: server.command,
    args: server.args,
    cwd: server.cwd ? path.resolve(projectRoot, server.cwd) : projectRoot,
    envPassthrough: server.envPassthrough,
    requestTimeoutMs: server.requestTimeoutMs,
    maxBufferSize: server.maxBufferSize,
  };
}

type PreparedTool = {
  source: ChildTool;
  exposedName: string;
  inputSchema: ReturnType<typeof fromJsonSchema>;
};

/**
 * 하위 도구들을 네임스페이스 규칙에 맞게 래핑 준비함
 */
function prepareTools(serverId: string, tools: ChildTool[]): PreparedTool[] {
  const localNames = new Set<string>();
  return tools.map((tool) => {
    if (localNames.has(tool.name)) {
      throw new Error(`하위 서버(${serverId})에서 중복된 도구명을 반환함: ${tool.name}`);
    }
    localNames.add(tool.name);

    return {
      source: tool,
      exposedName: namespacedToolName('mcp', serverId, tool.name),
      inputSchema: fromJsonSchema(
        (tool.inputSchema ?? {
          type: 'object',
          properties: {},
          additionalProperties: false,
        }) as Parameters<typeof fromJsonSchema>[0],
      ),
    };
  });
}

/**
 * 모든 자식 MCP 서버를 병렬 초기화하고 통합 게이트웨이 인스턴스를 구축함
 */
async function createGateway(clients: ChildMcpClient[]): Promise<McpServer> {
  const config = await loadGatewayConfig();
  const gateway = new McpServer({ name: config.name, version: '0.1.0' });
  const registeredNames = new Set<string>();

  const closeGateway = gateway.close.bind(gateway);
  gateway.close = async () => {
    await Promise.allSettled(clients.map((client) => client.close()));
    clients.splice(0, clients.length);
    await closeGateway();
  };

  for (const definition of config.servers.filter(({ enabled }) => enabled)) {
    const client = new ChildMcpClient(
      definition.id,
      definition.label,
      childConfig(definition),
    );

    try {
      await client.initialize();
      const tools = await client.listTools();
      const preparedTools = prepareTools(definition.id, tools);

      for (const { exposedName } of preparedTools) {
        if (registeredNames.has(exposedName)) {
          throw new Error(`정규화 후 도구명 충돌 발생함: ${exposedName}`);
        }
      }
      for (const { exposedName } of preparedTools) {
        registeredNames.add(exposedName);
      }

      for (const { source, exposedName, inputSchema } of preparedTools) {
        gateway.registerTool(
          exposedName,
          {
            description: `[${definition.label}] ${source.description ?? source.name}`,
            inputSchema,
          },
          async (args) => client.callTool(source.name, args),
        );
      }

      clients.push(client);
      process.stderr.write(
        `[mcp-gateway] ${definition.id}: 도구 ${tools.length}개 등록 완료함\n`,
      );
    } catch (error) {
      await client.close();
      process.stderr.write(
        `[mcp-gateway] ${definition.id}: 연결 건너뜀 (${describeError(error)})\n`,
      );
    }
  }

  return gateway;
}

let activeClients: ChildMcpClient[] = [];
let shuttingDown = false;
let handle: { close(): Promise<void> } | undefined;
let gatewayReady: Promise<McpServer> | undefined;
let gatewayStartedResolve: (() => void) | undefined;
const gatewayStarted = new Promise<void>((resolve) => {
  gatewayStartedResolve = resolve;
});

async function closeChildren(): Promise<void> {
  const clients = activeClients;
  activeClients = [];
  await Promise.allSettled(clients.map((client) => client.close()));
}

const shutdown = async (): Promise<void> => {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  await closeChildren();
  await handle?.close();
};

const shutdownAfterInputEnd = async (): Promise<void> => {
  await gatewayStarted;
  await gatewayReady?.catch(() => undefined);
  await shutdown();
};

process.once('SIGINT', () => void shutdown());
process.once('SIGTERM', () => void shutdown());
process.stdin.once('end', () => void shutdownAfterInputEnd());
process.stdin.once('close', () => void shutdownAfterInputEnd());
process.once('exit', () => void closeChildren());

handle = serveStdio(async () => {
  await closeChildren();
  gatewayReady = createGateway(activeClients);
  gatewayStartedResolve?.();
  return gatewayReady;
});

console.error('mcp-platform generic MCP gateway running on stdio');
