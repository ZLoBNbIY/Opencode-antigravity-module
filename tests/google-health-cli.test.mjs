import assert from 'node:assert/strict';
import test from 'node:test';
import { runCli, createDefaultCliDependencies } from '../plugin/dist/cli.js';

function dependencies(accounts = [{ email: 'test@example.com', refreshToken: 'private-refresh' }]) {
  let stdout = '', stderr = '';
  const deps = {
    stdout: { write: (text) => { stdout += text; } },
    stderr: { write: (text) => { stderr += text; } },
    accountStore: { legacyPath: () => 'unused', read: async () => ({ kind: 'store', accounts }) },
    refreshHealthToken: async () => ({ accessToken: 'fresh-access', expires: Date.now() + 3600000, projectId: 'project' }),
    getQuota: async () => [{ email: 'test@example.com', status: 'ok', accessToken: 'must-not-leak' }],
  };
  return { deps, output: () => ({ stdout, stderr }) };
}

test('health-token returns only the requested fresh access token, not refresh credentials', async () => {
  const { deps, output } = dependencies();
  assert.equal(typeof createDefaultCliDependencies().refreshHealthToken, 'function');
  assert.equal(await runCli(['health-token', '--email', 'test@example.com'], deps), 0);
  assert.equal(JSON.parse(output().stdout).accessToken, 'fresh-access');
  assert.ok(!output().stdout.includes('private-refresh'));
  assert.equal(output().stderr, '');
});

test('missing, ambiguous and disabled accounts never refresh', async () => {
  for (const accounts of [[], [{ email: 'test@example.com', enabled: false }],
    [{ email: 'test@example.com' }, { email: 'test@example.com' }]]) {
    const { deps, output } = dependencies(accounts);
    deps.refreshHealthToken = () => { assert.fail('must not refresh'); };
    assert.equal(await runCli(['health-token', '--email', 'test@example.com'], deps), 1);
    assert.equal(output().stdout, '');
  }
});

test('refresh failure and invalid grants are sanitized', async () => {
  for (const refresh of [async () => { throw new Error('secret-refresh'); },
    async () => ({ accessToken: '', expires: Date.now() + 3600000 }),
    async () => ({ accessToken: 'secret-access', expires: 1 })]) {
    const { deps, output } = dependencies();
    deps.refreshHealthToken = refresh;
    assert.equal(await runCli(['health-token', '--email', 'test@example.com'], deps), 1);
    assert.equal(output().stdout, '');
    assert.ok(!output().stderr.includes('secret'));
  }
});

test('health-token requires an explicit account; ordinary quota never prints tokens', async () => {
  const { deps, output } = dependencies();
  assert.equal(await runCli(['health-token'], deps), 2);
  assert.equal(await runCli(['quota', '--refresh', '--json'], deps), 0);
  assert.ok(!output().stdout.includes('must-not-leak'));
});
