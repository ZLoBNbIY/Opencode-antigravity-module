/**
 * Sidebar state contract for the OpenTUI sidebar.
 *
 * This module is the read-only seam between the long-running plugin and the
 * Solid/OpenTUI sidebar tree. It deliberately does NOT import account storage,
 * the account manager, OAuth code, or any other privileged host-side module:
 * the TUI is rendered inside the host's terminal and a single stray import
 * could leak credentials or pull a heavy manager into the render path.
 *
 * The plugin writes a redacted snapshot to the file resolved by
 * `getSidebarStateFile()` and the TUI polls it. The contract version is `1`:
 * any future field that the TUI cannot understand must be ignored, and any
 * broken/missing file must collapse to `DEFAULT_SIDEBAR_STATE`.
 *
 * ## Writer surface
 *
 * The plugin-side writers live here too so the read and write halves of the
 * contract evolve together. They are imported by the plugin (auth-loader,
 * quota, fetch-interceptor, event-handler, commands) but never invoked from
 * the TUI's compiled tree — that tree only calls the readers, so the
 * heavyweight core imports below never run inside the host's render path.
 *
 * Every disk mutation follows the same recipe:
 *
 *   1. Serialize through `sidebarWriteChain` so concurrent in-process calls
 *      never interleave merges against the same file.
 *   2. Acquire `acquireFencedFileLock` with bounded retry+jitter
 *      (≤2s). A live cross-process holder that does not release in time
 *      surfaces as `SidebarStateLockContentionError`.
 *   3. Re-read and normalize the on-disk state while holding the lock.
 *   4. Merge the new machine or routing payload against the re-read state.
 *   5. `assertOwned()` + `writeJsonAtomic` with mode 0o600, re-checking
 *      `assertOwned()` after the temp file is staged and just before the
 *      rename, then release.
 *
 * The merge step is deterministic: machine fields adopt only when the new
 * `checkedAt` is ≥ the on-disk one, `routingAuthoritative` is sticky-true,
 * and `activeRouting` is merged independently and pruned to the freshest
 * 100 entries within 24h.
 */
export declare const SIDEBAR_STATE_VERSION: 1;
export type SidebarQuotaKey = 'gemini' | 'non-gemini';
export interface SidebarQuotaWindowEntry {
    window: 'weekly' | '5h';
    remainingPercent: number;
    checkedAt?: number;
    resetAt?: number;
}
export interface SidebarQuotaEntry {
    /** Most-constrained window's remaining % (derived, for back-compat). */
    remainingPercent: number;
    checkedAt?: number;
    resetAt?: number;
    /** Per-window breakdown. Omitted in pre-windows snapshots. */
    windows?: SidebarQuotaWindowEntry[];
}
export interface SidebarAccountState {
    id: string;
    label: string;
    enabled: boolean;
    health: number;
    current: boolean;
    cooldownUntil?: number;
    quota: Partial<Record<SidebarQuotaKey, SidebarQuotaEntry>>;
    /**
     * Captured plan tier. Absent when unknown — do NOT default to `free-tier`.
     * `id` is the raw upstream string (e.g. `"free-tier"`); never normalised.
     */
    tier?: {
        id: string;
        paidId?: string;
        capturedAt: number;
    };
}
export interface SidebarRoutingEntry {
    accountId: string;
    modelFamily: 'claude' | 'gemini';
    headerStyle: 'antigravity' | 'gemini-cli';
    strategy?: 'sticky' | 'round-robin' | 'hybrid';
    updatedAt: number;
}
export interface SidebarStateV1 {
    version: typeof SIDEBAR_STATE_VERSION;
    checkedAt: number;
    accounts: SidebarAccountState[];
    activeRouting: Record<string, SidebarRoutingEntry>;
    routingAuthoritative: boolean;
    quotaBackoffUntil?: number;
    lastError?: string;
}
/**
 * The subset of `SidebarStateV1` that a non-routing writer may set. The
 * fetch interceptor writes `activeRouting` directly via its own entry point
 * because routing is session-scoped, not machine-scoped.
 */
