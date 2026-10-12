/**
 * OpenCode adapter for the harness-agnostic quota manager.
 *
 * Re-exports the core `QuotaManager` types and helpers so call sites in
 * `plugin.ts` and other modules don't need to switch imports. Also wires up
 * the host-specific fetch callback that handles:
 *   1. Token refresh via the existing `refreshAccessToken` path.
 *   2. Persisting rotated refresh tokens via `client.auth.set` (matching
 *      legacy behavior).
 *   3. Resolving project context via `ensureProjectContext`.
 *
 * The legacy `checkAccountsQuota(accounts, client, providerId)` export is
 * retained as a compatibility wrapper that creates a short-lived manager
 * with `force: true` — manual quota screens must always refresh, even if
 * the background manager has backed off.
 */
import { aggregateGeminiCliQuota, aggregateQuota, aggregateQuotaSummary, createQuotaManager, defaultKeyOf, fetchAvailableModels, fetchGeminiCliQuota, fetchQuotaSummary, fetchWithActiveTimeout, getHealthTracker, rowRefKey, sameRowRef, VAULT_ACCOUNT_REMEDY, } from '@cortexkit/antigravity-auth-core';
import { ANTIGRAVITY_ENDPOINT_FALLBACKS, ANTIGRAVITY_PROVIDER_ID, buildGeminiCliUserAgent, } from '../constants';
import { buildSidebarMachineStateFromAccounts, isAccountCurrent, setSidebarMachineState, } from '../sidebar-state';
import { createLocalAccountCredentials, } from './accounts';
import { accessTokenExpired, formatRefreshParts, parseRefreshParts, } from './auth';
import { logQuotaFetch, logQuotaStatus } from './debug';
import { buildAntigravityHarnessUserAgent } from './fingerprint';
import { createLogger } from './logger';
import { ensureProjectContext, loadManagedProject } from './project';
import { refreshAccessToken } from './token';
// Re-export the public surface so existing imports from `./quota` keep working.
const log = createLogger('quota');
export { classifyQuotaGroup, createQuotaManager, defaultKeyOf, } from '@cortexkit/antigravity-auth-core';
/**
 * Build an OpenCode-wired quota manager.
 *
 * The returned manager owns its cache, in-flight dedupe, and backoff state.
 * Register its `dispose()` with `PluginLifecycle` so refreshes abort on plugin
 * shutdown.
 *
 * The wrapper observes `refreshAccount` / `refreshAccounts` and pushes a
 * redacted sidebar snapshot after every refresh (success or backoff) so
 * the TUI's next poll renders the freshest cached quota. The snapshot is
 * sourced from the live AccountManager view (`getAccountsForSidebar`) so
 * it carries the just-updated percentages; before bootstrapping it is a
 * no-op.
 */
export function createOpenCodeQuotaManager(client, providerId = ANTIGRAVITY_PROVIDER_ID, options = {}) {
    const fetchPoolFileQuota = makeFetchAccountQuota(client, providerId, options.fetchVia);
    const fetchAccountQuota = async (account, request) => {
        const target = account;
        const ref = target.rowRef;
        if (options.mayRun && !(await options.mayRun()))
            throw new Error(VAULT_ACCOUNT_REMEDY);
        if (ref !== undefined) {
            if (!options.fetchStoreAccountQuota)
                throw new Error('Store quota authorization is unavailable');
            const captured = { ...target, rowRef: ref };
            return options.fetchStoreAccountQuota(captured, request);
        }
        return fetchPoolFileQuota(account, request);
    };
    const manager = createQuotaManager({
        fetchAccountQuota,
        keyOf: options.keyOf ?? defaultKeyOf,
        baseBackoffMs: options.baseBackoffMs,
        maxBackoffMs: options.maxBackoffMs,
        fetchTimeoutMs: options.fetchTimeoutMs,
    });
    const getAccountsForSidebar = options.getAccountsForSidebar;
    const getActiveIndexByFamily = options.getActiveIndexByFamily;
    return withSidebarPushAfterRefresh(manager, options.publishSidebar ??
        (getAccountsForSidebar
            ? (account) => pushSidebarQuotaSnapshot(getAccountsForSidebar, manager.getBackoffUntil(account), getActiveIndexByFamily)
            : undefined));
}
/**
 * Build one location's quota manager. Backoff, in-flight dedupe and the
 * per-account cache belong to the returned manager alone, so a second
 * location never shares another location's backoff or cached results.
 * Refreshes push a sidebar snapshot exactly like `createOpenCodeQuotaManager`
 * does, but to the location's own state file and through its own logger.
 */
export function createLocationQuotaManager(options) {
    if (typeof options?.logger?.debug !== 'function') {
        throw new TypeError('createLocationQuotaManager requires a location logger');
    }
    if (typeof options.fetchAccountQuota !== 'function') {
        throw new TypeError('createLocationQuotaManager requires a fetchAccountQuota function');
    }
    const manager = createQuotaManager({
        fetchAccountQuota: options.fetchAccountQuota,
        keyOf: options.keyOf ?? defaultKeyOf,
        baseBackoffMs: options.baseBackoffMs,
        maxBackoffMs: options.maxBackoffMs,
        fetchTimeoutMs: options.fetchTimeoutMs,
    });
    const sidebar = options.sidebar;
    const logger = options.logger;
    return withSidebarPushAfterRefresh(manager, sidebar
        ? (account) => pushSidebarQuotaSnapshot(sidebar.getAccounts, manager.getBackoffUntil(account), sidebar.getActiveIndexByFamily, {
            write: sidebar.write,
            logger,
            healthScore: sidebar.healthScore ?? null,
            now: sidebar.now,
        })
        : undefined);
}
/**
 * Wrap a quota manager so every refresh started before disposal pushes one
 * sidebar snapshot after it settles, and so `dispose()` waits for those
 * pushes. A refresh that starts after disposal pushes nothing.
 */
