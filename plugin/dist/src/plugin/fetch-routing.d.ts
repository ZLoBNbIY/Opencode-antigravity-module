import type { AccountModelFamily as ModelFamily } from '@cortexkit/antigravity-auth-core';
import type { HeaderStyle } from '../constants';
import type { AntigravityConfig } from './config';
import type { LocationDebug } from './debug';
export declare const MAX_TOTAL_CAPACITY_RETRIES = 4;
export declare const CAPACITY_BACKOFF_TIERS_MS: number[];
export declare function isCapacityRetryBudgetExhausted(totalCapacityRetries: number): boolean;
export declare function getCapacityBackoffDelay(consecutiveFailures: number): number;
export declare function toUrlString(value: RequestInfo): string;
export declare function toWarmupStreamUrl(value: RequestInfo): string;
export declare function extractModelFromUrl(urlString: string): string | null;
/**
 * Model family for a request URL. The caller's location debug log, when
 * given, records the decision; this module keeps no debug state of its own.
 */
export declare function getModelFamilyFromUrl(urlString: string, debug?: Pick<LocationDebug, 'isDebugEnabled' | 'logModelFamily'>): ModelFamily;
export declare function resolveQuotaFallbackHeaderStyle(input: {
    family: ModelFamily;
    headerStyle: HeaderStyle;
    alternateStyle: HeaderStyle | null;
}): HeaderStyle | null;
export type HeaderRoutingDecision = {
    cliFirst: boolean;
    preferredHeaderStyle: HeaderStyle;
    explicitQuota: boolean;
    allowQuotaFallback: boolean;
};
export declare function resolveHeaderRoutingDecision(urlString: string, family: ModelFamily, config: Partial<AntigravityConfig>): HeaderRoutingDecision;
export declare function getHeaderStyleFromUrl(urlString: string, family: ModelFamily, cliFirst?: boolean): HeaderStyle;
export declare function isExplicitQuotaFromUrl(urlString: string): boolean;
//# sourceMappingURL=fetch-routing.d.ts.map