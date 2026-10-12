/**
 * OpenCode adapter for the harness-agnostic quota manager.
 *
 * Re-exports the core `QuotaManager` types and helpers so call sites in
 * `plugin.ts` and other modules don't need to switch imports. Also wires up
 * the host-specific fetch callback that handles:
 *   1. Token refresh via the existing `refreshAccessToken` path.
 *   2. Persisting rotated refresh tokens via `client.auth.set` (matching
 *      legacy behavior).
 *   3. Resolving project context via `ensureProjectContext`.
 *
 * The legacy `checkAccountsQuota(accounts, client, providerId)` export is
 * retained as a compatibility wrapper that creates a short-lived manager
 * with `force: true` — manual quota screens must always refresh, even if
 * the background manager has backed off.
 */
import { type AccountMetadataV3, type AccountQuotaResult, type AccountQuotaTarget, type AccountRepository, type AntigravityQuotaCheckReport, type AntigravityVaultAccountSource, type AccountManager as CoreAccountManager, type FetchAccountQuota, type FetchAvailableModelsOptions, type GeminiCliQuotaSummary, type QuotaManager, type QuotaSummary, type RowRef, type VaultRouteRef, type VaultStateAttribution } from '@cortexkit/antigravity-auth-core';
import { type SidebarMachineState } from '../sidebar-state';
import { type LocalAccountCredentials } from './accounts';
import { type Logger } from './logger';
import type { PluginClient } from './types';
type QuotaFetch = NonNullable<FetchAvailableModelsOptions['fetchVia']>;
export type { AccountQuotaResult, AccountQuotaStatus, GeminiCliQuotaModel, GeminiCliQuotaSummary, PerModelQuotaEntry, QuotaGroup, QuotaGroupSummary, QuotaManager, QuotaManagerOptions, QuotaSummary, } from '@cortexkit/antigravity-auth-core';
export { classifyQuotaGroup, createQuotaManager, defaultKeyOf, } from '@cortexkit/antigravity-auth-core';
export interface CreateOpenCodeQuotaManagerOptions {
    /** Override the default key derivation (email → refresh-token hash). */
    keyOf?: (account: AccountMetadataV3) => string;
    baseBackoffMs?: number;
    maxBackoffMs?: number;
    fetchTimeoutMs?: number;
}
/**
 * Build an OpenCode-wired quota manager.
 *
 * The returned manager owns its cache, in-flight dedupe, and backoff state.
 * Register its `dispose()` with `PluginLifecycle` so refreshes abort on plugin
 * shutdown.
 *
 * The wrapper observes `refreshAccount` / `refreshAccounts` and pushes a
 * redacted sidebar snapshot after every refresh (success or backoff) so
 * the TUI's next poll renders the freshest cached quota. The snapshot is
 * sourced from the live AccountManager view (`getAccountsForSidebar`) so
 * it carries the just-updated percentages; before bootstrapping it is a
 * no-op.
 */
export declare function createOpenCodeQuotaManager(client: PluginClient, providerId?: string, options?: CreateOpenCodeQuotaManagerOptions & {
    /**
     * Optional account-snapshot provider. Wired by the plugin entry to
     * the live `AccountManager.getAccounts()` so each refresh can build
     * a sidebar snapshot from the actual cached quota + cooldown. When
     * omitted, the wrapper falls back to a no-op snapshot push.
     */
    getAccountsForSidebar?: () => SidebarQuotaAccount[] | null;
    /**
     * Optional provider for the active-account indexes per model family.
     * Wired by the plugin entry so every quota-refresh sidebar snapshot
     * carries the real `current` flag — not a hardcoded `false`.
     */
    getActiveIndexByFamily?: () => {
        claude: number;
        gemini: number;
    } | null;
    /**
     * Optional transport adapter used for both `fetchAvailableModels`
     * and the project-context lookup. When omitted, the production
     * `fetchWithAgyCliTransport` runs and binds to the real
     * Antigravity endpoints; the e2e harness injects a mock here so
     * quota refresh + project discovery stay on the loopback server.
     */
    fetchVia?: QuotaFetch;
    mayRun?: () => Promise<boolean>;
    fetchStoreAccountQuota?: FetchAccountQuota;
    /** Select the sidebar's account source before reading rows, so vault mode cannot expose the local pool. */
    publishSidebar?: () => Promise<void>;
}): QuotaManager;
/**
 * Sidebar binding for one location's quota manager. `createOpenCodeQuotaManager`
 * (the OpenCode 1 plugin's quota manager) reads these from process-wide
 * state; a location passes each one explicitly.
 */
