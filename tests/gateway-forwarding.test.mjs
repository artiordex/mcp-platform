/**
 * 파일명: gateway-forwarding.test.mjs
 * 경로: tests/gateway-forwarding.test.mjs
 * 목적: mcp-gateway의 도구·리소스·프롬프트 포워딩, 네임스페이스, 쓰기 정책, 장애 격리 기능을 종합 검증함
 * 작성자: AI전략팀
 * 작성일: 2026-09-30
 * 수정일: 2026-09-30
 */

import assert from 'node:assert/strict';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { Client } from '@modelcontextprotocol/client';
import { StdioClientTransport } from '@modelcontextprotocol/client/stdio';

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
);
const pythonBin = process.env.PYTHON ?? 'python3';
const fixtureServer = path.join(
  projectRoot,
  'tests/fixtures/comprehensive_fake_mcp_server.py',
);

test('generic gateway forwards tools, resources, and prompts with safety and fault tolerance', async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'mcp-gateway-forwarding-'));
  const configPath = path.join(tempDir, 'mcp-servers.json');

  const config = {
    name: 'test-forwarding-gateway',
    servers: [
      {
        id: 'comp',
        label: 'Comprehensive Server',
        transport: 'stdio',
        command: pythonBin,
        args: [fixtureServer],
        cwd: projectRoot,
        allowWriteTools: false,
      },
      {
        id: 'broken',
        label: 'Unreachable Server',
        transport: 'stdio',
        command: 'invalid-non-existent-binary-12345',
        args: [],
        cwd: projectRoot,
      },
    ],
  };

  await fs.writeFile(configPath, JSON.stringify(config, null, 2), 'utf8');

  const transport = new StdioClientTransport({
    command: 'node',
    args: ['dist/servers/mcp-gateway.js'],
    cwd: projectRoot,
    env: {
      ...process.env,
      MCP_SERVERS_CONFIG: configPath,
      MCP_ALLOW_WRITE_TOOLS: 'false',
    },
    stderr: 'pipe',
  });

  const client = new Client({ name: 'gateway-test-client', version: '1.0.0' });

  try {
    await client.connect(transport);

    // 1. 도구(Tools) 포워딩 및 쓰기 도구 기본 비활성화 검증
    const toolsResult = await client.listTools();
    const toolNames = toolsResult.tools.map((t) => t.name);
    assert.ok(toolNames.includes('mcp_comp_echo'), '네임스페이스 도구 mcp_comp_echo가 등록되어야 함');
    assert.equal(
      toolNames.includes('mcp_comp_create_item'),
      false,
      '쓰기 도구(create_item)는 allowWriteTools: false 시 기본 비활성화되어야 함',
    );

    // 도구 호출 검증
    const callResult = await client.callTool({
      name: 'mcp_comp_echo',
      arguments: { msg: '안녕 게이트웨이' },
    });
    assert.equal(callResult.isError, undefined);
    assert.match(callResult.content[0].text, /Echo: 안녕 게이트웨이/);

    // 2. 리소스(Resources) 포워딩 및 읽기 검증
    const resourcesResult = await client.listResources();
    const resourceUris = resourcesResult.resources.map((r) => r.uri);
    assert.ok(
      resourceUris.includes('mcp://comp/fake/catalog/sample'),
      '네임스페이스 리소스 mcp://comp/fake/catalog/sample이 등록되어야 함',
    );
    assert.ok(
      resourceUris.includes('mcp://system/servers'),
      '시스템 상태 리소스 mcp://system/servers가 등록되어야 함',
    );

    // 자식 리소스 읽기
    const readResult = await client.readResource({ uri: 'mcp://comp/fake/catalog/sample' });
    assert.equal(readResult.contents.length, 1);
    const parsedResource = JSON.parse(readResult.contents[0].text);
    assert.equal(parsedResource.status, 'active');
    assert.deepEqual(parsedResource.items, ['alpha', 'beta']);

    // 3. 프롬프트(Prompts) 포워딩 및 가져오기 검증
    const promptsResult = await client.listPrompts();
    const promptNames = promptsResult.prompts.map((p) => p.name);
    assert.ok(
      promptNames.includes('mcp_comp_generate_report'),
      '네임스페이스 프롬프트 mcp_comp_generate_report가 등록되어야 함',
    );

    const promptRes = await client.getPrompt({
      name: 'mcp_comp_generate_report',
      arguments: { topic: '인공지능' },
    });
    assert.ok(promptRes.messages.length > 0);
    assert.match(promptRes.messages[0].content.text, /report about 인공지능/);

    // 4. 장애 격리 및 서버 상태 리소스 검증
    const statusResource = await client.readResource({ uri: 'mcp://system/servers' });
    const statusData = JSON.parse(statusResource.contents[0].text);
    assert.equal(statusData.totalServers, 2);
    assert.equal(statusData.readyServers, 1);
    assert.equal(statusData.errorServers, 1);

    const compStatus = statusData.servers.find((s) => s.id === 'comp');
    assert.equal(compStatus.status, 'ready');
    assert.equal(compStatus.tools, 1);
    assert.equal(compStatus.resources, 1);
    assert.equal(compStatus.prompts, 1);

    const brokenStatus = statusData.servers.find((s) => s.id === 'broken');
    assert.equal(brokenStatus.status, 'error');
    assert.ok(brokenStatus.lastError);
  } finally {
    await client.close();
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('generic gateway activates write tools when allowWriteTools is explicitly enabled', async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'mcp-gateway-write-'));
  const configPath = path.join(tempDir, 'mcp-servers.json');

  const config = {
    name: 'test-write-gateway',
    servers: [
      {
        id: 'comp',
        label: 'Comprehensive Server',
        transport: 'stdio',
        command: pythonBin,
        args: [fixtureServer],
        cwd: projectRoot,
        allowWriteTools: true,
      },
    ],
  };

  await fs.writeFile(configPath, JSON.stringify(config, null, 2), 'utf8');

  const transport = new StdioClientTransport({
    command: 'node',
    args: ['dist/servers/mcp-gateway.js'],
    cwd: projectRoot,
    env: {
      ...process.env,
      MCP_SERVERS_CONFIG: configPath,
    },
  });

  const client = new Client({ name: 'gateway-write-test-client', version: '1.0.0' });

  try {
    await client.connect(transport);
    const toolsResult = await client.listTools();
    const toolNames = toolsResult.tools.map((t) => t.name);
    assert.ok(
      toolNames.includes('mcp_comp_create_item'),
      'allowWriteTools: true 일 때 쓰기 도구(create_item)가 활성화되어야 함',
    );

    const writeResult = await client.callTool({
      name: 'mcp_comp_create_item',
      arguments: { name: '신규문서' },
    });
    assert.equal(writeResult.isError, undefined);
    assert.match(writeResult.content[0].text, /Created: 신규문서/);
  } finally {
    await client.close();
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});
