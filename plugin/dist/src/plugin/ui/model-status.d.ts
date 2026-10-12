import type { CooldownReason } from '../accounts';
import type { QuotaGroupSummary } from '../quota';
import type { QuotaStatusInfo } from './quota-status';
/**
 * Per-account status data for a specific model family.
 * Extracted from AccountManager by the caller; kept simple for testability.
 */
export interface ModelAccountStatus {
    coolingDown: boolean;
    cooldownMs: number;
    cooldownReason?: CooldownReason;
    rateLimited: boolean;
    rateLimitWaitMs: number;
    quotaGroup?: QuotaGroupSummary;
}
/**
 * Determine per-model availability status by aggregating across accounts.
 *
 * Rules:
 *   1. If ANY enabled account can serve the model → READY (or LOW if all
 *      available accounts have low quota).
 *   2. If ALL accounts are blocked:
 *      - All cooling down → COOLDOWN with min cooldown time
 *      - Any rate-limited  → WAIT with min wait time
 *   3. Fail-open: returns READY when no accounts or no quota data exist.
 */
export declare function getModelStatusFromAccounts(accounts: readonly ModelAccountStatus[]): QuotaStatusInfo;
//# sourceMappingURL=model-status.d.ts.map