export interface LocationQuotaSidebarOptions {
    /**
     * Receives each snapshot: the sidebar file for the OpenCode 1 layout, or
     * an in-memory store for an OpenCode 2 location, which keeps no file.
     */
    write: (state: SidebarMachineState) => Promise<void>;
    /** Live account rows for the snapshot; `null` before accounts load. */
    getAccounts: () => SidebarQuotaAccount[] | null;
    getActiveIndexByFamily?: () => {
        claude: number;
        gemini: number;
    } | null;
    /**
     * Health score (0–100, how reliably the account has answered recently)
     * per account index, from this location's account rotation. When omitted
     * the snapshot carries no score, and the sidebar shows its default of 100.
     */
    healthScore?: (index: number) => number;
    /** Clock for the snapshot's `checkedAt`. Defaults to `Date.now`. */
    now?: () => number;
}
export interface LocationQuotaManagerOptions extends CreateOpenCodeQuotaManagerOptions {
    /** This location's logger. Required: there is no module-level fallback. */
    logger: Logger;
    /**
     * Fetches one account's quota with this location's credentials and
     * transport. The location's account service supplies it; this module never
     * builds a host client or reads a shared credential cache.
     */
    fetchAccountQuota: FetchAccountQuota;
    /** Sidebar snapshot binding; without it refreshes write no snapshot. */
    sidebar?: LocationQuotaSidebarOptions;
}
/**
 * Build one location's quota manager. Backoff, in-flight dedupe and the
 * per-account cache belong to the returned manager alone, so a second
 * location never shares another location's backoff or cached results.
 * Refreshes push a sidebar snapshot exactly like `createOpenCodeQuotaManager`
 * does, but to the location's own state file and through its own logger.
 */
export declare function createLocationQuotaManager(options: LocationQuotaManagerOptions): QuotaManager;
/**
 * Compatibility wrapper used by code paths that want a one-shot check across
 * the full account pool with no shared cache.
 *
 * Equivalent to spinning up a short-lived manager with `force: true` so
 * manual quota dialogs always reflect the latest data even if the background
 * manager has backed off.
 */
export declare function checkAccountsQuotaWith(accounts: AccountMetadataV3[], fetchAccountQuota: FetchAccountQuota): Promise<AccountQuotaResult[]>;
export declare function checkAccountsQuotaStandalone(accounts: AccountMetadataV3[], options: {
    refresh: boolean;
}): Promise<AccountQuotaResult[]>;
export declare function checkAccountsQuota(accounts: AccountMetadataV3[], client: PluginClient, providerId?: string): Promise<AccountQuotaResult[]>;
/** One live account row a sidebar quota snapshot is built from. */
export interface SidebarQuotaAccount {
    index: number;
    label?: string;
    enabled?: boolean;
    coolingDownUntil?: number;
    cachedQuota?: AccountMetadataV3['cachedQuota'];
    cachedQuotaUpdatedAt?: number;
    cachedQuotaAccountId?: string;
    currentQuotaAccountId?: string;
    /** Captured plan tier to surface in the sidebar state file. */
    tier?: {
        id: string;
        paidId?: string;
        capturedAt: number;
    };
}
/**
 * Where a sidebar quota snapshot goes and which state it reads. Omitted
 * fields use process-wide defaults, as the OpenCode 1 plugin (one location
 * per process) always has: the default sidebar file, module logger, health
 * tracker and wall clock.
 */
