import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { applyAnchoredEdits } from '../scripts/patch_plugin.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const script = path.join(root, 'scripts', 'patch_plugin.mjs');
const packageName = '@cortexkit/opencode-antigravity-auth';
const shippedTargets = [
  'dist/index.js',
  'dist/server.js',
  'dist/src/plugin/config/schema.js',
  'dist/src/hooks/auto-update-checker/index.js',
  'dist/src/hooks/auto-update-checker/checker.js',
  'dist/src/plugin/config/updater.js',
];

function run(args, env = process.env) {
  return spawnSync(process.execPath, [script, ...args], { cwd: root, encoding: 'utf8', env });
}

function fixture(t, version) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'ag-patch-test-'));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const dist = path.join(base, 'dist');
  fs.mkdirSync(dist);
  fs.writeFileSync(path.join(base, 'package.json'), JSON.stringify({ name: packageName, version, type: 'module' }));
  const entry = path.join(dist, 'index.js');
  const source = 'const defaults = { auto_update: true, };\r\n';
  fs.writeFileSync(entry, source);
  return { base, dist, entry, source };
}

test('anchor edits are idempotent and distinguish missing and ambiguous anchors', () => {
  const edits = [['widget', 'const color = "old";', 'const color = "new";']];
  const edited = applyAnchoredEdits('const color = "old";\n', edits);
  assert.deepEqual(edited, { content: 'const color = "new";\n', changed: ['widget'] });
  assert.deepEqual(applyAnchoredEdits(edited.content, edits), { content: edited.content, changed: [] });
  assert.throws(() => applyAnchoredEdits('const color = "custom";', edits), /widget: missing anchor/);
  assert.throws(() => applyAnchoredEdits('const color = "old";\nconst color = "old";', edits), /widget: ambiguous anchors/);
  assert.throws(() => applyAnchoredEdits('const color = "old";\nconst color = "new";', edits), /widget: ambiguous anchors/);
});

test('a structural match must also match the verified block bytes', () => {
  const expected = createHash('sha256').update('color: "blue"').digest('hex');
  const edits = [['widget', /color: "[a-z]+"/, 'color: null', expected]];
  assert.equal(applyAnchoredEdits('const settings = { color: "blue" };', edits).content, 'const settings = { color: null };');
  assert.throws(() => applyAnchoredEdits('const settings = { color: "green" };', edits), /original block differs/);
});

test('CLI rejects unknown versions without writing', (t) => {
  const { base, entry, source, dist } = fixture(t, '3.0.1');
  const result = run([base]);
  assert.equal(result.status, 1, result.error?.message);
  assert.match(result.stderr, /unsupported package.*@3\.0\.1/);
  assert.equal(fs.readFileSync(entry, 'utf8'), source);
  assert.deepEqual(fs.readdirSync(dist), ['index.js']);
});

test('known version with a missing anchor fails before any writes or migration', (t) => {
  const { base, entry, source, dist } = fixture(t, '3.0.0');
  const configDir = path.join(base, '.config', 'opencode');
  const store = path.join(configDir, 'antigravity-accounts.json');
  fs.mkdirSync(configDir, { recursive: true });
  fs.writeFileSync(store, '[]');
  fs.writeFileSync(path.join(dist, 'cli.js'), 'throw new Error("Must not execute the plugin CLI");\n');
  const result = run([base], { ...process.env, HOME: base, USERPROFILE: base, XDG_CONFIG_HOME: path.dirname(configDir) });
  assert.equal(result.status, 1, result.error?.message);
  assert.match(result.stderr, /dist\/index\.js: schema auto-update default: missing anchor/);
  assert.doesNotMatch(result.stdout, /Already applied|Updated|migration/i);
  assert.equal(fs.readFileSync(entry, 'utf8'), source);
  assert.equal(fs.readFileSync(store, 'utf8'), '[]');
  assert.deepEqual(fs.readdirSync(dist), ['cli.js', 'index.js']);
});

test('shipped updater variants match the patch recipe and template pin', () => {
  const result = run(['--check']);
  assert.equal(result.status, 0, result.stderr);
  assert.equal((result.stdout.match(/Already applied:/g) ?? []).length, shippedTargets.length);
  assert.doesNotMatch(result.stdout, /Would update/);
  const config = JSON.parse(fs.readFileSync(path.join(root, 'config-templates', 'opencode.json'), 'utf8'));
  assert.deepEqual(config.plugins, [`${packageName}@3.0.0`]);
  const settings = JSON.parse(fs.readFileSync(path.join(root, 'config-templates', 'antigravity.json'), 'utf8'));
  assert.equal(settings.auto_update, false);
});

