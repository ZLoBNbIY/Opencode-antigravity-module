/**
 * One server location's runtime. A location is one workspace directory the
 * host serves; on OpenCode 2 (the 2.x host line) one process can serve
 * several, and each plugin setup there (an activation) gets its own
 * runtime. This module builds the activation's services in order, tears them
 * down in a fixed order and rolls everything back if construction fails.
 *
 * Every service here is created for this location alone: logger,
 * configuration (its own clone of the defaults), debug file, the switch for
 * dumping Gemini requests to disk, operator settings handle, signature-cache
 * handle, quota manager, background quota poller and the queue that
 * refreshes OAuth tokens before they expire. Nothing falls back to the
 * module-level logger, configuration, health tracker or sidebar file that
 * the OpenCode 1 plugin (one location per process) uses, and no credential
 * cache is shared between locations. Disposing one location's runtime never
 * stops another's.
 *
 * Process-shared state stays shared on purpose and is reached only through
 * per-location handles: operator files have one controller per file
 * (`acquireLocationOperatorSettings`), the signature disk cache has one
 * writer per file (`acquireLocationSignatureCache`). With the OpenCode 1
 * sidebar file as the quota snapshot store, background pollers in different
 * processes coordinate through it: a poll is skipped while the file's
 * `checkedAt` is recent, and a lock file beside it lets only one process
 * poll at a time. An OpenCode 2 location keeps its snapshots in memory and
 * writes no sidebar file.
 *
 * Teardown order:
 *   1. producers (everything that can still queue snapshot writes) are
 *      stopped and awaited, newest first: the refresh queue, the background
 *      poller and the quota manager, plus anything the host binding adds
 *      (request bridge, RPC handlers);
 *   2. queued snapshot writes drain;
 *   3. consumers close, newest first: signature handle, operator settings,
 *      debug file.
 * Stopping producers before the drain means no write can be queued after
 * the drain has finished; consumers stay open until the last write lands.
 *
 * The functions that use credentials (quota fetch, tier lookup, token
 * refresh) and the account view come from the location's account service.
 * This module never reads account storage or builds a host client.
 */
import type { AccountMetadataV3, FetchAccountQuota } from '@cortexkit/antigravity-auth-core';
import type { acquireFencedFileLock } from '@cortexkit/antigravity-auth-core/file-lock';
import { type SidebarMachineState } from '../../sidebar-state.js';
import { BackgroundQuotaRefresh, type PollerAccountView, type PollerSnapshotStore } from '../background-quota-refresh.js';
import { type LocationSignatureCache, type SignatureProcessState } from '../cache.js';
import { type LocationConfig } from '../config/index.js';
import { type LocationDebug } from '../debug.js';
import { type GeminiDumpState } from '../gemini-dump.js';
import { type LocationLogger } from '../logger.js';
import type { LocationLogSink } from '../neutral-types.js';
import { type LocationOperatorSettings, type OperatorSettingsRegistry } from '../operator-settings.js';
import { type QuotaManager } from '../quota.js';
import { type ProactiveRefreshQueue, type RefreshQueueAccountView, type RefreshQueueTokenRefresher } from '../refresh-queue.js';
/** Producers stop before drains; consumers close after drains. */
export type RuntimePhase = 'producer' | 'consumer';
export interface RuntimeResource {
    dispose(): Promise<void> | void;
}
/**
 * Resources acquired by one activation, released exactly once in phase
 * order. A resource added after disposal started is disposed at once, so a
 * slow acquisition that finishes late cannot outlive its activation.
 */
export interface RuntimeScope {
    add(resource: RuntimeResource, phase: RuntimePhase): void;
    /** A step run after every producer stopped and before any consumer. */
    addDrain(drain: () => Promise<void>): void;
    readonly disposed: boolean;
    /**
     * Release everything. Idempotent: later calls return the first call's
     * promise. Every step runs even when an earlier one fails; failures are
     * reported together afterwards as an `AggregateError`.
     */
    dispose(): Promise<void>;
}
export declare function createRuntimeScope(): RuntimeScope;
/**
 * Where a location's quota snapshots (redacted accounts plus `checkedAt` and
 * backoff) go. The background poller also reads `checkedAt` from it and
 * takes its cross-process lock on `pollLockPath`.
 */
export interface LocationQuotaSnapshots extends PollerSnapshotStore {
    /**
     * Wait until every queued quota snapshot write has landed. The runtime
     * calls it after all producers stopped and before any consumer closes.
     */
    drain(): Promise<void>;
}
/**
 * The OpenCode 1 sidebar file: snapshots merge into the file the TUI reads,
 * pollers in other processes see its `checkedAt`, and the poll lock sits
 * beside it.
 */