export interface SidebarMachineState {
    checkedAt: number;
    accounts: SidebarAccountState[];
    quotaBackoffUntil?: number;
    lastError?: string;
    /**
     * Optional: opt in to mark the snapshot as authoritative. When `true`,
     * the merge keeps the existing `routingAuthoritative: true` even if a
     * later non-authoritative machine write lands. Sticky-true semantics.
     */
    routingAuthoritative?: boolean;
}
export declare const DEFAULT_SIDEBAR_STATE: SidebarStateV1;
export declare const SIDEBAR_STATE_ENV = "ANTIGRAVITY_AUTH_SIDEBAR_STATE_FILE";
/**
 * Thrown by every writer when the cross-process lock cannot be acquired
 * within `SIDEBAR_LOCK_TIMEOUT_MS`. The caller decides whether to surface
 * a toast, drop the write, or retry the next tick.
 */
export declare class SidebarStateLockContentionError extends Error {
    readonly details: {
        stateFile: string;
        timeoutMs: number;
    };
    constructor(stateFile: string, timeoutMs: number);
}
/**
 * Steps exposed to the merge hooks. Race tests pause writers here; production
 * callers leave the hooks unset (a no-op fast path).
 *
 * - `await-lock` — before invoking `acquireFencedFileLock`.
 * - `acquired-lock` — after the lock is granted and before the read.
 * - `read-state` — after the on-disk state is normalized.
 * - `merged-state` — after the merge but before `writeJsonAtomic`.
 * - `wrote-state` — after the rename but before `lock.release()`.
 */
export type SidebarMergeStep = 'await-lock' | 'acquired-lock' | 'read-state' | 'merged-state' | 'wrote-state';
export interface SidebarMergeHooks {
    onStep?: (step: SidebarMergeStep) => Promise<void> | void;
}
/**
 * Install (or clear with `null`) the deterministic race hooks. Tests use
 * these to inject interleavings; production callers leave them unset. The
 * module-level state means a test must reset hooks in its own `afterEach`
 * to avoid bleeding into the next test.
 */
export declare function setSidebarMergeHooks(hooks: SidebarMergeHooks | null): void;
/**
 * Resolve the on-disk path the plugin writes to and the TUI reads from.
 *
 * - `ANTIGRAVITY_AUTH_SIDEBAR_STATE_FILE` wins when set (tests, packaged
 *   installers, and any user override).
 * - Otherwise fall back to the XDG state directory, mirroring the path
 *   conventions used elsewhere in the project.
 */
export declare function getSidebarStateFile(): string;
/**
 * Read and normalize the sidebar state file. Returns the default state when
 * the file is missing, unreadable, malformed, or schema-incompatible — the TUI
 * must never throw out of `readSidebarState()`, the panel just shows
 * "Awaiting Antigravity state" and the next poll retries.
 *
 * The read is sync on purpose: the TUI polls on a 2-second timer and the file
 * is tiny (a handful of accounts); an async read here would just add race
 * surface area against Solid's reactive render cycle.
 */
export declare function readSidebarState(path?: string): SidebarStateV1;
/**
 * Ensure the parent directory for the sidebar state file exists. Convenience
 * helper used by writers (tests, plugins) — the TUI itself does not write.
 */
export declare function ensureSidebarStateDir(path?: string): void;
/**
 * Drop active-routing entries older than 24h and cap the map at the freshest
 * 100. Pure helper exposed for unit testing; the writers call it on every
 * merge so the on-disk map never grows without bound.
 */
