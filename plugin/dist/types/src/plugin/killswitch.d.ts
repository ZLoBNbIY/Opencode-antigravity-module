/**
 * Live killswitch for the account pool.
 *
 * The operator-configured killswitch excludes candidates whose freshest
 * cached quota remaining-percent is at or below a per-account
 * threshold (or the global minimum_remaining_percent when no
 * per-account override is set).
 *
 * Quota data is read live from `account.cachedQuota`, which is a
 * `Partial<Record<QuotaGroup, QuotaGroupSummary>>` populated by the
 * quota manager after every successful refresh. Stale or missing
 * data is treated as fail-open: the candidate is allowed through so a
 * cold start cannot deadlock the request pipeline on the operator's
 * first dial.
 */
import type { AccountModelFamily as ModelFamily, QuotaGroup, QuotaGroupSummary } from '@cortexkit/antigravity-auth-core';
import type { OperatorSettings } from './operator-settings.js';
export interface KillswitchAccountSnapshot {
    index: number;
    refreshToken?: string;
    email?: string;
    cachedQuota?: Partial<Record<QuotaGroup, QuotaGroupSummary>>;
    cachedQuotaUpdatedAt?: number;
}
export interface KillswitchDecision {
    allowed: boolean;
    reason: 'ok' | 'killswitch-disabled' | 'quota-missing-or-stale' | 'below-threshold';
    thresholdPercent: number;
    remainingPercent: number | null;
}
export interface KillswitchEvaluateOptions {
    now?: number;
    /** Cache TTL in milliseconds — cached quota older than this is fail-open. */
    cacheTtlMs?: number;
    /**
     * Model identifier to scope the evaluation to. When set, the
     * decision checks only the quota group that powers that model
     * (e.g. a `gemini-pro` request checks ONLY `gemini-pro`,
     * not the max of pro+flash). When omitted, the evaluation uses
     * the family-max behavior.
     */
    model?: string | null;
}
export declare function accountKeyForRefreshToken(refreshToken: string): string;
/**
 * Determine whether `account` is allowed under the operator killswitch.
 *
 * The decision is fail-open when:
 *   - killswitch is disabled
 *   - cached quota is missing entirely
 *   - cached quota is older than `cacheTtlMs`
 *
 * When `model` is provided, the evaluation is scoped to the single
 * quota group that powers that model (e.g. a `gemini-pro` request
 * checks ONLY `gemini-pro` — not the max of pro+flash). Without
 * `model`, the evaluation falls back to the family-max behavior so
 * existing callers that omit the model argument keep their previous
 * semantics.
 *
 * Returns a structured decision so callers can emit diagnostics for
 * each candidate without re-running the comparison.
 */
export declare function evaluateKillswitchForAccount(account: KillswitchAccountSnapshot, family: ModelFamily, settings: OperatorSettings, options?: KillswitchEvaluateOptions): KillswitchDecision;
/**
 * Build a redacted summary of every candidate's killswitch outcome.
 *
 * Used when the operator killswitch excludes the entire pool so the
 * host error message can list the offending accounts without leaking
 * identifiers or tokens.
 */
export declare function summarizeKillswitchOutcomes(accounts: readonly KillswitchAccountSnapshot[], family: ModelFamily, settings: OperatorSettings, options?: KillswitchEvaluateOptions): Array<{
    accountKey: string;
    remainingPercent: number | null;
    thresholdPercent: number;
}>;
/**
 * Throw `AntigravityKillswitchError` when every candidate is excluded.
 *
 * The interceptor calls this when its retry loop runs out of viable
 * accounts so the host surfaces a single, structured error rather than
 * a synthetic 200/401 body.
 */
export declare function throwIfAllKilled(input: {
    family: ModelFamily;
    model: string;
    accounts: readonly KillswitchAccountSnapshot[];
    settings: OperatorSettings;
    now?: number;
    cacheTtlMs?: number;
    /** Optional model to scope per-account evaluation to a single quota group. */
    quotaModel?: string | null;
}): void;
//# sourceMappingURL=killswitch.d.ts.map