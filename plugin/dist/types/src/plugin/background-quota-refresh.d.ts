/**
 * Background quota poller.
 *
 * Runs a jittered, `unref()`'d timer that periodically refreshes quota for
 * all accounts and pushes ONE snapshot per tick to its snapshot store (the
 * sidebar state file for OpenCode 1, memory for an OpenCode 2 location).
 * Three-layer cross-process dedup:
 *
 *   1. Freshness gate — the only hard correctness bound for quota snapshots.
 *      Reads `checkedAt` from the snapshot store; skips quota work when
 *      it is fresher than
 *      `max(intervalMs − 60_000, floor(intervalMs / 2))`. The /2 floor
 *      ensures the gate still fires at the 1-minute minimum interval.
 *
 *   2. Advisory fenced lock — an optimization that lets a single process do
 *      the network work when several wake up simultaneously. Held → skip.
 *      A store without a lock path skips this layer.
 *
 *   3. Lock throws → FAIL CLOSED (skip this tick, add jitter to next). A
 *      fallback mutex is NOT used here. The correct reasoning is: the
 *      freshness gate (layer 1) already bounds how many refreshes can land;
 *      a secondary "claim marker" file is just a worse re-implementation of
 *      the fenced lock we just failed to acquire — it replicates the same
 *      ownership problem without the protocol guarantees, and any transient
 *      I/O error that made the lock throw will likely affect a claim file
 *      too.
 */
import type { AccountMetadataV3, QuotaGroup, QuotaGroupSummary } from '@cortexkit/antigravity-auth-core';
import { acquireFencedFileLock } from '@cortexkit/antigravity-auth-core/file-lock';
import { type SidebarMachineState } from '../sidebar-state.js';
import type { Logger } from './logger.js';
import type { QuotaManager } from './quota.js';
/**
 * The subset of AccountManager that the poller needs. Using a narrow
 * interface keeps the module decoupled from the large concrete class and
 * lets tests pass minimal stubs without satisfying 90+ methods.
 */
export interface PollerAccountView {
    getAccounts(): Array<{
        index: number;
        label?: string;
        enabled?: boolean;
        parts: {
            refreshToken: string;
        };
        cachedQuota?: Partial<Record<QuotaGroup, QuotaGroupSummary>>;
        cachedQuotaAccountId?: string;
        coolingDownUntil?: number;
        /** Captured plan tier ID (raw upstream string). */
        capturedTierId?: string;
        /** Captured paid-tier ID (raw upstream string). */
        capturedPaidTierId?: string;
        /** Epoch ms when capturedTierId was last recorded. */
        capturedTierAt?: number;
        /** Schema version of the most recent tier capture. */
        capturedTierSchemaVersion?: number;
    }>;
    /** Must return the full AccountMetadataV3 shape so the quota manager
     *  can use token-refresh and project-context fields inside each fetch. */
    getAccountsForQuotaCheck(): AccountMetadataV3[];
    updateQuotaCache(accountIndex: number, quotaGroups: Partial<Record<QuotaGroup, QuotaGroupSummary>>, expectedRefreshToken?: string): void;
    /**
     * Apply a subset of quota-result fields (e.g. captured tier) onto the
     * in-memory account record without touching the quota cache itself.
     */
    applyUpdatedAccount(accountIndex: number, patch: {
        capturedTierId?: string;
        capturedPaidTierId?: string;
        capturedTierAt?: number;
        capturedTierSchemaVersion?: number;
    }, expectedRefreshToken?: string): void;
    requestSaveToDisk(): void;
    /**
     * Returns the active account index per model family so the sidebar
     * snapshot can stamp the `current` flag on the right account.
     */
    getActiveIndexByFamily(): {
        claude: number;
        gemini: number;
    };
}
/**
 * Where the poller keeps its snapshots and how it coordinates with other
 * processes. The OpenCode 1 layout uses the sidebar state file for both;
 * an OpenCode 2 location keeps snapshots in memory.
 */
