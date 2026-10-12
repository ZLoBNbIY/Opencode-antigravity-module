import type { HeaderStyle, AccountModelFamily as ModelFamily } from '@cortexkit/antigravity-auth-core';
export interface AccountFailureResult {
    failures: number;
    shouldCooldown: boolean;
    cooldownMs: number;
}
export interface RateLimitBackoffResult {
    attempt: number;
    delayMs: number;
    isDuplicate: boolean;
}
/**
 * Diagnostic snapshot of the four internal maps. Exposed for tests and for
 * future diagnostics endpoints; callers must not mutate the returned view.
 */
export interface RetryStateSizes {
    rateLimitState: number;
    accountFailure: number;
    rateLimitToast: number;
    emptyResponse: number;
}
export interface RetryState {
    /** Marks the instance as torn down; subsequent mutations are no-ops. */
    readonly disposed: boolean;
    /** Returns the rate-limit backoff for the given account + quota key. */
    getRateLimitBackoff(accountIndex: number, quotaKey: string, serverRetryAfterMs: number | null, maxBackoffMs?: number): RateLimitBackoffResult;
    /** Resets a single account/quota pair. */
    resetRateLimitState(accountIndex: number, quotaKey: string): void;
    /** Resets every quota key for the given account. */
    resetAllRateLimitStateForAccount(accountIndex: number): void;
    /** Maps header style + family to a deduplication bucket. */
    headerStyleToQuotaKey(headerStyle: HeaderStyle, family: ModelFamily): string;
    /** Records a non-429 failure and returns cooldown state. */
    trackAccountFailure(accountIndex: number): AccountFailureResult;
    /** Clears the failure counter for one account. */
    resetAccountFailureState(accountIndex: number): void;
    /** Returns true when the rate-limit warning toast may be shown. */
    shouldShowRateLimitToast(message: string): boolean;
    /** Marks the "all accounts blocked — soft quota" toast as shown. */
    markSoftQuotaToastShown(): void;
    /** Marks the "all accounts blocked — rate limit" toast as shown. */
    markRateLimitToastShown(): void;
    /** Reads the soft-quota toast guard flag. */
    softQuotaToastShown(): boolean;
    /** Reads the rate-limit toast guard flag. */
    rateLimitToastShown(): boolean;
    /** Clears both blocked-toast guards. */
    resetAllAccountsBlockedToasts(): void;
    /** Increments the per-session empty-response attempt counter. */
    recordEmptyResponseAttempt(key: string): number;
    /** Drops all empty-response attempt counters. */
    clearEmptyResponseAttempts(): void;
    /** Resets every map/flag. */
    clear(): void;
    /** Drops all state and prevents further mutations. */
    dispose(): void;
    /** Diagnostic snapshot of every internal map's current size. */
    sizes(): RetryStateSizes;
}
export declare function createRetryState(): RetryState;
//# sourceMappingURL=retry-state.d.ts.map