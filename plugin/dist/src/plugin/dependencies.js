/**
 * Composition seam for the opencode Antigravity plugin.
 *
 * `createAntigravityPlugin` is the single host-facing factory. Its surface
 * stayed stable for years (input → PluginResult) so production callers
 * never needed to think about which fetch, transport, or OAuth primitive
 * actually runs under the hood. Tests had to either reach for
 * `mock.module('./agy-transport', …)` or stub `globalThis.fetch` — both
 * leaks that pull on module-graph seams that should be invisible to the
 * factory's public surface.
 *
 * The contract here is intentionally narrow:
 *   - Every dependency below has a default that maps to the current
 *     production function (i.e. no behavior change in production).
 *   - Tests inject deterministic doubles for fetch / transport / OAuth /
 *     filesystem roots / clock so the e2e workspace can run without
 *     hitting the public internet or a real disk root.
 *   - No dependency below is intended to leak into the public exports of
 *     `packages/opencode/index.ts`. That barrel stays at "create the
 *     plugin and give me a PluginResult" — the override shape is a test-
 *     time contract, not a stable API.
 *
 * Anything that already had an inline `dependencies:` injection point on
 * a sub-factory (auth-loader, oauth-methods) is intentionally NOT re-
 * surfaced here. Those seams already work; the goal of THIS file is to
 * catch the seams that did NOT exist yet (fetch, transport, env-resolved
 * filesystem roots, clock).
 */
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fetchWithAgyCliTransport, } from '@cortexkit/antigravity-auth-core';
import { authorizeAntigravity, exchangeAntigravity } from '../antigravity/oauth';
/**
 * Default filesystem roots that mirror the loader's production layout.
 *
 * Tests override `filesystemRoots` to point at a temp directory — the
 * plugin will then read/write config + sidebar + port files inside the
 * test's mkdtemp root, never touching the host's actual HOME or XDG
 * dirs.
 */
export function defaultFilesystemRoots() {
    const xdgConfig = process.env.XDG_CONFIG_HOME ?? join(homedir(), '.config');
    const xdgState = process.env.XDG_STATE_HOME ?? join(homedir(), '.local', 'state');
    return {
        projectRoot: process.cwd(),
        userConfigRoot: join(xdgConfig, 'opencode'),
        sidebarStateRoot: join(xdgState, 'cortexkit', 'antigravity-auth'),
        rpcRoot: join(xdgState, 'cortexkit', 'antigravity-auth', 'rpc'),
    };
}
/**
 * Build the default dependency bag used by production. Each default is
 * deliberately written so the e2e tests can re-use the same functions
 * (e.g. `fetchImpl` defaults to `globalThis.fetch` — a test that wants
 * a stub can replace `globalThis.fetch` and the production bag picks it
 * up on the next call).
 */
export function resolvePluginDependencies(overrides = {}) {
    const fetchImpl = overrides.fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
    const agyTransport = overrides.agyTransport ?? fetchWithAgyCliTransport;
    const roots = {
        ...defaultFilesystemRoots(),
        ...overrides.filesystemRoots,
    };
    const oauth = {
        authorize: overrides.oauth?.authorize ?? authorizeAntigravity,
        exchange: overrides.oauth?.exchange ?? exchangeAntigravity,
    };
    const clock = {
        now: overrides.clock?.now ?? (() => Date.now()),
        random: overrides.clock?.random ?? Math.random,
        sleep: overrides.clock?.sleep ?? defaultSleep,
    };
    return {
        fetchImpl,
        agyTransport,
        filesystemRoots: roots,
        oauth,
        clock,
    };
}
async function defaultSleep(ms, signal) {
    if (ms <= 0)
        return;
    await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            signal?.removeEventListener('abort', onAbort);
            resolve();
        }, ms);
        timer.unref?.();
        const onAbort = () => {
            clearTimeout(timer);
            reject(signal?.reason instanceof Error ? signal.reason : new Error('Aborted'));
        };
        signal?.addEventListener('abort', onAbort, { once: true });
    });
}
/**
 * Default `getAuth` placeholder used by sub-modules that require one
 * (auth-loader, fetch-interceptor). The plugin entry builds the live
 * version once auth has loaded.
 */
export const placeholderGetAuth = async () => ({
    type: 'api_key',
    key: '',
});
//# sourceMappingURL=dependencies.js.map