export interface SidebarQuotaSnapshotOptions {
    /** Sidebar state file to write. Defaults to the process-wide file. */
    stateFile?: string;
    /**
     * Receives the redacted quota snapshot (account rows, `checkedAt` and
     * backoff) instead of it being written to a sidebar file. When given,
     * `stateFile` is ignored and no file is written.
     */
    write?: (state: SidebarMachineState) => Promise<void>;
    /** Receives best-effort write failures. Defaults to the module logger. */
    logger?: Pick<Logger, 'debug'>;
    /**
     * Health score per account index. `undefined` reads the process-wide
     * tracker; `null` writes no score so the projection uses its default.
     */
    healthScore?: ((index: number) => number) | null;
    /** Clock for `checkedAt`. Defaults to `Date.now`. */
    now?: () => number;
}
/**
 * Push a quota refresh into the sidebar. Called by every quota refresh
 * call site (manual `/antigravity-quota`, the `check` menu action, and the
 * background refresh in `fetch-interceptor`) AFTER the results have been
 * folded back into the AccountManager's cached quota. The function reads
 * the live account snapshot through `getAccounts` so the redacted entry
 * carries the just-refreshed percentages — not the previous tick's stale
 * numbers and not `undefined`.
 *
 * The mapping is deliberately tolerant: if `getAccounts` returns `null`
 * (e.g. before the plugin has finished bootstrapping) the call is a no-op.
 * On lock contention the error is logged-and-swallowed so a quota dialog
 * never fails just because the sidebar file is busy.
 */
export declare function pushSidebarQuotaSnapshot(getAccounts: () => SidebarQuotaAccount[] | null, backoffUntil?: number, getActiveIndexByFamily?: () => {
    claude: number;
    gemini: number;
} | null, options?: SidebarQuotaSnapshotOptions): Promise<void>;
/** The vault account source operations a quota check uses. */
export type VaultQuotaSource = Pick<AntigravityVaultAccountSource, 'send' | 'attribution'>;
/** Quota summaries and the credential versions that authorized their requests. */
export interface VaultQuotaReading {
    quota: QuotaSummary;
    geminiCliQuota: GeminiCliQuotaSummary;
    fellBackToLegacy: boolean;
    /**
     * The credential and record version of the receipt that authorized the
     * request whose answer produced `quota` (no token, no project), for
     * recording it with the source's `commitState`. Absent when no quota
     * answer was obtained.
     */
    quotaAttribution?: VaultStateAttribution;
    /** Likewise for `geminiCliQuota`. */
    geminiCliAttribution?: VaultStateAttribution;
}
export interface VaultQuotaCheckOptions {
    source: VaultQuotaSource;
    /** The vault account, as selected from the source's routes. */
    ref: VaultRouteRef;
    signal: AbortSignal;
    logger: Pick<Logger, 'debug'>;
    /** Physical request transport; defaults to `fetchWithActiveTimeout`. */
    transport?: QuotaFetch;
}
/**
 * Fetches a vault account's quota: the windowed quota summary (with the
 * legacy model-list fallback) and the Gemini CLI quota, from the same core
 * builders and endpoint list the local check uses.
 *
 * Every physical request (each endpoint, each fallback, and the model
 * list's retry without a project after a 403) is one `source.send` with a
 * new served receipt, and that request's bearer and project come from that
 * receipt alone. Nothing is authorized once and reused, and no local refresh
 * token, token exchange, project cache or earlier grant is used. A refused
 * receipt or an abort stops the check with no further request. Recording
 * the reading (with the returned attributions and the source's
 * `commitState`) is the caller's.
 */
export declare function fetchVaultAccountQuota(options: VaultQuotaCheckOptions): Promise<VaultQuotaReading>;
/** Result of re-checking a local grant immediately before one request. */
export type LocalQuotaGrantCheck = {
    readonly status: 'current';
} | {
    readonly status: 'stale';
    readonly reason: string;
};
/**
 * The bearer and project one quota check may use, or why it may not run.
 * Only a LOCAL credential (a stored OAuth grant the caller resolved for the
 * exact account being checked) can authorize a check here. A vault
 * credential needs a fresh admission for every physical request and goes
 * through the vault source's own per-send admission instead.
 */