function withSidebarPushAfterRefresh(manager, push) {
    const originalRefreshAccount = manager.refreshAccount;
    const originalRefreshAccounts = manager.refreshAccounts;
    let disposed = false;
    const inFlight = new Set();
    const pushAfterRefresh = async (account) => {
        if (!push)
            return;
        await push(account).catch(() => {
            // Sidebar persistence remains best-effort when lock contention
            // outlives its retry budget.
        });
    };
    const track = (operation) => {
        inFlight.add(operation);
        void operation.then(() => inFlight.delete(operation), () => inFlight.delete(operation));
        return operation;
    };
    const dispose = async () => {
        if (disposed)
            return;
        disposed = true;
        await manager.dispose();
        await Promise.allSettled(inFlight);
    };
    return {
        ...manager,
        async refreshAccount(account, refreshOptions) {
            const shouldPush = !disposed;
            return track((async () => {
                const result = await originalRefreshAccount(account, refreshOptions);
                if (shouldPush)
                    await pushAfterRefresh(account);
                return result;
            })());
        },
        async refreshAccounts(accounts, refreshOptions) {
            const shouldPush = !disposed;
            return track((async () => {
                const results = await originalRefreshAccounts(accounts, refreshOptions);
                // Push one snapshot per batch — the AccountManager's view is updated
                // by the caller (oauth-methods / fetch-interceptor) BEFORE we read
                // here, so a single post-batch snapshot captures the full diff.
                const lastAccount = accounts[accounts.length - 1];
                if (shouldPush && lastAccount)
                    await pushAfterRefresh(lastAccount);
                return results;
            })());
        },
        dispose,
    };
}
/**
 * Compatibility wrapper used by code paths that want a one-shot check across
 * the full account pool with no shared cache.
 *
 * Equivalent to spinning up a short-lived manager with `force: true` so
 * manual quota dialogs always reflect the latest data even if the background
 * manager has backed off.
 */
export async function checkAccountsQuotaWith(accounts, fetchAccountQuota) {
    const manager = createQuotaManager({
        fetchAccountQuota,
        keyOf: defaultKeyOf,
    });
    try {
        return await manager.refreshAccounts(accounts, {
            indexFor: (account) => accounts.indexOf(account),
            force: true,
        });
    }
    finally {
        manager.dispose();
    }
}
export async function checkAccountsQuotaStandalone(accounts, options) {
    if (!options.refresh) {
        return accounts.map((account, index) => ({
            index,
            email: account.email,
            status: account.enabled === false ? 'disabled' : 'ok',
            disabled: account.enabled === false,
            quota: {
                groups: account.cachedQuota ?? {},
                modelCount: Object.keys(account.cachedQuota ?? {}).length,
            },
        }));
    }
    return checkAccountsQuotaWith(accounts, makeFetchAccountQuota(undefined, ANTIGRAVITY_PROVIDER_ID));
}
export async function checkAccountsQuota(accounts, client, providerId = ANTIGRAVITY_PROVIDER_ID) {
    return checkAccountsQuotaWith(accounts, makeFetchAccountQuota(client, providerId));
}
/**
 * Push a quota refresh into the sidebar. Called by every quota refresh
 * call site (manual `/antigravity-quota`, the `check` menu action, and the
 * background refresh in `fetch-interceptor`) AFTER the results have been
 * folded back into the AccountManager's cached quota. The function reads
 * the live account snapshot through `getAccounts` so the redacted entry
 * carries the just-refreshed percentages — not the previous tick's stale
 * numbers and not `undefined`.
 *
 * The mapping is deliberately tolerant: if `getAccounts` returns `null`
 * (e.g. before the plugin has finished bootstrapping) the call is a no-op.
 * On lock contention the error is logged-and-swallowed so a quota dialog
 * never fails just because the sidebar file is busy.
 */
export async function pushSidebarQuotaSnapshot(getAccounts, backoffUntil = 0, getActiveIndexByFamily, options = {}) {
    const accounts = getAccounts();
    if (!accounts || accounts.length === 0)
        return;
    const activeByFamily = getActiveIndexByFamily?.() ?? null;
    // `undefined` keeps the process-wide health tracker the OpenCode 1 plugin
    // uses; `null` means the caller has no health source and the sidebar shows
    // its default.
    const healthScore = options.healthScore === undefined
        ? (index) => getHealthTracker().getScore(index)
        : options.healthScore;
    const now = options.now ?? Date.now;
    const write = options.write ??
        ((state) => setSidebarMachineState(state, options.stateFile === undefined ? {} : { stateFile: options.stateFile }));
    try {
        await write(buildSidebarMachineStateFromAccounts(accounts.map((entry) => ({
            index: entry.index,
            label: entry.label,
            enabled: entry.enabled,
            current: activeByFamily
                ? isAccountCurrent(entry.index, activeByFamily)
                : false,
            coolingDownUntil: entry.coolingDownUntil,
            cachedQuota: entry.cachedQuota,
            cachedQuotaUpdatedAt: entry.cachedQuotaUpdatedAt,
            cachedQuotaAccountId: entry.cachedQuotaAccountId,
            currentQuotaAccountId: entry.currentQuotaAccountId,
            ...(healthScore ? { healthScore: healthScore(entry.index) } : {}),
            tier: entry.tier,
        })), {
            checkedAt: now(),
            quotaBackoffUntil: backoffUntil > 0 ? backoffUntil : undefined,
        }));
    }
    catch (error) {
        ;
        (options.logger ?? log).debug('sidebar-quota-write-failed', {
            error: String(error),
        });
    }
}
/**
 * Legacy fallback: fetchAvailableModels → aggregateQuota. Used when
 * `fetchQuotaSummary` rejects (network, 403, etc.). Extracted so the
 * concurrent fetch path can reuse the same fallback logic without
 * duplicating the catch chain.
 */
