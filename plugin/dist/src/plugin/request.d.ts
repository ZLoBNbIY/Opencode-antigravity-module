import { type HeaderStyle } from '../constants';
import { type AgyRequestSessionContext } from './agy-request-metadata';
import { type LocationSignatureCache } from './cache';
import { createStreamingTransformer, transformSseLine, transformStreamingPayload } from './core/streaming';
import { type AntigravityDebugContext, type LocationDebug } from './debug';
import { type Fingerprint } from './fingerprint';
import { type GeminiDumpContext } from './gemini-dump';
import { type Logger } from './logger';
import type { GoogleSearchConfig } from './transform/types';
export declare function getImageModelLocalTitle(input: RequestInfo, init?: RequestInit): string | undefined;
declare function buildSignatureSessionKey(sessionId: string, model?: string, conversationKey?: string, projectKey?: string): string;
declare function hashConversationSeed(seed: string): string;
declare function extractTextFromContent(content: unknown): string;
declare function extractConversationSeedFromMessages(messages: any[]): string;
declare function extractConversationSeedFromContents(contents: any[]): string;
declare function resolveConversationKey(requestPayload: Record<string, unknown>): string | undefined;
declare function resolveProjectKey(candidate?: unknown, fallback?: string): string | undefined;
declare function isGeminiToolUsePart(part: any): boolean;
declare function isGeminiThinkingPart(part: any): boolean;
declare function ensureThoughtSignature(part: any, sessionId: string): any;
declare function hasToolUseInContents(contents: any[]): boolean;
declare function hasToolUseInMessages(messages: any[]): boolean;
/**
 * Gets the stable session ID for this plugin instance.
 */
export declare function getPluginSessionId(): string;
/** Prompt-cache statistics from the last response that reported them. */
export interface RequestCacheStats {
    model: string;
    read: number;
    total: number;
    hitRate: number;
}
/**
 * One location's state for the wire functions: its signature cache and
 * keep_thinking policy, debug log, logger, session fingerprint, the thinking
 * already shown in its debug view and its last prompt-cache statistics.
 * `createRequestWireLocation` builds one; OpenCode 1's module-level functions
 * use the single-location binding over the module-level state.
 */
export interface RequestWireLocation {
    readonly signatures: Pick<LocationSignatureCache, 'keepThinking' | 'signatureStore' | 'cacheSignature' | 'getCachedSignature'>;
    readonly debug: Pick<LocationDebug, 'isDebugTuiEnabled' | 'logAntigravityDebugResponse' | 'logCacheStats'>;
    readonly logger: Logger;
    /** Fingerprint used when the selected account has none. */
    sessionFingerprint(): Fingerprint;
    readonly displayedThinkingHashes: Set<string>;
    readonly cacheStats: {
        last: RequestCacheStats | null;
    };
}
/** Builds one location's wire state from its own collaborators. */
export declare function createRequestWireLocation(input: {
    signatures: RequestWireLocation['signatures'];
    debug: RequestWireLocation['debug'];
    logger: Logger;
    /** Defaults to a fingerprint generated once for this location. */
    sessionFingerprint?: Fingerprint;
}): RequestWireLocation;
export declare function getLastCacheStats(): RequestCacheStats | null;
/**
 * Extract a URL string from any fetch() input shape (string, URL, or Request).
 */
export declare function fetchInputToUrl(input: RequestInfo | URL): string;
/**
 * Detects requests headed to the Google Generative Language API so we can
 * intercept them. Handles string, URL, and Request inputs — matching on URL
 * only would let `fetch(new Request(...))` / `fetch(new URL(...))` bypass the
 * interceptor entirely.
 */
export declare function isGenerativeLanguageRequest(input: RequestInfo | URL): boolean;
/**
 * Options for request preparation.
 */
