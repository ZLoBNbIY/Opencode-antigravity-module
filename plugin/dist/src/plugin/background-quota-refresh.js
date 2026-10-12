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
import { createHash } from 'node:crypto';
import { acquireFencedFileLock, } from '@cortexkit/antigravity-auth-core/file-lock';
import { readSidebarState, setSidebarMachineState, toCapturedTier, } from '../sidebar-state';
import { pushSidebarQuotaSnapshot } from './quota';
/**
 * Opaque identity derived from a refresh token. Three callers keep
 * independent copies: this module, `command-data.ts` (ships into the TUI
 * compiled tree and cannot reach the core barrel), and `index.ts`. All
 * three must produce the same 16-char hex prefix.
 */
function quotaAccountIdentity(refreshToken) {
    return createHash('sha256').update(refreshToken).digest('hex').slice(0, 16);
}
/** Minimum poll interval (1 minute, matching the config schema min). */
const MIN_INTERVAL_MS = 60_000;
/** Spread startup jitter so N processes don't all fire at once on launch. */
const STARTUP_JITTER_MS = 30_000;
/** Additional jitter added to the next tick when the lock mechanism throws. */
const ERROR_JITTER_MS = 15_000;
/** TTL for the renewable advisory poll lock. */
const POLL_LOCK_TTL_MS = 60_000;
/**
 * No-op lock handle used in place of the fenced poll lock when the snapshot
 * store has no lock path; releasing it does nothing.
 */
const NO_POLL_LOCK = {
    release: async () => { },
};
/** Maximum age of a captured tier before the poller refreshes it. 24 h. */
const TIER_STALENESS_TTL_MS = 24 * 60 * 60 * 1_000;
/** A capture at this version distinguishes an absent paid tier from old data. */
const CAPTURED_TIER_SCHEMA_VERSION = 1;
/** The OpenCode 1 store: the sidebar state file and a lock beside it. */
export function createSidebarFileSnapshotStore(stateFile) {
    return {
        lastCheckedAt: () => readSidebarState(stateFile).checkedAt,
        write: (state) => setSidebarMachineState(state, { stateFile }),
        pollLockPath: stateFile,
    };
}
/**
 * Per-loader-instance background quota poller.
 *
 * Must be created after the plugin has initialised (so `getAccountManager()`
 * is populated) and disposed via the producer lifecycle phase.
 */