async function fetchLegacyModelsFallback(options) {
    try {
        const modelsResponse = await fetchAvailableModels({
            accessToken: options.accessToken,
            projectId: options.projectId,
            endpoints: ANTIGRAVITY_ENDPOINT_FALLBACKS,
            userAgent: buildAntigravityHarnessUserAgent(),
            timeoutMs: 10_000,
            ...(options.fetchVia ? { fetchVia: options.fetchVia } : {}),
        });
        if (modelsResponse.models) {
            return aggregateQuota(modelsResponse.models);
        }
        return {
            groups: {},
            modelCount: 0,
            error: 'Failed to fetch Antigravity quota (legacy fallback)',
        };
    }
    catch {
        return {
            groups: {},
            modelCount: 0,
            error: 'Failed to fetch Antigravity quota',
        };
    }
}
/**
 * Fetches both quota payloads for one account with a bearer and project the
 * caller already resolved: the windowed quota summary (with the legacy
 * model-list fallback) and the Gemini CLI quota. Shared by the OpenCode 1
 * fetcher and `createAuthorizedFetchAccountQuota`.
 */
async function fetchQuotaPayloads(options) {
    const { accessToken, managedProjectId, projectId, fetchVia } = options;
    // Two independent payload contracts: the windowed summary
    // (with legacy fallback) and the gemini-CLI quota. They share
    // access + project but target different endpoints, so the
    // two 10s timeouts ran back-to-back for ~20s per account on
    // modal open. Run them concurrently; either rejection is
    // handled by its own branch and the result is still merged.
    const fetchSummaryPayload = (async () => {
        try {
            const summaryResult = await fetchQuotaSummary({
                accessToken,
                managedProjectId,
                projectId,
                endpoints: ANTIGRAVITY_ENDPOINT_FALLBACKS,
                userAgent: buildAntigravityHarnessUserAgent(),
                timeoutMs: 10_000,
                ...(fetchVia ? { fetchVia } : {}),
            });
            return {
                result: aggregateQuotaSummary(summaryResult.summary),
                fellBackToLegacy: summaryResult.fellBackToLegacy ?? false,
            };
        }
        catch {
            return {
                result: await fetchLegacyModelsFallback({
                    accessToken,
                    projectId,
                    fetchVia,
                }),
                fellBackToLegacy: true,
            };
        }
    })();
    // CLI fetch is independent of the summary fetch. A CLI failure must
    // NOT kill the summary result, but it also must not be laundered into
    // "No Gemini CLI quota available" (a permanent-looking status) when
    // the real cause is a transient network error. Capture the error
    // message separately so the annotated result can carry it.
    let geminiCliFetchError;
    const fetchGeminiCliPayload = fetchGeminiCliQuota({
        accessToken,
        projectId,
        endpoints: ANTIGRAVITY_ENDPOINT_FALLBACKS,
        userAgent: buildGeminiCliUserAgent(),
        timeoutMs: 10_000,
        ...(fetchVia ? { fetchVia } : {}),
    }).catch((error) => {
        geminiCliFetchError = error instanceof Error ? error.message : String(error);
        options.logger.debug('fetchGeminiCliQuota failed', {
            error: geminiCliFetchError,
        });
        return { buckets: undefined };
    });
    const [summary, geminiCliResponse] = await Promise.all([
        fetchSummaryPayload,
        fetchGeminiCliPayload,
    ]);
    return {
        quota: summary.result,
        geminiCliQuota: annotateGeminiCliQuota(geminiCliResponse, geminiCliFetchError),
        fellBackToLegacy: summary.fellBackToLegacy,
    };
}
/**
 * The Gemini CLI quota summary for a `retrieveUserQuota` answer. An empty or
 * missing answer carries an error: the fetch error when the request failed
 * (a transient failure, not "no CLI quota configured"), else the generic
 * "no quota" text.
 */
function annotateGeminiCliQuota(response, fetchError) {
    const result = aggregateGeminiCliQuota(response);
    if (response.buckets !== undefined && response.buckets.length > 0) {
        return result;
    }
    return {
        ...result,
        error: fetchError ??
            (result.models.length === 0
                ? 'No Gemini CLI quota available'
                : undefined),
    };
}
/** Stops an outbound quota request after cancellation or a vault authorization refusal. */
class VaultQuotaCheckStoppedError extends Error {
    name = 'VaultQuotaCheckStoppedError';
    constructor() {
        super('the quota check was stopped before this request was sent');
    }
}
/** Refuses a second request using the same vault authorization. */
class VaultAdmissionReusedError extends Error {
    name = 'VaultAdmissionReusedError';
    constructor() {
        super('a vault admission authorizes exactly one physical request');
    }
}
/**
 * Makes exactly one physical quota request for `ref` under a new served
 * receipt from `source.send`. Inside the dispatch, `build` runs one of the
 * core quota builders with that receipt's access token and project, so the
 * Authorization header and the request project both come from the same
 * receipt and are built after it was served.
 *
 * The builder reads a clone of the response; the original Response goes back
 * to `send`. `send` needs the original to read its status: it reports a 401
 * against that receipt's record version and may retry once, under a new
 * receipt of the same credential and account, when the vault now serves a
 * different record version (not necessarily a higher one; a restore can
 * serve an older one). The retried request is built from the retry's
 * receipt. A builder that tries a second request under one receipt is
 * stopped before that request is sent.
 */
