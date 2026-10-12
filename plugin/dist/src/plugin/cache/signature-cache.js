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
import { existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync, } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { ensureGitignoreSync } from '../storage';
// =============================================================================
// Path Utilities
// =============================================================================
function getConfigDir() {
    const platform = process.platform;
    if (platform === 'win32') {
        return join(process.env.APPDATA || join(homedir(), 'AppData', 'Roaming'), 'opencode');
    }
    const xdgConfig = process.env.XDG_CONFIG_HOME || join(homedir(), '.config');
    return join(xdgConfig, 'opencode');
}
/** Default on-disk location of the signature cache for this environment. */
export function getSignatureCacheFilePath() {
    return join(getConfigDir(), 'antigravity-signature-cache.json');
}
// =============================================================================
// Signature Cache Class
// =============================================================================
export class SignatureCache {
    // In-memory cache: key -> entry with signature and optional thinking text
    cache = new Map();
    // Configuration. memoryTtlMs is the default reader TTL; the retention
    // values bound deletion, loading and disk merges.
    memoryTtlMs;
    retentionMemoryTtlMs;
    retentionDiskTtlMs;
    writeIntervalMs;
    cacheFilePath;
    enabled;
    now;
    // State
    dirty = false;
    writeTimer = null;
    cleanupTimer = null;
    // Statistics
    stats = {
        memoryHits: 0,
        diskHits: 0,
        misses: 0,
        writes: 0,
    };
    constructor(config, options = {}) {
        this.enabled = config.enabled;
        this.memoryTtlMs = config.memory_ttl_seconds * 1000;
        this.retentionMemoryTtlMs = this.memoryTtlMs;
        this.retentionDiskTtlMs = config.disk_ttl_seconds * 1000;
        this.writeIntervalMs = config.write_interval_seconds * 1000;
        this.cacheFilePath = options.filePath ?? getSignatureCacheFilePath();
        this.now = options.now ?? (() => Date.now());
        if (this.enabled) {
            this.loadFromDisk();
            this.startBackgroundTasks();
        }
    }
    // ===========================================================================
    // Public API
    // ===========================================================================
    /**
     * Generate a cache key from sessionId and modelId.
     */
    static makeKey(sessionId, modelId) {
        return `${sessionId}:${modelId}`;
    }
    /**
     * Store a signature in the cache.
     */
    store(key, signature) {
        if (!this.enabled)
            return;
        this.cache.set(key, {
            value: signature,
            timestamp: this.now(),
        });
        this.dirty = true;
    }
    /**
     * Retrieve a signature from the cache.
     * Returns null if not found or older than `memoryTtlMs` (the reader's own
     * TTL, defaulting to this cache's configured one). An entry is deleted
     * only once it is past the retention TTL, so another owner with a longer
     * TTL can still read it.
     */
    retrieve(key, memoryTtlMs = this.memoryTtlMs) {
        if (!this.enabled)
            return null;
        const entry = this.cache.get(key);
        if (entry) {
            const age = this.now() - entry.timestamp;
            if (age <= memoryTtlMs) {
                this.stats.memoryHits++;
                return entry.value;
            }
            // Too old for this caller's TTL. Delete it only once it is also past
            // the retention TTL (the longest TTL of any live consumer), so a
            // longer-TTL reader can still use it.
            this.deleteIfPastRetention(key, age);
        }
        this.stats.misses++;
        return null;
    }
    /**
     * Check if a key exists in the cache (without updating stats).
     */
    has(key, memoryTtlMs = this.memoryTtlMs) {
        if (!this.enabled)
            return false;
        const entry = this.cache.get(key);
        if (!entry)
            return false;
        const age = this.now() - entry.timestamp;
        return age <= memoryTtlMs;
    }
    /**
     * The stored entry's original timestamp, regardless of age (diagnostics
     * and tests; never refreshes the entry).
     */
    getTimestamp(key) {
        return this.cache.get(key)?.timestamp;
    }
    // ===========================================================================
    // Full Thinking Cache (ported from LLM-API-Key-Proxy)
    // ===========================================================================
    /**
     * Store full thinking content with signature.
     * This enables recovery even after thinking text is stripped by compaction.
     *
     * Port of LLM-API-Key-Proxy's _cache_thinking()
     */
    storeThinking(key, thinkingText, signature, toolIds) {
        if (!this.enabled || !thinkingText || !signature)
            return;
        this.cache.set(key, {
            value: signature,
            timestamp: this.now(),
            thinkingText,
            textPreview: thinkingText.slice(0, 100),
            toolIds,
        });
        this.dirty = true;
    }
    /**
     * Retrieve full thinking content by key.
     * Returns null if not found or expired.
     */
    retrieveThinking(key, memoryTtlMs = this.memoryTtlMs) {
        if (!this.enabled)
            return null;
        const entry = this.cache.get(key);
        if (!entry?.thinkingText)
            return null;
        const age = this.now() - entry.timestamp;
        if (age > memoryTtlMs) {
            this.deleteIfPastRetention(key, age);
            return null;
        }
        this.stats.memoryHits++;
        return {
            text: entry.thinkingText,
            signature: entry.value,
            toolIds: entry.toolIds,
        };
    }
    /**
     * Check if full thinking content exists for a key.
     */
    hasThinking(key, memoryTtlMs = this.memoryTtlMs) {
        if (!this.enabled)
            return false;
        const entry = this.cache.get(key);
        if (!entry?.thinkingText)
            return false;
        const age = this.now() - entry.timestamp;
        return age <= memoryTtlMs;
    }
    /**
     * Replace the retention policy (shared owners joined or left). A longer
     * disk TTL loads entries the previous policy skipped, never replacing or
     * re-timestamping entries already in memory; a changed write interval
     * restarts the periodic write.
     */
    setRetention(retention) {
        const diskTtlGrew = retention.diskTtlMs > this.retentionDiskTtlMs;
        const intervalChanged = retention.writeIntervalMs !== this.writeIntervalMs;
        this.retentionMemoryTtlMs = retention.memoryTtlMs;
        this.retentionDiskTtlMs = retention.diskTtlMs;
        this.writeIntervalMs = retention.writeIntervalMs;
        if (!this.enabled)
            return;
        if (diskTtlGrew)
            this.loadFromDisk();
        if (intervalChanged && this.writeTimer) {
            clearInterval(this.writeTimer);
            this.writeTimer = null;
            this.startWriteTimer();
        }
    }
    /**
     * Get cache statistics.
     */
    getStats() {
        return {
            ...this.stats,
            memoryEntries: this.cache.size,
            dirty: this.dirty,
            diskEnabled: this.enabled,
        };
    }
    /**
     * Manually trigger a disk save.
     */
    async flush() {
        if (!this.enabled)
            return true;
        return this.saveToDisk();
    }
    /**
     * Graceful shutdown: stop timers and flush to disk.
     */
    shutdown() {
        if (this.writeTimer) {
            clearInterval(this.writeTimer);
            this.writeTimer = null;
        }
        if (this.cleanupTimer) {
            clearInterval(this.cleanupTimer);
            this.cleanupTimer = null;
        }
        if (this.dirty && this.enabled) {
            this.saveToDisk();
        }
    }
    // ===========================================================================
    // Disk Operations
    // ===========================================================================
    /**
     * Load cache from disk file with TTL validation.
     */
    loadFromDisk() {
        try {
            if (!existsSync(this.cacheFilePath)) {
                return;
            }
            const content = readFileSync(this.cacheFilePath, 'utf-8');
            const data = JSON.parse(content);
            if (data.version !== '1.0') {
                // Version mismatch - silently start fresh
                return;
            }
            const now = this.now();
            let _loaded = 0;
            let _expired = 0;
            for (const [key, entry] of Object.entries(data.entries)) {
                // Memory is newer than the file: never replace or re-timestamp it.
                if (this.cache.has(key))
                    continue;
                const age = now - entry.timestamp;
                if (age <= this.retentionDiskTtlMs) {
                    this.cache.set(key, {
                        value: entry.value,
                        timestamp: entry.timestamp,
                    });
                    _loaded++;
                }
                else {
                    _expired++;
                }
            }
            // Silently load - no console output
        }
        catch {
            // Silently start fresh on any error (corruption, file not found, etc.)
        }
    }
    /**
     * Save cache to disk with atomic write pattern.
     * Merges with existing disk entries that haven't expired.
     */
    saveToDisk() {
        try {
            // Ensure directory exists
            const dir = dirname(this.cacheFilePath);
            if (!existsSync(dir)) {
                mkdirSync(dir, { recursive: true });
            }
            ensureGitignoreSync(dir);
            const now = this.now();
            // Step 1: Load existing disk entries (if any)
            let existingEntries = {};
            if (existsSync(this.cacheFilePath)) {
                try {
                    const content = readFileSync(this.cacheFilePath, 'utf-8');
                    const data = JSON.parse(content);
                    existingEntries = data.entries || {};
                }
                catch {
                    // Start fresh if corrupted
                }
            }
            // Step 2: Filter existing disk entries by the retention disk_ttl
            const validDiskEntries = {};
            for (const [key, entry] of Object.entries(existingEntries)) {
                const age = now - entry.timestamp;
                if (age <= this.retentionDiskTtlMs) {
                    validDiskEntries[key] = entry;
                }
            }
            // Step 3: Merge - memory entries take precedence
            const mergedEntries = { ...validDiskEntries };
            for (const [key, entry] of this.cache.entries()) {
                mergedEntries[key] = {
                    value: entry.value,
                    timestamp: entry.timestamp,
                };
            }
            // Step 4: Build cache data
            const cacheData = {
                version: '1.0',
                memory_ttl_seconds: this.retentionMemoryTtlMs / 1000,
                disk_ttl_seconds: this.retentionDiskTtlMs / 1000,
                entries: mergedEntries,
                statistics: {
                    memory_hits: this.stats.memoryHits,
                    disk_hits: this.stats.diskHits,
                    misses: this.stats.misses,
                    writes: this.stats.writes + 1,
                    last_write: now,
                },
            };
            // Step 5: Atomic write (temp file + rename)
            const tmpPath = join(tmpdir(), `antigravity-cache-${Date.now()}-${Math.random().toString(36).slice(2)}.tmp`);
            writeFileSync(tmpPath, JSON.stringify(cacheData, null, 2), 'utf-8');
            try {
                renameSync(tmpPath, this.cacheFilePath);
            }
            catch {
                // On Windows, rename across volumes may fail
                // Fall back to copy + delete
                writeFileSync(this.cacheFilePath, readFileSync(tmpPath));
                try {
                    unlinkSync(tmpPath);
                }
                catch {
                    // Ignore cleanup errors
                }
            }
            this.stats.writes++;
            this.dirty = false;
            return true;
        }
        catch {
            // Silently fail - disk cache is optional
            return false;
        }
    }
    // ===========================================================================
    // Background Tasks
    // ===========================================================================
    /**
     * Start background write and cleanup timers.
     */
    startBackgroundTasks() {
        // Periodic disk writes
        this.startWriteTimer();
        // Periodic memory cleanup (every 30 minutes)
        this.cleanupTimer = setInterval(() => {
            this.pruneExpired();
        }, 30 * 60 * 1000);
    }
    startWriteTimer() {
        this.writeTimer = setInterval(() => {
            if (this.dirty) {
                this.saveToDisk();
            }
        }, this.writeIntervalMs);
    }
    deleteIfPastRetention(key, age) {
        if (age > this.retentionMemoryTtlMs) {
            this.cache.delete(key);
        }
    }
    /**
     * Remove entries past the retention memory TTL (the periodic cleanup;
     * public so a deterministic test can run it without timers).
     */
    pruneExpired() {
        const now = this.now();
        let _cleaned = 0;
        for (const [key, entry] of this.cache.entries()) {
            const age = now - entry.timestamp;
            if (age > this.retentionMemoryTtlMs) {
                this.cache.delete(key);
                _cleaned++;
            }
        }
        // Silently clean - no console output
    }
}
// =============================================================================
// Factory Function
// =============================================================================
/**
 * Create a signature cache with the given configuration.
 * Returns null if caching is disabled.
 */
export function createSignatureCache(config, options = {}) {
    if (!config?.enabled) {
        return null;
    }
    return new SignatureCache(config, options);
}
//# sourceMappingURL=signature-cache.js.map