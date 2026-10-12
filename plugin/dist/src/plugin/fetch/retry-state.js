/**
 * Per-interceptor state that was previously module-global.
 *
 * The legacy plugin kept rate-limit cooldowns, account-failure counters, toast
 * dedup flags, and empty-response attempt counters at module scope. That kept
 * state alive across `dispose()`, which leaked warmup/rate-limit telemetry
 * across unrelated plugin lifetimes. This class owns the same bookkeeping but
 * scopes it to a single fetch interceptor instance.
 *
 * Every internal map is bounded by `MAX_MAP_ENTRIES`; once full, the oldest
 * insertion is evicted before the new entry is recorded. This matches the
 * warmup-state eviction policy and keeps long-lived interceptors from
 * accumulating telemetry past the cap.
 *
 * `dispose()` is terminal: every mutating method becomes a no-op (or returns
 * a documented identity value) once `disposed` flips to `true`. The plugin
 * tear-down order may race with an in-flight fetch, so guards must return
 * safe defaults rather than throw.
 */
const MAX_CONSECUTIVE_FAILURES = 5;
const FAILURE_COOLDOWN_MS = 30_000;
const FAILURE_STATE_RESET_MS = 120_000;
const RATE_LIMIT_DEDUP_WINDOW_MS = 2_000;
const RATE_LIMIT_STATE_RESET_MS = 120_000;
const RATE_LIMIT_TOAST_COOLDOWN_MS = 5_000;
const MAX_MAP_ENTRIES = 100;
/** Identity values returned by mutating methods once `disposed` flips. */
const DISPOSED_BACKOFF = {
    attempt: 1,
    delayMs: 1000,
    isDuplicate: false,
};
const DISPOSED_FAILURE = {
    failures: 0,
    shouldCooldown: false,
    cooldownMs: 0,
};
/**
 * Evicts the oldest entry from `map` if it is at the cap. Maps preserve
 * insertion order, so the first key from the iterator is the oldest. Returns
 * the number of evicted entries (0 or 1).
 */
