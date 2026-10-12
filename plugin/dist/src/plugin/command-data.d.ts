/**
 * Privacy-safe data service for the data-first slash-command dialogs.
 *
 * `/antigravity-quota` (this task) and the future `/antigravity-account`
 * dialogs (Tasks 10-11) read from a single shared service so they
 * never touch raw account storage, never see the email PII field, and
 * never run quota network I/O during the dialog's open path — the
 * Refresh action is the only path that performs a live fetch.
 *
 * Why this is a separate module:
 *
 * - `commands.ts` owns the slash-command orchestration; mixing the row
 *   projection + quota refresh logic in there would balloon the surface
 *   for what is fundamentally a small read/refresh service.
 * - The row type (`CommandAccountRow`) is the projection that crosses
 *   the PII firewall into the dialog payload. Defining it here (next
 *   to the code that constructs it) keeps the firewall reviewable.
 * - Tests can pin the read-vs-refresh boundary, the email redaction, and
 *   the refresh-token-keyed persistence in one file rather than chasing
 *   them across the dispatcher + RPC + apply layers.
 *
 * Cache-only opening contract (Task 9 operator requirement):
 *
 *   `listAccounts()` is a pure read of the live AccountManager view
 *   the auth-loader materialized at session start. It performs
 *   ZERO quota manager calls — opening the dialog must be instant even
 *   when the network is unreachable, and quota refresh must remain an
 *   explicit user-driven action so the cached percentages never quietly
 *   rewrite themselves behind the user's back.
 *
 * Refresh-token-keyed persistence (Task 9 plan trap):
 *
 *   `refreshQuota()` runs the shared quota manager across every enabled
 *   account and folds the results back into the live AccountManager +
 *   storage. Concurrent OAuth can renumber the flat `accounts[]` array
 *   between read and write, so we re-read under the lock and key the
 *   update by `refreshToken` (the canonical identity) rather than the
 *   array index. This way a successful OAuth add that lands between
 *   the read and the write cannot cause the refresh to overwrite the
 *   wrong account.
 */
/**
 * Local copies of the few core types the data service touches.
 *
 * The shipped TUI tree cannot depend on the `@cortexkit/antigravity-auth-core`
 * barrel (only subpath imports like `./file-lock` are allowed) — the
 * compiled `command-data.ts` is copied verbatim into `tui-compiled/`,
 * and the type-import would otherwise leak the full core surface into
 * the dialog render path. Declaring the structural shape locally keeps
 * the compiled tree free of the barrel while preserving duck-typed
 * compatibility with the production quota manager.
 */
type CommandDataAccountMetadata = {
    email?: string;
    refreshToken: string;
    projectId?: string;
    managedProjectId?: string;
    addedAt: number;
    lastUsed: number;
    enabled?: boolean;
    label?: string;
    cachedQuota?: Partial<Record<CommandDataQuotaGroup, CommandDataQuotaGroupSummary>>;
    cachedQuotaUpdatedAt?: number;
    cachedQuotaAccountId?: string;
    accountIneligible?: boolean;
};
type CommandDataQuotaGroup = 'gemini' | 'non-gemini';
type CommandDataQuotaGroupSummary = {
    remainingFraction?: number;
    resetTime?: string;
    modelCount: number;
    windows?: Array<{
        window: 'weekly' | '5h';
        remainingFraction: number;
        resetTime: string;
    }>;
};
type CommandDataAccountQuotaResult = {
    index: number;
    status: 'ok' | 'disabled' | 'error';
    error?: string;
    disabled?: boolean;
    quota?: {
        groups: Partial<Record<CommandDataQuotaGroup, CommandDataQuotaGroupSummary>>;
        perModel?: Array<{
            modelId: string;
            displayName?: string;
            group: CommandDataQuotaGroup | null;
            remainingFraction: number;
            resetTime?: string;
        }>;
        modelCount: number;
        error?: string;
    };
    updatedAccount?: CommandDataAccountMetadata;
};
export interface CommandDataAccountStorage {
    version: 4;
    activeIndex: number;
    activeIndexByFamily?: {
        claude?: number;
        gemini?: number;
    };
    accounts: CommandDataAccountMetadata[];
}
/**
 * Privacy-safe per-account row shown in `/antigravity-*` data-first
 * dialogs. Carries the cached quota percentages and the labels the
 * dialog needs, but NEVER the email — the email stays in private
 * account storage and is invisible to the sidebar and the dialog.
 *
 * `index` is the position in the live account array at the time of
 * projection. It is informational only and is NOT a stable identity
 * across refreshes — concurrent OAuth can renumber the array between
 * the dialog opening and a refresh.
 */