async function vaultQuotaAttempt(options, 
/**
 * True once the whole check must send nothing more (a receipt was refused
 * elsewhere in the check, or it was aborted). Checked again right before
 * the physical request, because serving this receipt may have taken a
 * while.
 */
isStopped, build) {
    const transport = options.transport ??
        ((url, init, extra) => fetchWithActiveTimeout(url, { ...init, signal: extra.signal ?? options.signal }, { timeoutMs: extra.timeoutMs }));
    let attempt = {};
    let dispatched = false;
    try {
        const response = await options.source.send(options.ref, async (admission, signal) => {
            dispatched = true;
            let used = false;
            let served;
            const fetchVia = async (url, init, extra) => {
                // Marked before the request goes out, so a failed or still
                // pending first request cannot let a second one use this receipt.
                if (used)
                    throw new VaultAdmissionReusedError();
                used = true;
                if (isStopped())
                    throw new VaultQuotaCheckStoppedError();
                served = await transport(url, init, {
                    ...extra,
                    signal: signal ?? options.signal,
                });
                // The builder reads a clone; `send` gets the original Response,
                // whose status it needs for 401 reporting.
                return served.clone();
            };
            attempt = {};
            try {
                attempt.value = await build({
                    accessToken: admission.accessToken,
                    projectId: admission.projectId,
                }, fetchVia);
            }
            catch (error) {
                attempt.error = error;
            }
            if (served === undefined)
                throw attempt.error ?? new Error('no request');
            attempt.status = served.status;
            if (attempt.value !== undefined) {
                attempt.attribution = options.source.attribution(admission);
            }
            return served;
        }, { site: 'quota', signal: options.signal });
        await response.body?.cancel().catch(() => { });
    }
    catch (error) {
        if (!dispatched)
            return { error, refused: true };
        attempt.error ??= error;
    }
    return attempt;
}
/**
 * Fetches a vault account's quota: the windowed quota summary (with the
 * legacy model-list fallback) and the Gemini CLI quota, from the same core
 * builders and endpoint list the local check uses.
 *
 * Every physical request (each endpoint, each fallback, and the model
 * list's retry without a project after a 403) is one `source.send` with a
 * new served receipt, and that request's bearer and project come from that
 * receipt alone. Nothing is authorized once and reused, and no local refresh
 * token, token exchange, project cache or earlier grant is used. A refused
 * receipt or an abort stops the check with no further request. Recording
 * the reading (with the returned attributions and the source's
 * `commitState`) is the caller's.
 */
export async function fetchVaultAccountQuota(options) {
    // Shared by the summary and Gemini CLI halves, which run concurrently: a
    // refusal in one stops requests in the other too, including one whose
    // receipt was being served when the refusal happened.
    const stopped = { value: false };
    const isStopped = () => stopped.value || options.signal.aborted;
    const attempt = async (build) => {
        if (isStopped()) {
            return { error: new VaultQuotaCheckStoppedError(), refused: true };
        }
        const result = await vaultQuotaAttempt(options, isStopped, build);
        if (result.refused || options.signal.aborted)
            stopped.value = true;
        return result;
    };
    const fetchSummary = async () => {
        for (const endpoint of ANTIGRAVITY_ENDPOINT_FALLBACKS) {
            // An answer that cannot be aggregated counts as a failed request.
            const result = await attempt(async (grant, fetchVia) => aggregateQuotaSummary((await fetchQuotaSummary({
                accessToken: grant.accessToken,
                projectId: grant.projectId,
                endpoints: [endpoint],
                userAgent: buildAntigravityHarnessUserAgent(),
                timeoutMs: 10_000,
                fetchVia,
            })).summary));
            if (result.value !== undefined) {
                return {
                    result: result.value,
                    fellBackToLegacy: false,
                    ...(result.attribution ? { attribution: result.attribution } : {}),
                };
            }
            if (result.refused)
                break;
        }
        // Fetch the legacy model list. After a 403, retry once without a project
        // as a separate request with a newly authorized vault credential, rather
        // than reusing the authorization from the rejected request.
        for (const endpoint of ANTIGRAVITY_ENDPOINT_FALLBACKS) {
            for (const withProject of [true, false]) {
                const result = await attempt((grant, fetchVia) => fetchAvailableModels({
                    accessToken: grant.accessToken,
                    projectId: withProject ? grant.projectId : '',
                    endpoints: [endpoint],
                    userAgent: buildAntigravityHarnessUserAgent(),
                    timeoutMs: 10_000,
                    fetchVia,
                }));
                if (result.value !== undefined) {
                    return result.value.models
                        ? {
                            result: aggregateQuota(result.value.models),
                            fellBackToLegacy: true,
                            ...(result.attribution
                                ? { attribution: result.attribution }
                                : {}),
                        }
                        : {
                            result: {
                                groups: {},
                                modelCount: 0,
                                error: 'Failed to fetch Antigravity quota (legacy fallback)',
                            },
                            fellBackToLegacy: true,
                        };
                }
                if (result.refused) {
                    return {
                        result: {
                            groups: {},
                            modelCount: 0,
                            error: 'Failed to fetch Antigravity quota',
                        },
                        fellBackToLegacy: true,
                    };
                }
                // Only a 403 for the request with a project is retried, without one.
                if (!withProject || result.status !== 403)
                    break;
            }
        }
        return {
            result: {
                groups: {},
                modelCount: 0,
                error: 'Failed to fetch Antigravity quota',
            },
            fellBackToLegacy: true,
        };
    };
    const fetchGeminiCli = async () => {
        const errors = [];
        for (const endpoint of ANTIGRAVITY_ENDPOINT_FALLBACKS) {
            const result = await attempt((grant, fetchVia) => fetchGeminiCliQuota({
                accessToken: grant.accessToken,
                projectId: grant.projectId,
                endpoints: [endpoint],
                userAgent: buildGeminiCliUserAgent(),
                timeoutMs: 10_000,
                fetchVia,
            }));
            if (result.value !== undefined) {
                return {
                    response: result.value,
                    ...(result.attribution ? { attribution: result.attribution } : {}),
                };
            }
            errors.push(result.error instanceof Error
                ? result.error.message
                : String(result.error));
            if (result.refused)
                break;
        }
        const error = errors.join('; ') || 'fetchGeminiCliQuota failed';
        options.logger.debug('vault fetchGeminiCliQuota failed', { error });
        return { response: { buckets: undefined }, error };
    };
    const [summary, cli] = await Promise.all([fetchSummary(), fetchGeminiCli()]);
    return {
        quota: summary.result,
        geminiCliQuota: annotateGeminiCliQuota(cli.response, cli.error),
        fellBackToLegacy: summary.fellBackToLegacy,
        ...(summary.attribution ? { quotaAttribution: summary.attribution } : {}),
        ...(cli.attribution ? { geminiCliAttribution: cli.attribution } : {}),
    };
}
/** Raised inside a check when a request's local grant is no longer current. */
class LocalQuotaGrantStaleError extends Error {
    name = 'LocalQuotaGrantStaleError';
}
/**
 * A quota fetcher for LOCAL credentials whose bearer and project come from
 * the caller's `authorize` callback instead of the account's stored refresh
 * token. The network requests and result shape are the OpenCode 1
 * fetcher's (`fetchQuotaPayloads`), sent through a transport that calls the
 * authorization's `confirmSend` before every physical request.
 *
 * - A disabled account is answered without calling `authorize`.
 * - A refused authorization, an authorization that is not `local`, or a
 *   throw from `authorize` is answered as an error result without any
 *   request.
 * - Once `confirmSend` reports `stale`, no further request of the check is
 *   sent and the whole check is answered as an error, so a reading taken
 *   for a replaced or removed credential is never applied.
 * - The result never carries `updatedAccount`: any credential or project
 *   change belongs to the `authorize` callback, which knows which stored row
 *   it may write to.
 */
