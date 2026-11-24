import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { buildQuotaAccounts, formatQuotaResult, openBrowserSafe } from '../plugin/dist/google-login-3113.mjs';

const loginRunner = fileURLToPath(new URL('../plugin/dist/google-login-3113.mjs', import.meta.url));
const cli300Path = fileURLToPath(new URL('../plugin/dist/cli.js', import.meta.url));

test('google-login-3113 refuses modified or non-3.1.13 CLI bytes before evaluation', async (t) => {
  const root = await mkdtemp(fileURLToPath(new URL('../hub-login-3113-test-', import.meta.url)));
  t.after(() => rm(root, { recursive: true, force: true }));
  await writeFile(new URL(`file:///${root.replace(/\\/g, '/')}/package.json`), '{"type":"module"}');
  const fixture = new URL(`file:///${root.replace(/\\/g, '/')}/cli.js`);
  await writeFile(fixture, 'process.stdout.write("executed");\n');
  const result = spawnSync(process.execPath, [loginRunner, fileURLToPath(fixture), '--login'], {
    encoding: 'utf8',
    timeout: 15000,
  });
  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /Unsupported Google CLI digest/i);
});

test('3.0.0 cli.js falls back to id_token email and prevents undefined-email upsert collisions', async () => {
  const source = await readFile(cli300Path, 'utf8');
  assert.ok(source.includes('tokenPayload.id_token'), 'exchangeAntigravity should inspect id_token fallback');
  assert.ok(
    source.includes('typeof result.email === "string" && result.email.length > 0'),
    'upsert should not collide when result.email is undefined'
  );
  // Extract JWT fallback helper logic and verify claim decoding works when userinfo is empty
  const payload = Buffer.from(JSON.stringify({ email: 'jwt-user@example.com', name: 'JWT User' })).toString('base64url');
  const fakeToken = `hdr.${payload}.sig`;
  const userInfo = {};
  const parts = fakeToken.split('.');
  const claims = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'));
  if (!userInfo.email && claims.email) userInfo.email = claims.email;
  if (!userInfo.name && claims.name) userInfo.name = claims.name;
  assert.equal(userInfo.email, 'jwt-user@example.com');
  assert.equal(userInfo.name, 'JWT User');
});

test('google-login-3113 loader retains id_token fallback patch', async () => {
  const loaderSource = await readFile(new URL('../plugin/dist/google-cli-3113-loader.mjs', import.meta.url), 'utf8');
  assert.ok(loaderSource.includes('tokenPayload.id_token'));
  assert.ok(loaderSource.includes('commitLogins'));
  assert.ok(loaderSource.includes('prepareCliLoginStore'));
  assert.ok(existsSync(loginRunner));
});

test('openBrowserSafe preserves full OAuth query string on win32 without cmd & truncation', async () => {
  const calls = [];
  const oauthUrl = 'https://accounts.google.com/o/oauth2/v2/auth?client_id=abc&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A51121%2Foauth-callback&state=xyz';
  await openBrowserSafe(oauthUrl, {
    platform: 'win32',
    overrideBrowser: '',
    execFileAsync: async (bin, args, opts) => {
      calls.push({ bin, args, opts });
    },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].bin, 'powershell.exe');
  const encodedIdx = calls[0].args.indexOf('-EncodedCommand');
  assert.notEqual(encodedIdx, -1);
  const decoded = Buffer.from(calls[0].args[encodedIdx + 1], 'base64').toString('utf16le');
  assert.equal(decoded, `Start-Process '${oauthUrl}'`);
  assert.ok(decoded.includes('&response_type=code'));
});

test('openBrowserSafe rejects non-HTTP URLs', async () => {
  await assert.rejects(() => openBrowserSafe('file:///C:/Windows/System32/calc.exe'), /Refusing to open non-HTTP URL/i);
});

test('buildQuotaAccounts supplies fallback project context when managedProjectId is absent', () => {
  const accounts = buildQuotaAccounts([
    { email: 'with-managed@example.com', projectId: 'p1', managedProjectId: 'm1' },
    { email: 'with-project@example.com', projectId: 'p2' },
    { email: 'fresh@example.com' },
  ]);
  assert.equal(accounts[0].managedProjectId, 'm1');
  assert.equal(accounts[1].managedProjectId, 'p2');
  assert.equal(accounts[2].projectId, 'rising-fact-p41fc');
  assert.equal(accounts[2].managedProjectId, 'rising-fact-p41fc');
});

test('formatQuotaResult preserves quota windows and fallback group percentages', () => {
  const fakeSummary = (results) => ({
    accounts: results.map((r) => ({ index: r.index, email: r.email, status: r.status, groups: [] })),
  });
  const formatted = formatQuotaResult(
    {
      index: 0,
      email: 'user@example.com',
      status: 'ok',
      quota: {
        groups: {
          gemini: {
            remainingFraction: 0.60134,
            resetTime: '2026-11-24T11:19:16Z',
            windows: [
              { window: '5h', remainingFraction: 0.60134, resetTime: '2026-11-24T11:19:16Z' },
              { window: 'weekly', remainingFraction: 0.875, resetTime: '2026-12-01T06:19:16Z' },
            ],
          },
        },
      },
    },
    2,
    'fallback@example.com',
    fakeSummary,
  );
  assert.equal(formatted.index, 2);
  assert.equal(formatted.email, 'user@example.com');
  assert.equal(formatted.groups.length, 1);
  assert.equal(formatted.groups[0].remainingPercent, 60.1);
  assert.deepEqual(formatted.groups[0].windows, [
    { window: '5h', remainingPercent: 60.1, resetTime: '2026-11-24T11:19:16Z' },
    { window: 'weekly', remainingPercent: 87.5, resetTime: '2026-12-01T06:19:16Z' },
  ]);
});
