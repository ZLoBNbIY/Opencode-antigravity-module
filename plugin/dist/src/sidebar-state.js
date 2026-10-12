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
import { mkdirSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
// Subpath imports (not the barrel): this file ships into the TUI's
// compiled tree, and the barrel re-exports account/OAuth/quota modules
// that must never execute inside the host's render path.
import { writeJsonAtomic } from '@cortexkit/antigravity-auth-core/atomic-write';
import { acquireFencedFileLock, } from '@cortexkit/antigravity-auth-core/file-lock';
import { xdgState } from 'xdg-basedir';
export const SIDEBAR_STATE_VERSION = 1;
export const DEFAULT_SIDEBAR_STATE = {
    version: SIDEBAR_STATE_VERSION,
    checkedAt: 0,
    accounts: [],
    activeRouting: {},
    routingAuthoritative: false,
};
export const SIDEBAR_STATE_ENV = 'ANTIGRAVITY_AUTH_SIDEBAR_STATE_FILE';
const SIDEBAR_STATE_DIR = 'cortexkit/antigravity-auth';
const SIDEBAR_STATE_FILENAME = 'sidebar-state.json';
/** Active routing entries older than this are dropped on every merge. */
const ACTIVE_ROUTING_MAX_AGE_MS = 24 * 60 * 60 * 1000;
/** Active routing map is capped at this many newest entries. */
const ACTIVE_ROUTING_MAX_ENTRIES = 100;
const SIDEBAR_LOCK_NAME = 'sidebar';
const SIDEBAR_LOCK_TTL_MS = 10_000;
const SIDEBAR_LOCK_TIMEOUT_MS = 2_000;
const SIDEBAR_LOCK_RETRY_BASE_MS = 25;
const SIDEBAR_LOCK_RETRY_CAP_MS = 75;
const SIDEBAR_LOCK_JITTER_MS = 25;
const SIDEBAR_STATE_DIR_MODE = 0o700;
const SIDEBAR_STATE_FILE_MODE = 0o600;
/**
 * Thrown by every writer when the cross-process lock cannot be acquired
 * within `SIDEBAR_LOCK_TIMEOUT_MS`. The caller decides whether to surface
 * a toast, drop the write, or retry the next tick.
 */
export class SidebarStateLockContentionError extends Error {
    details;
    constructor(stateFile, timeoutMs) {
        super(`Could not acquire sidebar-state lock at ${stateFile} within ${timeoutMs}ms`);
        this.name = 'SidebarStateLockContentionError';
        this.details = { stateFile, timeoutMs };
    }
}
let sidebarMergeHooks = null;
/**
 * Install (or clear with `null`) the deterministic race hooks. Tests use
 * these to inject interleavings; production callers leave them unset. The
 * module-level state means a test must reset hooks in its own `afterEach`
 * to avoid bleeding into the next test.
 */
export function setSidebarMergeHooks(hooks) {
    sidebarMergeHooks = hooks;
}
async function emitMergeStep(step) {
    await sidebarMergeHooks?.onStep?.(step);
}
/**
 * Resolve the on-disk path the plugin writes to and the TUI reads from.
 *
 * - `ANTIGRAVITY_AUTH_SIDEBAR_STATE_FILE` wins when set (tests, packaged
 *   installers, and any user override).
 * - Otherwise fall back to the XDG state directory, mirroring the path
 *   conventions used elsewhere in the project.
 */
export function getSidebarStateFile() {
    const override = process.env[SIDEBAR_STATE_ENV];
    if (override && override.trim().length > 0)
        return override;
    const base = xdgState ?? join(homedir(), '.local', 'state');
    return join(base, SIDEBAR_STATE_DIR, SIDEBAR_STATE_FILENAME);
}
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
export function readSidebarState(path = getSidebarStateFile()) {
    let raw;
    try {
        raw = readFileSync(path, 'utf-8');
    }
    catch {
        return { ...DEFAULT_SIDEBAR_STATE };
    }
    let parsed;
    try {
        parsed = JSON.parse(raw);
    }
    catch {
        return { ...DEFAULT_SIDEBAR_STATE, lastError: 'malformed-json' };
    }
    return normalizeSidebarState(parsed);
}
function normalizeSidebarState(input) {
    if (!isObject(input)) {
        return { ...DEFAULT_SIDEBAR_STATE, lastError: 'shape' };
    }
    const record = input;
    const version = record.version;
    if (version !== SIDEBAR_STATE_VERSION) {
        return {
            ...DEFAULT_SIDEBAR_STATE,
            lastError: `unsupported-version:${stringifySafe(version)}`,
        };
    }
    const accountsRaw = record.accounts;
    const accounts = Array.isArray(accountsRaw)
        ? accountsRaw
            .map((entry) => normalizeAccount(entry))
            .filter((entry) => entry !== null)
        : [];
    const routingRaw = record.activeRouting;
    const activeRouting = {};
    if (isObject(routingRaw)) {
        for (const [sessionId, entry] of Object.entries(routingRaw)) {
            const normalized = normalizeRouting(entry);
            if (normalized)
                activeRouting[sessionId] = normalized;
        }
    }
    const checkedAt = toFiniteNumber(record.checkedAt);
    const routingAuthoritative = record.routingAuthoritative === true;
    const quotaBackoffUntil = toFiniteNumber(record.quotaBackoffUntil);
    const lastError = typeof record.lastError === 'string' ? record.lastError : undefined;
    return {
        version: SIDEBAR_STATE_VERSION,
        checkedAt: checkedAt ?? 0,
        accounts,
        activeRouting,
        routingAuthoritative,
        quotaBackoffUntil: quotaBackoffUntil ?? undefined,
        lastError,
    };
}
function normalizeAccount(input) {
    if (!isObject(input))
        return null;
    const record = input;
    const id = typeof record.id === 'string' ? record.id : null;
    const label = typeof record.label === 'string' ? record.label : null;
    if (!id || !label)
        return null;
    const enabled = record.enabled !== false;
    const health = clampNumber(toFiniteNumber(record.health), 0, 100);
    const current = record.current === true;
    const cooldownUntil = toFiniteNumber(record.cooldownUntil) ?? undefined;
    const quotaRaw = record.quota;
    const quota = {};
    if (isObject(quotaRaw)) {
        for (const key of ['gemini', 'non-gemini']) {
            const entry = quotaRaw[key];
            const normalized = normalizeQuota(entry);
            if (normalized)
                quota[key] = normalized;
        }
    }
    const tier = normalizeTier(record.tier);
    return {
        id,
        label,
        enabled,
        health,
        current,
        cooldownUntil,
        quota,
        ...(tier !== undefined ? { tier } : {}),
    };
}
function normalizeTier(input) {
    if (!isObject(input))
        return undefined;
    const record = input;
    const id = typeof record.id === 'string' && record.id.length > 0 ? record.id : null;
    const capturedAt = toFiniteNumber(record.capturedAt);
    if (!id || capturedAt === null)
        return undefined;
    const paidId = typeof record.paidId === 'string' && record.paidId.length > 0
        ? record.paidId
        : undefined;
    return { id, ...(paidId ? { paidId } : {}), capturedAt };
}
function normalizeQuota(input) {
    if (!isObject(input))
        return null;
    const record = input;
    const remaining = toFiniteNumber(record.remainingPercent);
    if (remaining === null)
        return null;
    const resetAt = toFiniteNumber(record.resetAt) ?? undefined;
    const checkedAt = toFiniteNumber(record.checkedAt) ?? undefined;
    // Tolerant: deserialize windows array if present; drop malformed entries.
    const windowsRaw = record.windows;
    let windows;
    if (Array.isArray(windowsRaw)) {
        const parsed = windowsRaw
            .filter(isObject)
            .map((w) => {
            const win = w.window;
            const rp = toFiniteNumber(w.remainingPercent);
            const ra = toFiniteNumber(w.resetAt);
            const ca = toFiniteNumber(w.checkedAt);
            if ((win !== 'weekly' && win !== '5h') || rp === null)
                return null;
            return {
                window: win,
                remainingPercent: clampNumber(rp, 0, 100),
                resetAt: ra ?? undefined,
                ...(ca !== null && ca >= 0 ? { checkedAt: ca } : {}),
            };
        })
            .filter((v) => v !== null);
        if (parsed.length > 0)
            windows = parsed;
    }
    return {
        remainingPercent: clampNumber(remaining, 0, 100),
        resetAt,
        ...(checkedAt !== undefined ? { checkedAt } : {}),
        windows,
    };
}
function normalizeRouting(input) {
    if (!isObject(input))
        return null;
    const record = input;
    const accountId = typeof record.accountId === 'string' ? record.accountId : null;
    const modelFamily = record.modelFamily;
    const headerStyle = record.headerStyle;
    const strategy = record.strategy;
    const updatedAt = toFiniteNumber(record.updatedAt) ?? 0;
    if (!accountId ||
        (modelFamily !== 'claude' && modelFamily !== 'gemini') ||
        (headerStyle !== 'antigravity' && headerStyle !== 'gemini-cli')) {
        return null;
    }
    return {
        accountId,
        modelFamily,
        headerStyle,
        strategy: strategy === 'sticky' ||
            strategy === 'round-robin' ||
            strategy === 'hybrid'
            ? strategy
            : undefined,
        updatedAt,
    };
}
function isObject(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function toFiniteNumber(value) {
    if (typeof value === 'number' && Number.isFinite(value))
        return value;
    if (typeof value === 'string') {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
}
function clampNumber(value, min, max) {
    if (value === null)
        return min;
    if (value < min)
        return min;
    if (value > max)
        return max;
    return value;
}
function stringifySafe(value) {
    if (typeof value === 'string')
        return value;
    try {
        return JSON.stringify(value) ?? 'unknown';
    }
    catch {
        return 'unknown';
    }
}
/**
 * Ensure the parent directory for the sidebar state file exists. Convenience
 * helper used by writers (tests, plugins) — the TUI itself does not write.
 */
export function ensureSidebarStateDir(path = getSidebarStateFile()) {
    mkdirSync(dirname(path), { recursive: true, mode: SIDEBAR_STATE_DIR_MODE });
}
/**
 * Drop active-routing entries older than 24h and cap the map at the freshest
 * 100. Pure helper exposed for unit testing; the writers call it on every
 * merge so the on-disk map never grows without bound.
 */
export function pruneActiveRouting(map, now) {
    const cutoff = now - ACTIVE_ROUTING_MAX_AGE_MS;
    const filtered = [];
    for (const [sessionId, entry] of Object.entries(map)) {
        if (entry.updatedAt >= cutoff) {
            filtered.push([sessionId, entry]);
        }
    }
    filtered.sort((a, b) => b[1].updatedAt - a[1].updatedAt);
    if (filtered.length <= ACTIVE_ROUTING_MAX_ENTRIES) {
        return Object.fromEntries(filtered);
    }
    return Object.fromEntries(filtered.slice(0, ACTIVE_ROUTING_MAX_ENTRIES));
}
/**
 * Build a `{ id, capturedAt }` tier object from account fields, or `undefined`
 * when either field is absent. Centralised so every producer (index.ts,
 * background-quota-refresh.ts, command-data.ts) uses the same guard and the
 * same shape.
 */
export function toCapturedTier(account) {
    return account.capturedTierId !== undefined &&
        account.capturedTierAt !== undefined
        ? {
            id: account.capturedTierId,
            ...(account.capturedPaidTierId !== undefined
                ? { paidId: account.capturedPaidTierId }
                : {}),
            capturedAt: account.capturedTierAt,
        }
        : undefined;
}
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
export function normalizeLegacyCachedQuota(raw) {
    if (!raw)
        return raw;
    // Pool already carries current keys — fast path when no legacy keys present.
    const hasLegacy = 'gemini-pro' in raw ||
        'gemini-flash' in raw ||
        'claude' in raw ||
        'gpt-oss' in raw;
    if (!hasLegacy)
        return raw;
    // Pick the earlier of two ISO reset timestamps, preferring a defined
    // value over undefined. Both branches of minFraction must preserve the
    // earlier reset, regardless of which fraction wins.
    const earlierResetTime = (a, b) => {
        if (!a)
            return b;
        if (!b)
            return a;
        return a < b ? a : b;
    };
    const minFraction = (a, b) => {
        if (!a)
            return b;
        if (!b)
            return a;
        const fa = a.remainingFraction ?? 1;
        const fb = b.remainingFraction ?? 1;
        const winner = fa <= fb ? a : b;
        const loser = fa <= fb ? b : a;
        // Always merge to the earliest resetTime regardless of which pool wins
        // the fraction comparison — an earlier window expiry from the loser
        // pool must not be silently dropped.
        return {
            ...winner,
            resetTime: earlierResetTime(winner.resetTime, loser.resetTime),
        };
    };
    const gemini = minFraction(raw.gemini, minFraction(raw['gemini-pro'], raw['gemini-flash'])) ?? raw.gemini;
    const nonGemini = minFraction(raw['non-gemini'], minFraction(raw.claude, raw['gpt-oss'])) ?? raw['non-gemini'];
    return {
        ...(gemini !== undefined ? { gemini } : {}),
        ...(nonGemini !== undefined ? { 'non-gemini': nonGemini } : {}),
    };
}
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
export function projectQuotaPoolForSidebar(source, checkedAt) {
    const readingAt = typeof checkedAt === 'number' &&
        Number.isFinite(checkedAt) &&
        checkedAt >= 0
        ? checkedAt
        : undefined;
    const fraction = source.remainingFraction;
    if (typeof fraction !== 'number' || !Number.isFinite(fraction))
        return undefined;
    const remainingPercent = clampNumber(Math.round(fraction * 100), 0, 100);
    let resetAt;
    if (typeof source.resetTime === 'string' && source.resetTime.length > 0) {
        const parsed = Date.parse(source.resetTime);
        if (Number.isFinite(parsed))
            resetAt = parsed;
    }
    const windows = source.windows?.length
        ? source.windows.map((w) => ({
            window: w.window,
            ...(readingAt !== undefined ? { checkedAt: readingAt } : {}),
            remainingPercent: clampNumber(Math.round(w.remainingFraction * 100), 0, 100),
            resetAt: typeof w.resetTime === 'string' && w.resetTime.length > 0
                ? (() => {
                    const parsed = Date.parse(w.resetTime);
                    return Number.isFinite(parsed) ? parsed : undefined;
                })()
                : undefined,
        }))
        : undefined;
    return {
        remainingPercent,
        resetAt,
        windows,
        ...(readingAt !== undefined ? { checkedAt: readingAt } : {}),
    };
}
/**
 * Returns `true` when an account at `index` is the active account for
 * at least one model family. Two accounts CAN both be current — one
 * serving claude, one serving gemini — so this must not collapse to one.
 */
export function isAccountCurrent(index, activeIndexByFamily) {
    return (index === activeIndexByFamily.claude || index === activeIndexByFamily.gemini);
}
/**
 * Convert a live account snapshot into the redacted shape the TUI renders.
 * The redacted `SidebarAccountState` carries no email, refresh token, access
 * token, project ID, fingerprint, OAuth profile name, or other personal or
 * credential-shaped fields. Display labels are generated ordinal account names.
 */
export function redactAccountForSidebar(source) {
    const id = `acct-${source.index}`;
    const label = `Account ${source.index + 1}`;
    const enabled = source.enabled !== false;
    const current = source.current === true;
    const cooldownUntil = typeof source.coolingDownUntil === 'number' &&
        Number.isFinite(source.coolingDownUntil)
        ? source.coolingDownUntil
        : undefined;
    const health = clampNumber(typeof source.healthScore === 'number' ? source.healthScore : 100, 0, 100);
    const quota = {};
    // Stamp mismatch: the persisted quota snapshot was captured for a
    // different account than the one currently at this index. Drop the
    // stale cache rather than rendering the wrong account's quota
    // percentages. Mirrors `toCommandAccountRow` in command-data.
    const staleCachedQuota = typeof source.cachedQuotaAccountId === 'string' &&
        typeof source.currentQuotaAccountId === 'string' &&
        source.cachedQuotaAccountId !== source.currentQuotaAccountId;
    // Normalize legacy per-pool keys to the current two-pool schema before
    // reading. This is non-destructive: the next real quota refresh will
    // overwrite the migrated snapshot with authoritative data.
    const cached = staleCachedQuota
        ? undefined
        : normalizeLegacyCachedQuota(source.cachedQuota);
    if (cached) {
        for (const key of ['gemini', 'non-gemini']) {
            const entry = cached[key];
            if (!entry)
                continue;
            const projected = projectQuotaPoolForSidebar(entry, source.cachedQuotaUpdatedAt);
            if (projected)
                quota[key] = projected;
        }
    }
    return {
        id,
        label,
        enabled,
        health,
        current,
        cooldownUntil,
        quota,
        // Tier is plan metadata, not PII — it passes the redaction boundary.
        ...(source.tier !== undefined ? { tier: source.tier } : {}),
    };
}
/**
 * Build a `SidebarMachineState` from a list of live account snapshots.
 * Convenience for the auth-loader / quota writer call sites that already
 * hold an array of accounts and want to push a single snapshot.
 */
export function buildSidebarMachineStateFromAccounts(accounts, options = {}) {
    return {
        checkedAt: options.checkedAt ?? Date.now(),
        accounts: accounts.map((entry) => redactAccountForSidebar(entry)),
        quotaBackoffUntil: options.quotaBackoffUntil,
        lastError: options.lastError,
        routingAuthoritative: options.routingAuthoritative,
    };
}
let sidebarWriteChain = Promise.resolve();
function enqueueSidebarWrite(work) {
    // Always run `work` regardless of whether the prior link resolved or
    // rejected — a failed write must not poison the chain for the next caller.
    const next = sidebarWriteChain.then(work, work);
    sidebarWriteChain = next.then(() => undefined, () => undefined);
    return next;
}
/**
 * Wait for any in-flight sidebar state write to drain. The plugin lifecycle
 * calls this during `dispose()` so the file logger and RPC server are torn
 * down only after every queued write has either landed or thrown.
 */
export function drainSidebarWrites() {
    return sidebarWriteChain;
}
async function sleep(ms) {
    await new Promise((resolve) => setTimeout(resolve, ms));
}
async function acquireSidebarLockWithRetry(stateFile) {
    const start = Date.now();
    let attempt = 0;
    while (true) {
        await emitMergeStep('await-lock');
        const lock = await acquireFencedFileLock({
            path: stateFile,
            name: SIDEBAR_LOCK_NAME,
            ttlMs: SIDEBAR_LOCK_TTL_MS,
            renew: true,
        });
        if (lock) {
            await emitMergeStep('acquired-lock');
            return lock;
        }
        const elapsed = Date.now() - start;
        if (elapsed >= SIDEBAR_LOCK_TIMEOUT_MS) {
            throw new SidebarStateLockContentionError(stateFile, SIDEBAR_LOCK_TIMEOUT_MS);
        }
        const backoff = Math.min(SIDEBAR_LOCK_RETRY_CAP_MS, SIDEBAR_LOCK_RETRY_BASE_MS + attempt * 10);
        const jitter = Math.floor(Math.random() * SIDEBAR_LOCK_JITTER_MS);
        await sleep(backoff + jitter);
        attempt++;
    }
}
async function performSidebarWrite(stateFile, merge) {
    await enqueueSidebarWrite(async () => {
        ensureSidebarStateDir(stateFile);
        const lock = await acquireSidebarLockWithRetry(stateFile);
        try {
            await lock.assertOwned();
            const existing = readSidebarState(stateFile);
            await emitMergeStep('read-state');
            const merged = merge(existing);
            await emitMergeStep('merged-state');
            // Re-check ownership once the temp file is staged, right before the
            // rename: the first check runs before several awaits (step hooks,
            // temp-file write), and the lease can expire or be taken over by
            // another writer in between. This shrinks the lost-lease window to the
            // gap between this check and the rename; it is not an atomic
            // compare-and-swap.
            await writeJsonAtomic(stateFile, merged, {
                beforeRename: () => lock.assertOwned(),
            });
            // `writeJsonAtomic` stages a tmp file with mode 0o600 and renames onto
            // the target; POSIX rename replaces the inode so the new file inherits
            // the staged mode bits. Windows ignores POSIX modes so the assertion
            // in tests is best-effort there.
            await emitMergeStep('wrote-state');
        }
        finally {
            await lock.release().catch(() => { });
        }
    });
}
/**
 * Merge a new machine-state payload against the on-disk state.
 *
 * Stale writes (new `checkedAt` < existing) are dropped — only newer/equal
 * `checkedAt` may replace machine fields. The merge preserves
 * `routingAuthoritative: true` once it is true (sticky-true), keeps the
 * existing `activeRouting` (unless the caller excludes account IDs),
 * and prunes expired routing entries as a side effect.
 */
function mergeMachineState(existing, next, retainedAccountIds) {
    if (next.checkedAt < existing.checkedAt) {
        return {
            ...existing,
            activeRouting: pruneActiveRouting(existing.activeRouting, Date.now()),
        };
    }
    const routes = pruneActiveRouting(existing.activeRouting, Date.now());
    const retained = retainedAccountIds === undefined ? undefined : new Set(retainedAccountIds);
    const activeRouting = retained === undefined
        ? routes
        : Object.fromEntries(Object.entries(routes).filter(([, entry]) => retained.has(entry.accountId)));
    return {
        version: SIDEBAR_STATE_VERSION,
        checkedAt: next.checkedAt,
        accounts: next.accounts,
        quotaBackoffUntil: next.quotaBackoffUntil,
        lastError: next.lastError,
        routingAuthoritative: existing.routingAuthoritative === true ||
            next.routingAuthoritative === true,
        // Symmetric with the stale-write branch: every machine-write merge
        // re-prunes activeRouting so a long-running TUI session eventually
        // drops dead routes even when no fresh routing upsert lands. Cheap
        // (a single Object.entries + sort over ≤100 entries) and bounded.
        // A changed account source can also exclude the old source's routing
        // in this same write, without publishing new rows beside old routes.
        activeRouting,
    };
}
/**
 * Upsert a single session's active routing entry. The fetch interceptor calls
 * this with `authoritative: true` after every final route selection; the
 * `accountId`/`modelFamily`/`headerStyle` fields are already redacted by the
 * caller (the writer never sees token or project fields).
 */
export async function upsertSidebarActiveRouting(sessionId, entry, options = {}) {
    const stateFile = options.stateFile ?? getSidebarStateFile();
    await performSidebarWrite(stateFile, (existing) => {
        if (options.onlyForProjectedAccounts &&
            !existing.accounts.some((account) => account.id === entry.accountId))
            return existing;
        const activeRouting = { ...existing.activeRouting, [sessionId]: entry };
        return {
            ...existing,
            routingAuthoritative: options.authoritative === true ? true : existing.routingAuthoritative,
            activeRouting: pruneActiveRouting(activeRouting, Date.now()),
        };
    });
}
/**
 * Remove one session's active routing entry. The event handler calls this
 * when a session is deleted so the sidebar does not retain dead routes.
 */
export async function removeSidebarActiveRouting(sessionId, options = {}) {
    const stateFile = options.stateFile ?? getSidebarStateFile();
    await performSidebarWrite(stateFile, (existing) => {
        if (!(sessionId in existing.activeRouting)) {
            return existing;
        }
        const activeRouting = { ...existing.activeRouting };
        delete activeRouting[sessionId];
        return {
            ...existing,
            activeRouting,
        };
    });
}
/**
 * Write a new machine-state snapshot. The fetch interceptor and quota
 * manager call this after each refresh; auth-loader calls it after the
 * account pool is materialized.
 */
export async function setSidebarMachineState(next, options = {}) {
    const stateFile = options.stateFile ?? getSidebarStateFile();
    await performSidebarWrite(stateFile, (existing) => mergeMachineState(existing, next, options.retainRoutingForAccountIds));
}
void SIDEBAR_STATE_FILE_MODE;
//# sourceMappingURL=sidebar-state.js.map