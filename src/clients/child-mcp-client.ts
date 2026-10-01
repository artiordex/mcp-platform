/**
 * 파일명: child-mcp-client.ts
 * 경로: src/clients/child-mcp-client.ts
 * 목적: 하위 MCP 서버 프로세스(stdio) 및 원격 엔드포인트(HTTP)와의 연결·도구·리소스·프롬프트 통신을 감독함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

import {
  Client,
  StreamableHTTPClientTransport,
  type CallToolResult,
  type Transport,
} from '@modelcontextprotocol/client';
import {
  StdioClientTransport,
  type StdioServerParameters,
} from '@modelcontextprotocol/client/stdio';
import { type Stream } from 'node:stream';

export type JsonObject = Record<string, unknown>;

export type ChildClientStatus = 'uninitialized' | 'ready' | 'error' | 'stopped';

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

export type ChildTool = {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
  annotations?: {
    audience?: string[];
    priority?: number;
    readOnlyHint?: boolean;
    [key: string]: unknown;
  };
};

export type ChildResource = {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
  annotations?: {
    audience?: string[];
    priority?: number;
    [key: string]: unknown;
  };
};

export type ChildPrompt = {
  name: string;
  description?: string;
  arguments?: Array<{
    name: string;
    description?: string;
    required?: boolean;
  }>;
};

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
  private client!: Client;
  private transport!: Transport;
  private readonly requestTimeoutMs: number;
  private readonly secrets: string[] = [];
  private closed = false;
  private closing: Promise<void> | undefined;
  private reconnecting: Promise<boolean> | undefined;
  private _status: ChildClientStatus = 'uninitialized';
  private _lastError: string | undefined;
  private _reconnectAttempts = 0;
  private _lastConnectedAt: Date | undefined;

  constructor(
    private readonly serverId: string,
    private readonly label: string,
    private readonly config: ChildMcpServerConfig,
  ) {
    this.requestTimeoutMs = config.requestTimeoutMs ?? 30_000;
    this.setupTransport();
  }

  get id(): string {
    return this.serverId;
  }

  get displayName(): string {
    return this.label;
  }

  get status(): ChildClientStatus {
    return this._status;
  }

  get lastError(): string | undefined {
    return this._lastError;
  }

  get reconnectAttempts(): number {
    return this._reconnectAttempts;
  }

  get lastConnectedAt(): Date | undefined {
    return this._lastConnectedAt;
  }

  safeErrorMessage(error: unknown): string {
    return redactSecrets(describeError(error) || String(error), this.secrets);
  }

  private safeError(error: unknown): Error {
    const safe = new Error(this.safeErrorMessage(error));
    if (error instanceof Error) safe.name = error.name;
    return safe;
  }

  /**
   * 설정에 맞는 MCP 클라이언트 및 트랜스포트를 초기화함
   */
  private setupTransport(): void {
    this.client = new Client({ name: 'mcp-platform-gateway', version: '0.1.0' });

    if (this.config.transport === 'streamable-http') {
      const headers: Record<string, string> = {};
      for (const [headerName, environmentName] of Object.entries(
        this.config.headersFromEnv ?? {},
      )) {
        const value = process.env[environmentName];
        if (value !== undefined) {
          headers[headerName] = value;
          if (!this.secrets.includes(value)) {
            this.secrets.push(value);
          }
        }
      }
      const url = new URL(this.config.url);
      this.transport = new StreamableHTTPClientTransport(url, {
        requestInit: { headers },
      });
    } else {
      const env = selectedEnvironment(this.config.envPassthrough ?? []);
      for (const val of Object.values(env)) {
        if (!this.secrets.includes(val)) {
          this.secrets.push(val);
        }
      }
      const stdioTransport = new StdioClientTransport({
        command: this.config.command,
        args: this.config.args,
        cwd: this.config.cwd,
        env,
        maxBufferSize: this.config.maxBufferSize,
        stderr: 'pipe',
      });
      this.transport = stdioTransport;
      const stderr = stdioTransport.stderr;
      if (stderr) {
        this.pipeChildStderr(stderr);
      }
    }

    this.transport.onerror = (error) => {
      this._lastError = this.safeErrorMessage(error);
      this._status = 'error';
      process.stderr.write(
        `[mcp-platform:${this.serverId}] ${this._lastError}\n`,
      );
    };
    this.transport.onclose = () => {
      if (!this.closed) {
        this._status = 'error';
        this._lastError ??= '하위 MCP 서버 연결이 예기치 않게 종료됨';
      }
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
    if (this.closed) {
      throw new Error(`이미 종료된 서버(${this.serverId})는 초기화할 수 없음`);
    }

    try {
      await this.client.connect(this.transport, { timeout: this.requestTimeoutMs });
      if (this.closed) {
        await this.client.close();
        throw new Error(`연결 중 종료 요청을 받은 서버(${this.serverId})임`);
      }
      this._status = 'ready';
      this._lastError = undefined;
      this._lastConnectedAt = new Date();
      this._reconnectAttempts = 0;
    } catch (error) {
      if (!this.closed) {
        this._status = 'error';
        this._lastError = this.safeErrorMessage(error);
      }
      throw this.safeError(error);
    }
  }

  /**
   * 연결이 유효하지 않을 때 지수 백오프로 재연결을 시도함
   */
  async ensureConnected(maxRetries = 2): Promise<boolean> {
    if (this.closed) return false;
    if (this._status === 'ready') return true;

    if (this.reconnecting) return this.reconnecting;

    const reconnecting = this.reconnect(maxRetries);
    this.reconnecting = reconnecting;
    try {
      return await reconnecting;
    } finally {
      if (this.reconnecting === reconnecting) this.reconnecting = undefined;
    }
  }

  private async reconnect(maxRetries: number): Promise<boolean> {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      if (this.closed) return false;
      this._reconnectAttempts++;
      const backoffMs = Math.min(200 * Math.pow(2, attempt - 1), 2000);
      await new Promise((resolve) => setTimeout(resolve, backoffMs));
      if (this.closed) return false;

      try {
        // 기존 연결 정리 후 트랜스포트 재생성
        try {
          await this.client.close();
        } catch {
          // 닫기 실패는 무시함
        }
        this.setupTransport();
        await this.initialize();
        return true;
      } catch (error) {
        this._lastError = this.safeErrorMessage(error);
      }
    }

    return false;
  }

  /**
   * 하위 서버가 제공하는 도구 목록을 조회함
   */
  async listTools(): Promise<ChildTool[]> {
    if (this._status !== 'ready') {
      const connected = await this.ensureConnected();
      if (!connected) throw new Error(`하위 서버(${this.serverId}) 재연결에 실패함`);
    }
    const capabilities = this.client.getServerCapabilities();
    if (!capabilities?.tools) {
      return [];
    }
    try {
      const result = await this.client.listTools({}, { timeout: this.requestTimeoutMs });
      return (result.tools ?? []) as ChildTool[];
    } catch (error) {
      this._lastError = this.safeErrorMessage(error);
      throw this.safeError(error);
    }
  }

  /** 하위 서버의 도구를 호출함. 응답 유실 시 중복 실행될 수 있어 자동 재시도하지 않음 */
  async callTool(toolName: string, args: unknown): Promise<CallToolResult> {
    if (this.closed) throw new Error(`이미 종료된 서버(${this.serverId})임`);
    if (this._status !== 'ready' && !(await this.ensureConnected())) {
      throw new Error(`하위 서버(${this.serverId}) 재연결에 실패함`);
    }

    try {
      return await this.client.callTool(
        {
          name: toolName,
          arguments: isJsonObject(args) ? args : {},
        },
        { timeout: this.requestTimeoutMs },
      );
    } catch (error) {
      this._lastError = this.safeErrorMessage(error);
      throw this.safeError(error);
    }
  }

  /**
   * 하위 서버가 제공하는 리소스 목록을 조회함
   */
  async listResources(): Promise<ChildResource[]> {
    if (this._status !== 'ready') {
      const connected = await this.ensureConnected();
      if (!connected) throw new Error(`하위 서버(${this.serverId}) 재연결에 실패함`);
    }
    const capabilities = this.client.getServerCapabilities();
    if (!capabilities?.resources) {
      return [];
    }
    try {
      const result = await this.client.listResources({}, { timeout: this.requestTimeoutMs });
      return (result.resources ?? []) as ChildResource[];
    } catch (error) {
      this._lastError = this.safeErrorMessage(error);
      throw this.safeError(error);
    }
  }

  /**
   * 하위 서버의 특정 리소스를 URI로 읽음 (장애 시 1회 재연결 및 재시도)
   */
  async readResource(uri: string): Promise<Awaited<ReturnType<Client['readResource']>>> {
    if (this.closed) throw new Error(`이미 종료된 서버(${this.serverId})임`);
    if (this._status !== 'ready' && !(await this.ensureConnected())) {
      throw new Error(`하위 서버(${this.serverId}) 재연결에 실패함`);
    }

    try {
      return await this.client.readResource({ uri }, { timeout: this.requestTimeoutMs });
    } catch (error) {
      const recovered = this._status !== 'ready' && (await this.ensureConnected(1));
      if (recovered) {
        try {
          return await this.client.readResource({ uri }, { timeout: this.requestTimeoutMs });
        } catch (retryError) {
          this._lastError = this.safeErrorMessage(retryError);
          throw this.safeError(retryError);
        }
      }
      this._lastError = this.safeErrorMessage(error);
      throw this.safeError(error);
    }
  }

  /**
   * 하위 서버가 제공하는 프롬프트 목록을 조회함
   */
  async listPrompts(): Promise<ChildPrompt[]> {
    if (this._status !== 'ready') {
      const connected = await this.ensureConnected();
      if (!connected) throw new Error(`하위 서버(${this.serverId}) 재연결에 실패함`);
    }
    const capabilities = this.client.getServerCapabilities();
    if (!capabilities?.prompts) {
      return [];
    }
    try {
      const result = await this.client.listPrompts({}, { timeout: this.requestTimeoutMs });
      return (result.prompts ?? []) as ChildPrompt[];
    } catch (error) {
      this._lastError = this.safeErrorMessage(error);
      throw this.safeError(error);
    }
  }

  /**
   * 하위 서버의 특정 프롬프트를 인자와 함께 가져옴 (장애 시 1회 재연결 및 재시도)
   */
  async getPrompt(
    name: string,
    args?: Record<string, string>,
  ): Promise<Awaited<ReturnType<Client['getPrompt']>>> {
    if (this.closed) throw new Error(`이미 종료된 서버(${this.serverId})임`);
    if (this._status !== 'ready' && !(await this.ensureConnected())) {
      throw new Error(`하위 서버(${this.serverId}) 재연결에 실패함`);
    }

    try {
      return await this.client.getPrompt(
        { name, arguments: args },
        { timeout: this.requestTimeoutMs },
      );
    } catch (error) {
      const recovered = this._status !== 'ready' && (await this.ensureConnected(1));
      if (recovered) {
        try {
          return await this.client.getPrompt(
            { name, arguments: args },
            { timeout: this.requestTimeoutMs },
          );
        } catch (retryError) {
          this._lastError = this.safeErrorMessage(retryError);
          throw this.safeError(retryError);
        }
      }
      this._lastError = this.safeErrorMessage(error);
      throw this.safeError(error);
    }
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
    this._status = 'stopped';
    this.closing = this.client.close();
    return this.closing;
  }
}
