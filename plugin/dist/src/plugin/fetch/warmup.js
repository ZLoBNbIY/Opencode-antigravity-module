/**
 * Per-interceptor warmup attempt + success bookkeeping.
 *
 * The plugin used to keep two module-level sets: one for sessions that already
 * attempted a thinking warmup and another for sessions that succeeded. They
 * leaked across plugin lifetimes and across concurrent interceptors. This
 * factory scopes the same sets to a single interceptor; `dispose()` evicts
 * everything so the next interceptor starts clean.
 */
const MAX_WARMUP_SESSIONS = 1000;
const MAX_WARMUP_RETRIES = 2;
export function createWarmupState() {
    const warmupAttemptedSessionIds = new Set();
    const warmupSucceededSessionIds = new Set();
    let disposed = false;
    function trackAttempt(sessionId) {
        if (disposed)
            return false;
        if (warmupSucceededSessionIds.has(sessionId)) {
            return false;
        }
        if (warmupAttemptedSessionIds.size >= MAX_WARMUP_SESSIONS) {
            const first = warmupAttemptedSessionIds.values().next().value;
            if (first) {
                warmupAttemptedSessionIds.delete(first);
                warmupSucceededSessionIds.delete(first);
            }
        }
        const attempts = getAttemptCount(sessionId);
        if (attempts >= MAX_WARMUP_RETRIES) {
            return false;
        }
        warmupAttemptedSessionIds.add(sessionId);
        return true;
    }
    function getAttemptCount(sessionId) {
        return warmupAttemptedSessionIds.has(sessionId) ? 1 : 0;
    }
    function markSuccess(sessionId) {
        if (disposed)
            return;
        warmupSucceededSessionIds.add(sessionId);
        if (warmupSucceededSessionIds.size >= MAX_WARMUP_SESSIONS) {
            const first = warmupSucceededSessionIds.values().next().value;
            if (first)
                warmupSucceededSessionIds.delete(first);
        }
    }
    function clearWarmupAttempt(sessionId) {
        if (disposed)
            return;
        warmupAttemptedSessionIds.delete(sessionId);
    }
    function clear() {
        warmupAttemptedSessionIds.clear();
        warmupSucceededSessionIds.clear();
    }
    function dispose() {
        if (disposed)
            return;
        clear();
        disposed = true;
    }
    return {
        get disposed() {
            return disposed;
        },
        trackAttempt,
        getAttemptCount,
        markSuccess,
        clearWarmupAttempt,
        clear,
        dispose,
    };
}
//# sourceMappingURL=warmup.js.map