export interface PrepareRequestOptions {
    /** Enable Claude tool hardening (parameter signatures + system instruction). Default: true */
    claudeToolHardening?: boolean;
    /** Enable top-level Claude prompt auto-caching (`cache_control`). Default: false */
    claudePromptAutoCaching?: boolean;
    /** Google Search configuration (global default) */
    googleSearch?: GoogleSearchConfig;
    /** Per-account fingerprint for rate limit mitigation. Falls back to session fingerprint if not provided. */
    fingerprint?: Fingerprint;
    /** Stable AGY wire identity scoped to the exact OpenCode session. */
    agySession?: AgyRequestSessionContext;
    /** Monotonic request timestamp allocated once and reused across endpoint retries. */
    agyRequestTimestamp?: number;
}
declare function prepareAntigravityRequestIn(wire: RequestWireLocation, input: RequestInfo, init: RequestInit | undefined, accessToken: string, projectId: string, endpointOverride?: string, headerStyle?: HeaderStyle, forceThinkingRecovery?: boolean, options?: PrepareRequestOptions): {
    request: RequestInfo;
    init: RequestInit;
    streaming: boolean;
    requestedModel?: string;
    effectiveModel?: string;
    projectId?: string;
    endpoint?: string;
    sessionId?: string;
    toolDebugMissing?: number;
    toolDebugSummary?: string;
    toolDebugPayload?: string;
    needsSignedThinkingWarmup?: boolean;
    headerStyle: HeaderStyle;
    thinkingRecoveryMessage?: string;
};
/** OpenCode 1's request preparation over its module-level state. */
export declare function prepareAntigravityRequest(...args: Parameters<typeof prepareAntigravityRequestIn> extends [
    unknown,
    ...infer Rest
] ? Rest : never): ReturnType<typeof prepareAntigravityRequestIn>;
export declare function buildThinkingWarmupBody(bodyText: string | undefined, isClaudeThinking: boolean): string | null;
/**
 * Normalizes Antigravity responses: applies retry headers, extracts cache usage into headers,
 * rewrites preview errors, flattens streaming payloads, and logs debug metadata.
 *
 * For streaming SSE responses, uses TransformStream for true real-time incremental streaming.
 * Thinking/reasoning tokens are transformed and forwarded immediately as they arrive.
 */
declare function transformAntigravityResponseIn(wire: RequestWireLocation, response: Response, streaming: boolean, debugContext?: AntigravityDebugContext | null, requestedModel?: string, projectId?: string, endpoint?: string, effectiveModel?: string, sessionId?: string, toolDebugMissing?: number, toolDebugSummary?: string, toolDebugPayload?: string, debugLines?: string[], dumpContext?: GeminiDumpContext | null): Promise<Response>;
/** OpenCode 1's response transformation over its module-level state. */
export declare function transformAntigravityResponse(...args: Parameters<typeof transformAntigravityResponseIn> extends [
    unknown,
    ...infer Rest
] ? Rest : never): Promise<Response>;
/**
 * The wire functions bound to one location's state. Preparation and
 * response handling follow exactly the OpenCode 1 rules; only the signature
 * cache, keep_thinking policy, debug log, logger, fallback fingerprint,
 * displayed-thinking set and cache statistics are the location's own.
 */
export declare function createRequestWire(location: RequestWireLocation): {
    prepare: typeof prepareAntigravityRequest;
    transformResponse: typeof transformAntigravityResponse;
    buildThinkingWarmupBody: typeof buildThinkingWarmupBody;
    getImageModelLocalTitle: typeof getImageModelLocalTitle;
    getLastCacheStats: typeof getLastCacheStats;
};
export declare const __testExports: {
    buildSignatureSessionKey: typeof buildSignatureSessionKey;
    hashConversationSeed: typeof hashConversationSeed;
    extractTextFromContent: typeof extractTextFromContent;
    extractConversationSeedFromMessages: typeof extractConversationSeedFromMessages;
    extractConversationSeedFromContents: typeof extractConversationSeedFromContents;
    resolveConversationKey: typeof resolveConversationKey;
    resolveProjectKey: typeof resolveProjectKey;
    isGeminiToolUsePart: typeof isGeminiToolUsePart;
    isGeminiThinkingPart: typeof isGeminiThinkingPart;
    ensureThoughtSignature: typeof ensureThoughtSignature;
    hasSignedThinkingPart: (part: any, sessionId?: string) => boolean;
    hasSignedThinkingInContents: (contents: any[], sessionId?: string) => boolean;
    hasSignedThinkingInMessages: (messages: any[], sessionId?: string) => boolean;
    hasToolUseInContents: typeof hasToolUseInContents;
    hasToolUseInMessages: typeof hasToolUseInMessages;
    ensureThinkingBeforeToolUseInContents: (contents: any[], key: string) => any[];
    ensureThinkingBeforeToolUseInMessages: (messages: any[], key: string) => any[];
    MIN_SIGNATURE_LENGTH: number;
    transformSseLine: typeof transformSseLine;
    transformStreamingPayload: typeof transformStreamingPayload;
    createStreamingTransformer: typeof createStreamingTransformer;
};
export {};
//# sourceMappingURL=request.d.ts.map