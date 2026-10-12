import type { AccountManager } from './accounts';
import type { ProactiveRefreshQueue } from './refresh-queue';
export interface Disposable {
    dispose(): Promise<void> | void;
}
/**
 * Lifecycle phase for a registered disposable.
 *
 * - `producer`: runs on the same side of the sidebar drain as the
 *   fetch interceptor — the lifecycle disposes producers BEFORE the
 *   sidebar drain so a producer racing with shutdown cannot enqueue
 *   a write that lands after the drain asserts the queue is empty.
 * - `consumer`: runs AFTER the sidebar drain. These are the sinks
 *   (RPC server, file logger) that the TUI / host talk to and that
 *   must stay alive until every queued write has landed.
 */
export type LifecyclePhase = 'producer' | 'consumer';
export interface PluginLifecycleOptions {
    sessionRegistry: {
        clear(): void;
    };
    shutdownDiskSignatureCache: () => Promise<void>;
    clearFetchState: () => void;
    /**
     * Optional drain hook for in-flight sidebar-state writes. Lifecycle
     * awaits this AFTER producers are disposed but BEFORE consumers are
     * disposed, so:
     *   1. producers have stopped (no new writes can land)
     *   2. every queued write has flushed
     *   3. the file logger + RPC server are still alive
     */
    drainSidebarWrites?: () => Promise<void>;
}
/**
 * The request runtime serving an account manager. When its manager is
 * replaced it is retired: it refuses new requests and keeps the ones it
 * already admitted, so the manager they use stays open until they finish.
 */
export interface AccountRequestRuntime {
    /** Refuses new requests; resolves once admitted requests have finished. */
    retire(): Promise<void>;
    /** Aborts admitted requests; resolves once they have finished. */
    dispose(): Promise<void> | void;
}
export interface PluginLifecycle extends Disposable {
    getAccountManager(): AccountManager | null;
    /** True from the start of final shutdown, before any disposal hook runs. */
    isClosing(): boolean;
    /**
     * Publishes `manager` as the account manager and `requests` as the runtime
     * serving it. The previous refresh queue stops at once, and the
     * replacement waits for a refresh it already has under way. When the
     * previous manager had no request runtime it is then disposed before the
     * replacement is published; otherwise that runtime is retired and the
     * manager is disposed only after both the refresh and the retirement have
     * finished. Final disposal aborts and awaits such a retirement. Resolves
     * `false`, disposing everything offered, once the lifecycle is disposing.
     */
    replaceAccountRuntime(manager: AccountManager, refreshQueue: ProactiveRefreshQueue | null, requests?: AccountRequestRuntime | null): Promise<boolean>;
    register(disposable: Disposable, phase?: LifecyclePhase): void;
}
export declare function createPluginLifecycle(options: PluginLifecycleOptions): PluginLifecycle;
//# sourceMappingURL=lifecycle.d.ts.map