export interface CommandAccountRow {
    /** Stable identity for dialog keying (`acct-<index>`). */
    id: string;
    /** Position in the live account array at projection time. */
    index: number;
    /** Privacy-safe ordinal display label (for example, `Account 1`). */
    label: string;
    enabled: boolean;
    /** `true` when this row matches the harness-active account. */
    current: boolean;
    /**
     * Absolute timestamp (ms) until which this account is rate-limited.
     * Carried on the row so the sidebar refresher can match cooldowns
     * without relying on unstable numeric indices.
     */
    coolingDownUntil?: number;
    /** Health score in [0, 100], forwarded from the live tracker. */
    healthScore?: number;
    cachedQuotaUpdatedAt?: number;
    quota: Array<{
        key: 'gemini' | 'non-gemini';
        label: string;
        remainingPercent: number | null;
        resetAt?: number;
        windows?: Array<{
            window: 'weekly' | '5h';
            remainingPercent: number;
            resetAt?: number;
        }>;
    }>;
    /** Captured plan tier. Absent when unknown; never defaulted. */
    tier?: {
        id: string;
        capturedAt: number;
    };
}
interface LiveAccountSnapshot {
    index: number;
    refreshToken: string;
    label?: string;
    enabled: boolean;
    active: boolean;
    cachedQuota?: Partial<Record<CommandDataQuotaGroup, CommandDataQuotaGroupSummary>>;
    cachedQuotaUpdatedAt?: number;
    cachedQuotaAccountId?: string;
    accountIneligible?: boolean;
    coolingDownUntil?: number;
    healthScore?: number;
    /** Captured plan tier from the most recent loadCodeAssist response. */
    capturedTierId?: string;
    /** Captured paid-tier ID from the most recent loadCodeAssist response. */
    capturedPaidTierId?: string;
    /** Epoch ms when capturedTierId was last recorded. */
    capturedTierAt?: number;
}
export declare function projectCommandAccountRows(storage: CommandDataAccountStorage | null | undefined): CommandAccountRow[];
/**
 * Live AccountManager view the data service needs.
 *
 * - `getAccounts()` returns the in-memory snapshot — used for cache-only
 *   reads during dialog open and for re-reading the post-mutation state.
 *   `getAccountsForQuotaCheck()` returns the freshest `AccountMetadataV3`
 *   (the canonical shape the quota manager expects).
 * - `updateQuotaCache(index, groups)` + `requestSaveToDisk()` fold the
 *   refreshed quota back into the live view and persist it. The service
 *   calls them together after the network fetch resolves.
 * - `setAccountEnabled`, `setAccountCurrent`, `removeAccountByIndex`
 *   mirror the CLI menu's mutation primitives — the dialog actions
 *   (Task 10) reuse them so the TUI never invents its own mutation
 *   logic. Each method returns `true` when the live view changed.
 * - `getRefreshTokenAt(index)` lets the service identify the canonical
 *   account identity before it reaches the locked storage mutator; a
 *   concurrent OAuth could renumber the flat array between the dialog
 *   opening and the apply, so keying by refresh token is mandatory.
 * - `flushSaveToDisk()` drains the AccountManager's debounced save so a
 *   dialog-triggered mutation lands on disk before the dialog's response
 *   returns. Without it, the dialog could toast "Account removed" while
 *   the file still carries the old pool.
 */
export interface CommandDataAccountManagerView {
    getAccounts(): LiveAccountSnapshot[];
    getAccountsForQuotaCheck(): CommandDataAccountMetadata[];
    updateQuotaCache(index: number, groups: Partial<Record<CommandDataQuotaGroup, CommandDataQuotaGroupSummary>>, expectedRefreshToken?: string): void;
    requestSaveToDisk(): void;
    flushSaveToDisk(): Promise<void>;
    /**
     * Per-family live cursor. Used by the remove path so the persisted
     * `activeIndexByFamily` follows each model's currently-active account
     * independently — collapsing both families to a single index would
     * silently unelect one family on every restart.
     */
    getActiveIndexByFamily(): {
        claude: number;
        gemini: number;
    };
    /** Enable/disable the account at `index`. Returns true when it changed. */
    setAccountEnabled(index: number, enabled: boolean): boolean;
    /** Pin `index` as the active account for every family the dialog cares about. */
    setAccountCurrent(index: number): boolean;
    /** Remove the account at `index` from the live view. Returns true when it changed. */
    removeAccountByIndex(index: number): boolean;
    /** Canonical refresh token for the account at `index`, or undefined. */
    getRefreshTokenAt(index: number): string | undefined;
}
/**
 * Storage adapter the data service uses for re-read-under-lock writes.
 * `mutate` runs the supplied callback against the latest snapshot under
 * the file lock — the callback receives the current storage and may
 * return a replacement; returning the input unchanged is a no-op.
 *
 * The promise resolves with the (possibly mutated) storage snapshot so
 * the data service can await it. A rejected promise signals a failed
 * write — `AccountStorageUnreadableError`, lock contention, or any
 * other I/O failure — which the data service surfaces to the dialog
 * as a friendly error toast.
 */
