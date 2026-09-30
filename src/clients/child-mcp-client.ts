/**
 * 파일명: child-mcp-client.ts
 * 경로: src/clients/child-mcp-client.ts
 * 목적: 하위 MCP 서버 프로세스(stdio) 및 원격 엔드포인트(HTTP)와의 연결·도구 호출을 감독함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

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
      /** 하위 프로세스에 상속을 허용할 환경변수 이름 목록임 */
      envPassthrough?: string[];
      requestTimeoutMs?: number;
    })
  | {
      transport: 'streamable-http';
      url: string;
      /** HTTP 헤더명과 주입할 부모 환경변수명 매핑임 */
      headersFromEnv?: Record<string, string>;
      requestTimeoutMs?: number;
    };

export type ChildTool = Pick<Tool, 'name' | 'description' | 'inputSchema'>;

/**
 * 값이 유효한 JSON 객체인지 검증함
 */
export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * 오류 객체를 사람이 읽기 쉬운 문자열로 변환함
 */
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
 * 허용된 환경변수만 추출하여 자식 프로세스 주입용 딕셔너리를 구성함
 */
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

/**
 * 로그 및 오류 메시지에서 비밀 키를 안전하게 마스킹함
 */
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
 * 하위 MCP 서버 프로세스를 관리하고 통신하는 재사용 클라이언트 클래스임
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

  /**
   * 하위 서버와 MCP 핸드셰이크 프로토콜 연결을 수행함
   */
  async initialize(): Promise<void> {
    await this.client.connect(this.transport, { timeout: this.requestTimeoutMs });
  }

  /**
   * 하위 서버가 제공하는 도구 목록을 조회함
   */
  async listTools(): Promise<ChildTool[]> {
    const result = await this.client.listTools({}, { timeout: this.requestTimeoutMs });
    return result.tools;
  }

  /**
   * 하위 서버의 특정 도구를 인자와 함께 호출함
   */
  async callTool(toolName: string, args: unknown): Promise<CallToolResult> {
    return this.client.callTool(
      {
        name: toolName,
        arguments: isJsonObject(args) ? args : {},
      },
      { timeout: this.requestTimeoutMs },
    );
  }

  /**
   * 하위 서버 연결 및 프로세스를 정상 종료함
   */
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