export function createAuthorizedFetchAccountQuota(options) {
    return async (account, signal) => {
        const base = { index: 0, email: account.email };
        if (account.enabled === false) {
            return { ...base, status: 'disabled', disabled: true };
        }
        if (signal.aborted) {
            return { ...base, status: 'error', disabled: false, error: 'aborted' };
        }
        let staleReason = null;
        try {
            // Called before the first await, so the callback sees the account as
            // handed in; a synchronous throw lands in the catch below.
            const authorizing = options.authorize(account, signal);
            const authorization = await authorizing;
            if (authorization.status !== 'authorized') {
                return {
                    ...base,
                    status: 'error',
                    disabled: false,
                    error: `quota check refused (${authorization.reason})`,
                };
            }
            if (authorization.domain !== 'local') {
                return {
                    ...base,
                    status: 'error',
                    disabled: false,
                    error: 'quota check refused (unsupported credential domain)',
                };
            }
            if (signal.aborted) {
                return { ...base, status: 'error', disabled: false, error: 'aborted' };
            }
            const send = options.transport?.(signal) ??
                ((url, init, extra) => fetchWithActiveTimeout(url, { ...init, signal: extra.signal ?? signal }, { timeoutMs: extra.timeoutMs }));
            const guarded = async (url, init, extra) => {
                if (staleReason !== null)
                    throw new LocalQuotaGrantStaleError(staleReason);
                const check = await authorization.confirmSend(signal);
                if (check.status !== 'current') {
                    staleReason = check.reason;
                    throw new LocalQuotaGrantStaleError(check.reason);
                }
                // `confirmSend` (the check that the account still holds this exact
                // credential and access token) has just finished; the request goes
                // out at once, with this quota check's abort signal.
                return send(url, init, { ...extra, signal });
            };
            const payloads = await fetchQuotaPayloads({
                accessToken: authorization.accessToken,
                managedProjectId: authorization.managedProjectId,
                projectId: authorization.projectId,
                fetchVia: guarded,
                logger: options.logger,
            });
            if (staleReason !== null) {
                return {
                    ...base,
                    status: 'error',
                    disabled: false,
                    error: `quota check refused (stale grant: ${staleReason})`,
                };
            }
            return {
                ...base,
                status: 'ok',
                disabled: false,
                quota: payloads.quota,
                geminiCliQuota: payloads.geminiCliQuota,
            };
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            options.logger.debug('authorized quota check failed', { error: message });
            return { ...base, status: 'error', disabled: false, error: message };
        }
    };
}
function makeFetchAccountQuota(client, providerId, fetchVia) {
    return async (account, signal) => {
        const index = 0;
        const disabled = account.enabled === false;
        if (disabled) {
            return {
                index,
                email: account.email,
                status: 'disabled',
                disabled: true,
            };
        }
        if (signal.aborted) {
            return {
                index,
                email: account.email,
                status: 'error',
                error: signal.reason instanceof Error ? signal.reason.message : 'aborted',
            };
        }
        let auth = buildAuthFromAccount(account);
        let rotatedRefresh;
        try {
            if (accessTokenExpired(auth)) {
                const refreshed = await refreshAccessToken(auth, client, providerId);
                if (!refreshed) {
                    throw new Error('Token refresh failed');
                }
                if (refreshed.refresh !== auth.refresh) {
                    rotatedRefresh = refreshed.refresh;
                }
                auth = refreshed;
            }
            const projectContext = await ensureProjectContext(auth);
            auth = projectContext.auth;
            const updatedAccount = applyAccountUpdates(account, auth, projectContext.capturedTier);
            if (rotatedRefresh && client) {
                await persistRotatedRefresh(client, providerId, auth).catch(() => { });
            }
            let quotaResult;
            let fellBackToLegacy = false;
            const authParts = parseRefreshParts(auth.refresh);
            // Bare refresh tokens have no packed project IDs — fall back to the
            // account record. The real managedProjectId lives on the persisted
            // account, not in the packed refresh string.
            const managedProjectId = authParts.managedProjectId ?? account.managedProjectId;
            const payloads = await fetchQuotaPayloads({
                accessToken: auth.access ?? '',
                managedProjectId,
                projectId: projectContext.effectiveProjectId,
                fetchVia,
                logger: log,
            });
            quotaResult = payloads.quota;
            fellBackToLegacy = payloads.fellBackToLegacy;
            const annotated = payloads.geminiCliQuota;
            for (const [family, groupQuota] of Object.entries(quotaResult.groups)) {
                const remainingPercent = (groupQuota.remainingFraction ?? 0) * 100;
                logQuotaStatus(account.email, index, remainingPercent, family);
            }
            const legacyTag = fellBackToLegacy ? ' legacy=1' : '';
            logQuotaFetch('complete', 1, `ok=1 errors=0${legacyTag}`);
            return {
                index,
                email: account.email,
                status: 'ok',
                disabled: false,
                quota: quotaResult,
                geminiCliQuota: annotated,
                updatedAccount,
            };
        }
        catch (error) {
            logQuotaFetch('error', undefined, `account=${account.email ?? index} error=${error instanceof Error ? error.message : String(error)}`);
            return {
                index,
                email: account.email,
                status: 'error',
                error: error instanceof Error ? error.message : String(error),
                disabled: false,
            };
        }
    };
}
function buildAuthFromAccount(account) {
    return {
        type: 'oauth',
        refresh: formatRefreshParts({
            refreshToken: account.refreshToken,
            projectId: account.projectId,
            managedProjectId: account.managedProjectId,
        }),
        access: undefined,
        expires: undefined,
    };
}
function applyAccountUpdates(account, auth, capturedTier) {
    const parts = parseRefreshParts(auth.refresh);
    if (!parts.refreshToken) {
        return undefined;
    }
    const updated = {
        ...account,
        refreshToken: parts.refreshToken,
        projectId: parts.projectId ?? account.projectId,
        managedProjectId: parts.managedProjectId ?? account.managedProjectId,
        // Persist the captured tier alongside the project-context write. Only
        // present when the loadCodeAssist payload returned a non-empty currentTier.id.
        ...(capturedTier
            ? {
                capturedTierId: capturedTier.id,
                ...(capturedTier.paidId !== undefined
                    ? { capturedPaidTierId: capturedTier.paidId }
                    : {}),
                capturedTierAt: capturedTier.capturedAt,
            }
            : {}),
    };
    const changed = updated.refreshToken !== account.refreshToken ||
        updated.projectId !== account.projectId ||
        updated.managedProjectId !== account.managedProjectId ||
        updated.capturedTierId !== account.capturedTierId ||
        updated.capturedPaidTierId !== account.capturedPaidTierId ||
        // capturedAt represents when the tier was LAST CONFIRMED, not when it
        // changed -- always update it on a successful observation so consumers
        // can gate staleness on that timestamp even when the id stays the same.
        (capturedTier !== undefined &&
            updated.capturedTierAt !== account.capturedTierAt);
    return changed ? updated : undefined;
}
async function persistRotatedRefresh(client, providerId, auth) {
    await client.auth.set({
        path: { id: providerId },
        body: {
            type: 'oauth',
            refresh: auth.refresh,
            access: auth.access ?? '',
            expires: auth.expires ?? 0,
        },
    });
}
/**
 * Build a per-account tier-loader callback for the background poller.
 *
 * Calls `loadManagedProject` (loadCodeAssist) directly. The
 * `ensureProjectContext` cache answers from a known `managedProjectId`
 * without asking Google, so for an account that already has a project it
 * never returns a tier; the tier is only in loadCodeAssist's answer. One
 * call per account per 24 h.
 *
 * An expired access token is refreshed the same way `makeFetchAccountQuota`
 * refreshes it, so the lookup does not fail just because the token aged.
 *
 * `loadManagedProject` sends through the native TLS transport
 * (`fetchWithAgyCliTransport`), not through a generic `fetch`, so a
 * `fetchVia` override cannot intercept it; `ensureProjectContext` has the
 * same limit. Tier lookup is best-effort; any failure resolves `null`.
 */
