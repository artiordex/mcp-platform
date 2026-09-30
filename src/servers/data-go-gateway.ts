/**
 * 파일명: data-go-gateway.ts
 * 경로: src/servers/data-go-gateway.ts
 * 목적: 공공데이터(NPS, NTS, PPS 나라장터 등) 및 사내 RAG-vLLM의 도구·리소스·프롬프트를 단일 MCP 프로세스로 통합 제공함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { fromJsonSchema, McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import * as z from 'zod/v4';

import {
  ChildMcpClient,
  describeError,
} from '../clients/child-mcp-client.js';
import { namespacedToolName } from './tool-name.js';
import { isWriteTool, type ServerStatusRecord } from './mcp-gateway.js';

// stdio 통신 환경에서 stdout의 JSON-RPC 프로토콜 순수성을 보장하기 위해 로그를 stderr로 우회함
console.log = (...args: unknown[]) => console.error(...args);

type DataGoServerDefinition = {
  id: string;
  label: string;
  launcher: string;
  envPassthrough: string[];
  allowWriteTools?: boolean;
};

const publicDataEnvironment = [
  'DATA_GO_API_KEY',
  'API_KEY',
  'DART_API_KEY',
  'JUSO_API_KEY',
  'BIZINFO_API_KEY',
  'KIPRIS_API_KEY',
  'RAG_VLLM_URL',
  'RAG_API_KEY',
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'NO_PROXY',
  'http_proxy',
  'https_proxy',
  'no_proxy',
];
const foodSafetyEnvironment = [
  'FOOD_SAFETY_API_KEY',
  'FOOD_API_KEY',
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'NO_PROXY',
  'http_proxy',
  'https_proxy',
  'no_proxy',
];

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../..',
);

// 기본 활성화 서버 목록 (사내 RAG, 기업분석, 나라장터, 국민연금, 금융위, 카탈로그, 식품안전나라, DART, 도로명주소, 지원사업, 특허청)
const defaultServerIds = new Set([
  'rag',
  'corporate_intelligence',
  'pps',
  'nps',
  'fsc',
  'public_data_catalog',
  'food_safety',
  'dart',
  'address',
  'smes',
  'kipris',
]);

const serverDefinitions: DataGoServerDefinition[] = [
  {
    id: 'corporate_intelligence',
    label: 'Corporate Intelligence Hub',
    launcher: 'run-corporate-intelligence.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'rag',
    label: 'Internal RAG-vLLM Knowledge Hub',
    launcher: 'run-internal-rag.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'pps',
    label: 'PPS Narajangteo',
    launcher: 'run-data-go-pps.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'nps',
    label: 'NPS Business Enrollment',
    launcher: 'run-data-go-nps.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'nts',
    label: 'NTS Business Verification',
    launcher: 'run-data-go-nts.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'fsc',
    label: 'FSC Financial Information',
    launcher: 'run-data-go-fsc.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'public_data_catalog',
    label: 'Public Data Portal Catalog',
    launcher: 'run-data-go-catalog.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'food_safety',
    label: 'Food Safety Korea',
    launcher: 'run-data-go-food-safety.sh',
    envPassthrough: foodSafetyEnvironment,
  },
  {
    id: 'dart',
    label: 'OpenDART Corporate Disclosures',
    launcher: 'run-dart-filings.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'address',
    label: 'Address and District Lookup',
    launcher: 'run-address-lookup.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'smes',
    label: 'SMES Support Programs',
    launcher: 'run-smes-programs.sh',
    envPassthrough: publicDataEnvironment,
  },
  {
    id: 'kipris',
    label: 'KIPRIS Patent and Utility Model',
    launcher: 'run-kipris-patents.sh',
    envPassthrough: publicDataEnvironment,
  },
];

function makeToolName(serverId: string, toolName: string): string {
  return namespacedToolName('data_go', serverId, toolName);
}

/**
 * 환경변수(DATA_GO_SERVERS) 또는 기본 설정에 따라 활성화할 서버 목록을 선별함
 */
function enabledDefinitions(): DataGoServerDefinition[] {
  const requested = process.env.DATA_GO_SERVERS?.split(',')
    .map((value) => value.trim())
    .filter(Boolean);

  if (!requested || requested.length === 0) {
    return serverDefinitions.filter(({ id }) => defaultServerIds.has(id));
  }

  const byId = new Map(serverDefinitions.map((definition) => [definition.id, definition]));
  return requested.flatMap((id) => {
    const definition = byId.get(id);
    if (!definition) {
      process.stderr.write(`[data-go] DATA_GO_SERVERS에 알 수 없는 서버 식별자임: ${id}\n`);
      return [];
    }
    return [definition];
  });
}

