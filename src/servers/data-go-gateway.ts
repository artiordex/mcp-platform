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
const defaultServerIds = new Set([
  'nps',
  'fsc',
  'public_data_catalog',
  'food_safety',
]);

const serverDefinitions: DataGoServerDefinition[] = [
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
    id: 'pps',
    label: 'PPS Narajangteo',
    launcher: 'run-data-go-pps.sh',
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
      process.stderr.write(`[data-go] Unknown server in DATA_GO_SERVERS: ${id}\n`);
      return [];
    }
    return [definition];
  });
}

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
    const launcherPath = path.join(projectRoot, 'scripts', definition.launcher);
    const client = new ChildMcpClient(definition.id, definition.label, {
      transport: 'stdio',
      command: '/bin/bash',
      args: [launcherPath],
      cwd: projectRoot,
      envPassthrough: definition.envPassthrough,
    });

    try {
      await client.initialize();
      const tools = await client.listTools();

      const preparedTools = tools.map((tool) => ({
        source: tool,
        exposedName: makeToolName(definition.id, tool.name),
        inputSchema: fromJsonSchema(
          (tool.inputSchema ?? {
            type: 'object',
            properties: {},
            additionalProperties: false,
          }) as Parameters<typeof fromJsonSchema>[0],
        ),
      }));
      const localNames = new Set<string>();
      for (const { exposedName } of preparedTools) {
        if (registeredNames.has(exposedName) || localNames.has(exposedName)) {
          throw new Error(`Tool name collision after normalization: ${exposedName}`);
        }
        localNames.add(exposedName);
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
        registeredNames.add(exposedName);
      }

      clients.push(client);
      process.stderr.write(
        `[data-go] ${definition.id}: registered ${tools.length} tools\n`,
      );
    } catch (error) {
      await client.close();
      process.stderr.write(
        `[data-go] ${definition.id}: skipped (${describeError(error)})\n`,
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
  await Promise.allSettled(activeClients.map((client) => client.close()));
  activeClients = [];
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
process.once('exit', () => closeChildren());

handle = serveStdio(async () => {
  await closeChildren();
  gatewayReady = createGateway(activeClients);
  gatewayStartedResolve?.();
  return gatewayReady;
});

console.error('data-go-mcp-gateway MCP server running on stdio');
