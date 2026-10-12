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
import { VAULT_ACCOUNT_REMEDY } from '@cortexkit/antigravity-auth-core';
import { drainSidebarWrites, toCapturedTier, } from "../../sidebar-state.js";
import { BackgroundQuotaRefresh, createSidebarFileSnapshotStore, } from "../background-quota-refresh.js";
import { acquireLocationSignatureCache, } from "../cache.js";
import { createLocationConfig } from "../config/index.js";
import { createLocationDebug } from "../debug.js";
import { createGeminiDumpState } from "../gemini-dump.js";
import { createLocationLogger } from "../logger.js";
import { acquireLocationOperatorSettings, } from "../operator-settings.js";
import { createLocationQuotaManager, } from "../quota.js";
import { createLocationProactiveRefreshQueue, } from "../refresh-queue.js";
export function createRuntimeScope() {
    const producers = [];
    const consumers = [];
    const drains = [];
    let disposal = null;
    const lateDisposals = new Set();
    const run = async (step, errors) => {
        try {
            await step();
        }
        catch (error) {
            errors.push(error);
        }
    };
    return {
        add(resource, phase) {
            if (disposal) {
                const late = Promise.resolve()
                    .then(() => resource.dispose())
                    .catch(() => {
                    // The scope already reported its result; a late resource's
                    // failure has no caller left to receive it.
                });
                lateDisposals.add(late);
                void late.finally(() => lateDisposals.delete(late));
                return;
            }
            ;
            (phase === 'producer' ? producers : consumers).push(resource);
        },
        addDrain(drain) {
            if (disposal)
                return;
            drains.push(drain);
        },
        get disposed() {
            return disposal !== null;
        },
        dispose() {
            if (!disposal) {
                disposal = (async () => {
                    const errors = [];
                    for (const resource of producers.splice(0).reverse()) {
                        await run(() => resource.dispose(), errors);
                    }
                    for (const drain of drains.splice(0)) {
                        await run(drain, errors);
                    }
                    for (const resource of consumers.splice(0).reverse()) {
                        await run(() => resource.dispose(), errors);
                    }
                    await Promise.allSettled([...lateDisposals]);
                    if (errors.length > 0) {
                        throw new AggregateError(errors, 'Location runtime disposal failed');
                    }
                })();
            }
            return disposal;
        },
    };
}
/**
 * The OpenCode 1 sidebar file: snapshots merge into the file the TUI reads,
 * pollers in other processes see its `checkedAt`, and the poll lock sits
 * beside it.
 */
export function createSidebarFileQuotaSnapshots(stateFile) {
    return {
        ...createSidebarFileSnapshotStore(stateFile),
        drain: () => drainSidebarWrites(),
    };
}
export function createMemoryQuotaSnapshots(options = {}) {
    let latest = null;
    return {
        latest: () => latest,
        lastCheckedAt: () => latest?.checkedAt ?? 0,
        write: async (state) => {
            // Snapshots are built from the live account view, so the newest one
            // replaces the previous one whole.
            latest = state;
        },
        pollLockPath: options.pollLockPath ?? null,
        drain: async () => { },
    };
}
/**
 * Build one location's runtime. If any step throws, everything acquired so
 * far is released before the error is rethrown, so a failed activation
 * leaves no timer, file handle or shared-controller reference behind.
 */
