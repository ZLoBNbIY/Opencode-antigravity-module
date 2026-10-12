import { resolveModelWithTier } from './transform/model-resolver';
export const MAX_TOTAL_CAPACITY_RETRIES = 4;
export const CAPACITY_BACKOFF_TIERS_MS = [5000, 10000, 20000, 30000, 60000];
export function isCapacityRetryBudgetExhausted(totalCapacityRetries) {
    return totalCapacityRetries >= MAX_TOTAL_CAPACITY_RETRIES;
}
export function getCapacityBackoffDelay(consecutiveFailures) {
    const index = Math.min(consecutiveFailures, CAPACITY_BACKOFF_TIERS_MS.length - 1);
    return CAPACITY_BACKOFF_TIERS_MS[Math.max(0, index)] ?? 5000;
}
export function toUrlString(value) {
    if (typeof value === 'string') {
        return value;
    }
    const candidate = value.url;
    if (candidate) {
        return candidate;
    }
    return value.toString();
}
export function toWarmupStreamUrl(value) {
    const urlString = toUrlString(value);
    try {
        const url = new URL(urlString);
        if (!url.pathname.includes(':streamGenerateContent')) {
            url.pathname = url.pathname.replace(':generateContent', ':streamGenerateContent');
        }
        url.searchParams.set('alt', 'sse');
        return url.toString();
    }
    catch {
        return urlString;
    }
}
export function extractModelFromUrl(urlString) {
    const match = urlString.match(/\/models\/([^:/?]+)(?::\w+)?/);
    return match?.[1] ?? null;
}
function extractModelFromUrlWithSuffix(urlString) {
    const match = urlString.match(/\/models\/([^:/?]+)/);
    return match?.[1] ?? null;
}
/**
 * Model family for a request URL. The caller's location debug log, when
 * given, records the decision; this module keeps no debug state of its own.
 */
export function getModelFamilyFromUrl(urlString, debug) {
    const model = extractModelFromUrl(urlString);
    let family = 'gemini';
    if (model?.includes('claude')) {
        family = 'claude';
    }
    if (debug?.isDebugEnabled()) {
        debug.logModelFamily(urlString, model, family);
    }
    return family;
}
export function resolveQuotaFallbackHeaderStyle(input) {
    if (input.family !== 'gemini') {
        return null;
    }
    if (!input.alternateStyle || input.alternateStyle === input.headerStyle) {
        return null;
    }
    return input.alternateStyle;
}
export function resolveHeaderRoutingDecision(urlString, family, config) {
    const cliFirst = getCliFirst(config);
    const preferredHeaderStyle = getHeaderStyleFromUrl(urlString, family, cliFirst);
    const explicitQuota = isExplicitQuotaFromUrl(urlString);
    return {
        cliFirst,
        preferredHeaderStyle,
        explicitQuota,
        allowQuotaFallback: family === 'gemini' && !!(config.quota_style_fallback ?? false),
    };
}
function getCliFirst(config) {
    return config.cli_first ?? false;
}
export function getHeaderStyleFromUrl(urlString, family, cliFirst = false) {
    if (family === 'claude') {
        return 'antigravity';
    }
    const modelWithSuffix = extractModelFromUrlWithSuffix(urlString);
    if (!modelWithSuffix) {
        return cliFirst ? 'gemini-cli' : 'antigravity';
    }
    const { quotaPreference } = resolveModelWithTier(modelWithSuffix, {
        cli_first: cliFirst,
    });
    return quotaPreference ?? 'antigravity';
}
export function isExplicitQuotaFromUrl(urlString) {
    const modelWithSuffix = extractModelFromUrlWithSuffix(urlString);
    if (!modelWithSuffix) {
        return false;
    }
    const { explicitQuota } = resolveModelWithTier(modelWithSuffix);
    return explicitQuota ?? false;
}
//# sourceMappingURL=fetch-routing.js.map