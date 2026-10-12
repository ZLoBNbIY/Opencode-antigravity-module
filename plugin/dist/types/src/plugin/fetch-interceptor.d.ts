import { type AccountRepository } from '@cortexkit/antigravity-auth-core';
import { type AccountManager } from './accounts.js';
import type { GetAuth } from './auth.js';
import type { AntigravityConfig } from './config/index.js';
import type { AgyTransport, FetchImpl } from './dependencies.js';
import type { OperatorSettingsController } from './operator-settings.js';
import type { QuotaManager } from './quota.js';
import type { AgySessionRegistry } from './session-context.js';
import { type RequestRoutingEntry } from './shared/request-services.js';
import { type VaultAccountPool, type VaultRequestSource } from './shared/vault-request-credentials.js';
import type { PluginClient } from './types.js';
/**
 * Inputs the fetch interceptor needs from the plugin bootstrap. Each plugin
 * instance builds its own interceptor without sharing state with siblings.
 */
export interface FetchInterceptorContext {
    readonly assertAdmission?: () => Promise<void>;
    readonly client: PluginClient;
    readonly directory: string;
    readonly providerId: string;
    readonly config: AntigravityConfig;
    readonly accountManager: AccountManager;
    /**
     * Where `accountManager`'s accounts come from, as the auth loader opened
     * them. `pool-file`: the pre-store pool file, whose tokens are refreshed
     * through the host's OAuth refresh. `store`: the account store, read
     * through `repository`, the same opening the manager was loaded from;
     * tokens are refreshed only by the repository on the selected account's
     * own row reference, and every send is checked against that row.
     */
    readonly accountSource: {
        readonly kind: 'pool-file';
    } | {
        readonly kind: 'store';
        readonly repository: Pick<AccountRepository, 'read'>;
    };
    readonly quotaManager: QuotaManager;
    readonly getAuth: GetAuth;
    readonly agySessionRegistry: AgySessionRegistry;
    /**
     * Live operator settings controller. Optional for backward
     * compatibility — when present, the interceptor reads routing
     * overrides and killswitch thresholds per request.
     */
    readonly operatorSettings?: OperatorSettingsController;
    /**
     * Transport adapter used for Antigravity HTTPS requests. Defaults to
     * the production `fetchWithAgyCliTransport` when omitted; tests inject
     * a deterministic stub so the e2e workspace can route calls at a mock
     * server bound to 127.0.0.1.
     */
    readonly agyTransport?: AgyTransport;
    /**
     * HTTP primitive used for non-Antigravity URLs. Defaults to
     * `globalThis.fetch`; tests inject a guarded stub that refuses any
     * non-loopback target so a regression cannot silently leak a real
     * network call.
     */
    readonly fetchImpl?: FetchImpl;
    readonly onRouting?: (sessionId: string, entry: RequestRoutingEntry) => void;
}
/**
 * Public surface exposed to the auth-loader plumbing. `fetch` mirrors the
 * host signature so it can be slotted into `LoaderResult` unchanged.
 */
export interface FetchInterceptor {
    fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
    dispose(): void | Promise<void>;
}
/**
 * The interceptor of this plugin's own accounts. The auth loader replaces it
 * whenever it reloads the account pool, and retires the old one instead of
 * disposing it, so requests it already admitted keep running.
 */
export interface LocalFetchInterceptor extends FetchInterceptor {
    /**
     * Refuses later Generative Language requests (they are never passed
     * upstream) and resolves once every request that entered `fetch` before
     * retirement, and its response body, has finished. `dispose` still aborts
     * them.
     */
    retire(): Promise<void>;
}
/**
 * OpenCode 1 binding of the shared request engine for accounts this plugin
 * holds itself (pool file or account store). The retry, rotation and
 * quota-fallback pipeline lives in `createRequestExecutor`; this wrapper
 * decides which requests reach it and binds the account manager, its
 * source's credential operations and OpenCode 1's collaborators.
 */
export declare function createFetchInterceptor(context: FetchInterceptorContext): LocalFetchInterceptor;
/**
 * Inputs of the OpenCode 1 interceptor for a location whose accounts the
 * vault holds (custody). There is no account manager, host OAuth record or
 * quota manager: accounts are the vault's selectable routes and every
 * credential comes from the vault source.
 */
export interface VaultFetchInterceptorContext extends Pick<FetchInterceptorContext, 'client' | 'config' | 'agySessionRegistry' | 'operatorSettings' | 'agyTransport' | 'fetchImpl' | 'onRouting' | 'assertAdmission'> {
    /** This location's custody source (the vault account source). */
    readonly source: VaultRequestSource;
    /** Share selection and cached vault state with this activation's menu and sidebar. */
    readonly pool?: VaultAccountPool;
}
/**
 * OpenCode 1 binding of the shared request engine for vault-held accounts.
 * Selection runs on an `AccountSelector` over the vault's selectable routes
 * (metadata rows, no credential). Every physical send takes a fresh receipt
 * for the selected route through `createVaultRequestCredentials`: its token
 * and project serve that one send, and a 401 is reported against it.
 * Nothing is refreshed locally, cached or copied from the host's own Google
 * sign-in, which is why no host auth is read here.
 */
export declare function createVaultFetchInterceptor(context: VaultFetchInterceptorContext): FetchInterceptor;
//# sourceMappingURL=fetch-interceptor.d.ts.map