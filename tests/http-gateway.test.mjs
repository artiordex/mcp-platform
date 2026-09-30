import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TEST_PORT = 8135;

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(data) });
        } catch (err) {
          resolve({ status: res.statusCode, body: data });
        }
      });
    }).on('error', reject);
  });
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test('HTTP gateway exposes /health, /tools, /servers, and /cache/stats', async (t) => {
  const child = spawn('node', ['dist/servers/http-gateway.js'], {
    cwd: projectRoot,
    env: {
      ...process.env,
      MCP_HTTP_PORT: String(TEST_PORT),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  try {
    // 게이트웨이가 뜰 때까지 대기
    let ready = false;
    for (let i = 0; i < 20; i++) {
      await wait(200);
      try {
        const res = await fetchJson(`http://127.0.0.1:${TEST_PORT}/health`);
        if (res.status === 200 && res.body.status === 'ok') {
          ready = true;
          break;
        }
      } catch {
        // 재시도
      }
    }
    assert.equal(ready, true, 'HTTP 게이트웨이가 포트 8135에서 응답해야 함');

    // 1. /tools 엔드포인트 검증
    const toolsRes = await fetchJson(`http://127.0.0.1:${TEST_PORT}/tools`);
    assert.equal(toolsRes.status, 200);
    assert.equal(toolsRes.body.service, 'mcp-platform-http-gateway');
    assert.ok(Array.isArray(toolsRes.body.tools));
    const toolNames = toolsRes.body.tools.map((x) => x.name);
    assert.ok(toolNames.includes('grep_workspace_files'));
    assert.ok(toolNames.includes('workspace_project_summary'));

    // 2. /servers 엔드포인트 검증
    const serversRes = await fetchJson(`http://127.0.0.1:${TEST_PORT}/servers`);
    assert.equal(serversRes.status, 200);
    assert.equal(serversRes.body.success, true);
    assert.ok(serversRes.body.count >= 10);

    // 3. /cache/stats 엔드포인트 검증
    const cacheRes = await fetchJson(`http://127.0.0.1:${TEST_PORT}/cache/stats`);
    assert.equal(cacheRes.status, 200);
    assert.equal(cacheRes.body.success, true);
    assert.equal(cacheRes.body.stats.status, 'active');
  } finally {
    child.kill('SIGTERM');
  }
});