export function makeTierLoader(client, providerId, options = {}) {
    return async (account) => {
        try {
            if (options.mayRun && !(await options.mayRun()))
                return null;
            let accessToken;
            const target = account;
            if (target.rowRef !== undefined) {
                if (!options.authorizeStore)
                    return null;
                const authorization = await options.authorizeStore(target);
                if (authorization.status !== 'authorized' ||
                    authorization.domain !== 'local')
                    return null;
                if (options.mayRun && !(await options.mayRun()))
                    return null;
                if ((await authorization.confirmSend(new AbortController().signal))
                    .status !== 'current')
                    return null;
                accessToken = authorization.accessToken;
            }
            else {
                let auth = buildAuthFromAccount(account);
                if (accessTokenExpired(auth)) {
                    const refreshed = await refreshAccessToken(auth, client, providerId);
                    if (!refreshed)
                        return null;
                    auth = refreshed;
                }
                accessToken = auth.access;
            }
            if (!accessToken)
                return null;
            if (options.mayRun && !(await options.mayRun()))
                return null;
            const payload = await loadManagedProject(accessToken);
            if (!payload?.currentTier?.id)
                return null;
            const paidTierId = typeof payload.paidTier === 'string'
                ? payload.paidTier
                : payload.paidTier?.id;
            return {
                id: payload.currentTier.id,
                ...(paidTierId ? { paidId: paidTierId } : {}),
                capturedAt: Date.now(),
            };
        }
        catch {
            return null;
        }
    };
}
/**
 * The quota groups a reading carries, in one canonical text: groups by
 * name, each with its model count, remaining fraction, reset time and
 * windows in order; absent and null are the same. The in-memory groups a
 * check records and the groups the store keeps for them give the same text,
 * so the two can be compared exactly.
 */