export type LocalQuotaCheckAuthorization = {
    readonly status: 'authorized';
    readonly domain: 'local';
    readonly accessToken: string;
    readonly projectId: string;
    readonly managedProjectId?: string;
    /**
     * Required per-send freshness check, bound by the caller to the
     * account reference it captured and to this access token. It runs
     * immediately before every physical quota request (after every earlier
     * await of that request); `stale` means the account no longer holds
     * that exact credential, and no further request of the check is sent.
     */
    readonly confirmSend: (signal: AbortSignal) => Promise<LocalQuotaGrantCheck>;
} | {
    readonly status: 'refused';
    readonly reason: string;
};
export interface AuthorizedFetchAccountQuotaOptions {
    /**
     * Resolves the local bearer and project for exactly the account being
     * checked. It is called once per check, before this fetcher awaits
     * anything, with the same account object the quota manager handed in, so
     * the callback can capture that account's identity (for example a
     * repository row reference it carries) before any other work runs. This
     * fetcher never refreshes, caches or stores a token.
     */
    authorize(account: AccountMetadataV3, signal: AbortSignal): Promise<LocalQuotaCheckAuthorization>;
    /** Receives the fetcher's diagnostic records; never tokens. */
    logger: Pick<Logger, 'debug'>;
    /**
     * Transport for one check's quota requests, given the check's abort
     * signal. Without it, requests go through `fetchWithActiveTimeout` (the
     * core package's default quota transport) with that signal.
     */
    transport?: (signal: AbortSignal) => QuotaFetch;
}
/**
 * A quota fetcher for LOCAL credentials whose bearer and project come from
 * the caller's `authorize` callback instead of the account's stored refresh
 * token. The network requests and result shape are the OpenCode 1
 * fetcher's (`fetchQuotaPayloads`), sent through a transport that calls the
 * authorization's `confirmSend` before every physical request.
 *
 * - A disabled account is answered without calling `authorize`.
 * - A refused authorization, an authorization that is not `local`, or a
 *   throw from `authorize` is answered as an error result without any
 *   request.
 * - Once `confirmSend` reports `stale`, no further request of the check is
 *   sent and the whole check is answered as an error, so a reading taken
 *   for a replaced or removed credential is never applied.
 * - The result never carries `updatedAccount`: any credential or project
 *   change belongs to the `authorize` callback, which knows which stored row
 *   it may write to.
 */
export declare function createAuthorizedFetchAccountQuota(options: AuthorizedFetchAccountQuotaOptions): FetchAccountQuota;
/**
 * Build a per-account tier-loader callback for the background poller.
 *
 * Calls `loadManagedProject` (loadCodeAssist) directly. The
 * `ensureProjectContext` cache answers from a known `managedProjectId`
 * without asking Google, so for an account that already has a project it
 * never returns a tier; the tier is only in loadCodeAssist's answer. One
 * call per account per 24 h.
 *
 * An expired access token is refreshed the same way `makeFetchAccountQuota`
 * refreshes it, so the lookup does not fail just because the token aged.
 *
 * `loadManagedProject` sends through the native TLS transport
 * (`fetchWithAgyCliTransport`), not through a generic `fetch`, so a
 * `fetchVia` override cannot intercept it; `ensureProjectContext` has the
 * same limit. Tier lookup is best-effort; any failure resolves `null`.
 */
export declare function makeTierLoader(client: PluginClient | undefined, providerId: string, options?: {
    mayRun?: () => Promise<boolean>;
    authorizeStore?: (account: AccountQuotaTarget) => Promise<LocalQuotaCheckAuthorization>;
}): (account: AccountMetadataV3) => Promise<{
    id: string;
    paidId?: string;
    capturedAt: number;
} | null>;
/** What one account-store quota check did with its reading. */
export type StoreQuotaOutcome = {
    /**
     * The reading was handed to the manager for exactly the checked row
     * and credential. This does not prove the store kept it:
     * `checkStoreQuota` reads the store back and compares the whole
     * reading.
     */
    readonly status: 'recorded';
    readonly result: AccountQuotaResult;
    /** The reading this check produced, as the manager recorded it. */
    readonly reading: RecordedQuotaReading;
} | {
    /**
     * The check ran, but the row no longer holds the checked credential
     * (replaced, re-added or removed); the reading is discarded, never
     * attached to whatever holds the row now.
     */
    readonly status: 'discarded';
    readonly result: AccountQuotaResult;
}
/** The check failed or was refused; nothing was recorded. */
 | {
    readonly status: 'failed';
    readonly result: AccountQuotaResult;
};
export type { AntigravityQuotaCheckReport };
/**
 * One check's reading, captured at the moment it was handed to the manager,
 * so a later reading for the same row cannot be mistaken for it.
 */
