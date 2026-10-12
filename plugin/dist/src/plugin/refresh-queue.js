/**
 * Proactive Token Refresh Queue
 *
 * Ported from LLM-API-Key-Proxy's BackgroundRefresher.
 *
 * This module provides background token refresh to ensure OAuth tokens
 * remain valid without blocking user requests. It periodically checks
 * all accounts and refreshes tokens that are approaching expiry.
 *
 * Features:
 * - Non-blocking background refresh (doesn't block requests)
 * - Configurable refresh buffer (default: 30 minutes before expiry)
 * - Configurable check interval (default: 5 minutes)
 * - Serialized refresh to prevent concurrent refresh storms
 * - Integrates with existing AccountManager and token refresh logic
 * - Silent operation: no console output, uses structured logger
 */
import { createLogger } from './logger';
import { refreshAccessToken } from './token';
const log = createLogger('refresh-queue');
export const DEFAULT_PROACTIVE_REFRESH_CONFIG = {
    enabled: true,
    bufferSeconds: 1800, // 30 minutes
    checkIntervalSeconds: 300, // 5 minutes
};
/**
 * Proactive Token Refresh Queue
 *
 * Runs in the background and proactively refreshes tokens before they expire.
 * This ensures that user requests never block on token refresh.
 *
 * All logging is silent by default - uses structured logger with TUI integration.
 */
