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
    }, 'Use an HTTP(S) URL without embedded credentials, query parameters, or fragments.'),
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

function configPath(): string {
  const configuredPath = process.env.MCP_SERVERS_CONFIG ?? 'config/mcp-servers.json';
  return path.resolve(projectRoot, configuredPath);
}

async function loadGatewayConfig(): Promise<GatewayConfig> {
  const filename = configPath();
  let contents: string;
  try {
    contents = await fs.readFile(filename, 'utf8');
  } catch (error) {
    throw new Error(
      `Could not read MCP server config at ${filename}. Copy ` +
        'config/mcp-servers.example.json to config/mcp-servers.json, then edit it.',
      { cause: error },
    );
  }

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(contents) as unknown;
  } catch (error) {
    throw new Error(`MCP server config is not valid JSON: ${describeError(error)}`, {
      cause: error,
    });
  }

  const config = GatewayConfigSchema.safeParse(parsedJson);
  if (!config.success) {
    throw new Error(`MCP server config is invalid: ${config.error.message}`);
  }

  const seenIds = new Set<string>();
  for (const server of config.data.servers) {
    if (seenIds.has(server.id)) {
      throw new Error(`MCP server config contains duplicate id: ${server.id}`);
    }
    seenIds.add(server.id);
  }

  return config.data;
}

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

function prepareTools(serverId: string, tools: ChildTool[]): PreparedTool[] {
  const localNames = new Set<string>();
  return tools.map((tool) => {
    if (localNames.has(tool.name)) {
      throw new Error(`Child server ${serverId} returned duplicate tool name: ${tool.name}`);
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
          throw new Error(`Tool name collision after normalization: ${exposedName}`);
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
        `[mcp-gateway] ${definition.id}: registered ${tools.length} tools\n`,
      );
    } catch (error) {
      await client.close();
      process.stderr.write(
        `[mcp-gateway] ${definition.id}: skipped (${describeError(error)})\n`,
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
