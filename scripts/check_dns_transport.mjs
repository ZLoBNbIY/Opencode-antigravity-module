// Probe the shipped transport without loading OAuth or sending credentials.
import fs from 'node:fs';
import vm from 'node:vm';
import dns from 'node:dns';
import tls from 'node:tls';
import net from 'node:net';
import { PassThrough, Readable, Transform } from 'node:stream';
import { createGunzip } from 'node:zlib';
import os from 'node:os';
import path from 'node:path';
let account;
const argument = (name, fallback) => process.argv.find(arg => arg.startsWith(`--${name}=`))?.split('=').slice(1).join('=') || fallback;
const endpoint = argument('endpoint', 'daily-cloudcode-pa.googleapis.com');
if (!['cloudcode-pa.googleapis.com', 'daily-cloudcode-pa.googleapis.com'].includes(endpoint)) throw new Error('Unsupported diagnostic endpoint');
if (process.argv.includes('--generate')) {
  const dir = path.join(os.homedir(), '.config/opencode');
  const pointer = JSON.parse(fs.readFileSync(path.join(dir, 'antigravity-accounts.json.store.pointer.json'), 'utf8'));
  const generation = path.join(dir, pointer.directoryBasename);
  const config = JSON.parse(fs.readFileSync(path.join(generation, 'config.json'), 'utf8'));
  const state = JSON.parse(fs.readFileSync(path.join(generation, 'state.json'), 'utf8'));
  account = state.accounts[config.antigravityRouting.activeRow.id];
  if (!account?.access || account.expires < Date.now()) throw new Error('Selected account needs token refresh');
}
const source = fs.readFileSync(new URL('../plugin/dist/server.js', import.meta.url), 'utf8');
const code = source.slice(source.indexOf('var DEFAULT_HTTPS_PORT'), source.indexOf('// ../core/dist/antigravity/oauth.js'));
for (const mode of argument('mode', 'standard,dot,doh').split(',')) {
  const config = { dns_mode: mode, custom_dns: ['143.20.64.55', '31.58.216.201'], dot_host: 'dns.bezmezhau.com', doh_url: 'https://dns.bezmezhau.com/dns-query' };
  const context = vm.createContext({ Buffer3: Buffer, dns, tls, net, PassThrough, Readable, Transform, createGunzip, URL, Headers, Response, Request, DOMException, AbortController, AbortSignal, fetch, setTimeout, clearTimeout, process: { env: {}, platform: process.platform }, getUserConfigPath: () => 'test', existsSync5: () => true, readFileSync2: () => JSON.stringify(config), buildAntigravityHarnessUserAgent: () => 'antigravity-dns-diagnostic' });
  vm.runInContext(code, context);
  const start = Date.now();
  try {
    const catalog = process.argv.includes('--catalog');
    const routedModel = source.match(/var GEMINI_38_FLASH_ROUTES = \{\s*defaultModel: "([^"]+)"/)[1];
    const body = account ? JSON.stringify(catalog ? { project: account.commonAuthProviderState.metadata.projectId } : { project: account.commonAuthProviderState.metadata.projectId, model: argument('model', routedModel), request: { contents: [{ role: 'user', parts: [{ text: 'Reply with OK' }] }], generationConfig: { maxOutputTokens: 256 } } }) : '{}';
    const response = await context.fetchWithAgyCliTransport(`https://${endpoint}/v1internal:${catalog ? 'fetchAvailableModels' : 'streamGenerateContent?alt=sse'}`, { method: 'POST', body, headers: account ? { Authorization: `Bearer ${account.access}` } : {} }, { timeoutMs: 8000, idleTimeoutMs: 8000, signal: AbortSignal.timeout(15000), onDebug: console.log });
    const text = await response.text();
    if (catalog && response.ok) console.log('Available model IDs:', Object.keys(JSON.parse(text).models || {}).join(', '));
    if (account) console.log('Response summary:', text.includes('"candidates"') ? 'generation candidates received' : text.match(/"status"\s*:\s*"([A-Z_]+)"/)?.[1] || 'no candidates');
    if (account && !catalog && response.ok) {
      const events = text.split('\n').filter(line => line.startsWith('data:')).map(line => { try { return JSON.parse(line.slice(5)); } catch { return {}; } });
      const parts = events.flatMap(event => (event.response || event).candidates || []).flatMap(candidate => candidate.content?.parts || []);
      console.log('Visible model answer received:', parts.some(part => part.text?.trim() && !part.thought));
    }
    if (account && !response.ok) {
      try {
        const error = JSON.parse(text).error;
        console.log('API reason:', error?.details?.map(d => d.reason || d.retryDelay).filter(Boolean).join(', ') || 'unspecified');
        console.log('API message:', error?.message?.replace(/[\w.+-]+@[\w.-]+/g, '[email]').slice(0, 400));
      } catch {}
    }
    console.log(mode, 'HTTP', response.status, `${Date.now() - start}ms`);
  } catch (error) { console.log(mode, error.message, `${Date.now() - start}ms`); }
}