export interface PollerSnapshotStore {
    /** `checkedAt` of the newest snapshot, or 0 when there is none. */
    lastCheckedAt(): number;
    write(state: SidebarMachineState): Promise<void>;
    /**
     * File the cross-process poll lock is taken on, or `null` to poll without
     * one (each process then polls on its own schedule).
     */
    readonly pollLockPath: string | null;
}
/** The OpenCode 1 store: the sidebar state file and a lock beside it. */
export declare function createSidebarFileSnapshotStore(stateFile: string): PollerSnapshotStore;
export interface BackgroundQuotaRefreshOptions {
    publishSidebar?: () => Promise<void>;
    mayRun?: () => Promise<boolean>;
    intervalMs: number;
    /**
     * The sidebar state file (OpenCode 1). One of `sidebarStateFile` and
     * `snapshots` is required.
     */
    sidebarStateFile?: string;
    /**
     * Snapshot store and lock path. When given it takes precedence and
     * `sidebarStateFile` is ignored.
     */
    snapshots?: PollerSnapshotStore;
    /**
     * Supplier for the live account pool. Called inside each locked phase, so it
     * observes any concurrent add/remove that completed while waiting for the
     * lock.
     */
    getAccountManager: () => PollerAccountView | null;
    quotaManager: QuotaManager;
    /**
     * Optional tier-refresh callback. When provided, the poller calls this
     * once per tick for the account whose capturedTierAt is missing or older
     * than TIER_STALENESS_TTL_MS. The callback handles its own token-refresh
     * and must resolve to a tier object (or null on failure / nothing to
     * report) -- failure must never reject, since tier is best-effort.
     *
     * Wired in index.ts through the same agyTransport seam the quota manager
     * uses, so e2e tests can inject a mock alongside the mock quota fetch.
     */
    loadAccountTier?: (account: AccountMetadataV3) => Promise<{
        id: string;
        paidId?: string;
        capturedAt: number;
    } | null>;
    /**
     * Clock / randomness seam. Defaults to the system clock.
     */
    now?: () => number;
    random?: () => number;
    /** Lock acquisition seam used by deterministic concurrency tests. */
    acquireLock?: typeof acquireFencedFileLock;
    /**
     * Health score per account index for the poller's sidebar snapshot.
     * Omitted: the process-wide health tracker, which the OpenCode 1 plugin
     * (one location per process) keeps using. `null`: no score, for a location
     * that has no health tracker of its own.
     */
    healthScore?: ((index: number) => number) | null;
    /**
     * Receives best-effort snapshot write failures. Omitted: the quota
     * module's process-wide logger, as the OpenCode 1 plugin uses it.
     */
    logger?: Pick<Logger, 'debug'>;
}
/**
 * Per-loader-instance background quota poller.
 *
 * Must be created after the plugin has initialised (so `getAccountManager()`
 * is populated) and disposed via the producer lifecycle phase.
 */
export declare class BackgroundQuotaRefresh {
    private readonly intervalMs;
    private readonly snapshots;
    private readonly getAccountManager;
    private readonly quotaManager;
    private readonly loadAccountTier?;
    private readonly now;
    private readonly random;
    private readonly acquireLock;
    private readonly healthScore?;
    private readonly logger?;
    private timer;
    /** Resolves when the currently-running tick completes (or immediately if none). */
    private inFlight;
    private disposed;
    private readonly mayRun?;
    private readonly publishSidebar?;
    constructor(options: BackgroundQuotaRefreshOptions);
    /** Start the background timer. Idempotent: a second call is a no-op. */
    start(): void;
    /** Stop the timer and await any in-flight tick. */
    dispose(): Promise<void>;
    private jitteredStartDelay;
    private jitteredInterval;
    private scheduleNext;
    private runTick;
    private refresh;
    private refreshQuota;
    private refreshTierSlot;
    private pushSnapshot;
}
//# sourceMappingURL=background-quota-refresh.d.ts.map