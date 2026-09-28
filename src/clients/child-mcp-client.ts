import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface, type Interface } from 'node:readline';

import type { CallToolResult } from '@modelcontextprotocol/server';

export type JsonObject = Record<string, unknown>;
type JsonRpcId = number | string;

type JsonRpcResponse = {
  jsonrpc?: string;
  id?: JsonRpcId | null;
  result?: unknown;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
};

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

export type ChildTool = {
  name: string;
  description?: string;
  inputSchema?: JsonObject;
};

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

/**
 * A small stdio MCP client used by gateway processes to supervise child MCP
 * servers. This is intentionally independent from any specific data source.
 */
export class ChildMcpClient {
  private readonly child: ChildProcessWithoutNullStreams;
  private readonly output: Interface;
  private readonly pending = new Map<JsonRpcId, PendingRequest>();
  private nextRequestId = 1;
  private closed = false;

  constructor(
    private readonly serverId: string,
    private readonly label: string,
    launcherPath: string,
    private readonly requestTimeoutMs = 30_000,
  ) {
    this.child = spawn('/bin/bash', [launcherPath], {
      env: { ...process.env },
      stdio: 'pipe',
    });

    this.output = createInterface({ input: this.child.stdout });
    this.output.on('line', (line) => this.handleLine(line));

    this.child.stderr.setEncoding('utf8');
    this.child.stderr.on('data', (chunk: string) => {
      process.stderr.write(`[mcp-platform:${this.serverId}] ${chunk}`);
    });

    this.child.on('error', (error) => this.failPending(error));
    this.child.on('exit', (code, signal) => {
      if (!this.closed) {
        this.failPending(
          new Error(
            `${this.label} exited before completing the request (code=${code}, signal=${signal})`,
          ),
        );
      }
    });
  }

  private handleLine(line: string): void {
    if (line.trim().length === 0) {
      return;
    }

    let message: JsonRpcResponse;
    try {
      message = JSON.parse(line) as JsonRpcResponse;
    } catch (error) {
      process.stderr.write(
        `[mcp-platform:${this.serverId}] Ignoring non-JSON stdout: ${describeError(error)}\n`,
      );
      return;
    }

    if (message.id === undefined || message.id === null) {
      return;
    }

    const pending = this.pending.get(message.id);
    if (!pending) {
      return;
    }

    this.pending.delete(message.id);
    clearTimeout(pending.timer);

    if (message.error) {
      pending.reject(
        new Error(
          `${this.label} returned MCP error ${message.error.code}: ${message.error.message}`,
        ),
      );
      return;
    }

    pending.resolve(message.result);
  }

  private failPending(error: Error): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
  }

  private request<T>(method: string, params: JsonObject = {}): Promise<T> {
    if (this.closed) {
      return Promise.reject(new Error(`${this.label} is closed`));
    }

    const id = this.nextRequestId++;
    const message = `${JSON.stringify({
      jsonrpc: '2.0',
      id,
      method,
      params,
    })}\n`;

    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${this.label} timed out during ${method}`));
      }, this.requestTimeoutMs);

      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      });
      this.child.stdin.write(message, (error) => {
        if (!error) {
          return;
        }

        this.pending.delete(id);
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  private notify(method: string, params: JsonObject = {}): void {
    if (this.closed) {
      return;
    }

    this.child.stdin.write(
      `${JSON.stringify({ jsonrpc: '2.0', method, params })}\n`,
    );
  }

  async initialize(): Promise<void> {
    await this.request('initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: {
        name: 'mcp-platform-gateway',
        version: '0.1.0',
      },
    });
    this.notify('notifications/initialized');
  }

  async listTools(): Promise<ChildTool[]> {
    const tools: ChildTool[] = [];
    let cursor: string | undefined;

    do {
      const result = await this.request<{ tools?: ChildTool[]; nextCursor?: string }>(
        'tools/list',
        cursor ? { cursor } : {},
      );
      tools.push(...(result.tools ?? []));
      cursor = result.nextCursor;
    } while (cursor);

    return tools;
  }

  async callTool(toolName: string, args: unknown): Promise<CallToolResult> {
    return this.request<CallToolResult>('tools/call', {
      name: toolName,
      arguments: isJsonObject(args) ? args : {},
    });
  }

  close(): void {
    if (this.closed) {
      return;
    }

    this.closed = true;
    this.failPending(new Error(`${this.label} closed`));
    this.output.close();
    this.child.kill('SIGTERM');
  }
}
