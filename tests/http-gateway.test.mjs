/**
 * 파일명: http-gateway.test.mjs
 * 경로: tests/http-gateway.test.mjs
 * 목적: HTTP 게이트웨이의 REST 엔드포인트, 표준 Streamable HTTP 전송(/mcp), 보안 기본값(바인딩, Origin, 토큰)을 검증함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TEST_PORT = 8135;

function fetchJson(url, options = {}) {
  return new Promise((resolve, reject) => {
    const parsedUrl = new URL(url);
    const reqOptions = {
      hostname: parsedUrl.hostname,
      port: parsedUrl.port,
      path: parsedUrl.pathname + parsedUrl.search,
      method: options.method ?? 'GET',
      headers: options.headers ?? {},
    };

    const req = http.request(reqOptions, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, headers: res.headers, body: JSON.parse(data) });
        } catch {
          resolve({ status: res.statusCode, headers: res.headers, body: data });
        }
      });
    });

    req.on('error', reject);
    if (options.body) {
      req.write(typeof options.body === 'string' ? options.body : JSON.stringify(options.body));
    }
    req.end();
  });
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForServer(port) {
  for (let i = 0; i < 30; i++) {
    await wait(150);
    try {
      const res = await fetchJson(`http://127.0.0.1:${port}/health`);
      if (res.status === 200 && res.body.status === 'ok') {
        return true;
      }
    } catch {
      // 재시도
    }
  }
  return false;
}

test('HTTP gateway exposes /health, /tools, /servers, and /cache/stats', async () => {
  const child = spawn('node', ['dist/servers/http-gateway.js'], {
    cwd: projectRoot,
    env: {
      ...process.env,
      MCP_HTTP_PORT: String(TEST_PORT),
      MCP_HTTP_HOST: '127.0.0.1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  try {
    const ready = await waitForServer(TEST_PORT);
    assert.equal(ready, true, `HTTP 게이트웨이가 포트 ${TEST_PORT}에서 응답해야 함`);

    // 1. /tools 및 /api/tools 엔드포인트 검증
    const toolsRes = await fetchJson(`http://127.0.0.1:${TEST_PORT}/api/tools`);
    assert.equal(toolsRes.status, 200);
    assert.equal(toolsRes.body.service, 'mcp-platform-http-gateway');
    assert.ok(Array.isArray(toolsRes.body.tools));
    const toolNames = toolsRes.body.tools.map((x) => x.name);
    assert.ok(toolNames.includes('grep_workspace_files'));
    assert.ok(toolNames.includes('workspace_project_summary'));

    // 2. /servers 엔드포인트 검증
    const serversRes = await fetchJson(`http://127.0.0.1:${TEST_PORT}/api/servers`);
    assert.equal(serversRes.status, 200);
    assert.equal(serversRes.body.success, true);
    assert.ok(serversRes.body.count >= 10);

    // 3. /cache/stats 엔드포인트 검증
    const cacheRes = await fetchJson(`http://127.0.0.1:${TEST_PORT}/api/cache/stats`);
    assert.equal(cacheRes.status, 200);
    assert.equal(cacheRes.body.success, true);
    assert.equal(cacheRes.body.stats.status, 'active');

    // 4. /api/metrics 엔드포인트 및 X-Request-Id 상관 ID 헤더 검증
    const metricsRes = await fetchJson(`http://127.0.0.1:${TEST_PORT}/api/metrics`);
    assert.equal(metricsRes.status, 200);
    assert.equal(metricsRes.body.service, 'mcp-platform');
    assert.ok(typeof metricsRes.body.totalRequests === 'number');
    assert.ok(metricsRes.headers['x-request-id'] !== undefined, 'X-Request-Id 헤더가 존재해야 함');
  } finally {
    child.kill('SIGTERM');
  }
});

test('HTTP gateway serves standard Streamable HTTP over /mcp using official Client SDK', async () => {
  const port = 8136;
  const child = spawn('node', ['dist/servers/http-gateway.js'], {
    cwd: projectRoot,
    env: {
      ...process.env,
      MCP_HTTP_PORT: String(port),
      MCP_HTTP_HOST: '127.0.0.1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  try {
    const ready = await waitForServer(port);
    assert.equal(ready, true);

    const transport = new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`));
    const client = new Client({ name: 'http-test-client', version: '1.0.0' });

    await client.connect(transport);

    // tools/list 호출 검증
    const toolsResult = await client.listTools();
    const toolNames = toolsResult.tools.map((t) => t.name);
    assert.ok(toolNames.includes('platform_status'), 'platform_status 도구가 등록되어 있어야 함');

    // tools/call 호출 검증
    const callResult = await client.callTool({ name: 'platform_status' });
    assert.equal(callResult.isError, undefined);
    assert.match(callResult.content[0].text, /mcp-platform-http-gateway/);

    await client.close();
  } finally {
    child.kill('SIGTERM');
  }
});

test('HTTP gateway security: rejects non-loopback binding when bearer token is missing', async () => {
  const child = spawn('node', ['dist/servers/http-gateway.js'], {
    cwd: projectRoot,
    env: {
      ...process.env,
      MCP_HTTP_PORT: '8138',
      MCP_HTTP_HOST: '0.0.0.0',
      MCP_HTTP_BEARER_TOKEN: '',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stderr = '';
  child.stderr.on('data', (d) => { stderr += d; });

  const exitCode = await new Promise((resolve) => {
    child.on('exit', resolve);
  });

  assert.equal(exitCode, 1, '비루프백 바인딩 시 토큰이 없으면 종료 코드 1로 기동을 거부해야 함');
  assert.match(stderr, /MCP_HTTP_BEARER_TOKEN 환경변수가 반드시 설정되어야 함/);
});

test('HTTP gateway security: blocks untrusted Origin and sets strict CORS headers', async () => {
  const port = 8139;
  const child = spawn('node', ['dist/servers/http-gateway.js'], {
    cwd: projectRoot,
    env: {
      ...process.env,
      MCP_HTTP_PORT: String(port),
      MCP_HTTP_HOST: '127.0.0.1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  try {
    const ready = await waitForServer(port);
    assert.equal(ready, true);

    // 1. 차단 대상 Origin 테스트 (evil.com)
    const evilRes = await fetchJson(`http://127.0.0.1:${port}/api/health`, {
      headers: { Origin: 'http://malicious-website.com' },
    });
    assert.equal(evilRes.status, 403, '허용되지 않은 Origin은 403 Forbidden 차단되어야 함');

    // 2. 허용 대상 Origin 테스트 (localhost)
    const validRes = await fetchJson(`http://127.0.0.1:${port}/api/health`, {
      headers: { Origin: `http://localhost:${port}` },
    });
    assert.equal(validRes.status, 200);
    assert.equal(validRes.headers['access-control-allow-origin'], `http://localhost:${port}`);
    assert.notEqual(validRes.headers['access-control-allow-origin'], '*', '와일드카드(*) CORS는 사용하지 않아야 함');

    // 3. 폐기된 /mcp/events 엔드포인트 410 확인
    const eventsRes = await fetchJson(`http://127.0.0.1:${port}/mcp/events`);
    assert.equal(eventsRes.status, 410, '폐기된 /mcp/events는 410 Gone 응답이어야 함');
  } finally {
    child.kill('SIGTERM');
  }
});
