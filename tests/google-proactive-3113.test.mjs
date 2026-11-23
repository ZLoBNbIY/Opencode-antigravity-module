import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { basename, dirname, isAbsolute, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const runner = fileURLToPath(new URL('../plugin/dist/google-cli-3113.mjs', import.meta.url));
const offline = new URL('./fixtures/google_3113_offline_fetch.mjs', import.meta.url).href;
const pkg = '@cortexkit/opencode-antigravity-auth';
const cache = join(homedir(), '.cache', 'opencode', 'npm', `${pkg}@3.1.13`);
const dependencyFolder = process.env.HUB_TEST_3113_NODE_MODULES ??
  join(cache, '1795449545541', 'node_modules');
const realCli = join(dependencyFolder, pkg, 'dist', 'cli.js');

async function sandbox(t) {
  // The 3.1 native repository rejects even writable-by-others ancestors.
  // Windows Temp can be shared on CI; use an isolated directory in the checkout.
  const root = await mkdtemp(fileURLToPath(new URL('../hub-3113-test-', import.meta.url)));
  t.after(() => rm(root, { recursive: true, force: true }));
  if (process.platform === 'win32') {
    const owner = spawnSync('whoami.exe', ['/user', '/fo', 'csv', '/nh'], { encoding: 'utf8' });
    const sid = owner.stdout.match(/S-1-\d+(?:-\d+)+/)?.[0];
    assert.ok(sid);
    const acl = spawnSync('icacls.exe', [root, '/inheritance:r', '/grant:r', `*${sid}:(OI)(CI)F`],
      { encoding: 'utf8' });
    assert.equal(acl.status, 0, acl.stderr);
  }
  const config = join(root, 'config');
  await mkdir(config);
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (/^(?:NODE_OPTIONS|OPENCODE_|CORTEXKIT_|CLAUSTRUM_|ANTIGRAVITY_|HUB_TEST_OAUTH)/i.test(key))
      delete env[key];
  }
  Object.assign(env, {
    HOME: root, USERPROFILE: root, APPDATA: join(root, 'roaming'), LOCALAPPDATA: join(root, 'local'),
    OPENCODE_CONFIG_DIR: config, XDG_STATE_HOME: join(root, 'state'),
    XDG_CONFIG_HOME: root, XDG_CACHE_HOME: join(root, 'cache'), XDG_DATA_HOME: join(root, 'data'),
  });
  const run = (args, extra = {}) => {
    const result = spawnSync(process.execPath, ['--import', offline, ...args], {
      cwd: root, env: { ...env, ...extra }, encoding: 'utf8', timeout: 15000,
    });
    assert.equal(result.error, undefined);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stderr, '');
    return result.stdout;
  };
  const command = (entry, args, extra) => {
    const stdout = run([runner, entry, ...args], extra);
    assert.doesNotMatch(stdout, /private|accessToken|refreshToken/);
    return JSON.parse(stdout);
  };
  return { root, config, run, command };
}

test('3.1.13 loader refuses other bytes before evaluation', async (t) => {
  const { root, command } = await sandbox(t);
  await writeFile(join(root, 'package.json'), '{"type":"module"}');
  const fixture = join(root, 'cli.js');
  await writeFile(fixture, 'process.stdout.write("executed");\n');
  assert.deepEqual(command(fixture, ['--list']), { status: 'unavailable' });
});