export interface CommandDataStorage {
    mutate(mutator: (current: CommandDataAccountStorage) => CommandDataAccountStorage | undefined | Promise<CommandDataAccountStorage | undefined>): Promise<CommandDataAccountStorage | undefined> | undefined;
}
/**
 * Options for `createCommandDataService`. Each field is required so
 * production wiring is explicit — a missing dependency is a startup
 * error, not a silent no-op at dialog-open time.
 */
export interface CommandDataServiceOptions {
    accountManagerView: CommandDataAccountManagerView;
    quotaManager: {
        refreshAccounts(accounts: CommandDataAccountMetadata[], options: {
            indexFor?: (account: CommandDataAccountMetadata) => number;
            force?: boolean;
        }): Promise<CommandDataAccountQuotaResult[]>;
    };
    /** Path to the label-only sidebar state file. */
    sidebarStateFile: string;
    /**
     * Optional storage adapter. When provided, the service persists the
     * refreshed quota to disk via the lock-held mutator (best-effort —
     * a lock contention never breaks the dialog response). When omitted,
     * the service still folds results into the live AccountManager view;
     * the auth-loader is responsible for the on-disk write.
     */
    storage?: CommandDataStorage;
    /** Clock for `cachedQuotaUpdatedAt`. Tests inject a fixed clock. */
    now?: () => number;
}
/**
 * Public surface of the command-data service. Each method is the
 * smallest possible projection so the dialog layer never has to know
 * how the underlying quota manager or storage adapter is wired.
 */
export interface CommandDataService {
    /**
     * Cache-only snapshot. Performs zero quota manager calls — safe to
     * call as part of the dialog's open path.
     */
    listAccounts(): Promise<CommandAccountRow[]>;
    /**
     * Force-refresh quota through the shared quota manager, persist by
     * refresh token, bump `cachedQuotaUpdatedAt`, and push a label-only
     * sidebar snapshot. Returns the freshly persisted rows so the
     * dialog can re-render in place.
     *
     * Bypass flag is intentional: explicit user-triggered refreshes
     * ("Refresh" button, direct slash-command with `refresh` argument)
     * must always fetch, even if the quota manager has backed off.
     */
    refreshQuota(): Promise<CommandAccountRow[]>;
    /**
     * Non-forced quota check that RESPECTS the quota manager's per-account
     * backoff. Used by the dialog OPEN path — which is a VIEW, not a user
     * request to fetch. Accounts already fresh (or in backoff) are skipped;
     * the result is discarded (the sidebar poller carries the freshness
     * guarantee for idle accounts).
     */
    refreshQuotaRespectingBackoff(): Promise<void>;
    /**
     * Pin `index` as the active account for every family the dialog
     * tracks (claude + gemini). Mutates the live AccountManager AND the
     * locked storage so the new active index survives a restart. Returns
     * the freshly projected rows so the dialog can re-render in place.
     * Returns `null` when the index is out of range or the account has
     * no refresh token — the dialog surfaces the null as a toast.
     */
    setCurrentAccount(index: number): Promise<CommandAccountRow[] | null>;
    /**
     * Flip the `enabled` flag on the account at `index`. Mirrors the CLI
     * menu's "manage" toggle so the on-disk state matches what the CLI
     * would produce. Returns the freshly projected rows (or `null` when
     * the index is invalid or the account is ineligible).
     */
    toggleAccountEnabled(index: number): Promise<CommandAccountRow[] | null>;
    /**
     * Remove the account at `index` from both the live view and the
     * locked storage. Removal renumbers the flat `accounts[]` array so
     * the returned rows use the freshest indices; callers MUST re-key
     * their transient dialog IDs (`acct-${index}`) by the row's `id`
     * field after this method returns.
     *
     * Returns `null` when the index is out of range — the dialog
     * surfaces the null as a toast.
     */
    removeAccount(index: number): Promise<CommandAccountRow[] | null>;
}
/**
 * Build the data service.
 *
 * The factory form (instead of a module-level singleton) keeps the
 * service unit-testable: each test constructs its own dependencies
 * (storage stub, quota manager stub, fixed clock) without touching
 * the production quota path.
 */
export declare function createCommandDataService(options: CommandDataServiceOptions): CommandDataService;
export {};
//# sourceMappingURL=command-data.d.ts.map