export class ProactiveRefreshQueue {
    config;
    log;
    refresh;
    accountManager = null;
    inflightRefresh = null;
    disposed = false;
    state = {
        isRunning: false,
        intervalHandle: null,
        initialTimeoutHandle: null,
        isRefreshing: false,
        lastCheckTime: 0,
        lastRefreshTime: 0,
        refreshCount: 0,
        errorCount: 0,
    };
    /**
     * `client` and `providerId` bind the OpenCode 1 token refresh. When
     * `dependencies` is given, its logger and refresher are used instead and
     * the client is never called.
     */
    constructor(client, providerId, config, dependencies) {
        if (dependencies) {
            this.log = dependencies.logger;
            this.refresh = dependencies.refreshToken;
        }
        else {
            if (!client) {
                throw new TypeError('ProactiveRefreshQueue needs a host client or explicit dependencies');
            }
            this.log = log;
            this.refresh = (auth) => refreshAccessToken(auth, client, providerId);
        }
        this.config = {
            ...DEFAULT_PROACTIVE_REFRESH_CONFIG,
            ...config,
        };
    }
    /**
     * Set the account manager to use for refresh operations.
     * Must be called before start().
     */
    setAccountManager(manager) {
        this.accountManager = manager;
    }
    /**
     * Check if a token needs proactive refresh.
     * Returns true if the token expires within the buffer period.
     */
    needsRefresh(account) {
        if (!account.expires) {
            // No expiry set - assume it's fine
            return false;
        }
        const now = Date.now();
        const bufferMs = this.config.bufferSeconds * 1000;
        const refreshThreshold = now + bufferMs;
        return account.expires <= refreshThreshold;
    }
    /**
     * Check if a token is already expired.
     */
    isExpired(account) {
        if (!account.expires) {
            return false;
        }
        return account.expires <= Date.now();
    }
    /**
     * Get all accounts that need proactive refresh.
     */
    getAccountsNeedingRefresh() {
        if (!this.accountManager) {
            return [];
        }
        return this.accountManager.getAccounts().filter((account) => {
            // Skip disabled accounts - they shouldn't receive proactive refresh
            if (account.enabled === false) {
                return false;
            }
            // Only refresh if not already expired (let the main flow handle expired tokens)
            if (this.isExpired(account)) {
                return false;
            }
            return this.needsRefresh(account);
        });
    }
    /**
     * Perform a single refresh check iteration.
     * This is called periodically by the background interval.
     */
    runRefreshCheck() {
        if (this.inflightRefresh) {
            return this.inflightRefresh;
        }
        this.inflightRefresh = this.performRefreshCheck().finally(() => {
            this.inflightRefresh = null;
        });
        return this.inflightRefresh;
    }
    async performRefreshCheck() {
        if (this.config.mayRun && !(await this.config.mayRun()))
            return;
        if (this.state.isRefreshing) {
            // Already refreshing - skip this iteration
            return;
        }
        if (!this.accountManager) {
            return;
        }
        this.state.isRefreshing = true;
        this.state.lastCheckTime = Date.now();
        try {
            const accountsToRefresh = this.getAccountsNeedingRefresh();
            if (accountsToRefresh.length === 0) {
                return;
            }
            this.log.debug('Found accounts needing refresh', {
                count: accountsToRefresh.length,
            });
            // Refresh accounts serially to avoid concurrent refresh storms
            for (const account of accountsToRefresh) {
                if (this.config.mayRun && !(await this.config.mayRun()))
                    break;
                if (!this.state.isRunning) {
                    // Recheck shutdown after the asynchronous authority read.
                    break;
                }
                try {
                    const auth = this.accountManager.toAuthDetails(account);
                    const refreshed = await this.refreshToken(auth, account);
                    if (refreshed) {
                        this.accountManager.updateFromAuth(account, refreshed);
                        this.state.refreshCount++;
                        this.state.lastRefreshTime = Date.now();
                        // Persist the refreshed token
                        try {
                            await this.accountManager.saveToDisk();
                        }
                        catch {
                            // Non-fatal - token is refreshed in memory
                        }
                    }
                }
                catch (error) {
                    this.state.errorCount++;
                    // Log but don't throw - continue with other accounts
                    this.log.warn('Failed to refresh account', {
                        accountIndex: account.index,
                        error: error instanceof Error ? error.message : String(error),
                    });
                }
            }
        }
        finally {
            this.state.isRefreshing = false;
        }
    }
    /**
     * Refresh a single token.
     */
    async refreshToken(auth, account) {
        const minutesUntilExpiry = account.expires
            ? Math.round((account.expires - Date.now()) / 60000)
            : 'unknown';
        this.log.debug('Proactively refreshing token', {
            accountIndex: account.index,
            email: account.email ?? 'unknown',
            minutesUntilExpiry,
        });
        return this.refresh(auth, account);
    }
    /**
     * Start the background refresh queue.
     */
    start() {
        if (this.disposed || this.state.isRunning) {
            return;
        }
        if (!this.config.enabled) {
            this.log.debug('Proactive refresh disabled by config');
            return;
        }
        this.state.isRunning = true;
        const intervalMs = this.config.checkIntervalSeconds * 1000;
        this.log.debug('Started proactive refresh queue', {
            checkIntervalSeconds: this.config.checkIntervalSeconds,
            bufferSeconds: this.config.bufferSeconds,
        });
        // Run initial check after a short delay (let things settle)
        this.state.initialTimeoutHandle = setTimeout(() => {
            this.state.initialTimeoutHandle = null;
            if (this.state.isRunning) {
                this.runRefreshCheck().catch((error) => {
                    this.log.error('Initial check failed', {
                        error: error instanceof Error ? error.message : String(error),
                    });
                });
            }
        }, 5000);
        // Set up periodic checks
        this.state.intervalHandle = setInterval(() => {
            this.runRefreshCheck().catch((error) => {
                this.log.error('Check failed', {
                    error: error instanceof Error ? error.message : String(error),
                });
            });
        }, intervalMs);
    }
    /**
     * Stop the background refresh queue.
     */
    stop() {
        if (!this.state.isRunning) {
            return;
        }
        this.state.isRunning = false;
        if (this.state.intervalHandle) {
            clearInterval(this.state.intervalHandle);
            this.state.intervalHandle = null;
        }
        if (this.state.initialTimeoutHandle) {
            clearTimeout(this.state.initialTimeoutHandle);
            this.state.initialTimeoutHandle = null;
        }
        this.log.debug('Stopped proactive refresh queue', {
            refreshCount: this.state.refreshCount,
            errorCount: this.state.errorCount,
        });
    }
    async dispose() {
        this.disposed = true;
        this.stop();
        await this.inflightRefresh;
    }
    /**
     * Get current queue statistics.
     */
    getStats() {
        return { ...this.state };
    }
    /**
     * Check if the queue is currently running.
     */
    isRunning() {
        return this.state.isRunning;
    }
}
/**
 * Create a proactive refresh queue instance.
 */
export function createProactiveRefreshQueue(client, providerId, config) {
    return new ProactiveRefreshQueue(client, providerId, config);
}
/**
 * Create one location's refresh queue. The location supplies its logger and
 * token refresher; nothing is read from the OpenCode 1 host client or the
 * module logger.
 */
export function createLocationProactiveRefreshQueue(dependencies, config) {
    if (typeof dependencies?.logger?.debug !== 'function' ||
        typeof dependencies.refreshToken !== 'function') {
        throw new TypeError('createLocationProactiveRefreshQueue requires a logger and refreshToken');
    }
    // The provider id is only used by the host-client refresh path, which a
    // queue built with explicit dependencies never takes.
    return new ProactiveRefreshQueue(null, '', config, dependencies);
}
//# sourceMappingURL=refresh-queue.js.map