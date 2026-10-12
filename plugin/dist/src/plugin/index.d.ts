import { BackgroundQuotaRefresh } from './background-quota-refresh';
import { type PluginDependencyOverrides } from './dependencies';
import { type PluginLifecycle } from './lifecycle';
import { type QuotaManager } from './quota';
import type { PluginInput, PluginResult } from './types';
export type { PluginResult } from './types';
/**
 * High-level options for the plugin factory. Production callers omit it
 * entirely; the e2e workspace injects overrides so the same factory can
 * build against a mock Antigravity server bound to 127.0.0.1.
 */
export interface CreateAntigravityPluginOptions {
    /**
     * Dependency overrides for the composition seam — fetch implementation,
     * Antigravity transport, OAuth primitives, filesystem roots, clock, and
     * randomness. Defaults to production implementations.
     */
    dependencies?: PluginDependencyOverrides;
    /**
     * Test-only seam: called synchronously after the background poller is
     * constructed, before `start()`. Lets wiring tests capture the instance
     * without reaching into lifecycle internals.
     */
    _onPollerCreated?: (poller: BackgroundQuotaRefresh) => void;
}
export declare function registerQuotaManagerProducer(lifecycle: PluginLifecycle, quotaManager: QuotaManager): void;
export declare const createAntigravityPlugin: (providerId: string, options?: CreateAntigravityPluginOptions) => (input: PluginInput) => Promise<PluginResult>;
export declare const AntigravityCLIOAuthPlugin: (input: PluginInput) => Promise<PluginResult>;
export declare const GoogleOAuthPlugin: (input: PluginInput) => Promise<PluginResult>;
//# sourceMappingURL=index.d.ts.map