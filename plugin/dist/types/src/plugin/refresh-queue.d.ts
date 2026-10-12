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
import type { AccountManager, ManagedAccount } from './accounts.js';
import { type Logger } from './logger.js';
import type { OAuthAuthDetails, PluginClient } from './types.js';
/**
 * The account-manager methods the queue uses. Narrower than the concrete
 * class so a location can hand in its own account view.
 */
export type RefreshQueueAccountView = Pick<AccountManager, 'getAccounts' | 'toAuthDetails' | 'updateFromAuth' | 'saveToDisk'>;
/** Refreshes one account's OAuth token; resolves `undefined` when it cannot. */
export type RefreshQueueTokenRefresher = (auth: OAuthAuthDetails, account: ManagedAccount) => Promise<OAuthAuthDetails | undefined>;
/**
 * Per-location collaborators. A location passes its own logger and token
 * refresher, so the queue never logs through the module logger or refreshes
 * through the OpenCode 1 host client (`PluginClient`).
 */
export interface ProactiveRefreshDependencies {
    logger: Logger;
    refreshToken: RefreshQueueTokenRefresher;
}
/** Configuration for the proactive refresh queue */
export interface ProactiveRefreshConfig {
    mayRun?: () => Promise<boolean>;
    /** Enable proactive token refresh (default: true) */
    enabled: boolean;
    /** Seconds before expiry to trigger proactive refresh (default: 1800 = 30 minutes) */
    bufferSeconds: number;
    /** Interval between refresh checks in seconds (default: 300 = 5 minutes) */
    checkIntervalSeconds: number;
}
export declare const DEFAULT_PROACTIVE_REFRESH_CONFIG: ProactiveRefreshConfig;
/**
 * Proactive Token Refresh Queue
 *
 * Runs in the background and proactively refreshes tokens before they expire.
 * This ensures that user requests never block on token refresh.
 *
 * All logging is silent by default - uses structured logger with TUI integration.
 */
export declare class ProactiveRefreshQueue {
    private readonly config;
    private readonly log;
    private readonly refresh;
    private accountManager;
    private inflightRefresh;
    private disposed;
    private state;
    /**
     * `client` and `providerId` bind the OpenCode 1 token refresh. When
     * `dependencies` is given, its logger and refresher are used instead and
     * the client is never called.
     */
    constructor(client: PluginClient | null, providerId: string, config?: Partial<ProactiveRefreshConfig>, dependencies?: ProactiveRefreshDependencies);
    /**
     * Set the account manager to use for refresh operations.
     * Must be called before start().
     */
    setAccountManager(manager: RefreshQueueAccountView): void;
    /**
     * Check if a token needs proactive refresh.
     * Returns true if the token expires within the buffer period.
     */
    needsRefresh(account: ManagedAccount): boolean;
    /**
     * Check if a token is already expired.
     */
    isExpired(account: ManagedAccount): boolean;
    /**
     * Get all accounts that need proactive refresh.
     */
    getAccountsNeedingRefresh(): ManagedAccount[];
    /**
     * Perform a single refresh check iteration.
     * This is called periodically by the background interval.
     */
    private runRefreshCheck;
    private performRefreshCheck;
    /**
     * Refresh a single token.
     */
    private refreshToken;
    /**
     * Start the background refresh queue.
     */
    start(): void;
    /**
     * Stop the background refresh queue.
     */
    stop(): void;
    dispose(): Promise<void>;
    /**
     * Get current queue statistics.
     */
    getStats(): {
        isRunning: boolean;
        isRefreshing: boolean;
        lastCheckTime: number;
        lastRefreshTime: number;
        refreshCount: number;
        errorCount: number;
    };
    /**
     * Check if the queue is currently running.
     */
    isRunning(): boolean;
}
/**
 * Create a proactive refresh queue instance.
 */
export declare function createProactiveRefreshQueue(client: PluginClient, providerId: string, config?: Partial<ProactiveRefreshConfig>): ProactiveRefreshQueue;
/**
 * Create one location's refresh queue. The location supplies its logger and
 * token refresher; nothing is read from the OpenCode 1 host client or the
 * module logger.
 */
export declare function createLocationProactiveRefreshQueue(dependencies: ProactiveRefreshDependencies, config?: Partial<ProactiveRefreshConfig>): ProactiveRefreshQueue;
//# sourceMappingURL=refresh-queue.d.ts.map