/**
 * 파일명: data-go-gateway.ts
 * 경로: src/servers/data-go-gateway.ts
 * 목적: 공공데이터(NPS, NTS, PPS 나라장터 등) 및 사내 RAG-vLLM을 단일 MCP 프로세스로 통합 제공함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { fromJsonSchema, McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';

import {
  ChildMcpClient,
  describeError,
  type ChildTool,
} from '../clients/child-mcp-client.js';
import { namespacedToolName } from './tool-name.js';

type DataGoServerDefinition = {
  id: string;
  label: string;
  launcher: string;
  envPassthrough: string[];
};

const publicDataEnvironment = [
  'DATA_GO_API_KEY',
  'API_KEY',
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

// 기본 활성화 서버 목록 (사내 RAG, 나라장터, 기업분석, 국민연금, 금융위, 카탈로그, 식품안전나라)
const defaultServerIds = new Set([
  'rag',
  'corporate_intelligence',
  'pps',
  'nps',
  'fsc',
  'public_data_catalog',
  'food_safety',
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
  const registeredNames = new Set<string>();

  for (const definition of enabledDefinitions()) {
    const client = new ChildMcpClient(definition.id, definition.label, {
      command: '/bin/bash',
      args: [`scripts/${definition.launcher}`],
      cwd: projectRoot,
      envPassthrough: definition.envPassthrough,
    });

    try {
      await client.initialize();
      const tools = await client.listTools();

      for (const tool of tools) {
        const exposedName = makeToolName(definition.id, tool.name);
        if (registeredNames.has(exposedName)) {
          throw new Error(`도구명 충돌 발생함: ${exposedName}`);
        }
        registeredNames.add(exposedName);

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
          },
          async (args) => client.callTool(tool.name, args),
        );
      }

      clients.push(client);
      process.stderr.write(
        `[data-go] ${definition.id}: 도구 ${tools.length}개 등록 완료함\n`,
      );
    } catch (error) {
      await client.close();
      process.stderr.write(
        `[data-go] ${definition.id}: 연결 건너뜀 (${describeError(error)})\n`,
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

console.error('Data.go.kr MCP gateway running on stdio');