/**
 * 복수의 공공데이터/RAG 서버를 단일 게이트웨이로 취합하여 초기화함
 */
async function createGateway(clients: ChildMcpClient[]): Promise<McpServer> {
  const gateway = new McpServer({
    name: 'data-go-mcp-gateway',
    version: '0.1.0',
  });

  const closeGateway = gateway.close.bind(gateway);
  gateway.close = async () => {
    await Promise.allSettled(clients.map((client) => client.close()));
    clients.splice(0, clients.length);
    await closeGateway();
  };

  const registeredToolNames = new Set<string>();
  const registeredResourceUris = new Set<string>();
  const registeredPromptNames = new Set<string>();
  const serverStatuses: ServerStatusRecord[] = [];
  const globalAllowWrite = process.env.MCP_ALLOW_WRITE_TOOLS === 'true';

  for (const definition of enabledDefinitions()) {
    const client = new ChildMcpClient(definition.id, definition.label, {
      command: '/bin/bash',
      args: [`scripts/${definition.launcher}`],
      cwd: projectRoot,
      envPassthrough: definition.envPassthrough,
    });

    try {
      await client.initialize();
      const allowWrite = definition.allowWriteTools || globalAllowWrite;

      // 1. 도구(Tools) 등록
      const tools = await client.listTools();
      let registeredToolsCount = 0;

      for (const tool of tools) {
        const isWrite = isWriteTool(tool.name, tool.annotations);
        if (isWrite && !allowWrite) {
          process.stderr.write(
            `[data-go] ${definition.id}: 쓰기 도구(${tool.name})는 비활성화 기본값에 따라 제외됨\n`,
          );
          continue;
        }

        const exposedName = makeToolName(definition.id, tool.name);
        if (registeredToolNames.has(exposedName)) {
          throw new Error(`도구명 충돌 발생함: ${exposedName}`);
        }
        registeredToolNames.add(exposedName);

        gateway.registerTool(
          exposedName,
          {
            description: `[${definition.label}] ${tool.description ?? tool.name}`,
            inputSchema: fromJsonSchema(
              (tool.inputSchema ?? {
                type: 'object',
                properties: {},
                additionalProperties: false,
              }) as Parameters<typeof fromJsonSchema>[0],
            ),
            annotations: {
              audience: ['user', 'assistant'],
              priority: 0.5,
              readOnlyHint: !isWrite,
              ...(tool.annotations ?? {}),
            },
          },
          async (args) => {
            if (isWrite && !allowWrite) {
              throw new Error(`도구(${tool.name})는 쓰기 작업이 허용되지 않아 실행이 차단됨`);
            }
            return client.callTool(tool.name, args);
          },
        );
        registeredToolsCount++;
      }

      // 2. 리소스(Resources) 등록
      const resources = await client.listResources();
      let registeredResourcesCount = 0;
      for (const resource of resources) {
        const namespacedUri = `data_go://${definition.id}/${resource.uri.replace('://', '/')}`;
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

      // 3. 프롬프트(Prompts) 등록
      const prompts = await client.listPrompts();
      let registeredPromptsCount = 0;
      for (const prompt of prompts) {
        const namespacedName = namespacedToolName('data_go', definition.id, prompt.name);
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
        tools: registeredToolsCount,
        resources: registeredResourcesCount,
        prompts: registeredPromptsCount,
      });

      process.stderr.write(
        `[data-go] ${definition.id}: 도구 ${registeredToolsCount}개, 리소스 ${registeredResourcesCount}개, 프롬프트 ${registeredPromptsCount}개 등록 완료함\n`,
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
        `[data-go] ${definition.id}: 연결 건너뜀 (${errorMessage})\n`,
      );
    }
  }

  // 공공데이터 하위 서버 종합 상태 리소스 등록 (진단용)
  gateway.registerResource(
    '[data-go] Child Servers Status',
    'data_go://system/servers',
    {
      description: '공공데이터 및 RAG 하위 서버들의 상태, 도구/자원 수, 에러 내역을 반환함',
      mimeType: 'application/json',
    },
    async () => ({
      contents: [
        {
          uri: 'data_go://system/servers',
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

console.error('Data.go.kr MCP gateway running on stdio');