function evictOldestIfFull(map, key) {
    if (map.has(key) || map.size < MAX_MAP_ENTRIES)
        return 0;
    const oldest = map.keys().next().value;
    if (oldest === undefined)
        return 0;
    map.delete(oldest);
    return 1;
}
export function createRetryState() {
    const rateLimitStateByAccountQuota = new Map();
    const accountFailureState = new Map();
    const rateLimitToastCooldowns = new Map();
    const emptyResponseAttempts = new Map();
    let softQuotaToastShownFlag = false;
    let rateLimitToastShownFlag = false;
    let disposed = false;
    function isDisposed() {
        return disposed;
    }
    function cleanupToastCooldowns() {
        if (rateLimitToastCooldowns.size <= MAX_MAP_ENTRIES)
            return;
        const now = Date.now();
        for (const [key, time] of rateLimitToastCooldowns) {
            if (now - time > RATE_LIMIT_TOAST_COOLDOWN_MS * 2) {
                rateLimitToastCooldowns.delete(key);
            }
        }
    }
    function getRateLimitBackoff(accountIndex, quotaKey, serverRetryAfterMs, maxBackoffMs = 60_000) {
        if (isDisposed())
            return DISPOSED_BACKOFF;
        const now = Date.now();
        const stateKey = `${accountIndex}:${quotaKey}`;
        const previous = rateLimitStateByAccountQuota.get(stateKey);
        if (previous && now - previous.lastAt < RATE_LIMIT_DEDUP_WINDOW_MS) {
            const baseDelay = serverRetryAfterMs ?? 1000;
            const backoffDelay = Math.min(baseDelay * 2 ** (previous.consecutive429 - 1), maxBackoffMs);
            return {
                attempt: previous.consecutive429,
                delayMs: Math.max(baseDelay, backoffDelay),
                isDuplicate: true,
            };
        }
        const attempt = previous && now - previous.lastAt < RATE_LIMIT_STATE_RESET_MS
            ? previous.consecutive429 + 1
            : 1;
        evictOldestIfFull(rateLimitStateByAccountQuota, stateKey);
        rateLimitStateByAccountQuota.set(stateKey, {
            consecutive429: attempt,
            lastAt: now,
            quotaKey,
        });
        const baseDelay = serverRetryAfterMs ?? 1000;
        const backoffDelay = Math.min(baseDelay * 2 ** (attempt - 1), maxBackoffMs);
        return {
            attempt,
            delayMs: Math.max(baseDelay, backoffDelay),
            isDuplicate: false,
        };
    }
    function resetRateLimitState(accountIndex, quotaKey) {
        if (isDisposed())
            return;
        const stateKey = `${accountIndex}:${quotaKey}`;
        rateLimitStateByAccountQuota.delete(stateKey);
    }
    function resetAllRateLimitStateForAccount(accountIndex) {
        if (isDisposed())
            return;
        for (const key of rateLimitStateByAccountQuota.keys()) {
            if (key.startsWith(`${accountIndex}:`)) {
                rateLimitStateByAccountQuota.delete(key);
            }
        }
    }
    function headerStyleToQuotaKey(headerStyle, family) {
        if (family === 'claude')
            return 'claude';
        return headerStyle === 'antigravity' ? 'gemini-antigravity' : 'gemini-cli';
    }
    function trackAccountFailure(accountIndex) {
        if (isDisposed())
            return DISPOSED_FAILURE;
        const now = Date.now();
        const previous = accountFailureState.get(accountIndex);
        const failures = previous && now - previous.lastFailureAt < FAILURE_STATE_RESET_MS
            ? previous.consecutiveFailures + 1
            : 1;
        evictOldestIfFull(accountFailureState, accountIndex);
        accountFailureState.set(accountIndex, {
            consecutiveFailures: failures,
            lastFailureAt: now,
        });
        const shouldCooldown = failures >= MAX_CONSECUTIVE_FAILURES;
        const cooldownMs = shouldCooldown ? FAILURE_COOLDOWN_MS : 0;
        return { failures, shouldCooldown, cooldownMs };
    }
    function resetAccountFailureState(accountIndex) {
        if (isDisposed())
            return;
        accountFailureState.delete(accountIndex);
    }
    function shouldShowRateLimitToast(message) {
        if (isDisposed())
            return false;
        cleanupToastCooldowns();
        const toastKey = message.replace(/\d+/g, 'X');
        const lastShown = rateLimitToastCooldowns.get(toastKey) ?? 0;
        const now = Date.now();
        if (now - lastShown < RATE_LIMIT_TOAST_COOLDOWN_MS) {
            return false;
        }
        evictOldestIfFull(rateLimitToastCooldowns, toastKey);
        rateLimitToastCooldowns.set(toastKey, now);
        return true;
    }
    function markSoftQuotaToastShown() {
        if (isDisposed())
            return;
        softQuotaToastShownFlag = true;
    }
    function markRateLimitToastShown() {
        if (isDisposed())
            return;
        rateLimitToastShownFlag = true;
    }
    function softQuotaToastShown() {
        return !isDisposed() && softQuotaToastShownFlag;
    }
    function rateLimitToastShown() {
        return !isDisposed() && rateLimitToastShownFlag;
    }
    function resetAllAccountsBlockedToasts() {
        if (isDisposed())
            return;
        softQuotaToastShownFlag = false;
        rateLimitToastShownFlag = false;
    }
    function recordEmptyResponseAttempt(key) {
        if (isDisposed())
            return 0;
        const next = (emptyResponseAttempts.get(key) ?? 0) + 1;
        evictOldestIfFull(emptyResponseAttempts, key);
        emptyResponseAttempts.set(key, next);
        return next;
    }
    function clearEmptyResponseAttempts() {
        if (isDisposed())
            return;
        emptyResponseAttempts.clear();
    }
    function clear() {
        if (isDisposed())
            return;
        rateLimitStateByAccountQuota.clear();
        accountFailureState.clear();
        rateLimitToastCooldowns.clear();
        emptyResponseAttempts.clear();
        softQuotaToastShownFlag = false;
        rateLimitToastShownFlag = false;
    }
    function dispose() {
        if (disposed)
            return;
        rateLimitStateByAccountQuota.clear();
        accountFailureState.clear();
        rateLimitToastCooldowns.clear();
        emptyResponseAttempts.clear();
        softQuotaToastShownFlag = false;
        rateLimitToastShownFlag = false;
        disposed = true;
    }
    function sizes() {
        return {
            rateLimitState: rateLimitStateByAccountQuota.size,
            accountFailure: accountFailureState.size,
            rateLimitToast: rateLimitToastCooldowns.size,
            emptyResponse: emptyResponseAttempts.size,
        };
    }
    return {
        get disposed() {
            return disposed;
        },
        getRateLimitBackoff,
        resetRateLimitState,
        resetAllRateLimitStateForAccount,
        headerStyleToQuotaKey,
        trackAccountFailure,
        resetAccountFailureState,
        shouldShowRateLimitToast,
        markSoftQuotaToastShown,
        markRateLimitToastShown,
        softQuotaToastShown,
        rateLimitToastShown,
        resetAllAccountsBlockedToasts,
        recordEmptyResponseAttempt,
        clearEmptyResponseAttempts,
        clear,
        dispose,
        sizes,
    };
}
//# sourceMappingURL=retry-state.js.map