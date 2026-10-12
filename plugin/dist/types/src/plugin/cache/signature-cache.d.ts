/**
 * Signature cache for persisting thinking block signatures to disk.
 *
 * Features (based on LLM-API-Key-Proxy's ProviderCache):
 * - Dual-TTL system: short memory TTL, longer disk TTL
 * - Background disk persistence with batched writes
 * - Atomic writes with temp file + move pattern
 * - Automatic cleanup of expired entries
 *
 * One instance may serve several owners that share its file (see
 * `acquireLocationSignatureCache` in ../cache.ts). Each owner reads with its
 * own memory TTL; retention (what may be deleted, merged away on disk or
 * skipped while loading) follows the longest TTLs among live owners, so a
 * short-TTL owner never destroys an entry a longer-TTL owner can still use.
 * Entries keep their original timestamps throughout.
 *
 * Cache key format: `${sessionId}:${modelId}`
 */
import type { SignatureCacheConfig } from '../config/index.js';
import type { Clock } from '../neutral-types.js';
interface CacheStats {
    memoryHits: number;
    diskHits: number;
    misses: number;
    writes: number;
    memoryEntries: number;
    dirty: boolean;
    diskEnabled: boolean;
}
/**
 * Full thinking content with signature (for recovery)
 */
export interface ThinkingCacheData {
    text: string;
    signature: string;
    toolIds?: string[];
}
/** Default on-disk location of the signature cache for this environment. */
export declare function getSignatureCacheFilePath(): string;
export interface SignatureCacheOptions {
    /** File to persist to; defaults to `getSignatureCacheFilePath()`. */
    filePath?: string;
    /** Wall clock in epoch milliseconds; defaults to `Date.now()`. */
    now?: Clock;
}
/**
 * How long a shared cache keeps entries: the longest memory and disk TTLs
 * and the shortest write interval among its live owners.
 */
export interface SignatureCacheRetention {
    memoryTtlMs: number;
    diskTtlMs: number;
    writeIntervalMs: number;
}
export declare class SignatureCache {
    private cache;
    private memoryTtlMs;
    private retentionMemoryTtlMs;
    private retentionDiskTtlMs;
    private writeIntervalMs;
    private cacheFilePath;
    private enabled;
    private now;
    private dirty;
    private writeTimer;
    private cleanupTimer;
    private stats;
    constructor(config: SignatureCacheConfig, options?: SignatureCacheOptions);
    /**
     * Generate a cache key from sessionId and modelId.
     */
    static makeKey(sessionId: string, modelId: string): string;
    /**
     * Store a signature in the cache.
     */
    store(key: string, signature: string): void;
    /**
     * Retrieve a signature from the cache.
     * Returns null if not found or older than `memoryTtlMs` (the reader's own
     * TTL, defaulting to this cache's configured one). An entry is deleted
     * only once it is past the retention TTL, so another owner with a longer
     * TTL can still read it.
     */
    retrieve(key: string, memoryTtlMs?: number): string | null;
    /**
     * Check if a key exists in the cache (without updating stats).
     */
    has(key: string, memoryTtlMs?: number): boolean;
    /**
     * The stored entry's original timestamp, regardless of age (diagnostics
     * and tests; never refreshes the entry).
     */
    getTimestamp(key: string): number | undefined;
    /**
     * Store full thinking content with signature.
     * This enables recovery even after thinking text is stripped by compaction.
     *
     * Port of LLM-API-Key-Proxy's _cache_thinking()
     */
    storeThinking(key: string, thinkingText: string, signature: string, toolIds?: string[]): void;
    /**
     * Retrieve full thinking content by key.
     * Returns null if not found or expired.
     */
    retrieveThinking(key: string, memoryTtlMs?: number): ThinkingCacheData | null;
    /**
     * Check if full thinking content exists for a key.
     */
    hasThinking(key: string, memoryTtlMs?: number): boolean;
    /**
     * Replace the retention policy (shared owners joined or left). A longer
     * disk TTL loads entries the previous policy skipped, never replacing or
     * re-timestamping entries already in memory; a changed write interval
     * restarts the periodic write.
     */
    setRetention(retention: SignatureCacheRetention): void;
    /**
     * Get cache statistics.
     */
    getStats(): CacheStats;
    /**
     * Manually trigger a disk save.
     */
    flush(): Promise<boolean>;
    /**
     * Graceful shutdown: stop timers and flush to disk.
     */
    shutdown(): void;
    /**
     * Load cache from disk file with TTL validation.
     */
    private loadFromDisk;
    /**
     * Save cache to disk with atomic write pattern.
     * Merges with existing disk entries that haven't expired.
     */
    private saveToDisk;
    /**
     * Start background write and cleanup timers.
     */
    private startBackgroundTasks;
    private startWriteTimer;
    private deleteIfPastRetention;
    /**
     * Remove entries past the retention memory TTL (the periodic cleanup;
     * public so a deterministic test can run it without timers).
     */
    pruneExpired(): void;
}
/**
 * Create a signature cache with the given configuration.
 * Returns null if caching is disabled.
 */
export declare function createSignatureCache(config: SignatureCacheConfig | undefined, options?: SignatureCacheOptions): SignatureCache | null;
export {};
//# sourceMappingURL=signature-cache.d.ts.map