export declare function pruneActiveRouting(map: Record<string, SidebarRoutingEntry>, now: number): Record<string, SidebarRoutingEntry>;
/**
 * Structural input for `redactAccountForSidebar`. Decoupled from the core
 * `ManagedAccount` type so this module never forces a type-level import
 * shape on callers (and so the TUI's compiled tree does not see the core
 * ManagedAccount shape beyond what's actually used).
 *
 * Deliberately excludes `email`: the sidebar/redaction boundary is a PII
 * firewall. Adding `email` here would re-introduce the leak this boundary
 * exists to prevent. Legacy profile labels are accepted but never serialized.
 */
export interface SidebarAccountRedactionInput {
    /** Position in the harness-visible account array. */
    index: number;
    /** Legacy profile label; deliberately ignored by the redactor. */
    label?: string;
    enabled?: boolean;
    current?: boolean;
    coolingDownUntil?: number;
    /** Health score in `[0, 100]`. Defaults to 100 when missing. */
    healthScore?: number;
    /** Timestamp when the successful quota response was cached, never the sidebar write timestamp. */
    cachedQuotaUpdatedAt?: number;
    cachedQuota?: {
        gemini?: {
            remainingFraction?: number;
            resetTime?: string;
            windows?: Array<{
                window: 'weekly' | '5h';
                remainingFraction: number;
                resetTime: string;
            }>;
        };
        'non-gemini'?: {
            remainingFraction?: number;
            resetTime?: string;
            windows?: Array<{
                window: 'weekly' | '5h';
                remainingFraction: number;
                resetTime: string;
            }>;
        };
        [legacyKey: string]: {
            remainingFraction?: number;
            resetTime?: string;
            modelCount?: number;
            windows?: Array<{
                window: 'weekly' | '5h';
                remainingFraction: number;
                resetTime: string;
            }>;
        } | undefined;
    };
    /**
     * Opaque identity stamp that was attached to the persisted quota snapshot.
     * Used together with `currentQuotaAccountId` to detect a stale cache that
     * landed on the wrong account after an index shift or token replacement.
     * PII-safe — it is a 16-char hash, not the refresh token itself.
     */
    cachedQuotaAccountId?: string;
    /**
     * Opaque identity stamp for the account that is currently at this index.
     * The redactor drops `cachedQuota` when `cachedQuotaAccountId` is set
     * AND does not match this value, mirroring `toCommandAccountRow` in the
     * command-data service. Omitted in the persisted sidebar state.
     */
    currentQuotaAccountId?: string;
    /**
     * Captured plan tier from `loadCodeAssist`. Absent when unknown. The `id`
     * is the raw upstream string; `capturedAt` is epoch ms. Not PII — tier
     * metadata survives the redaction boundary unchanged.
     */
    tier?: {
        id: string;
        paidId?: string;
        capturedAt: number;
    };
}
/**
 * Build a `{ id, capturedAt }` tier object from account fields, or `undefined`
 * when either field is absent. Centralised so every producer (index.ts,
 * background-quota-refresh.ts, command-data.ts) uses the same guard and the
 * same shape.
 */
export declare function toCapturedTier(account: {
    capturedTierId?: string;
    capturedPaidTierId?: string;
    capturedTierAt?: number;
}): {
    id: string;
    paidId?: string;
    capturedAt: number;
} | undefined;
/**
 * Map pre-pool legacy quota keys to the current two-pool schema at read time.
 *
 * Legacy mappings (empirically settled from burn tests):
 *   `gemini-pro` + `gemini-flash`  →  `gemini`
 *   `claude`      + `gpt-oss`       →  `non-gemini`
 *
 * Where multiple legacy keys collapse into one pool the MIN remainingFraction
 * and earliest resetTime are used (most-constrained-first, matching the
 * window-level rule). No `windows` arrays are invented for migrated entries;
 * the single aggregate bar is the correct render for pre-window snapshots.
 *
 * Non-legacy keys that are already canonical (`gemini`, `non-gemini`) are
 * carried through unchanged. The next real quota refresh overwrites any
 * migrated snapshot with authoritative data.
 */