export declare function createSidebarFileQuotaSnapshots(stateFile: string): LocationQuotaSnapshots;
/**
 * An OpenCode 2 location's snapshots, kept in memory: no sidebar file is
 * written or read, and clients get the data through the native RPC
 * `state` method. Without `pollLockPath` the poller takes no cross-process
 * lock.
 */
export interface MemoryQuotaSnapshots extends LocationQuotaSnapshots {
    /** The newest snapshot, or `null` before the first refresh. */
    latest(): SidebarMachineState | null;
}
export declare function createMemoryQuotaSnapshots(options?: {
    readonly pollLockPath?: string | null;
}): MemoryQuotaSnapshots;
/**
 * The live account pool as the runtime's services use it: the background
 * poller's view plus the refresh queue's view. The core `AccountManager`
 * satisfies both.
 */
export type LocationAccountView = PollerAccountView & RefreshQueueAccountView;
export interface LocationRuntimeOptions {
    /** The host-owned location directory; never a caller-supplied path. */
    directory: string;
    /**
     * Host destination for this location's log records. Without one, records
     * reach only the environment-gated console fallback.
     */
    logSink?: LocationLogSink;
    /**
     * Where this location's quota snapshots go:
     * `createSidebarFileQuotaSnapshots` for the OpenCode 1 sidebar file, or
     * `createMemoryQuotaSnapshots` for an OpenCode 2 location, which keeps no
     * sidebar file.
     */
    quotaSnapshots: LocationQuotaSnapshots;
    /** Fetches one account's model quota with the location's credentials. */
    fetchAccountQuota: FetchAccountQuota;
    /**
     * Refreshes one account's OAuth token. The refresh queue calls it for
     * tokens close to expiry, so requests rarely wait on a refresh.
     */
    refreshToken: RefreshQueueTokenRefresher;
    /** Check current enrollment before each background task; vault mode suppresses local work. */
    mayRun?: () => boolean | Promise<boolean>;
    /**
     * Best-effort plan tier lookup. The background poller refreshes quota for
     * all accounts on a timer and also records each account's plan tier for
     * the sidebar.
     */
    loadAccountTier?: (account: AccountMetadataV3) => Promise<{
        id: string;
        paidId?: string;
        capturedAt: number;
    } | null>;
    /**
     * Health score (0–100, how reliably the account has answered recently) per
     * account index, from this location's account rotation. Without one,
     * sidebar snapshots carry no score.
     */
    healthScore?: (index: number) => number;
    /**
     * Derives a short hash from an account's refresh token. Each cached quota
     * entry is stamped with it, so a cached reading is dropped when a
     * different account now sits at the same position.
     */
    quotaAccountIdentity?: (refreshToken: string) => string;
    /**
     * Table of operator-settings file controllers. Defaults to the one the
     * whole process shares; tests pass an isolated one.
     */
    operatorSettingsRegistry?: OperatorSettingsRegistry;
    /**
     * Thinking-signature cache state. Defaults to the one the whole process
     * shares; tests pass an isolated one.
     */
    signatureState?: SignatureProcessState;
    /** Clock and randomness for the poller; defaults to the system's. */
    now?: () => number;
    random?: () => number;
    /** Replaces the poller's lock acquisition so tests are deterministic. */
    acquireLock?: typeof acquireFencedFileLock;
}
export interface LocationRuntime {
    readonly directory: string;
    readonly logger: LocationLogger;
    readonly config: LocationConfig;
    readonly debug: LocationDebug;
    readonly dump: GeminiDumpState;
    readonly operatorSettings: LocationOperatorSettings;
    readonly signatures: LocationSignatureCache;
    readonly quotaManager: QuotaManager;
    /** `null` when the `background_quota_refresh` config option is off. */
    readonly backgroundQuotaRefresh: BackgroundQuotaRefresh | null;
    /**
     * The current token refresh queue, or `null` when no account view is
     * bound or the `proactive_token_refresh` config option is off.
     */
    refreshQueue(): ProactiveRefreshQueue | null;
    /** The location's current account view, or `null` before one is bound. */
    accounts(): LocationAccountView | null;
    /**
     * Replace the location's account view. The previous refresh queue is
     * stopped and awaited before a new one starts for the new view. After
     * disposal the call does nothing.
     */
    replaceAccounts(view: LocationAccountView | null): Promise<void>;
    /** Apply the operator-configured log level to this location's logger. */
    applyOperatorSettings(): void;
    /**
     * The host binding registers its own resources here, as producers or
     * consumers, so one dispose tears everything down in order.
     */
    readonly scope: RuntimeScope;
    dispose(): Promise<void>;
}
/**
 * Build one location's runtime. If any step throws, everything acquired so
 * far is released before the error is rethrown, so a failed activation
 * leaves no timer, file handle or shared-controller reference behind.
 */
export declare function createLocationRuntime(options: LocationRuntimeOptions, accountResources?: RuntimeResource): Promise<LocationRuntime>;
//# sourceMappingURL=runtime.d.ts.map