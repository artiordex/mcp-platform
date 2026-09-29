import {
  Client,
  StreamableHTTPClientTransport,
  type CallToolResult,
  type Tool,
  type Transport,
} from '@modelcontextprotocol/client';
import {
  StdioClientTransport,
  type StdioServerParameters,
} from '@modelcontextprotocol/client/stdio';
import { type Stream } from 'node:stream';

export type JsonObject = Record<string, unknown>;

export type ChildMcpServerConfig =
  | (Pick<StdioServerParameters, 'command' | 'args' | 'cwd' | 'maxBufferSize'> & {
      transport?: 'stdio';
      /** Parent environment variables that this child is allowed to receive. */
      envPassthrough?: string[];
      requestTimeoutMs?: number;
    })
  | {
      transport: 'streamable-http';
      url: string;
      /** HTTP header name to parent environment variable name. */
      headersFromEnv?: Record<string, string>;
      requestTimeoutMs?: number;
    };

export type ChildTool = Pick<Tool, 'name' | 'description' | 'inputSchema'>;

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function describeError(value: unknown): string {
  if (value instanceof Error) {
    return value.message;
  }

  if (typeof value === 'string') {
    return value;
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function selectedEnvironment(names: string[]): Record<string, string> {
  const environment: Record<string, string> = {};
  for (const name of names) {
    const value = process.env[name];
    if (value !== undefined) {
      environment[name] = value;
    }
  }
  return environment;
}

function redactSecrets(text: string, secrets: string[]): string {
  return secrets
    .filter((secret) => secret.length > 0)
    .sort((left, right) => right.length - left.length)
    .reduce((result, secret) => {
      const encoded = encodeURIComponent(secret);
      return result
        .split(secret).join('[REDACTED]')
        .split(encoded).join('[REDACTED]');
    }, text);
}

/**
 * A reusable MCP client for supervising configured child servers.
 * The official SDK owns protocol negotiation, JSON-RPC framing, timeouts,
 * pagination, and process shutdown.
 */
export class ChildMcpClient {
  private readonly client: Client;
  private readonly transport: Transport;
  private readonly requestTimeoutMs: number;
  private readonly secrets: string[] = [];
  private closed = false;
  private closing: Promise<void> | undefined;

  constructor(
    private readonly serverId: string,
    private readonly label: string,
    config: ChildMcpServerConfig,
  ) {
    this.requestTimeoutMs = config.requestTimeoutMs ?? 30_000;
    this.client = new Client({ name: 'mcp-platform-gateway', version: '0.1.0' });
    if (config.transport === 'streamable-http') {
      const headers: Record<string, string> = {};
      for (const [headerName, environmentName] of Object.entries(
        config.headersFromEnv ?? {},
      )) {
        const value = process.env[environmentName];
        if (value !== undefined) {
          headers[headerName] = value;
          this.secrets.push(value);
        }
      }
      const url = new URL(config.url);
      this.transport = new StreamableHTTPClientTransport(url, {
        requestInit: { headers },
      });
    } else {
      const env = selectedEnvironment(config.envPassthrough ?? []);
      this.secrets.push(...Object.values(env));
      const stdioTransport = new StdioClientTransport({
        command: config.command,
        args: config.args,
        cwd: config.cwd,
        env,
        maxBufferSize: config.maxBufferSize,
        stderr: 'pipe',
      });
      this.transport = stdioTransport;
      const stderr = stdioTransport.stderr;
      if (stderr) {
        this.pipeChildStderr(stderr);
      }
    }

    this.transport.onerror = (error) => {
      process.stderr.write(
        `[mcp-platform:${this.serverId}] ${redactSecrets(error.message, this.secrets)}\n`,
      );
    };
  }

  private pipeChildStderr(stderr: Stream): void {
    stderr.on('data', (chunk: Buffer | string) => {
      const message = redactSecrets(String(chunk), this.secrets);
      process.stderr.write(`[mcp-platform:${this.serverId}] ${message}`);
    });
  }

  async initialize(): Promise<void> {
    await this.client.connect(this.transport, { timeout: this.requestTimeoutMs });
  }

  async listTools(): Promise<ChildTool[]> {
    const result = await this.client.listTools({}, { timeout: this.requestTimeoutMs });
    return result.tools;
  }

  async callTool(toolName: string, args: unknown): Promise<CallToolResult> {
    return this.client.callTool(
      {
        name: toolName,
        arguments: isJsonObject(args) ? args : {},
      },
      { timeout: this.requestTimeoutMs },
    );
  }

  close(): Promise<void> {
    if (this.closing) {
      return this.closing;
    }
    if (this.closed) {
      return Promise.resolve();
    }

    this.closed = true;
    this.closing = this.client.close();
    return this.closing;
  }
}
