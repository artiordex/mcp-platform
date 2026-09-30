/**
 * 파일명: mcp-gateway.ts
 * 경로: src/servers/mcp-gateway.ts
 * 목적: 설정 파일에 정의된 복수 MCP 서버(stdio/HTTP)의 도구·리소스·프롬프트를 단일 MCP 게이트웨이로 통합 제공함
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

// stdio 통신 환경에서 stdout의 JSON-RPC 프로토콜 순수성을 보장하기 위해 로그를 stderr로 우회함
console.log = (...args: unknown[]) => console.error(...args);

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../..',
);

const CommonServerFields = {
  id: z.string().regex(/^[A-Za-z0-9_-]+$/).max(32),
  label: z.string().trim().min(1).max(100),
  enabled: z.boolean().default(true),
  allowWriteTools: z.boolean().default(false),
  enabledTools: z.array(z.string()).optional(),
  disabledTools: z.array(z.string()).optional(),
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

export type ServerStatusRecord = {
  id: string;
  label: string;
  status: 'ready' | 'error' | 'disabled';
  tools: number;
  resources: number;
  prompts: number;
  lastError?: string;
};

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

/**
 * 도구의 이름 및 어노테이션을 기반으로 쓰기(변경) 작업 도구인지 판별함
 */
export function isWriteTool(
  toolName: string,
  annotations?: { readOnlyHint?: boolean; [key: string]: unknown },
): boolean {
  if (annotations?.readOnlyHint === false) {
    return true;
  }
  if (annotations?.readOnlyHint === true) {
    return false;
  }
  const writePatterns = [
    /^(create|insert|update|delete|modify|write|clear|drop|execute|ingest|publish|send|patch)_/i,
    /_(create|insert|update|delete|modify|write|clear|drop|execute|ingest|publish|send|patch)$/i,
    /(ingest|clear|delete|modify|write)/i,
  ];
  return writePatterns.some((pattern) => pattern.test(toolName));
}

type PreparedTool = {
  source: ChildTool;
  exposedName: string;
  isWrite: boolean;
  inputSchema: ReturnType<typeof fromJsonSchema>;
};

/**
 * 하위 도구들을 네임스페이스 규칙 및 쓰기 정책에 맞게 필터링하고 래핑 준비함
 */
function prepareTools(
  serverId: string,
  tools: ChildTool[],
  allowWrite: boolean,
  enabledTools?: string[],
  disabledTools?: string[],
): PreparedTool[] {
  const localNames = new Set<string>();
  const enabledSet = enabledTools ? new Set(enabledTools) : undefined;
  const disabledSet = disabledTools ? new Set(disabledTools) : undefined;
  const result: PreparedTool[] = [];

  for (const tool of tools) {
    if (localNames.has(tool.name)) {
      throw new Error(`하위 서버(${serverId})에서 중복된 도구명을 반환함: ${tool.name}`);
    }
    localNames.add(tool.name);

    if (enabledSet && !enabledSet.has(tool.name)) {
      continue;
    }
    if (disabledSet && disabledSet.has(tool.name)) {
      continue;
    }

    const isWrite = isWriteTool(tool.name, tool.annotations);
    if (isWrite && !allowWrite) {
      process.stderr.write(
        `[mcp-gateway] ${serverId}: 쓰기 도구(${tool.name})는 비활성화 기본값에 따라 제외됨\n`,
      );
      continue;
    }

    result.push({
      source: tool,
      exposedName: namespacedToolName('mcp', serverId, tool.name),
      isWrite,
      inputSchema: fromJsonSchema(
        (tool.inputSchema ?? {
          type: 'object',
          properties: {},
          additionalProperties: false,
        }) as Parameters<typeof fromJsonSchema>[0],
      ),
    });
  }

  return result;
}

/**
 * 모든 자식 MCP 서버를 초기화하고 도구·리소스·프롬프트를 통합한 게이트웨이 인스턴스를 구축함
 */