test('preflights the entire plan, supports dry run, and atomically replaces only the file that changes', (t) => {
  const { base, dist } = fixture(t, '3.0.0');
  for (const file of shippedTargets) {
    const dest = path.join(base, file);
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(path.join(root, 'plugin', file), dest);
  }
  const cli = path.join(dist, 'cli.js');
  fs.writeFileSync(cli, 'export const unrelated = true;\n');
  const schema = path.join(base, 'dist/src/plugin/config/schema.js');
  const syntheticOld = 'const z = {};\r\nconst config = { auto_update: z.boolean().default(true), };\r\nconst fallback = { auto_update: true, };\r\n';
  fs.writeFileSync(schema, syntheticOld);
  const oldMode = fs.statSync(schema).mode;
  const updater = path.join(base, 'dist/src/plugin/config/updater.js');
  const savedUpdater = fs.readFileSync(updater);
  fs.writeFileSync(updater, 'export const unexpected = true;\n');
  const rejected = run([base]);
  assert.equal(rejected.status, 1, rejected.stderr);
  assert.match(rejected.stderr, /dist\/src\/plugin\/config\/updater\.js: default package pin: missing anchor/);
  assert.equal(fs.readFileSync(schema, 'utf8'), syntheticOld);
  fs.writeFileSync(updater, savedUpdater);
  const dry = run(['--check', base]);
  assert.equal(dry.status, 0, dry.stderr);
  assert.match(dry.stdout, /Would update dist\/src\/plugin\/config\/schema\.js/);
  assert.equal(fs.readFileSync(schema, 'utf8'), syntheticOld);
  const written = run([base]);
  assert.equal(written.status, 0, written.stderr);
  assert.equal((written.stdout.match(/Updated /g) ?? []).length, 1);
  assert.equal(fs.readFileSync(schema, 'utf8'), syntheticOld.replaceAll('true', 'false'));
  assert.equal(fs.statSync(schema).mode, oldMode);
  assert.equal(fs.readFileSync(cli, 'utf8'), 'export const unrelated = true;\n');
  assert.deepEqual(fs.readdirSync(path.dirname(schema)).sort(), ['schema.js', 'updater.js']);
});

test('shipped hooks do not poll by default or invalidate cache/rewrite pins on opt-in', async () => {
  for (const file of ['dist/server.js', 'dist/index.js', 'dist/src/hooks/auto-update-checker/index.js']) {
    const source = fs.readFileSync(path.join(root, 'plugin', file), 'utf8');
    const hook = source.match(/^(?:export )?(function createAutoUpdateCheckerHook\([\s\S]+?)(?=^async function showLocalDevToast)/m)?.[1];
    assert.ok(hook, file);
    let pin = true;
    let polls = 0;
    const timers = [];
    const toasts = [];
    const createHook = runInNewContext(`${hook}\ncreateAutoUpdateCheckerHook`, {
      findPluginEntry: () => ({ isPinned: pin }),
      getCachedVersion: () => '3.0.0',
      getLatestVersion: async () => { polls += 1; return '3.1.0'; },
      getLocalDevVersion: () => null,
      logAutoUpdate: () => {},
      setTimeout: (callback) => timers.push(callback),
      // Intentionally no cache or config writers are available.
    });
    const client = { tui: { showToast: async (toast) => toasts.push(toast) } };
    function session(options) {
      createHook(client, '/synthetic/project', options).event({ event: { type: 'session.created' } });
      timers.shift()?.();
    }
    session();
    session({ autoUpdate: true });
    assert.equal(polls, 0, file);
    pin = false;
    session({ autoUpdate: true });
    await new Promise(setImmediate);
    assert.equal(polls, 1, file);
    assert.equal(toasts.length, 1, file);
  }
});

test('shipped config updaters preserve explicit string and object package selections', async () => {
  for (const file of ['dist/server.js', 'dist/index.js', 'dist/src/plugin/config/updater.js']) {
    const source = fs.readFileSync(path.join(root, 'plugin', file), 'utf8');
    const fn = source.match(/^(?:export )?(async function updateOpencodeConfig\([\s\S]+?^})/m)?.[1];
    assert.ok(fn, file);
    const read = fn.match(/\b(readFileSync\d*)\(configPath,/)?.[1];
    const write = fn.match(/\b(writeFileSync\d*)\(configPath,/)?.[1];
    const exists = fn.match(/\b(existsSync\d*)\(configPath\)/)?.[1];
    const dirname = fn.match(/\b(dirname\d*)\(configPath\)/)?.[1];
    const pin = source.match(/(?:var|const) PLUGIN_NAME = ['"]([^'"]+)['"];/)?.[1];
    assert.equal(pin, `${packageName}@3.0.0`);
    let input;
    let output;
    const update = runInNewContext(`${fn}\nupdateOpencodeConfig`, {
      [read]: () => JSON.stringify(input),
      [write]: (_, value) => { output = JSON.parse(value); },
      [exists]: (file) => file === '/synthetic' || input !== undefined,
      [dirname]: () => '/synthetic',
      stripJsonCommentsAndTrailingCommas: (text) => text,
      SCHEMA_URL: 'https://opencode.ai/config.json',
      PLUGIN_NAME: pin,
      OPENCODE_MODEL_DEFINITIONS: {},
      getAntigravityOpencodeModelIds: () => [],
    });
    const explicit = `${packageName}@2.9.0`;
    const objectEntry = { package: explicit, options: { enabled: true } };
    for (input of [{ plugin: [explicit] }, { plugins: [objectEntry] }, undefined]) {
      const result = await update({ configPath: '/synthetic/opencode.json' });
      assert.equal(result.success, true, result.error);
      if (input?.plugin) assert.deepEqual(output.plugin, input.plugin);
      else assert.deepEqual(output.plugins, input?.plugins ?? [pin]);
    }
  }
});
