import { NO_QUOTA_READING } from './common-auth-embedded/quota/index.js';
export { NO_QUOTA_READING };
export interface QuotaReading {
    readonly remainingPercent: number;
    readonly resetAt?: number;
    readonly checkedAt?: number;
    readonly window?: 'weekly' | '5h';
}
/** A quota figure needs its own read timestamp; snapshot writes never supply one. */
export declare function formatQuotaReading(label: string, reading: QuotaReading | undefined, now: number): string;
/** Use common-auth's formatQuota text for a bar row without separately formatting figures, resets or ages. */
export declare function quotaReadingParts(label: string, reading: QuotaReading | undefined, now: number): {
    name: string;
    figure: string;
    detail: string;
    remaining: number | null;
};
//# sourceMappingURL=quota-presentation.d.ts.map