export class BackgroundQuotaRefresh {
    intervalMs;
    snapshots;
    getAccountManager;
    quotaManager;
    loadAccountTier;
    now;
    random;
    acquireLock;
    healthScore;
    logger;
    timer = null;
    /** Resolves when the currently-running tick completes (or immediately if none). */
    inFlight = null;
    disposed = false;
    mayRun;
    publishSidebar;
    constructor(options) {
        this.intervalMs = options.intervalMs;
        this.mayRun = options.mayRun;
        this.publishSidebar = options.publishSidebar;
        if (options.snapshots) {
            this.snapshots = options.snapshots;
        }
        else if (typeof options.sidebarStateFile === 'string') {
            this.snapshots = createSidebarFileSnapshotStore(options.sidebarStateFile);
        }
        else {
            throw new TypeError('BackgroundQuotaRefresh needs a sidebarStateFile or a snapshot store');
        }
        this.getAccountManager = options.getAccountManager;
        this.quotaManager = options.quotaManager;
        this.loadAccountTier = options.loadAccountTier;
        this.now = options.now ?? (() => Date.now());
        this.random = options.random ?? Math.random;
        this.acquireLock = options.acquireLock ?? acquireFencedFileLock;
        this.healthScore = options.healthScore;
        this.logger = options.logger;
    }
    /** Start the background timer. Idempotent: a second call is a no-op. */
    start() {
        if (this.disposed || this.timer !== null)
            return;
        this.scheduleNext(this.jitteredStartDelay());
    }
    /** Stop the timer and await any in-flight tick. */
    async dispose() {
        if (this.disposed)
            return;
        this.disposed = true;
        if (this.timer !== null) {
            clearTimeout(this.timer);
            this.timer = null;
        }
        await this.inFlight;
    }
    // ── internals ─────────────────────────────────────────────────────────────
    jitteredStartDelay() {
        return Math.floor(this.random() * STARTUP_JITTER_MS);
    }
    jitteredInterval(extraJitterMs = 0) {
        // ±10% on top of the base interval prevents phase-locking across restarts.
        const jitter = Math.floor(this.random() * this.intervalMs * 0.1);
        return this.intervalMs + jitter + extraJitterMs;
    }
    scheduleNext(delayMs) {
        if (this.disposed)
            return;
        this.timer = setTimeout(() => {
            this.timer = null;
            // Re-entry guard: if the previous tick is still in flight (refresh
            // duration > interval), skip this timer callback. The in-flight tick
            // calls scheduleNext itself when it completes, so the poller continues.
            // Without this guard, assigning this.inFlight here would overwrite the
            // first tick's promise and dispose() would await the wrong one.
            if (this.inFlight !== null)
                return;
            this.inFlight = this.runTick()
                .catch(() => {
                // Errors inside runTick are already caught per-phase. An unexpected
                // throw here (before any internal reschedule) means no next tick
                // was queued — reschedule with error jitter so the poller degrades
                // to a delayed tick rather than dying permanently.
                this.scheduleNext(this.jitteredInterval(ERROR_JITTER_MS));
            })
                .finally(() => {
                this.inFlight = null;
            });
        }, delayMs);
        // Unreffing lets the process exit while the timer is pending — the poller
        // must never be the reason an idle session stays alive.
        if (this.timer.unref)
            this.timer.unref();
    }
    async runTick() {
        if (this.mayRun && !(await this.mayRun())) {
            if (!this.disposed)
                this.scheduleNext(this.jitteredInterval());
            return;
        }
        if (this.disposed)
            return;
        // ── 1. Quota freshness gate ──────────────────────────────────────────
        //
        // Bound: `max(intervalMs − 60_000, floor(intervalMs / 2))`.
        //
        // - intervalMs − 60_000: at 5-minute intervals this is 240 s — tight
        //   enough to prevent double refreshes while allowing drift.
        // - floor(intervalMs / 2): the fallback that keeps the gate non-trivial
        //   at the 1-minute minimum (floor(60000/2) = 30 000 ms, i.e. 30 s).
        const freshnessThresholdMs = Math.max(this.intervalMs - MIN_INTERVAL_MS, Math.floor(this.intervalMs / 2));
        const ageMs = this.now() - this.snapshots.lastCheckedAt();
        // ── 2. Advisory fenced lock ──────────────────────────────────────────
        // A store without a lock path polls on its own schedule; its tick takes
        // no lock and always proceeds to the freshness decision.
        const lockPath = this.snapshots.pollLockPath;
        let lock = null;
        try {
            lock =
                lockPath === null
                    ? NO_POLL_LOCK
                    : await this.acquireLock({
                        path: lockPath,
                        name: 'bg-quota-poll',
                        ttlMs: POLL_LOCK_TTL_MS,
                    });
        }
        catch {
            // Lock mechanism threw (I/O error, filesystem issue). FAIL CLOSED:
            // skip this tick. See module-level invariant comment for why we do not
            // invent a fallback mutex here.
            this.scheduleNext(this.jitteredInterval(ERROR_JITTER_MS));
            return;
        }
        if (lock === null) {
            // Another process holds the lock — its tier phase owns this tick's
            // metadata work as well as any quota snapshot write.
            this.scheduleNext(this.jitteredInterval());
            return;
        }
        try {
            if (this.disposed || (this.mayRun && !(await this.mayRun())))
                return;
            if (ageMs >= freshnessThresholdMs)
                await this.refresh();
            else
                await this.refreshTierSlot();
        }
        finally {
            await lock.release().catch(() => {
                // Release is best-effort; the TTL expires it if we can't reach it.
            });
        }
        if (!this.disposed) {
            this.scheduleNext(this.jitteredInterval());
        }
    }
    async refresh() {
        const refreshedQuota = await this.refreshQuota();
        if (!this.disposed && (!this.mayRun || (await this.mayRun())))
            await this.refreshTierSlot();
        if (refreshedQuota)
            await this.pushSnapshot();
    }
    async refreshQuota() {
        if (this.disposed || (this.mayRun && !(await this.mayRun())))
            return false;
        const manager = this.getAccountManager();
        if (!manager)
            return false;
        const accounts = manager.getAccountsForQuotaCheck();
        if (accounts.length === 0)
            return false;
        // Refresh all accounts, then stamp the live manager once per result.
        // Using the shared quotaManager deduplicates in-flight refreshes with
        // any concurrent modal or fetch-interceptor refresh.
        let results;
        try {
            results = await this.quotaManager.refreshAccounts(accounts, {
                indexFor: (account) => accounts.indexOf(account),
                // Do not force: the quota manager's per-account dedup and backoff
                // apply — an account that already refreshed recently is skipped.
                force: false,
            });
        }
        catch {
            return false;
        }
        if (this.disposed)
            return false;
        // Re-resolve live indices after the await: a concurrent add/remove may
        // have shifted positions.
        const liveAccounts = manager.getAccounts();
        const liveIndexByToken = new Map();
        for (const entry of liveAccounts) {
            liveIndexByToken.set(entry.parts.refreshToken, entry.index);
        }
        let anyUpdated = false;
        for (let i = 0; i < results.length; i++) {
            const result = results[i];
            if (result?.status !== 'ok' || !result.quota?.groups)
                continue;
            const candidateTokens = [
                result.updatedAccount?.refreshToken,
                accounts[i]?.refreshToken,
            ].filter((token) => Boolean(token));
            const liveIndex = candidateTokens
                .map((token) => liveIndexByToken.get(token))
                .find((index) => index !== undefined);
            if (liveIndex === undefined)
                continue;
            const liveToken = liveAccounts[liveIndex]?.parts.refreshToken;
            if (!liveToken)
                continue;
            manager.updateQuotaCache(liveIndex, result.quota.groups, liveToken);
            // Persist tier captured during ensureProjectContext (same tick, no extra
            // network call) so the sidebar snapshot carries it after every poll.
            const uaTier = toCapturedTier(result.updatedAccount ?? {});
            if (uaTier !== undefined) {
                manager.applyUpdatedAccount(liveIndex, {
                    capturedTierId: uaTier.id,
                    ...(uaTier.paidId !== undefined
                        ? { capturedPaidTierId: uaTier.paidId }
                        : {}),
                    capturedTierAt: uaTier.capturedAt,
                    capturedTierSchemaVersion: CAPTURED_TIER_SCHEMA_VERSION,
                }, liveToken);
            }
            anyUpdated = true;
        }
        if (anyUpdated)
            manager.requestSaveToDisk();
        return true;
    }
    async refreshTierSlot() {
        if (this.disposed || !this.loadAccountTier)
            return;
        const manager = this.getAccountManager();
        if (!manager)
            return;
        const liveAccounts = manager.getAccounts();
        const accounts = manager.getAccountsForQuotaCheck();
        const accountByToken = new Map(accounts.map((account) => [account.refreshToken, account]));
        const now = this.now();
        let stalestEntry;
        for (const entry of liveAccounts) {
            const needsPaidTierBackfill = entry.capturedPaidTierId === undefined &&
                entry.capturedTierSchemaVersion !== CAPTURED_TIER_SCHEMA_VERSION;
            const isTierStale = entry.capturedTierAt === undefined ||
                now - entry.capturedTierAt >= TIER_STALENESS_TTL_MS ||
                needsPaidTierBackfill;
            if (isTierStale &&
                (stalestEntry === undefined ||
                    (entry.capturedTierAt ?? 0) < (stalestEntry.capturedTierAt ?? 0))) {
                stalestEntry = entry;
            }
        }
        if (stalestEntry === undefined)
            return;
        const refreshToken = stalestEntry.parts.refreshToken;
        const accountForTier = accountByToken.get(refreshToken);
        if (!accountForTier)
            return;
        try {
            const tier = await this.loadAccountTier(accountForTier);
            if (tier === null || this.disposed)
                return;
            const liveEntry = manager
                .getAccounts()
                .find((entry) => entry.parts.refreshToken === refreshToken);
            if (!liveEntry)
                return;
            manager.applyUpdatedAccount(liveEntry.index, {
                capturedTierId: tier.id,
                ...(tier.paidId !== undefined
                    ? { capturedPaidTierId: tier.paidId }
                    : {}),
                capturedTierAt: tier.capturedAt,
                capturedTierSchemaVersion: CAPTURED_TIER_SCHEMA_VERSION,
            }, refreshToken);
            manager.requestSaveToDisk();
        }
        catch {
            // Tier is best-effort; a failure must never break the tick.
        }
    }
    async pushSnapshot() {
        if (this.publishSidebar) {
            await this.publishSidebar();
            return;
        }
        // ONE snapshot write per poll. `pushSidebarQuotaSnapshot` reads the live
        // account view (with the just-updated cached values) and writes it to
        // the same store whose `checkedAt` the freshness check reads, so each
        // location's poller writes only its own store.
        const getAccounts = () => {
            const m = this.getAccountManager();
            return m ? m.getAccounts() : null;
        };
        await pushSidebarQuotaSnapshot(() => {
            const accts = getAccounts();
            if (!accts)
                return null;
            return accts.map((entry) => ({
                index: entry.index,
                label: entry.label,
                enabled: entry.enabled,
                coolingDownUntil: entry.coolingDownUntil,
                cachedQuota: entry.cachedQuota,
                cachedQuotaAccountId: entry.cachedQuotaAccountId,
                // An account reorder changes which cached reading occupies an index.
                // Use a refresh-token-derived account ID to detect that mismatch
                // before showing quota in the sidebar.
                currentQuotaAccountId: quotaAccountIdentity(entry.parts.refreshToken),
                tier: toCapturedTier(entry),
            }));
        }, 0, () => {
            const m = this.getAccountManager();
            return m ? m.getActiveIndexByFamily() : null;
        }, {
            write: (state) => this.snapshots.write(state),
            ...(this.healthScore === undefined
                ? {}
                : { healthScore: this.healthScore }),
            ...(this.logger ? { logger: this.logger } : {}),
        }).catch(() => {
            // Sidebar write failure is not fatal; the next tick will retry.
        });
    }
}
//# sourceMappingURL=background-quota-refresh.js.map