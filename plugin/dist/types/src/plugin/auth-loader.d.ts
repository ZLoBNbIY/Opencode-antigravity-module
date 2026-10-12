import { type AccountManager as CoreAccountManager, type EnrollmentAuthority } from '@cortexkit/antigravity-auth-core';
import { AccountManager } from './accounts.js';
import type { AntigravityConfig } from './config/index.js';
import { getLogFilePath, isDebugEnabled } from './debug.js';
import type { FetchImpl } from './dependencies.js';
import type { PluginLifecycle } from './lifecycle.js';
import { createLocationProactiveRefreshQueue, createProactiveRefreshQueue } from './refresh-queue.js';
import { type AccountStoreOpening, clearAccounts, loadAccounts } from './storage.js';
import type { GetAuth, LoaderResult, PluginClient, Provider } from './types.js';
export interface AuthFetchRuntime {
    fetch: LoaderResult['fetch'];
    dispose(): Promise<void> | void;
}
/**
 * The runtime of this plugin's own accounts. A reload retires the runtime it
 * replaces instead of disposing it: requests it already admitted keep
 * running on the account manager they started with, and that manager is
 * disposed only after they finish.
 */
export interface LocalFetchRuntime extends AuthFetchRuntime {
    /** Refuses new requests; resolves once admitted requests have finished. */
    retire(): Promise<void>;
}
/**
 * Request routing uses the repository manager for an active account store.
 * The pool-file manager remains only for the fresh-install compatibility
 * path; an existing pool cannot serve before explicit offline migration.
 */
export type RuntimeAccountManager = AccountManager | CoreAccountManager;
export type CreateAuthFetch = (input: {
    accountManager: RuntimeAccountManager;
    getAuth: GetAuth;
    /**
     * Where `accountManager`'s accounts come from: the pool file, or the
     * account store through the repository of the same opening the manager
     * was loaded from.
     */
    source: {
        kind: 'pool-file';
    } | {
        kind: 'store';
        repository: Extract<AccountStoreOpening, {
            status: 'ready';
        }>['repository'];
    };
}) => LocalFetchRuntime;
/**
 * Loader returned by `createAuthLoader`. The function loads the
 * account pool from disk and installs the runtime.
 */
export type LoadAndInstallRuntime = (getAuth: GetAuth, provider: Provider) => Promise<LoaderResult | Record<string, unknown>>;
/**
 * Reload the live AccountManager + fetch runtime without going through
 * the full startup loader. Used by the OAuth add flow so the new account
 * is visible to routing immediately after `persistAccountPool`.
 */
export type ReloadAccountRuntime = (getAuth: GetAuth) => Promise<void>;
export interface AuthLoaderHandle {
    load: LoadAndInstallRuntime;
    reload: ReloadAccountRuntime;
    /**
     * This plugin's single opening of its account pool's store. OAuth
     * additions and account commands must use this same opening, so they
     * write through the very repository request routing reads.
     */
    accountStore(): Promise<AccountStoreOpening>;
    /** Whether that opening leaves the pool file as the source of accounts. */
    usesPoolFile(opening: AccountStoreOpening): boolean;
    /**
     * The explicit first-account step of a genuinely fresh installation: when
     * the plugin's account pool has neither a pool file nor a store
     * (`initialization-required`), creates an empty account store and opens
     * it, so the first login is admitted by the store rather than written to
     * a new pool file. Any other opening is returned unchanged; nothing is
     * initialized over an existing pool file or store.
     */
    initializeFreshStore(): Promise<AccountStoreOpening>;
}
interface AuthLoaderDependencies {
    loadAccounts: typeof loadAccounts;
    clearAccounts: typeof clearAccounts;
    loadAccountManager(auth: Parameters<typeof AccountManager.loadFromDisk>[0]): Promise<AccountManager>;
    createRefreshQueue: typeof createProactiveRefreshQueue;
    /** The proactive queue of a store-backed manager; see `installRuntime`. */
    createStoreRefreshQueue: typeof createLocationProactiveRefreshQueue;
    /** Creates the empty store of a fresh installation. */
    initializeFreshStore(): Promise<{
        status: string;
    }>;
    isDebugEnabled: typeof isDebugEnabled;
    getLogFilePath: typeof getLogFilePath;
    /**
     * Opens the account store (`openAccountStore`). An existing unmigrated pool
     * makes local requests unavailable without loading the pool. Pending work,
     * rollback, or invalid store files refuse rather than falling back to it.
     */
    openAccountStore(): Promise<AccountStoreOpening>;
}
interface CreateAuthLoaderOptions {
    publishSidebar?: () => Promise<void>;
    client: PluginClient;
    providerId: string;
    config: AntigravityConfig;
    lifecycle: PluginLifecycle;
    createFetch: CreateAuthFetch;
    fetchImpl?: FetchImpl;
    readAuthority?: () => Promise<EnrollmentAuthority>;
    createVaultFetch?: () => Promise<AuthFetchRuntime>;
    onGetAuth?(getAuth: GetAuth): void;
    dependencies?: Partial<AuthLoaderDependencies>;
}
export declare function createAuthLoader({ publishSidebar, client, providerId, config, lifecycle, createFetch, fetchImpl, readAuthority, createVaultFetch, onGetAuth, dependencies, }: CreateAuthLoaderOptions): LoadAndInstallRuntime & AuthLoaderHandle;
export {};
//# sourceMappingURL=auth-loader.d.ts.map