export async function createLocationRuntime(options, accountResources) {
    const scope = createRuntimeScope();
    // Keep account managers and repositories open until quota and token-refresh
    // producers finish their pending writes.
    if (accountResources)
        scope.add(accountResources, 'producer');
    try {
        return await buildLocationRuntime(options, scope);
    }
    catch (error) {
        await scope.dispose().catch(() => {
            // The construction error is the one the caller needs; disposal
            // failures during rollback cannot replace it.
        });
        throw error;
    }
}
async function buildLocationRuntime(options, scope) {
    if (typeof options?.directory !== 'string' || options.directory === '') {
        throw new TypeError('createLocationRuntime requires the location directory');
    }
    if (typeof options.quotaSnapshots?.write !== 'function' ||
        typeof options.quotaSnapshots.drain !== 'function') {
        throw new TypeError('createLocationRuntime requires a quota snapshot store');
    }
    if (typeof options.refreshToken !== 'function') {
        throw new TypeError('createLocationRuntime requires a refreshToken function');
    }
    // The logger's host-sink policy reads this location's debug_tui flag,
    // which is known only after the configuration loads with that logger.
    let config;
    const logger = createLocationLogger({
        sink: options.logSink,
        sinkEnabled: () => config?.config.debug_tui === true,
    });
    const log = logger.createLogger('runtime');
    config = createLocationConfig(options.directory, {
        logger: logger.createLogger('config'),
    });
    const debug = createLocationDebug(config.config);
    scope.add({ dispose: () => debug.close() }, 'consumer');
    const operatorSettings = acquireLocationOperatorSettings({
        projectConfigPath: config.projectConfigPath,
        userConfigPath: config.userConfigPath,
        ...(options.operatorSettingsRegistry
            ? { registry: options.operatorSettingsRegistry }
            : {}),
    });
    scope.add(operatorSettings, 'consumer');
    const applyOperatorSettings = () => {
        logger.setLevel(operatorSettings.get().log_level);
    };
    applyOperatorSettings();
    const signatureOptions = {
        keepThinking: config.keepThinking,
        signatureCache: config.config.signature_cache,
    };
    const signatures = options.signatureState
        ? options.signatureState.acquireLocation(signatureOptions)
        : acquireLocationSignatureCache(signatureOptions);
    scope.add(signatures, 'consumer');
    const dump = createGeminiDumpState();
    let accounts = null;
    const identity = options.quotaAccountIdentity;
    const sidebarAccounts = () => {
        const view = accounts;
        if (!view)
            return null;
        return view.getAccounts().map((entry) => ({
            index: entry.index,
            label: entry.label,
            enabled: entry.enabled,
            coolingDownUntil: entry.coolingDownUntil,
            cachedQuota: entry.cachedQuota,
            cachedQuotaAccountId: entry.cachedQuotaAccountId,
            ...(identity
                ? { currentQuotaAccountId: identity(entry.parts.refreshToken) }
                : {}),
            tier: toCapturedTier(entry),
        }));
    };
    const quotaManager = createLocationQuotaManager({
        logger: logger.createLogger('quota'),
        fetchAccountQuota: options.mayRun
            ? async (account, signal) => {
                if (!(await options.mayRun?.()))
                    throw new Error(VAULT_ACCOUNT_REMEDY);
                return options.fetchAccountQuota(account, signal);
            }
            : options.fetchAccountQuota,
        sidebar: {
            write: async (state) => {
                if (options.mayRun && !(await options.mayRun()))
                    return;
                await options.quotaSnapshots.write(state);
            },
            getAccounts: sidebarAccounts,
            getActiveIndexByFamily: () => accounts?.getActiveIndexByFamily() ?? null,
            ...(options.healthScore ? { healthScore: options.healthScore } : {}),
            ...(options.now ? { now: options.now } : {}),
        },
    });
    // Producer: refreshes enqueue snapshot writes, so the manager must stop
    // before the drain asserts the queue is empty.
    scope.add(quotaManager, 'producer');
    let backgroundQuotaRefresh = null;
    if (config.config.background_quota_refresh) {
        backgroundQuotaRefresh = new BackgroundQuotaRefresh({
            intervalMs: config.config.background_quota_refresh_interval_minutes * 60_000,
            snapshots: options.quotaSnapshots,
            getAccountManager: () => accounts,
            ...(options.mayRun
                ? { mayRun: async () => Boolean(await options.mayRun?.()) }
                : {}),
            quotaManager,
            ...(options.loadAccountTier
                ? { loadAccountTier: options.loadAccountTier }
                : {}),
            ...(options.now ? { now: options.now } : {}),
            ...(options.random ? { random: options.random } : {}),
            ...(options.acquireLock ? { acquireLock: options.acquireLock } : {}),
            healthScore: options.healthScore ?? null,
            logger: logger.createLogger('background-quota'),
        });
        const poller = backgroundQuotaRefresh;
        scope.add({ dispose: () => poller.dispose() }, 'producer');
    }
    // The refresh queue follows the account view. It is registered last among
    // producers, so it stops first: no token refresh can start while the quota
    // manager and poller are shutting down.
    let refreshQueue = null;
    let accountChange = Promise.resolve();
    const stopRefreshQueue = async () => {
        const queue = refreshQueue;
        refreshQueue = null;
        await queue?.dispose();
    };
    scope.add({
        dispose: async () => {
            // Let an in-progress account swap finish before stopping its queue.
            await accountChange;
            accounts = null;
            await stopRefreshQueue();
        },
    }, 'producer');
    scope.addDrain(() => options.quotaSnapshots.drain());
    const replaceAccounts = (view) => {
        const next = accountChange.then(async () => {
            if (scope.disposed)
                return;
            await stopRefreshQueue();
            if (scope.disposed)
                return;
            accounts = view;
            if (!view || !config?.config.proactive_token_refresh)
                return;
            const queue = createLocationProactiveRefreshQueue({
                logger: logger.createLogger('refresh-queue'),
                refreshToken: options.refreshToken,
            }, {
                enabled: true,
                ...(options.mayRun
                    ? { mayRun: async () => Boolean(await options.mayRun?.()) }
                    : {}),
                bufferSeconds: config.config.proactive_refresh_buffer_seconds,
                checkIntervalSeconds: config.config.proactive_refresh_check_interval_seconds,
            });
            queue.setAccountManager(view);
            refreshQueue = queue;
            queue.start();
        });
        accountChange = next.catch((error) => {
            log.warn('account view replacement failed', {
                error: error instanceof Error ? error.message : String(error),
            });
        });
        return next;
    };
    // Timers start only after every acquisition succeeded, so a failed build
    // never leaves a scheduled tick behind.
    backgroundQuotaRefresh?.start();
    const runtimeConfig = config;
    return {
        directory: options.directory,
        logger,
        config: runtimeConfig,
        debug,
        dump,
        operatorSettings,
        signatures,
        quotaManager,
        backgroundQuotaRefresh,
        refreshQueue: () => refreshQueue,
        accounts: () => accounts,
        replaceAccounts,
        applyOperatorSettings,
        scope,
        dispose: () => scope.dispose(),
    };
}
//# sourceMappingURL=runtime.js.map