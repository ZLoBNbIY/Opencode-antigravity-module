import assert from 'node:assert/strict';
import fs from 'node:fs';
import { EventEmitter } from 'node:events';

// Exercise the actual bundled functions, including the CLI's config-path lookup.
for (const bundle of ['server', 'index', 'cli']) {
  const source = fs.readFileSync(new URL(`../plugin/dist/${bundle}.js`, import.meta.url), 'utf8');
  if (bundle !== 'cli') {
    const routes = new Function(source.match(/var GEMINI_38_FLASH_ROUTES = \{[\s\S]*?\n\};/)[0] + '; return GEMINI_38_FLASH_ROUTES;')();
    assert.equal(routes.defaultModel, 'gemini-3.8-flash-tiered');
    assert.ok(Object.values(routes.byTier).every(model => model === routes.defaultModel));
  }
  assert.match(source, /var ANTIGRAVITY_ENDPOINT_FALLBACKS = \[\s*ANTIGRAVITY_ENDPOINT_DAILY,/);
  const code = source.slice(source.indexOf('function buildDnsQueryWire('), source.indexOf('async function connectDirect('));
  let config;
  let udpCalls = 0;
  let cancelled = 0;
  class Resolver {
    setServers() {}
    resolve4(host, callback) { udpCalls++; this.callback = callback; }
    cancel() { cancelled++; this.callback?.(new Error('cancelled')); }
  }
  const dependencies = {
    Buffer2: Buffer, Buffer3: Buffer,
    process: { env: {} },
    getUserConfigPath: () => 'test', existsSync2: () => true, existsSync5: () => true,
    readFileSync: () => JSON.stringify(config), readFileSync2: () => JSON.stringify(config),
    dns: { Resolver },
    fetch: (_url, { signal }) => new Promise((resolve, reject) => {
      if (signal.aborted) return reject(signal.reason);
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    }),
    tls: { connect: () => {
      const socket = new EventEmitter();
      socket.setTimeout = () => {};
      setImmediate(() => socket.emit('close'));
      return socket;
    } }
  };
  const resolve = new Function(...Object.keys(dependencies), `${code}; return resolveHostWithCustomDns;`)(...Object.values(dependencies));
  config = { dns_mode: 'system', doh_url: 'https://unused.invalid' };
  assert.equal(await resolve('example.com'), 'example.com');
  config = { dns_mode: 'doh', doh_url: 'https://unused.invalid', custom_dns: ['192.0.2.1'] };
  let start = Date.now();
  await assert.rejects(resolve('example.com', undefined, undefined, 40), /DoH resolution failed/);
  assert.ok(Date.now() - start < 1000, 'DoH must be bounded');
  assert.equal(udpCalls, 0, 'DoH must not silently downgrade to UDP');
  const controller = new AbortController();
  const pending = resolve('example.com', undefined, controller.signal);
  controller.abort(new Error('user cancelled'));
  await assert.rejects(pending, /user cancelled/);
  config = { dns_mode: 'dot', dot_host: 'unused.invalid' };
  await assert.rejects(resolve('example.com'), /DoT resolution failed/);
  config = { dns_mode: 'standard', custom_dns: ['192.0.2.1'] };
  start = Date.now();
  await assert.rejects(resolve('example.com', undefined, undefined, 40), /timed out|cancelled/);
  assert.ok(Date.now() - start < 1000, 'UDP must be bounded');
  assert.equal(cancelled, 1);
  console.log(`${bundle}: DNS timeout, cancellation, closed DoT, system mode, no downgrade OK`);
}