function canonicalQuotaGroups(groups) {
    const entries = Object.entries(groups ?? {})
        .filter((entry) => entry[1] !== undefined)
        .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
        .map(([name, group]) => [
        name,
        group.modelCount,
        group.remainingFraction ?? null,
        group.resetTime ?? null,
        group.windows?.map((window) => [
            window.window,
            window.remainingFraction ?? null,
            window.resetTime ?? null,
        ]) ?? null,
    ]);
    return JSON.stringify(entries);
}
/**
 * The manager's account holding exactly `ref`. A RowRef names one
 * credential version of one row (row id, credential epoch and recorded
 * identity), so the lookup succeeds only while that row still holds that
 * very credential.
 */
function heldAccount(manager, ref) {
    return manager
        .getAccounts()
        .find((candidate) => candidate.ref !== undefined && sameRowRef(candidate.ref, ref));
}
/**
 * Quota checks for one plugin account pool whose accounts come from the
 * account store. One check, in order:
 * 1. Capture the target's RowRef before any await, and take the manager's
 *    account holding exactly that ref; if none does, the check is refused.
 * 2. If that account's access token has expired, refresh it through the
 *    repository, which commits the new token only to the row still holding
 *    that ref. Neither a token copied from an earlier read nor the host
 *    client is used.
 * 3. Resolve the account's project from the local project cache; a newly
 *    resolved project is recorded through the manager on the account's ref.
 * 4. Before every physical quota request, check that the manager still
 *    holds the same account object, at the same ref, enabled, with the same
 *    access token; otherwise no further request of the check is sent.
 * 5. Hand the reading to the manager only while it still holds that exact
 *    ref; otherwise discard it. The manager's write can still be refused by
 *    the store, so `checkStoreQuota` reads the store back and counts a
 *    check only when the store holds this check's whole reading.
 *
 * Only accounts whose refresh token is stored locally use this service;
 * vault-held accounts never do.
 */
