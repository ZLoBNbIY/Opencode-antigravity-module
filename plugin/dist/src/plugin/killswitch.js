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
import { createHash } from 'node:crypto';
import { AntigravityKillswitchError } from './errors';
const DEFAULT_CACHE_TTL_MS = 5 * 60 * 1000;
const QUOTA_GROUP_BY_FAMILY = {
    claude: ['non-gemini'],
    gemini: ['gemini', 'non-gemini'],
};
/**
 * Best-effort mapping from a model string to the quota group it draws
 * on. The mapping is intentionally inline (no shared regex table) so
 * the killswitch does not pull a transform stack into its import
 * graph. Models that are not recognised fall back to the family-max
 * behavior so a missed match can never widen the kill.
 */
function quotaGroupForModel(family, model) {
    if (!model)
        return null;
    const lower = model.toLowerCase();
    if (family === 'claude')
        return 'non-gemini';
    if (family === 'gemini') {
        // Check Claude / GPT-OSS substrings BEFORE the `gemini` substring so
        // a `gemini-claude-*` alias (Claude route exposed under a `gemini-`
        // namespace) attributes to the non-gemini pool rather than the
        // gemini pool.
        if (lower.includes('claude') || lower.includes('gpt-oss')) {
            return 'non-gemini';
        }
        if (lower.includes('gemini') || lower.startsWith('tab_'))
            return 'gemini';
    }
    return null;
}
export function accountKeyForRefreshToken(refreshToken) {
    return createHash('sha256').update(refreshToken).digest('hex').slice(0, 12);
}
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
export function evaluateKillswitchForAccount(account, family, settings, options = {}) {
    if (!settings.killswitch.enabled) {
        return {
            allowed: true,
            reason: 'killswitch-disabled',
            thresholdPercent: 0,
            remainingPercent: null,
        };
    }
    const accountKey = account.refreshToken
        ? accountKeyForRefreshToken(account.refreshToken)
        : `idx-${account.index}`;
    const thresholdPercent = settings.killswitch.accounts?.[accountKey] ??
        settings.killswitch.minimum_remaining_percent;
    const now = options.now ?? Date.now();
    const cacheTtlMs = options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
    const freshEnough = typeof account.cachedQuotaUpdatedAt === 'number' &&
        now - account.cachedQuotaUpdatedAt <= cacheTtlMs;
    const quota = freshEnough ? account.cachedQuota : undefined;
    if (!quota) {
        return {
            allowed: true,
            reason: 'quota-missing-or-stale',
            thresholdPercent,
            remainingPercent: null,
        };
    }
    const remainingPercent = quotaGroupForModel(family, options.model)
        ? remainingPercentForGroup(quota, family, options.model)
        : freshestRemainingPercent(quota, family);
    if (remainingPercent === null) {
        return {
            allowed: true,
            reason: 'quota-missing-or-stale',
            thresholdPercent,
            remainingPercent: null,
        };
    }
    return {
        allowed: remainingPercent >= thresholdPercent,
        reason: remainingPercent >= thresholdPercent ? 'ok' : 'below-threshold',
        thresholdPercent,
        remainingPercent,
    };
}
function freshestRemainingPercent(quota, family) {
    const groups = QUOTA_GROUP_BY_FAMILY[family];
    let best = null;
    for (const group of groups) {
        const entry = quota[group];
        if (!entry || typeof entry.remainingFraction !== 'number')
            continue;
        const pct = clampPercent(entry.remainingFraction * 100);
        if (best === null || pct > best)
            best = pct;
    }
    return best;
}
function remainingPercentForGroup(quota, family, model) {
    const group = quotaGroupForModel(family, model);
    if (!group)
        return null;
    const entry = quota[group];
    if (!entry || typeof entry.remainingFraction !== 'number')
        return null;
    return clampPercent(entry.remainingFraction * 100);
}
function clampPercent(value) {
    if (Number.isNaN(value))
        return 0;
    if (value < 0)
        return 0;
    if (value > 100)
        return 100;
    return value;
}
/**
 * Build a redacted summary of every candidate's killswitch outcome.
 *
 * Used when the operator killswitch excludes the entire pool so the
 * host error message can list the offending accounts without leaking
 * identifiers or tokens.
 */
export function summarizeKillswitchOutcomes(accounts, family, settings, options = {}) {
    return accounts.map((account) => {
        const decision = evaluateKillswitchForAccount(account, family, settings, options);
        const accountKey = account.refreshToken
            ? accountKeyForRefreshToken(account.refreshToken)
            : `idx-${account.index}`;
        return {
            accountKey,
            remainingPercent: decision.remainingPercent,
            thresholdPercent: decision.thresholdPercent,
        };
    });
}
/**
 * Throw `AntigravityKillswitchError` when every candidate is excluded.
 *
 * The interceptor calls this when its retry loop runs out of viable
 * accounts so the host surfaces a single, structured error rather than
 * a synthetic 200/401 body.
 */
export function throwIfAllKilled(input) {
    const { family, model, accounts, settings, quotaModel } = input;
    if (!settings.killswitch.enabled)
        return;
    const summaryOptions = {
        ...(input.now !== undefined ? { now: input.now } : {}),
        ...(input.cacheTtlMs !== undefined ? { cacheTtlMs: input.cacheTtlMs } : {}),
        ...(quotaModel !== undefined ? { model: quotaModel } : {}),
    };
    const summaries = summarizeKillswitchOutcomes(accounts, family, settings, summaryOptions);
    const allKilled = accounts.every((account) => {
        const decision = evaluateKillswitchForAccount(account, family, settings, summaryOptions);
        return decision.reason === 'below-threshold';
    });
    if (!allKilled)
        return;
    const thresholdPercent = settings.killswitch.minimum_remaining_percent;
    throw new AntigravityKillswitchError({
        family,
        model,
        thresholdPercent,
        summaries,
    });
}
//# sourceMappingURL=killswitch.js.map