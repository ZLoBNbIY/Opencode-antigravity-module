import type { CooldownReason } from '../accounts';
import type { QuotaGroupSummary } from '../quota';
/**
 * Quota-aware status labels for models and accounts.
 *
 * Labels:
 *   [READY]       — quota available, no rate limits
 *   [WAIT Xm]     — rate-limited, resets in X minutes
 *   [EXHAUSTED]   — quota fully consumed (0%), reset time known
 *   [COOLDOWN]    — account cooling down (auth failure, network error, etc.)
 *   [LOW]         — quota below 20% but still available
 */
export type QuotaLabel = 'READY' | 'WAIT' | 'EXHAUSTED' | 'COOLDOWN' | 'LOW';
export interface QuotaStatusInfo {
    label: QuotaLabel;
    waitMs?: number;
    cooldownReason?: CooldownReason;
}
/**
 * Format a duration in milliseconds to a compact human-readable string.
 * Used for wait/cooldown labels.
 */
export declare function formatWaitDuration(ms: number): string;
/**
 * Classify a quota group's status based on remaining fraction and reset time.
 */
export declare function classifyGroupStatus(group: QuotaGroupSummary | undefined): QuotaStatusInfo;
/**
 * Build a cooldown status for an account that is cooling down.
 */
export declare function buildCooldownStatus(cooldownMs: number, reason?: CooldownReason): QuotaStatusInfo;
/**
 * Build a rate-limited (WAIT) status with optional wait time.
 */
export declare function buildWaitStatus(waitMs?: number): QuotaStatusInfo;
/**
 * Format a QuotaStatusInfo into a colored ANSI badge string.
 *
 * Examples:
 *   [READY]
 *   [WAIT 3m 20s]
 *   [EXHAUSTED resets in 2h 15m]
 *   [COOLDOWN auth-failure]
 *   [LOW]
 */
export declare function formatQuotaStatusBadge(status: QuotaStatusInfo): string;
/**
 * Format a plain-text (no ANSI) quota status label.
 * Suitable for hints and non-colored contexts.
 */
export declare function formatQuotaStatusPlain(status: QuotaStatusInfo): string;
/**
 * Classify the overall quota health of an account across all model groups.
 * Returns "exhausted" when ALL groups with data are at 0%, "partial" when
 * some but not all are exhausted, or "available" when none are exhausted.
 */
export declare function classifyOverallQuotaHealth(cachedQuota: Partial<Record<string, {
    remainingFraction?: number;
    resetTime?: string;
}>> | undefined): {
    health: 'available' | 'partial' | 'exhausted' | 'unknown';
    maxResetMs?: number;
};
export declare function formatCachedQuotaWithStatus(cachedQuota: Partial<Record<string, {
    remainingFraction?: number;
    resetTime?: string;
}>> | undefined, checkedAt?: number, now?: number): string | undefined;
/**
 * Format a per-group quota status badge for the "Check quotas" output.
 * Combines the progress bar with a status label.
 */
export declare function formatGroupQuotaBadge(remaining?: number, resetTime?: string): string;
//# sourceMappingURL=quota-status.d.ts.map