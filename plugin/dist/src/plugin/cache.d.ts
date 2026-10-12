import { SignatureCache } from './cache/signature-cache';
import type { SignatureCacheConfig } from './config';
import type { SignatureStore } from './core/streaming/types';
import type { Clock } from './neutral-types';
export interface LocationSignatureOptions {
    /** The location's keep_thinking setting. */
    keepThinking: boolean;
    /** The location's signature_cache setting. */
    signatureCache: SignatureCacheConfig | undefined;
    /** Disk cache file; defaults to `getSignatureCacheFilePath()`. */
    cacheFilePath?: string;
}
/**
 * One location's view of the process-shared signature cache.
 */
export interface LocationSignatureCache {
    /**
     * Thought restoration/injection policy for this location's requests.
     * Lookup and extraction do not consult it.
     */
    readonly keepThinking: boolean;
    /**
     * This location's owned handle on the shared disk cache when keep_thinking
     * and signature_cache.enabled are both on, else null. With thought replay
     * disabled (keep_thinking off) and signature_cache.enabled on, the location
     * has read-only lookup access to a cache another owner is running, and this
     * stays null.
     */
    readonly diskCache: SignatureCache | null;
    /** This location's current-session signed-thinking replay store. */
    readonly signatureStore: SignatureStore;
    /** Record a signature in the hot map and, when owned, the disk cache. */
    cacheSignature(sessionId: string, text: string, signature: string): void;
    /**
     * Hot map first (fixed one-hour gate), then the disk cache for this
     * location's file, when one is running, against this location's memory
     * TTL; a disk hit is promoted into the hot map.
     */
    getCachedSignature(sessionId: string, text: string): string | undefined;
    /**
     * Release this location's share of the disk cache. Idempotent. The last
     * enabled owner of a disk cache flushes and stops it, even while readers
     * remain; otherwise retention is recomputed from the remaining consumers.
     * Nothing is cleared for any other location, and this handle neither reads
     * nor writes afterwards.
     */
    dispose(): Promise<void>;
}
export interface SignatureProcessState {
    /** Acquire one location's handle over this state. */
    acquireLocation(options: LocationSignatureOptions): LocationSignatureCache;
    /**
     * Whether the hot map holds an entry for this session and text, whatever
     * its age. Never deletes or refreshes anything (diagnostics and tests).
     */
    hasHotEntry(sessionId: string, text: string): boolean;
    /** The shared disk cache for a file while an enabled owner holds it. */
    diskCacheFor(filePath: string): SignatureCache | null;
    /** Clear the hot map for one session, or entirely. */
    clearHot(sessionId?: string): void;
}
export interface SignatureProcessStateOptions {
    /** Wall clock in epoch milliseconds; defaults to `Date.now()`. */
    now?: Clock;
}
/**
 * Create a signature-cache state: the hot map plus the table of shared disk
 * caches. Production uses the single `processSignatureState`; tests create
 * isolated ones with a deterministic clock.
 */
export declare function createSignatureProcessState(options?: SignatureProcessStateOptions): SignatureProcessState;
/** The signature-cache state every location in this process shares. */
export declare const processSignatureState: SignatureProcessState;
/** Acquire a location's handle over the process-shared signature cache. */
export declare function acquireLocationSignatureCache(options: LocationSignatureOptions): LocationSignatureCache;
/**
 * Make the module-level OpenCode 1 handle own the disk cache for `config`.
 * Called from OpenCode 1 plugin initialization when keep_thinking is enabled.
 */
export declare function initDiskSignatureCache(config: SignatureCacheConfig | undefined): SignatureCache | null;
/**
 * Get the OpenCode 1 disk cache instance (for testing/debugging).
 */
export declare function getDiskSignatureCache(): SignatureCache | null;
/**
 * Release the OpenCode 1 disk ownership (flushing when it was the last
 * owner) and clear the hot map. Clears no credential state.
 */
export declare function shutdownDiskSignatureCache(): Promise<void>;
/**
 * Caches a thinking signature for a given session and text.
 * Used for Claude models that require signed thinking blocks in multi-turn conversations.
 * Also writes to disk cache if enabled.
 */
export declare function cacheSignature(sessionId: string, text: string, signature: string): void;
/**
 * Retrieves a cached signature for a given session and text.
 * Checks memory first, then falls back to disk cache.
 * Returns undefined if not found or expired.
 */
export declare function getCachedSignature(sessionId: string, text: string): string | undefined;
/**
 * Clears signature cache for a specific session or all sessions.
 * Disk entries are left to expire through their TTL.
 */
export declare function clearSignatureCache(sessionId?: string): void;
export { createSignatureCache, getSignatureCacheFilePath, SignatureCache, } from './cache/signature-cache';
export type { SignatureCacheConfig } from './config';
//# sourceMappingURL=cache.d.ts.map