async function createGateway(clients: ChildMcpClient[]): Promise<McpServer> {
  const config = await loadGatewayConfig();
  const gateway = new McpServer({ name: config.name, version: '0.1.0' });
  const registeredToolNames = new Set<string>();
  const registeredResourceUris = new Set<string>();
  const registeredPromptNames = new Set<string>();
  const serverStatuses: ServerStatusRecord[] = [];

  const closeGateway = gateway.close.bind(gateway);
  gateway.close = async () => {
    await Promise.allSettled(clients.map((client) => client.close()));
    clients.splice(0, clients.length);
    await closeGateway();
  };

  const globalAllowWrite = process.env.MCP_ALLOW_WRITE_TOOLS === 'true';

  for (const definition of config.servers) {
    if (!definition.enabled) {
      serverStatuses.push({
        id: definition.id,
        label: definition.label,
        status: 'disabled',
        tools: 0,
        resources: 0,
        prompts: 0,
      });
      continue;
    }

    const client = new ChildMcpClient(
      definition.id,
      definition.label,
      childConfig(definition),
    );

    try {
      await client.initialize();
      const allowWrite = definition.allowWriteTools || globalAllowWrite;

      // 1. 도구(Tools) 전달 등록
      const tools = await client.listTools();
      const preparedTools = prepareTools(
        definition.id,
        tools,
        allowWrite,
        definition.enabledTools,
        definition.disabledTools,
      );

      for (const { exposedName } of preparedTools) {
        if (registeredToolNames.has(exposedName)) {
          throw new Error(`정규화 후 도구명 충돌 발생함: ${exposedName}`);
        }
      }
      for (const { exposedName } of preparedTools) {
        registeredToolNames.add(exposedName);
      }

      for (const { source, exposedName, inputSchema, isWrite } of preparedTools) {
        gateway.registerTool(
          exposedName,
          {
            description: `[${definition.label}] ${source.description ?? source.name}`,
            inputSchema,
            annotations: {
              audience: ['user', 'assistant'],
              priority: 0.5,
              readOnlyHint: !isWrite,
              ...(source.annotations ?? {}),
            },
          },
          async (args) => {
            if (isWrite && !allowWrite) {
              throw new Error(`도구(${source.name})는 쓰기 작업이 허용되지 않아 실행이 차단됨`);
            }
            return client.callTool(source.name, args);
          },
        );
      }

      // 2. 리소스(Resources) 전달 등록
      const resources = await client.listResources();
      let registeredResourcesCount = 0;
      for (const resource of resources) {
        const namespacedUri = `mcp://${definition.id}/${resource.uri.replace('://', '/')}`;
        if (!registeredResourceUris.has(namespacedUri)) {
          registeredResourceUris.add(namespacedUri);
          gateway.registerResource(
            `[${definition.label}] ${resource.name}`,
            namespacedUri,
            {
              description: resource.description,
              mimeType: resource.mimeType ?? 'text/plain',
            },
            async () => {
              return await client.readResource(resource.uri);
            },
          );
          registeredResourcesCount++;
        }
      }

      // 3. 프롬프트(Prompts) 전달 등록
      const prompts = await client.listPrompts();
      let registeredPromptsCount = 0;
      for (const prompt of prompts) {
        const namespacedName = namespacedToolName('mcp', definition.id, prompt.name);
        if (!registeredPromptNames.has(namespacedName)) {
          registeredPromptNames.add(namespacedName);

          const shape: Record<string, z.ZodTypeAny> = {};
          if (prompt.arguments && prompt.arguments.length > 0) {
            for (const arg of prompt.arguments) {
              let fieldSchema = z.string();
              if (arg.description) {
                fieldSchema = fieldSchema.describe(arg.description);
              }
              shape[arg.name] = arg.required ? fieldSchema : fieldSchema.optional();
            }
          }

          gateway.registerPrompt(
            namespacedName,
            {
              description: `[${definition.label}] ${prompt.description ?? prompt.name}`,
              argsSchema: Object.keys(shape).length > 0 ? shape : undefined,
            },
            async (args) => {
              return await client.getPrompt(prompt.name, args as Record<string, string>);
            },
          );
          registeredPromptsCount++;
        }
      }

      clients.push(client);
      serverStatuses.push({
        id: definition.id,
        label: definition.label,
        status: 'ready',
        tools: preparedTools.length,
        resources: registeredResourcesCount,
        prompts: registeredPromptsCount,
      });

      process.stderr.write(
        `[mcp-gateway] ${definition.id}: 도구 ${preparedTools.length}개, 리소스 ${registeredResourcesCount}개, 프롬프트 ${registeredPromptsCount}개 등록 완료함\n`,
      );
    } catch (error) {
      await client.close();
      const errorMessage = describeError(error);
      serverStatuses.push({
        id: definition.id,
        label: definition.label,
        status: 'error',
        tools: 0,
        resources: 0,
        prompts: 0,
        lastError: errorMessage,
      });
      process.stderr.write(
        `[mcp-gateway] ${definition.id}: 연결 건너뜀 (${errorMessage})\n`,
      );
    }
  }

  // 하위 서버 종합 상태 리소스 등록 (장애 및 정상 서버 식별용)
  gateway.registerResource(
    '[mcp-platform] Child Servers Status',
    'mcp://system/servers',
    {
      description: '등록된 하위 MCP 서버들의 상태, 도구/자원 수, 에러 내역을 반환함',
      mimeType: 'application/json',
    },
    async () => ({
      contents: [
        {
          uri: 'mcp://system/servers',
          mimeType: 'application/json',
          text: JSON.stringify(
            {
              servers: serverStatuses,
              totalServers: serverStatuses.length,
              readyServers: serverStatuses.filter((s) => s.status === 'ready').length,
              errorServers: serverStatuses.filter((s) => s.status === 'error').length,
            },
            null,
            2,
          ),
        },
      ],
    }),
  );

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
