import { fetchWithAgyCliTransport, } from '@cortexkit/antigravity-auth-core';
import { upsertSidebarActiveRouting } from '../sidebar-state';
import { extractAccountAccessErrorDetails } from './account-access';
import { createLocalAccountCredentials, StaleAccountGrantError, } from './accounts';
import { isOAuthAuth } from './auth';
import * as moduleDebug from './debug';
import { dumpGeminiRequest } from './gemini-dump';
import { createLogger } from './logger';
import { ensureProjectContext } from './project';
import { buildThinkingWarmupBody, getImageModelLocalTitle, getLastCacheStats, isGenerativeLanguageRequest, prepareAntigravityRequest, transformAntigravityResponse, } from './request';
import { createLocalQuotaRefresh, createRequestExecutor, } from './shared/request-services';
import { createVaultAccountPool, } from './shared/vault-request-credentials';
import { AntigravityTokenRefreshError, refreshAccessToken } from './token';
const log = createLogger('fetch-interceptor');
/** Production transport — used when the interceptor context omits one. */
const defaultAgyTransport = (url, init, options) => fetchWithAgyCliTransport(url, init, options);
/** Default `fetchImpl` used when the interceptor context omits one. */
const defaultFetchImpl = (input, init) => globalThis.fetch(input, init);
/**
 * A pool-file account: the selected account's stored OAuth record is
 * refreshed through the host's OAuth refresh, and a grant is sent only while
 * that account is still in the pool, enabled and still holds the token.
 */
function poolFileCredentials(accountManager, client, providerId) {
    return {
        refresh: (account) => refreshAccessToken(accountManager.toAuthDetails(account), client, providerId),
        // A pool-file row has no repository identity; its grant is checked
        // against the pool itself.
        captureGrant: ({ account, accessToken }) => ({
            source: 'pool-file',
            check() {
                if (!accountManager.getAccounts().includes(account) ||
                    account.enabled === false ||
                    accountManager.toAuthDetails(account).access !== accessToken) {
                    throw new StaleAccountGrantError();
                }
            },
        }),
        ensureProject: (auth) => ensureProjectContext(auth),
        isInvalidGrant: (error) => error instanceof AntigravityTokenRefreshError &&
            error.code === 'invalid_grant',
    };
}
/**
 * An account-store account: refresh, grant check and invalid-grant
 * recognition are the store adapter's own (`createLocalAccountCredentials`
 * over the manager's repository), so a token is refreshed only through the
 * repository on the selected account's row reference and never through the
 * host client. The row reference is captured when the grant is resolved;
 * every send is checked against that exact row, never against whatever the
 * account object holds later, and a grant without one is never sent.
 */
function storeCredentials(accountManager, repository) {
    const credentials = createLocalAccountCredentials(accountManager, {
        repository,
    });
    return {
        refresh: (account) => credentials.refresh(account),
        captureGrant: (grant) => credentials.captureGrant(grant),
        ensureProject: (auth) => credentials.ensureProject(auth),
        isInvalidGrant: (error) => credentials.isInvalidGrant(error),
    };
}
/**
 * The engine collaborators every OpenCode 1 interceptor shares, whatever
 * holds its accounts: wire functions, the module-level debug, dump and
 * logger bindings, host toasts and the sidebar routing file.
 */
function openCode1EngineCollaborators(common) {
    const { client } = common;
    return {
        config: common.config,
        sessions: common.agySessionRegistry,
        operatorSettings: common.operatorSettings,
        transport: common.transport,
        fetchImpl: common.fetchImpl,
        wire: {
            prepare: prepareAntigravityRequest,
            transformResponse: transformAntigravityResponse,
            buildThinkingWarmupBody,
            getImageModelLocalTitle,
            getLastCacheStats,
        },
        // OpenCode 1's module-level debug namespace provides the debug methods
        // the engine calls.
        debug: moduleDebug,
        dump: { dumpRequest: dumpGeminiRequest },
        logger: log,
        classifyAccessError: extractAccountAccessErrorDetails,
        notify: (message, variant) => client.tui.showToast({ body: { message, variant } }),
        onRouting: common.onRouting ??
            ((sessionId, entry) => {
                void upsertSidebarActiveRouting(sessionId, entry, {
                    authoritative: true,
                }).catch((error) => {
                    log.debug('sidebar-routing-upsert-failed', {
                        sessionId,
                        error: String(error),
                    });
                });
            }),
    };
}
/**
 * OpenCode 1 binding of the shared request engine for accounts this plugin
 * holds itself (pool file or account store). The retry, rotation and
 * quota-fallback pipeline lives in `createRequestExecutor`; this wrapper
 * decides which requests reach it and binds the account manager, its
 * source's credential operations and OpenCode 1's collaborators.
 */
