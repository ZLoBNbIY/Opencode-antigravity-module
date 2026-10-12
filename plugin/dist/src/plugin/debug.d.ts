import type { AntigravityConfig } from './config';
export declare const DEBUG_MESSAGE_PREFIX = "[opencode-antigravity-auth debug]";
/** The configuration fields that decide one location's debug sinks. */
export type DebugConfig = Pick<AntigravityConfig, 'debug' | 'debug_tui' | 'log_dir'>;
export interface AntigravityDebugContext {
    id: string;
    streaming: boolean;
    startedAt: number;
}
export interface AntigravityDebugRequestMeta {
    originalUrl: string;
    resolvedUrl: string;
    method?: string;
    headers?: HeadersInit;
    body?: BodyInit | null;
    streaming: boolean;
    projectId?: string;
}
export interface AntigravityDebugResponseMeta {
    body?: string;
    note?: string;
    error?: unknown;
    headersOverride?: HeadersInit;
}
export interface AccountDebugInfo {
    index: number;
    email?: string;
    family: string;
    totalAccounts: number;
    rateLimitState?: {
        claude?: number;
        gemini?: number;
    };
}
export interface RateLimitBodyInfo {
    message?: string;
    quotaResetTime?: string;
    retryDelayMs?: number | null;
    reason?: string;
}
/**
 * One location's debug sinks: its own file, debug/debug_tui policy and
 * request counter. Every method writes only to this location's file.
 */
export interface LocationDebug {
    isDebugEnabled(): boolean;
    isDebugTuiEnabled(): boolean;
    getLogFilePath(): string | undefined;
    startAntigravityDebugRequest(meta: AntigravityDebugRequestMeta): AntigravityDebugContext | null;
    logAntigravityDebugResponse(context: AntigravityDebugContext | null | undefined, response: Response, meta?: AntigravityDebugResponseMeta): void;
    logAccountContext(label: string, info: AccountDebugInfo): void;
    logRateLimitEvent(accountIndex: number, email: string | undefined, family: string, status: number, retryAfterMs: number, bodyInfo: RateLimitBodyInfo): void;
    logRateLimitSnapshot(family: string, accounts: Array<{
        index: number;
        email?: string;
        rateLimitResetTimes?: {
            claude?: number;
            gemini?: number;
        };
    }>): void;
    logResponseBody(context: AntigravityDebugContext | null | undefined, response: Response, status: number): Promise<string | undefined>;
    logModelFamily(url: string, extractedModel: string | null, family: string): void;
    debugLogToFile(message: string): void;
    logToast(message: string, variant: 'info' | 'warning' | 'success' | 'error'): void;
    logRetryAttempt(attempt: number, maxAttempts: number, reason: string, delayMs?: number): void;
    logCacheStats(model: string, cacheReadTokens: number, cacheWriteTokens: number, totalInputTokens: number): void;
    logQuotaStatus(accountEmail: string | undefined, accountIndex: number, quotaPercent: number, family?: string): void;
    logQuotaFetch(event: 'start' | 'complete' | 'error', accountCount?: number, details?: string): void;
    logModelUsed(requestedModel: string, actualModel: string, accountEmail?: string): void;
    /**
     * Flush and close this location's log file. Idempotent; lines logged
     * afterwards are dropped rather than reopening the file.
     */
    close(): Promise<void>;
}
/**
 * Build one server location's debug sinks from its own configuration. The
 * handle owns its log file and request counter; it never reads or replaces
 * the OpenCode 1 module-level debug state below, and closing it leaves every
 * other location's file open.
 */
export declare function createLocationDebug(config: DebugConfig): LocationDebug;
/**
 * Close the OpenCode 1 debug log stream and resolve once all buffered writes
 * have been flushed to disk. Tests use this to wait deterministically for
 * log lines before reading the log file.
 */
export declare function closeDebugLog(): Promise<void>;
/**
 * Initialize or reinitialize the OpenCode 1 debug state with the given
 * config. Call this once at plugin startup after loading config.
 */
export declare function initializeDebug(config: AntigravityConfig): void;
export declare function isDebugEnabled(): boolean;
export declare function isDebugTuiEnabled(): boolean;
export declare function getLogFilePath(): string | undefined;
/**
 * Begins a debug trace for an Antigravity request.
 */
export declare function startAntigravityDebugRequest(meta: AntigravityDebugRequestMeta): AntigravityDebugContext | null;
/**
 * Logs response details for a previously started debug trace.
 */
export declare function logAntigravityDebugResponse(context: AntigravityDebugContext | null | undefined, response: Response, meta?: AntigravityDebugResponseMeta): void;
export declare function logAccountContext(label: string, info: AccountDebugInfo): void;
export declare function logRateLimitEvent(accountIndex: number, email: string | undefined, family: string, status: number, retryAfterMs: number, bodyInfo: RateLimitBodyInfo): void;
export declare function logRateLimitSnapshot(family: string, accounts: Array<{
    index: number;
    email?: string;
    rateLimitResetTimes?: {
        claude?: number;
        gemini?: number;
    };
}>): void;
export declare function logResponseBody(context: AntigravityDebugContext | null | undefined, response: Response, status: number): Promise<string | undefined>;
export declare function logModelFamily(url: string, extractedModel: string | null, family: string): void;
export declare function debugLogToFile(message: string): void;
/**
 * Logs a toast message to the debug file.
 * This helps correlate what the user saw with debug events.
 */
export declare function logToast(message: string, variant: 'info' | 'warning' | 'success' | 'error'): void;
/**
 * Logs retry attempt information.
 * @param maxAttempts - Use -1 for unlimited retries
 */
export declare function logRetryAttempt(attempt: number, maxAttempts: number, reason: string, delayMs?: number): void;
/**
 * Logs cache hit/miss information from response usage metadata.
 */
export declare function logCacheStats(model: string, cacheReadTokens: number, cacheWriteTokens: number, totalInputTokens: number): void;
/**
 * Logs quota status for an account.
 */
export declare function logQuotaStatus(accountEmail: string | undefined, accountIndex: number, quotaPercent: number, family?: string): void;
/**
 * Logs background quota fetch events.
 */
export declare function logQuotaFetch(event: 'start' | 'complete' | 'error', accountCount?: number, details?: string): void;
/**
 * Logs which model is being used for a request.
 */
export declare function logModelUsed(requestedModel: string, actualModel: string, accountEmail?: string): void;
//# sourceMappingURL=debug.d.ts.map