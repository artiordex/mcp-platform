import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const harness = path.join(projectRoot, 'tests/fixtures/run_stdio_checks.py');

function runCheck(name) {
  let stdout;
  try {
    stdout = execFileSync(process.env.PYTHON ?? 'python3', [harness, name], {
      cwd: projectRoot,
      encoding: 'utf8',
      timeout: 30_000,
    });
  } catch (error) {
    // The managed sandbox can report EPERM after a child has exited successfully.
    // Keep the completed process output when its recorded exit status is zero.
    if (error?.status !== 0 || typeof error.stdout !== 'string') {
      throw error;
    }
    stdout = error.stdout;
  }
  return JSON.parse(stdout);
}

test('generic gateway routes configured MCP tools and filters child environment', () => {
  const result = runCheck('generic');
  assert.deepEqual(result.tools, ['mcp_fake_inspect_env']);
  assert.deepEqual(result.child_environment, { allowed: 'present', private: null });
});

test('Data.go gateway starts all public-data MCP servers', () => {
  const result = runCheck('data-go');
  assert.equal(result.total_tools, 18);
  assert.deepEqual(result.by_server, {
    nps: 3,
    nts: 3,
    pps: 4,
    fsc: 4,
    public_data_catalog: 1,
    food_safety: 3,
  });
});

test('generic gateway connects to remote Streamable HTTP MCP servers with secret headers', () => {
  const result = runCheck('remote');
  assert.deepEqual(result.tools, ['mcp_remote_inspect_auth']);
  assert.equal(result.authorization_forwarded, true);
});

test('workspace server blocks hidden files and symlinks outside the workspace', () => {
  const result = runCheck('workspace');
  assert.match(result.visible_file, /visible content/);
  assert.equal(result.hidden_blocked, true);
  assert.equal(result.outside_symlink_blocked, true);
});
