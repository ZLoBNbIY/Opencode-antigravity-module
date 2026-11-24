import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { createDefaultCliDependencies, refreshDueGoogleStore, runCli } from '../plugin/dist/cli.js';

async function fixture(t, accounts) {
  const directory = await mkdtemp(join(await realpath(tmpdir()), 'hub-refresh-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const now = Date.now();
  let clock = now;
  t.mock.method(Date, 'now', () => clock);
  const advanceTime = (ms) => { clock += ms; };
  const legacy = join(directory, 'antigravity-accounts.json');
  const run = async (args) => {
    let stdout = '', stderr = '';
    const deps = createDefaultCliDependencies();
    const code = await runCli(args, {
      ...deps,
      accountStore: { ...deps.accountStore, legacyPath: () => legacy },
      refreshDueAccount: (account) => refreshDueGoogleStore(legacy, account),
      stdout: { write: (text) => { stdout += text; } },
      stderr: { write: (text) => { stderr += text; } },
    });
    return { code, stdout, stderr };
  };
  const command = async (...args) => {
    const result = await run(['refresh-due', ...args]);
    assert.equal(result.code, 0);
    assert.equal(result.stderr, '');
    assert.doesNotMatch(result.stdout, /private|@example|accessToken|refreshToken/);
    return JSON.parse(result.stdout);
  };
  const exchange = t.mock.method(globalThis, 'fetch', () => assert.fail('unexpected OAuth request'));
  if (!accounts) return { command, run, exchange, legacy };

  await writeFile(legacy, JSON.stringify({
    version: 4, activeIndex: 0, accounts: accounts.map((account, index) => ({
      email: `row-${index}@example.com`,
      refreshToken: `private-refresh-${index}`,
      enabled: account.enabled ?? true,
      verificationRequired: account.verificationRequired ?? false,
      addedAt: now - 3600000, lastUsed: now - 3600000,
    })),
  }), { mode: 0o600 });
  const migration = await run(['migrate', '--offline', '--yes']);
  assert.equal(migration.code, 0, migration.stderr);
  const pointer = JSON.parse(await readFile(`${legacy}.store.pointer.json`, 'utf8'));
  const configPath = join(dirname(legacy), pointer.directoryBasename, 'config.json');
  const statePath = join(dirname(configPath), 'state.json');
  const config = JSON.parse(await readFile(configPath, 'utf8'));
  // Migration imports only a refresh token. Simulate a prior normal exchange
  // in this isolated fixture; the tested exchange and writes use the real repo.
  const state = JSON.parse(await readFile(statePath, 'utf8'));
  for (const [index, { id }] of config.accounts.entries()) {
    const row = state.accounts[id];
    const offset = accounts[index].expiresInMs;
    if (offset === undefined) continue;
    row.access = `private-access-${index}`;
    row.expires = now + offset;
    row.commonAuthPool.dispatch = createHash('sha256').update(
      `credential-dispatch\0${JSON.stringify(['oauth', row.access, row.refresh, row.expires])}`,
    ).digest('hex');
  }
  await writeFile(statePath, JSON.stringify(state));
  return { command, run, exchange, statePath, configPath, config, now, advanceTime };
}

function attempt(command, listing, row = listing.accounts[0]) {
  return command('--account', listing.generation, row.id, String(row.epoch), String(row.expires));
}

test('refresh-due uses the generation repository, does no quota/project requests, and ignores a stale snapshot', async (t) => {
  const { command, statePath, configPath, config, exchange, now } = await fixture(t, [
    { expiresInMs: 1800000 }, { expiresInMs: 1800001 }, { expiresInMs: 0 }, {},
    { expiresInMs: 1200000, enabled: false },
    { expiresInMs: 1200000, verificationRequired: true },
  ]);
  const listing = await command('--list');
  assert.equal(listing.status, 'ready');
  assert.deepEqual(listing.accounts.map((row) => row.id), [config.accounts[0].id]);
  assert.equal(exchange.mock.callCount(), 0);
  exchange.mock.mockImplementation((url, init) => {
    assert.equal(url, 'https://oauth2.googleapis.com/token');
    assert.equal(init.body.get('refresh_token'), 'private-refresh-0');
    return new Response(JSON.stringify({
      access_token: 'private-access-successor', refresh_token: 'private-refresh-successor', expires_in: 3600,
    }));
  });
  const results = await Promise.all([attempt(command, listing), attempt(command, listing)]);
  assert.deepEqual(results.map(({ status }) => status).sort(), ['refreshed', 'skipped']);
  assert.deepEqual(await attempt(command, listing), { status: 'skipped' });
  assert.equal(exchange.mock.callCount(), 1);
  const state = JSON.parse(await readFile(statePath, 'utf8'));
  const row = state.accounts[listing.accounts[0].id];
  assert.equal(row.access, 'private-access-successor');
  assert.equal(row.refresh, 'private-refresh-successor');
  assert.equal(row.expires, now + 3600000);
  assert.deepEqual(JSON.parse(await readFile(configPath, 'utf8')), config);
});

test('invalid_grant and 429 are redacted and failed exchanges do not rotate the credential', async (t) => {
  const { command, statePath, exchange, now } = await fixture(t, [{ expiresInMs: 60000 }]);
  const listing = await command('--list');
  const before = await readFile(statePath, 'utf8');
  exchange.mock.mockImplementation(() => new Response(
    '{"error":"invalid_grant","error_description":"private credential echo"}', { status: 400 },
  ));
  assert.deepEqual(await attempt(command, listing), { status: 'invalid_grant' });
  exchange.mock.mockImplementation(() => new Response('private', {
    status: 429, headers: { 'retry-after': '1200' },
  }));
  assert.deepEqual(await attempt(command, listing), { status: 'rate_limited', retryAfterSeconds: 1200 });
  exchange.mock.mockImplementation(() => new Response('private', {
    status: 429, headers: { 'retry-after': new Date(now + 600000).toUTCString() },
  }));
  assert.deepEqual(await attempt(command, listing), { status: 'rate_limited', retryAfterSeconds: 600 });
  exchange.mock.mockImplementation(() => new Response('{"refresh_token":"private-invalid-successor"}'));
  assert.deepEqual(await attempt(command, listing), { status: 'failed' });
  assert.equal(await readFile(statePath, 'utf8'), before);
});

test('a rotation still commits when the old access token expires during the exchange', async (t) => {
  const { command, now, exchange, statePath, advanceTime } = await fixture(t, [{ expiresInMs: 1000 }]);
  const listing = await command('--list');
  exchange.mock.mockImplementation(() => {
    advanceTime(1100);
    return new Response(JSON.stringify({ access_token: 'private-access-successor', expires_in: 3600 }));
  });
  assert.deepEqual(await attempt(command, listing), { status: 'refreshed' });
  const state = JSON.parse(await readFile(statePath, 'utf8'));
  assert.equal(state.accounts[listing.accounts[0].id].expires, now + 3600000);
});

test('refresh-due has no legacy fallback and rejects force', async (t) => {
  const { command, run, exchange, legacy } = await fixture(t);
  assert.deepEqual(await command('--list'), { status: 'unavailable' });
  const source = '{"version":4,"accounts":[{"refreshToken":"private"}]}';
  await writeFile(legacy, source);
  assert.deepEqual(await command('--list'), { status: 'unavailable' });
  assert.equal(await readFile(legacy, 'utf8'), source);
  assert.equal((await run(['refresh-due', '--force'])).code, 2);
  assert.equal(exchange.mock.callCount(), 0);
});

test('vendored 3.0.0 CLI refuses a 3.1.x forwarding pointer without touching either store', async (t) => {
  const { command, exchange, legacy } = await fixture(t);
  const from = '11111111-1111-1111-1111-111111111111';
  const to = '22222222-2222-2222-2222-222222222222';
  const relocated = join(dirname(legacy), 'relocated-accounts.json');
  const pointerPath = `${legacy}.store.pointer.json`;
  const pointer = JSON.stringify({
    schemaVersion: 2, id: from,
    directoryBasename: `antigravity-accounts.json.store.${from}.generation`,
    relocatedTo: { legacyPath: relocated, id: to },
  });
  await writeFile(pointerPath, pointer);
  await writeFile(relocated, 'private sentinel');
  assert.deepEqual(await command('--list'), { status: 'unavailable' });
  assert.deepEqual(await command('--account', to, 'row', '1', '1720000000000'), { status: 'unavailable' });
  assert.equal(await readFile(pointerPath, 'utf8'), pointer);
  assert.equal(await readFile(relocated, 'utf8'), 'private sentinel');
  assert.equal(exchange.mock.callCount(), 0);
});