export function createFetchInterceptor(context) {
    const { client, providerId, accountManager, accountSource, quotaManager, getAuth, agyTransport = defaultAgyTransport, fetchImpl = defaultFetchImpl,
    // directory is part of the contract but not consumed by this interceptor;
    // callers use it when constructing sibling services (e.g. project context).
     } = context;
    void context.directory;
    // Capture the host fetch at factory time so the interceptor never shadows
    // it with its own (recursive) fetch binding. Production wires this up via
    // the OpenCode plugin runtime; tests inject a mock by stubbing globalThis
    // OR — preferred for e2e — pass `fetchImpl` through the context so the
    // stub survives a process-wide fetch replacement.
    const upstreamFetch = fetchImpl;
    const refreshQuotaAfterSuccess = createLocalQuotaRefresh(accountManager, quotaManager, log);
    const executor = createRequestExecutor({
        assertAdmission: context.assertAdmission,
        ...openCode1EngineCollaborators({
            ...context,
            transport: agyTransport,
            fetchImpl: upstreamFetch,
        }),
        accounts: accountManager,
        credentials: {
            domain: 'local',
            toAuthDetails: (account) => accountManager.toAuthDetails(account),
            updateFromAuth: (account, auth) => accountManager.updateFromAuth(account, auth),
            removeAccount: (account) => accountManager.removeAccount(account),
            saveToDisk: () => accountManager.saveToDisk(),
            saveToDiskReplace: () => accountManager.saveToDiskReplace(),
            ...(accountSource.kind === 'store'
                ? storeCredentials(accountManager, accountSource.repository)
                : poolFileCredentials(accountManager, client, providerId)),
            clearStoredAuth: async () => {
                await context.assertAdmission?.();
                await client.auth.set({
                    path: { id: providerId },
                    body: { type: 'oauth', refresh: '', access: '', expires: 0 },
                });
            },
            refreshQuotaAfterSuccess: async (account, intervalMinutes) => {
                await context.assertAdmission?.();
                await refreshQuotaAfterSuccess(account, intervalMinutes);
            },
        },
        // The trackers the manager selects with: its own for a store-backed
        // manager, the process-wide ones for the pool-file manager.
        trackers: {
            get health() {
                return accountManager.healthTracker;
            },
            get token() {
                return accountManager.tokenTracker;
            },
        },
    });
    let disposed = false;
    let disposePromise;
    let retired = false;
    let retirePromise;
    // Requests that entered `fetch` but have not yet reached the executor
    // (they wait on admission or the host sign-in). Retirement waits for them
    // so the executor admits them before it stops admitting; disposal waits
    // for them so none resumes after it reports done.
    const entering = new Set();
    async function intercept(input, init) {
        await context.assertAdmission?.();
        // Disposal may have begun during the admission read; nothing more is
        // read or sent for this request.
        if (disposed)
            throw new Error('The local request runtime is disposed');
        if (accountSource.kind === 'pool-file') {
            const latestAuth = await getAuth();
            if (disposed)
                throw new Error('The local request runtime is disposed');
            if (!isOAuthAuth(latestAuth))
                return upstreamFetch(input, init);
        }
        return executor.execute(input, init);
    }
    async function fetch(input, init) {
        if (disposed) {
            // After dispose we deliberately stop intercepting so an in-flight call
            // can still resolve without throwing. The plugin tear-down order may
            // race with a final inflight fetch.
            return upstreamFetch(input, init);
        }
        if (!isGenerativeLanguageRequest(input)) {
            return upstreamFetch(input, init);
        }
        // A retired interceptor has been replaced; a request reaching it now is
        // refused rather than sent without this plugin's credentials.
        if (retired)
            throw new Error('The local request runtime is retired');
        const pending = intercept(input, init);
        entering.add(pending);
        void pending.then(() => entering.delete(pending), () => entering.delete(pending));
        return pending;
    }
    function retire() {
        retired = true;
        retirePromise ??= (async () => {
            while (entering.size > 0)
                await Promise.allSettled([...entering]);
            await executor.retire();
        })();
        return retirePromise;
    }
    function dispose() {
        disposed = true;
        disposePromise ??= (async () => {
            await executor.dispose();
            // Requests still reading their admission or the host sign-in stop at
            // their next check; disposal reports done only once they have.
            while (entering.size > 0)
                await Promise.allSettled([...entering]);
            // A retirement still waiting on those requests settles with them.
            await retirePromise;
        })();
        return disposePromise;
    }
    return { fetch, retire, dispose };
}
/**
 * OpenCode 1 binding of the shared request engine for vault-held accounts.
 * Selection runs on an `AccountSelector` over the vault's selectable routes
 * (metadata rows, no credential). Every physical send takes a fresh receipt
 * for the selected route through `createVaultRequestCredentials`: its token
 * and project serve that one send, and a 401 is reported against it.
 * Nothing is refreshed locally, cached or copied from the host's own Google
 * sign-in, which is why no host auth is read here.
 */
export function createVaultFetchInterceptor(context) {
    const { source, agyTransport = defaultAgyTransport, fetchImpl = defaultFetchImpl, } = context;
    const upstreamFetch = fetchImpl;
    const pool = context.pool ?? createVaultAccountPool({ source });
    const selector = pool.selector;
    const executor = createRequestExecutor({
        assertAdmission: context.assertAdmission,
        ...openCode1EngineCollaborators({
            ...context,
            transport: agyTransport,
            fetchImpl: upstreamFetch,
        }),
        accounts: selector,
        credentials: pool.credentials,
        trackers: {
            health: selector.healthTracker,
            token: selector.tokenTracker,
        },
    });
    let disposed = false;
    let disposePromise;
    async function fetch(input, init) {
        if (!isGenerativeLanguageRequest(input))
            return upstreamFetch(input, init);
        if (disposed)
            throw new Error('The vault request runtime is disposed');
        await pool.sync();
        return executor.execute(input, init);
    }
    function dispose() {
        disposed = true;
        disposePromise ??= (async () => {
            await executor.dispose();
            await pool.flush();
        })();
        return disposePromise;
    }
    return { fetch, dispose };
}
//# sourceMappingURL=fetch-interceptor.js.map