export function createStoreQuotaService(options) {
    const { manager, logger } = options;
    const credentials = options.credentials ??
        createLocalAccountCredentials(manager, { repository: options.repository });
    const authorize = async (account) => {
        const ref = account.rowRef;
        if (ref === undefined) {
            return { status: 'refused', reason: 'the account has no store ref' };
        }
        if (options.mayRun && !(await options.mayRun()))
            return { status: 'refused', reason: VAULT_ACCOUNT_REMEDY };
        const held = heldAccount(manager, ref);
        if (held === undefined) {
            return { status: 'refused', reason: 'the account changed or was removed' };
        }
        let auth = manager.toAuthDetails(held);
        if (accessTokenExpired(auth)) {
            const refreshed = await credentials.refresh(held);
            if (refreshed === undefined) {
                return { status: 'refused', reason: 'token refresh failed' };
            }
            auth = refreshed;
        }
        // A refresh keeps the credential epoch but can record the provider's
        // account identity on the ref and always brings a new access token, so
        // the grant is the account's ref and token as they are now, after it.
        const grantRef = held.ref;
        const accessToken = auth.access;
        if (grantRef === undefined || !accessToken) {
            return { status: 'refused', reason: 'no access token' };
        }
        if (options.mayRun && !(await options.mayRun()))
            return { status: 'refused', reason: VAULT_ACCOUNT_REMEDY };
        const project = await credentials.ensureProject(auth);
        if (options.mayRun && !(await options.mayRun()))
            return { status: 'refused', reason: VAULT_ACCOUNT_REMEDY };
        if (project.auth.refresh !== auth.refresh) {
            // The resolved project belongs to this credential: the manager records
            // only the project fields, fenced on this account's ref, so they can
            // never land on another row or a replaced credential.
            manager.updateFromAuth(held, { ...project.auth, access: accessToken });
        }
        const managedProjectId = parseRefreshParts(project.auth.refresh).managedProjectId ??
            held.managedProjectId;
        return {
            status: 'authorized',
            domain: 'local',
            accessToken,
            projectId: project.effectiveProjectId,
            ...(managedProjectId !== undefined ? { managedProjectId } : {}),
            async confirmSend() {
                try {
                    if (options.mayRun && !(await options.mayRun()))
                        return { status: 'stale', reason: VAULT_ACCOUNT_REMEDY };
                    if (held.ref === undefined || !sameRowRef(held.ref, grantRef)) {
                        return { status: 'stale', reason: 'the credential changed' };
                    }
                    await credentials.assertGrantCurrent({
                        account: held,
                        accessToken,
                        ref: grantRef,
                    });
                    if (options.mayRun && !(await options.mayRun()))
                        return { status: 'stale', reason: VAULT_ACCOUNT_REMEDY };
                    return { status: 'current' };
                }
                catch (error) {
                    return {
                        status: 'stale',
                        reason: error instanceof Error ? error.message : String(error),
                    };
                }
            },
        };
    };
    const fetchAccountQuota = createAuthorizedFetchAccountQuota({
        authorize: (account) => authorize(account),
        logger,
        transport: options.transport,
    });
    const quotaManager = createLocationQuotaManager({
        logger,
        fetchAccountQuota,
        // Backoff and cache are per credential: a re-authenticated row starts
        // fresh instead of inheriting its predecessor's state.
        keyOf: (account) => {
            const ref = account.rowRef;
            return ref === undefined ? defaultKeyOf(account) : rowRefKey(ref);
        },
        baseBackoffMs: options.baseBackoffMs,
        maxBackoffMs: options.maxBackoffMs,
        fetchTimeoutMs: options.fetchTimeoutMs,
        sidebar: options.sidebar,
    });
    const record = async (target, result) => {
        if (result.status !== 'ok' || result.quota === undefined) {
            return { status: 'failed', result };
        }
        // A completed poll does not authorize deferred local metadata writes after enrollment.
        if (options.mayRun && !(await options.mayRun()))
            return { status: 'discarded', result };
        const held = target.rowRef === undefined
            ? undefined
            : heldAccount(manager, target.rowRef);
        if (held === undefined)
            return { status: 'discarded', result };
        manager.updateQuotaCache(held.index, result.quota.groups, held.parts.refreshToken);
        // Captured now: the account's fields may change before the store is
        // read back, and a later reading must not stand in for this one.
        return {
            status: 'recorded',
            result,
            reading: {
                cachedQuotaAccountId: held.cachedQuotaAccountId,
                cachedQuotaUpdatedAt: held.cachedQuotaUpdatedAt,
                groups: canonicalQuotaGroups(result.quota.groups),
            },
        };
    };
    const refreshAccount = async (target, refreshOptions = {}) => {
        const index = Math.max(0, manager
            .getAccountsForQuotaCheck()
            .findIndex((candidate) => candidate.rowRef !== undefined &&
            target.rowRef !== undefined &&
            sameRowRef(candidate.rowRef, target.rowRef)));
        const result = await quotaManager.refreshAccount(target, {
            index,
            force: refreshOptions.force === true,
        });
        return record(target, result);
    };
    return {
        quotaManager,
        fetchAccountQuota,
        authorizeLocalCheck: authorize,
        refreshAccount,
        async checkStoreQuota(refs) {
            // Targets are taken before any await, so each names the credential
            // the manager held when the action started.
            const targets = manager.getAccountsForQuotaCheck();
            const outcomes = await Promise.all(refs.map((ref) => {
                const target = targets.find((candidate) => candidate.rowRef !== undefined &&
                    sameRowRef(candidate.rowRef, ref));
                return target === undefined
                    ? undefined
                    : refreshAccount(target, { force: true });
            }));
            // Wait for queued quota writes before counting an account as checked.
            // If a failed write cannot be attributed to an account, no account's
            // quota reading is confirmed.
            let failedRows = new Set();
            try {
                await manager.saveToDisk();
            }
            catch (error) {
                // AccountManagerPersistError includes a flush report, but the public
                // core entry does not export its constructor. Identify it by name and
                // require at least one failed row ID. Only accounts outside the
                // reported failure list can still count as checked; missing or empty
                // failure details confirm none.
                const report = error instanceof Error && error.name === 'AccountManagerPersistError'
                    ? error.report
                    : undefined;
                const failedIds = (report?.failures ?? []).map((failure) => failure.rowId);
                failedRows =
                    report === undefined ||
                        failedIds.length === 0 ||
                        failedIds.some((id) => id === undefined)
                        ? 'all'
                        : new Set(failedIds.filter((id) => id !== undefined));
                logger.debug('quota readings were not all persisted', {
                    error: error instanceof Error ? error.message : String(error),
                });
            }
            const read = await options.repository.read();
            let checked = 0;
            refs.forEach((ref, position) => {
                const outcome = outcomes[position];
                if (outcome?.status !== 'recorded')
                    return;
                if (failedRows === 'all' || failedRows.has(ref.id))
                    return;
                const row = read.status === 'ready'
                    ? read.rows.find((candidate) => sameRowRef(candidate.ref, ref))
                    : undefined;
                if (row?.quota.status !== 'present')
                    return;
                const stored = row.quota.quota;
                // The store must hold exactly this check's reading: same identity
                // stamp, same time and the same groups. An older reading stored with
                // the same time, or another check's reading of the same row, does
                // not count.
                if (stored.cachedQuotaAccountId ===
                    outcome.reading.cachedQuotaAccountId &&
                    stored.cachedQuotaUpdatedAt ===
                        outcome.reading.cachedQuotaUpdatedAt &&
                    canonicalQuotaGroups(stored.cachedQuota) === outcome.reading.groups) {
                    checked += 1;
                }
            });
            return { checked, notChecked: refs.length - checked };
        },
        async refreshAll(refreshOptions = {}) {
            const targets = manager.getAccountsForQuotaCheck();
            const results = await quotaManager.refreshAccounts(targets, {
                indexFor: (account) => targets.indexOf(account),
                force: refreshOptions.force === true,
            });
            return Promise.all(results.map((result, position) => {
                const target = targets[position];
                return target === undefined
                    ? { status: 'failed', result }
                    : record(target, result);
            }));
        },
        dispose: () => quotaManager.dispose(),
    };
}
//# sourceMappingURL=quota.js.map