test('exact 3.1.13 profile refreshes a relocated generation without modifying CLI or pointer', {
  skip: !existsSync(realCli) && 'set HUB_TEST_3113_NODE_MODULES to the exact cached npm profile',
}, async (t) => {
  const { root, config, run, command } = await sandbox(t);
  const modules = join(root, 'node_modules');
  await cp(dependencyFolder, modules, { recursive: true, dereference: true });
  const entry = join(modules, pkg, 'dist', 'cli.js');
  const original = await readFile(entry);
  const legacy = join(config, 'antigravity-accounts.json');
  const now = Date.now();
  await writeFile(legacy, JSON.stringify({ version: 4, activeIndex: 0, accounts: [{
    refreshToken: 'private-fixture-refresh', email: 'test@example.com', addedAt: now, lastUsed: now,
  }] }));
  run(['--input-type=module', '--eval', `
    import { pathToFileURL } from 'node:url';
    const { createDefaultAccountStoreOperations } = await import(pathToFileURL(process.argv[1]));
    const ops = createDefaultAccountStoreOperations();
    if ((await ops.migrate(process.argv[2])).status !== 'completed') process.exit(2);
    if ((await ops.relocate()).status !== 'completed') process.exit(3);
  `, entry, legacy]);
  const pointerName = `${legacy}.store.pointer.json`;
  const forwarding = await readFile(pointerName, 'utf8');
  const pointer = JSON.parse(forwarding);
  assert.equal(pointer.schemaVersion, 2);
  const { legacyPath: target } = pointer.relocatedTo;
  const sandboxPath = relative(root, target);
  assert.ok(sandboxPath && !isAbsolute(sandboxPath) && !sandboxPath.startsWith(`..${sep}`));
  const targetPointer = JSON.parse(await readFile(`${target}.store.pointer.json`, 'utf8'));
  assert.equal(targetPointer.schemaVersion, 1);
  assert.equal(basename(targetPointer.directoryBasename), targetPointer.directoryBasename);
  const statePath = join(dirname(target), targetPointer.directoryBasename, 'state.json');
  const state = JSON.parse(await readFile(statePath, 'utf8'));
  const [id] = Object.keys(state.accounts);
  const row = state.accounts[id];
  // The native migration imports only refresh credentials. Seed a fake
  // previous access token in this isolated repo as in the 3.0.0 test.
  row.access = 'private-previous';
  row.expires = now + 15 * 60 * 1000;
  row.commonAuthPool.dispatch = createHash('sha256').update(
    `credential-dispatch\0${JSON.stringify(['oauth', row.access, row.refresh, row.expires])}`,
  ).digest('hex');
  await writeFile(statePath, JSON.stringify(state));

  await writeFile(pointerName, JSON.stringify({
    ...pointer, relocatedTo: { ...pointer.relocatedTo, id: '22222222-2222-2222-2222-222222222222' },
  }));
  assert.deepEqual(command(entry, ['--list']), { status: 'unavailable' });
  await writeFile(pointerName, forwarding);
  assert.deepEqual(command(entry, ['--list'], { CORTEXKIT_VAULT_HOST: 'thalamus' }), { status: 'unavailable' });
  const listing = command(entry, ['--list']);
  assert.equal(listing.status, 'ready');
  assert.equal(listing.generation, pointer.relocatedTo.id);
  assert.deepEqual(listing.accounts.map((account) => account.id), [id]);
  const [{ epoch, expires }] = listing.accounts;
  const attempt = ['--account', listing.generation, id, String(epoch), String(expires)];
  const beforeErrors = await readFile(statePath);
  assert.deepEqual(command(entry, attempt, { HUB_TEST_OAUTH: 'invalid' }), { status: 'invalid_grant' });
  assert.deepEqual(command(entry, attempt, { HUB_TEST_OAUTH: '429' }), { status: 'rate_limited', retryAfterSeconds: 780 });
  assert.deepEqual(await readFile(statePath), beforeErrors);
  assert.deepEqual(command(entry, attempt, { HUB_TEST_OAUTH: 'refresh' }), { status: 'refreshed' });
  assert.deepEqual(command(entry, attempt), { status: 'skipped' });
  assert.equal(JSON.parse(await readFile(statePath, 'utf8')).accounts[id].access, 'private-successor');
  assert.equal(await readFile(pointerName, 'utf8'), forwarding);
  assert.deepEqual(await readFile(entry), original);
});
