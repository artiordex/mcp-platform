import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { fromJsonSchema, McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';

import {
  ChildMcpClient,
  describeError,
  type ChildTool,
} from '../clients/child-mcp-client.js';

type DataGoServerDefinition = {
  id: string;
  label: string;
  launcher: string;
};

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
  { id: 'nps', label: 'NPS Business Enrollment', launcher: 'run-data-go-nps.sh' },
  { id: 'nts', label: 'NTS Business Verification', launcher: 'run-data-go-nts.sh' },
  { id: 'pps', label: 'PPS Narajangteo', launcher: 'run-data-go-pps.sh' },
  { id: 'fsc', label: 'FSC Financial Information', launcher: 'run-data-go-fsc.sh' },
  {
    id: 'public_data_catalog',
    label: 'Public Data Portal Catalog',
    launcher: 'run-data-go-catalog.sh',
  },
  {
    id: 'food_safety',
    label: 'Food Safety Korea',
    launcher: 'run-data-go-food-safety.sh',
  },
];

function makeToolName(serverId: string, toolName: string): string {
  const normalized = `data_go_${serverId}_${toolName}`.replace(
    /[^a-zA-Z0-9_-]/g,
    '_',
  );
  return normalized.slice(0, 64);
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
    for (const client of clients) {
      client.close();
    }
    clients.splice(0, clients.length);
    await closeGateway();
  };

  for (const definition of enabledDefinitions()) {
    const launcherPath = path.join(projectRoot, 'scripts', definition.launcher);
    const client = new ChildMcpClient(definition.id, definition.label, launcherPath);

    try {
      await client.initialize();
      const tools = await client.listTools();

      for (const tool of tools) {
        const exposedName = makeToolName(definition.id, tool.name);
        const inputSchema = fromJsonSchema(
          tool.inputSchema ?? {
            type: 'object',
            properties: {},
            additionalProperties: false,
          },
        );

        gateway.registerTool(
          exposedName,
          {
            description: `[${definition.label}] ${tool.description ?? tool.name}`,
            inputSchema,
          },
          async (args) => client.callTool(tool.name, args),
        );
      }

      clients.push(client);
      process.stderr.write(
        `[data-go] ${definition.id}: registered ${tools.length} tools\n`,
      );
    } catch (error) {
      client.close();
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

function closeChildren(): void {
  for (const client of activeClients) {
    client.close();
  }
  activeClients = [];
}

const shutdown = async (): Promise<void> => {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  closeChildren();
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
  closeChildren();
  gatewayReady = createGateway(activeClients);
  gatewayStartedResolve?.();
  return gatewayReady;
});

console.error('data-go-mcp-gateway MCP server running on stdio');
