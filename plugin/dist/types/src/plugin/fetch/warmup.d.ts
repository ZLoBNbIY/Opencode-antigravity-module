/**
 * Per-interceptor warmup attempt + success bookkeeping.
 *
 * The plugin used to keep two module-level sets: one for sessions that already
 * attempted a thinking warmup and another for sessions that succeeded. They
 * leaked across plugin lifetimes and across concurrent interceptors. This
 * factory scopes the same sets to a single interceptor; `dispose()` evicts
 * everything so the next interceptor starts clean.
 */
export interface WarmupState {
    readonly disposed: boolean;
    /**
     * Records an attempt for the given session id. Returns false when the
     * session already succeeded (no further attempts permitted) or when the
     * retry budget is exhausted.
     */
    trackAttempt(sessionId: string): boolean;
    /** Returns the number of tracked attempts for the session. */
    getAttemptCount(sessionId: string): number;
    /** Marks the session as warmed-up; subsequent attempts are rejected. */
    markSuccess(sessionId: string): void;
    /** Drops a single session's attempt counter (used on warmup failure). */
    clearWarmupAttempt(sessionId: string): void;
    /** Drops every session entry. */
    clear(): void;
    /** Marks the instance as torn down; subsequent mutations are no-ops. */
    dispose(): void;
}
export declare function createWarmupState(): WarmupState;
//# sourceMappingURL=warmup.d.ts.map