export declare function normalizeLegacyCachedQuota(raw: SidebarAccountRedactionInput['cachedQuota']): SidebarAccountRedactionInput['cachedQuota'];
/**
 * Project a raw cachedQuota pool entry into the sidebar-safe shape.
 *
 * Centralized seam — every producer (quota.ts pushSidebarQuotaSnapshot,
 * auth-loader.ts materializer, command-data.ts writeSidebar) routes
 * through here so the `windows` array is never dropped by an inline
 * `{ remainingFraction, resetTime }` literal.
 *
 * Tolerant: returns `undefined` when the source is missing or the
 * `remainingFraction` is not a finite number. Legacy entries without
 * `windows` produce `{ remainingPercent, resetAt }` only — the TUI's
 * legacy path then renders a single bar.
 */
export declare function projectQuotaPoolForSidebar(source: {
    remainingFraction?: number;
    resetTime?: string;
    windows?: ReadonlyArray<{
        window: 'weekly' | '5h';
        remainingFraction: number;
        resetTime: string;
    }>;
}, checkedAt?: number): SidebarQuotaEntry | undefined;
/**
 * Returns `true` when an account at `index` is the active account for
 * at least one model family. Two accounts CAN both be current — one
 * serving claude, one serving gemini — so this must not collapse to one.
 */
export declare function isAccountCurrent(index: number, activeIndexByFamily: {
    claude: number;
    gemini: number;
}): boolean;
/**
 * Convert a live account snapshot into the redacted shape the TUI renders.
 * The redacted `SidebarAccountState` carries no email, refresh token, access
 * token, project ID, fingerprint, OAuth profile name, or other personal or
 * credential-shaped fields. Display labels are generated ordinal account names.
 */
export declare function redactAccountForSidebar(source: SidebarAccountRedactionInput): SidebarAccountState;
/**
 * Build a `SidebarMachineState` from a list of live account snapshots.
 * Convenience for the auth-loader / quota writer call sites that already
 * hold an array of accounts and want to push a single snapshot.
 */
export declare function buildSidebarMachineStateFromAccounts(accounts: SidebarAccountRedactionInput[], options?: {
    checkedAt?: number;
    quotaBackoffUntil?: number;
    lastError?: string;
    routingAuthoritative?: boolean;
}): SidebarMachineState;
interface SidebarStateWriteOptions {
    stateFile?: string;
    /** Drop routing entries for accounts outside this projection in the same locked write. */
    retainRoutingForAccountIds?: readonly string[];
}
/**
 * Wait for any in-flight sidebar state write to drain. The plugin lifecycle
 * calls this during `dispose()` so the file logger and RPC server are torn
 * down only after every queued write has either landed or thrown.
 */
export declare function drainSidebarWrites(): Promise<void>;
/**
 * Upsert a single session's active routing entry. The fetch interceptor calls
 * this with `authoritative: true` after every final route selection; the
 * `accountId`/`modelFamily`/`headerStyle` fields are already redacted by the
 * caller (the writer never sees token or project fields).
 */
export declare function upsertSidebarActiveRouting(sessionId: string, entry: SidebarRoutingEntry, options?: SidebarStateWriteOptions & {
    authoritative?: boolean;
    onlyForProjectedAccounts?: boolean;
}): Promise<void>;
/**
 * Remove one session's active routing entry. The event handler calls this
 * when a session is deleted so the sidebar does not retain dead routes.
 */
export declare function removeSidebarActiveRouting(sessionId: string, options?: SidebarStateWriteOptions): Promise<void>;
/**
 * Write a new machine-state snapshot. The fetch interceptor and quota
 * manager call this after each refresh; auth-loader calls it after the
 * account pool is materialized.
 */
export declare function setSidebarMachineState(next: SidebarMachineState, options?: SidebarStateWriteOptions): Promise<void>;
export {};
//# sourceMappingURL=sidebar-state.d.ts.map