export interface RecordedQuotaReading {
    readonly cachedQuotaAccountId: string | undefined;
    readonly cachedQuotaUpdatedAt: number | undefined;
    /** Canonical form of the quota groups (`canonicalQuotaGroups`). */
    readonly groups: string;
}
/**
 * Quota checks for one plugin account pool served by the account store.
 * The service owns that pool's quota cache, in-flight deduplication and
 * backoff.
 */
export interface StoreQuotaService {
    readonly authorizeLocalCheck: (account: AccountQuotaTarget) => Promise<LocalQuotaCheckAuthorization>;
    readonly fetchAccountQuota: FetchAccountQuota;
    /** The pool's quota manager (cache, in-flight dedupe and backoff). */
    readonly quotaManager: QuotaManager;
    /**
     * Checks one account, named by the quota target the caller took from
     * `getAccountsForQuotaCheck()` (its `rowRef` is the identity). `force`
     * is the manual check: it bypasses backoff.
     */
    refreshAccount(target: AccountQuotaTarget, options?: {
        force?: boolean;
    }): Promise<StoreQuotaOutcome>;
    /** Checks every account in the pool, not only the selected one. */
    refreshAll(options?: {
        force?: boolean;
    }): Promise<StoreQuotaOutcome[]>;
    /**
     * The menu's manual quota action: checks exactly the accounts named by
     * `refs` (the refs the menu read before the action), bypassing backoff.
     * A ref the manager does not hold at that exact credential is not
     * checked. After the checks, the store is read back: a ref counts as
     * checked only when the store's row at that exact ref holds this check's
     * whole reading (identity stamp, time and every group). A matching time
     * alone is not proof the reading was written.
     */
    checkStoreQuota(refs: readonly RowRef[]): Promise<AntigravityQuotaCheckReport>;
    dispose(): Promise<void>;
}
export interface StoreQuotaServiceOptions {
    readonly mayRun?: () => Promise<boolean>;
    /** The pool's account manager, whose accounts come from the repository. */
    manager: CoreAccountManager;
    /** That manager's repository; read back to confirm recorded readings. */
    repository: Pick<AccountRepository, 'read'>;
    logger: Logger;
    /** Defaults to `createLocalAccountCredentials(manager)`. */
    credentials?: Pick<LocalAccountCredentials, 'refresh' | 'ensureProject' | 'assertGrantCurrent'>;
    /** Quota request transport; see `createAuthorizedFetchAccountQuota`. */
    transport?: (signal: AbortSignal) => QuotaFetch;
    sidebar?: LocationQuotaSidebarOptions;
    baseBackoffMs?: number;
    maxBackoffMs?: number;
    fetchTimeoutMs?: number;
}
/**
 * Quota checks for one plugin account pool whose accounts come from the
 * account store. One check, in order:
 * 1. Capture the target's RowRef before any await, and take the manager's
 *    account holding exactly that ref; if none does, the check is refused.
 * 2. If that account's access token has expired, refresh it through the
 *    repository, which commits the new token only to the row still holding
 *    that ref. Neither a token copied from an earlier read nor the host
 *    client is used.
 * 3. Resolve the account's project from the local project cache; a newly
 *    resolved project is recorded through the manager on the account's ref.
 * 4. Before every physical quota request, check that the manager still
 *    holds the same account object, at the same ref, enabled, with the same
 *    access token; otherwise no further request of the check is sent.
 * 5. Hand the reading to the manager only while it still holds that exact
 *    ref; otherwise discard it. The manager's write can still be refused by
 *    the store, so `checkStoreQuota` reads the store back and counts a
 *    check only when the store holds this check's whole reading.
 *
 * Only accounts whose refresh token is stored locally use this service;
 * vault-held accounts never do.
 */
export declare function createStoreQuotaService(options: StoreQuotaServiceOptions): StoreQuotaService;
//# sourceMappingURL=quota.d.ts.map