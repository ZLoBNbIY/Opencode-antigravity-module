/**
 * The OpenCode 2 (GA host) location services: account state for the
 * `antigravity-auth` RPC `state` method, the shared `/antigravity` menu
 * behind `apply`, and `createGaLocationServicesFactory`, which builds a
 * location's services from the bound account repository and the shared
 * request pipeline.
 *
 * Accounts come from the location's account repository, read once per
 * `state` call. Each account in a state answer carries an opaque selector: a
 * random string issued for one exact credential (row id, credential epoch
 * and recorded identity), kept across reads and reorders and retired when
 * that credential is replaced, re-identified or removed. Account actions run
 * through the shared menu, whose own opaque item ids are bound the same way;
 * an account position is never accepted as a target.
 *
 * Everything a location needs (repository, settings controller, dump switch,
 * logger) arrives explicitly; nothing here reads a process-global binding.
 * The GA server module is imported for types only, so it can import this
 * module's factory without a cycle.
 */
import { randomBytes } from 'node:crypto';
import { ANTIGRAVITY_MENU_COMMAND, antigravitySettingsSections, authorizeAntigravity, createAccountRepositoryFactory, createAntigravityCommandMenu, ensureProjectContext, exchangeAntigravity, fetchWithAgyCliTransport, formatRefreshParts, loadCommonAuthCommands, loadCommonAuthStoreModules, parseRefreshParts, readAccountStoreAdmission, readAccountStoreBinding, refreshAntigravityToken, rowRefKey, sameRowRef, VAULT_ACCOUNT_REMEDY, } from '@cortexkit/antigravity-auth-core';
import { createRepositoryAccountAccessService, extractAccountAccessErrorDetails, } from "./account-access.js";
import { createLocalAccountCredentials, loadAccountManagerFromRepository, } from "./accounts.js";
import { createStoreAccountLimits, diagnosticsMenuSection, operatorMenuSettings, } from "./command-apply.js";
import { createAuthorizedFetchAccountQuota, createStoreQuotaService, } from "./quota.js";
import { buildThinkingWarmupBody, getImageModelLocalTitle, getLastCacheStats, prepareAntigravityRequest, transformAntigravityResponse, } from "./request.js";
import { startOAuthListener } from "./server.js";
import { AgySessionRegistry } from "./session-context.js";
import { createLocalQuotaRefresh, createRequestExecutor, } from "./shared/request-services.js";
import { createMemoryQuotaSnapshots, } from "./shared/runtime.js";
import { createVaultAccountMenuSections } from './shared/vault-menu';
import { checkVaultQuota, createVaultAccountPool, vaultAccountRowKey, } from "./shared/vault-request-credentials.js";
import { getStoragePath } from './storage';
import { createOpenCodeVaultCustody, } from "./vault-custody.js";
/** Accounts one `state` answer may carry (`ANTIGRAVITY_RPC_LIMITS.accounts`). */
const ACCOUNT_LIMIT = 64;
/**
 * How many retired selectors are remembered so a late action on one is
 * answered `stale-target` rather than `unknown-target`. Older ones are
 * forgotten and then answered `unknown-target`; neither outcome writes.
 */
const RETIRED_SELECTOR_MEMORY = 256;
/**
 * 192 random bits as `sel-` plus 32 URL-safe characters, the selector shape
 * the RPC contract accepts; carries no account data.
 */
function defaultSelector() {
    return `sel-${randomBytes(24).toString('base64url')}`;
}
export function createGaSelectorRegistry(createSelector = defaultSelector) {
    /** Live selectors by exact ref key, and the ref each selector names. */
    const live = new Map();
    const liveRefs = new Map();
    /** Retired selectors in retirement order (oldest first). */
    const retired = new Map();
    const issued = new Set();
    const fresh = () => {
        for (;;) {
            const selector = createSelector();
            if (!issued.has(selector))
                return selector;
        }
    };
    return {
        plan(refs) {
            const additions = new Map();
            const selectors = refs.map((ref) => {
                const key = rowRefKey(ref);
                const existing = live.get(key) ?? additions.get(key)?.selector;
                if (existing !== undefined)
                    return existing;
                const selector = fresh();
                additions.set(key, { selector, ref });
                return selector;
            });
            const keep = new Set(refs.map((ref) => rowRefKey(ref)));
            let committed = false;
            return {
                selectors,
                commit() {
                    if (committed)
                        return [];
                    committed = true;
                    const retiredNow = [];
                    for (const [key, selector] of live) {
                        if (keep.has(key))
                            continue;
                        const ref = liveRefs.get(selector);
                        live.delete(key);
                        liveRefs.delete(selector);
                        if (ref !== undefined)
                            retired.set(selector, ref);
                        retiredNow.push(selector);
                    }
                    for (const [key, entry] of additions) {
                        if (live.has(key))
                            continue;
                        issued.add(entry.selector);
                        live.set(key, entry.selector);
                        liveRefs.set(entry.selector, entry.ref);
                    }
                    while (retired.size > RETIRED_SELECTOR_MEMORY) {
                        const oldest = retired.keys().next().value;
                        if (oldest === undefined)
                            break;
                        retired.delete(oldest);
                    }
                    return retiredNow;
                },
            };
        },
        resolve(selector) {
            const ref = liveRefs.get(selector);
            if (ref !== undefined)
                return { kind: 'live', ref };
            const old = retired.get(selector);
            if (old !== undefined)
                return { kind: 'retired', ref: old };
            return { kind: 'unknown' };
        },
    };
}
function routingSlotsOf(read, ref) {
    const routing = read.routing;
    if (routing === undefined)
        return [];
    const slots = [];
    if (routing.activeRow && sameRowRef(routing.activeRow, ref))
        slots.push('active');
    const byFamily = routing.activeRowByFamily;
    if (byFamily?.claude && sameRowRef(byFamily.claude, ref))
        slots.push('claude');
    if (byFamily?.gemini && sameRowRef(byFamily.gemini, ref))
        slots.push('gemini');
    return slots;
}
function metadataStatusOf(row) {
    const view = row.metadata;
    if (view.status === 'present')
        return 'present';
    if (view.status === 'absent')
        return 'absent';
    return view.reason === 'uncovered' ? 'dropped-uncovered' : 'dropped-invalid';
}
/**
 * The access block the row's metadata records. Absent or dropped metadata
 * cannot rule a block out, so it is `unknown`, never `none`.
 */
export function accessBlockOf(row) {
    if (row.metadata.status !== 'present')
        return { kind: 'unknown' };
    const metadata = row.metadata.metadata;
    const verification = metadata.verificationRequired;
    const ineligible = metadata.accountIneligible;
    const flag = (value) => value === undefined || value === null || typeof value === 'boolean';
    if (!flag(verification) || !flag(ineligible))
        return { kind: 'invalid' };
    if (verification === true && ineligible === true)
        return { kind: 'invalid' };
    if (verification === true) {
        const reason = metadata.verificationRequiredReason;
        return {
            kind: 'verification-required',
            reason: reason === undefined || reason === null
                ? 'unrecorded'
                : reason === 'validation-required'
                    ? 'validation-required'
                    : 'other',
        };
    }
    if (ineligible === true) {
        const reason = metadata.accountIneligibleReason;
        return {
            kind: 'ineligible',
            reason: reason === undefined || reason === null
                ? 'unrecorded'
                : reason === 'account-ineligible'
                    ? 'account-ineligible'
                    : 'other',
        };
    }
    return { kind: 'none' };
}
function cooldownOf(row) {
    if (row.metadata.status !== 'present')
        return null;
    const until = row.metadata.metadata.coolingDownUntil;
    return typeof until === 'number' ? until : null;
}
function quotaOf(row) {
    if (row.quota.status !== 'present')
        return undefined;
    const groups = row.quota.quota.cachedQuota;
    if (!groups)
        return undefined;
    const out = {};
    for (const [key, group] of Object.entries(groups)) {
        out[key] = {
            ...(typeof group.remainingFraction === 'number'
                ? { remainingFraction: group.remainingFraction }
                : {}),
            ...(typeof group.resetTime === 'string'
                ? { resetTime: group.resetTime }
                : {}),
            modelCount: group.modelCount,
            ...(group.windows
                ? {
                    windows: group.windows.map((window) => ({
                        window: window.window,
                        remainingFraction: window.remainingFraction,
                        resetTime: window.resetTime,
                    })),
                }
                : {}),
        };
    }
    return out;
}
function tierOf(row) {
    if (row.metadata.status !== 'present')
        return undefined;
    const metadata = row.metadata.metadata;
    if (typeof metadata.capturedTierId !== 'string' ||
        typeof metadata.capturedTierAt !== 'number')
        return undefined;
    return {
        id: metadata.capturedTierId,
        ...(typeof metadata.capturedPaidTierId === 'string'
            ? { paidId: metadata.capturedPaidTierId }
            : {}),
        capturedAt: metadata.capturedTierAt,
    };
}
/**
 * The redaction input for one row: position, flags, cooldown, quota and
 * tier. It carries no email, label, token, project, identity or row id.
 */
function redactionInputOf(row, position, current, health) {
    const cooldown = cooldownOf(row);
    const quota = quotaOf(row);
    const tier = tierOf(row);
    const score = health(row);
    return {
        index: position,
        enabled: row.enabled,
        current,
        ...(cooldown !== null ? { coolingDownUntil: cooldown } : {}),
        ...(score !== undefined ? { healthScore: score } : {}),
        ...(quota !== undefined ? { cachedQuota: quota } : {}),
        ...(row.quota.status === 'present' &&
            typeof row.quota.quota.cachedQuotaUpdatedAt === 'number'
            ? { cachedQuotaUpdatedAt: row.quota.quota.cachedQuotaUpdatedAt }
            : {}),
        ...(tier !== undefined ? { tier } : {}),
    };
}
// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
/**
 * The settings DTO from the location's live controller and dump switch. It
 * only reads; per-account killswitch overrides stay out because their keys
 * derive from refresh tokens.
 */
export function gaSettingsOf(settings, dump) {
    return {
        routing: {
            cliFirst: settings.routing.cli_first,
            quotaStyleFallback: settings.routing.quota_style_fallback,
        },
        killswitch: {
            enabled: settings.killswitch.enabled,
            minimumRemainingPercent: settings.killswitch.minimum_remaining_percent,
        },
        logLevel: settings.log_level,
        dump: { enabled: dump.isEnabled() },
    };
}
function project(read, registry, health) {
    if (read.status !== 'ready') {
        return { read, rows: [], overLimit: null, plan: null };
    }
    if (read.rows.length > ACCOUNT_LIMIT) {
        return { read, rows: [], overLimit: read.rows.length, plan: null };
    }
    const plan = registry.plan(read.rows.map((row) => row.ref));
    const rows = read.rows.map((row, position) => {
        const slots = routingSlotsOf(read, row.ref);
        return {
            selector: plan.selectors[position] ?? '',
            row: redactionInputOf(row, position, slots.includes('active'), health),
            source: row,
            slots,
        };
    });
    return { read, rows, overLimit: null, plan };
}
function abortError(signal) {
    return signal.reason instanceof Error
        ? signal.reason
        : new Error('The state read was aborted');
}
/**
 * Builds the `state` source. Reads run one at a time, so `readSeq` follows
 * the order answers are built in; an aborted read leaves the selector
 * registry unchanged. The diagnostic observer, when present, is called
 * synchronously with a view of the same read.
 */
export function createGaAccountStateSource(options) {
    let readSeq = 0;
    let queue = Promise.resolve();
    const health = options.health ?? (() => undefined);
    const readOnce = async (input) => {
        if (input.signal.aborted)
            throw abortError(input.signal);
        const read = await options.repository.read();
        if (input.signal.aborted)
            throw abortError(input.signal);
        const projected = project(read, options.registry, health);
        const settings = options.settings();
        const status = options.status();
        const route = options.route(input.scope);
        if (input.signal.aborted)
            throw abortError(input.signal);
        const retiredSelectors = projected.plan?.commit() ?? [];
        readSeq = options.nextReadSeq?.() ?? readSeq + 1;
        const answer = {
            readSeq,
            accounts: projected.overLimit !== null
                ? { kind: 'over-limit', count: projected.overLimit }
                : {
                    kind: 'complete',
                    rows: projected.rows.map(({ selector, row }) => ({
                        selector,
                        row,
                    })),
                },
            route,
            status,
            settings,
        };
        if (options.observe) {
            const accounts = projected.rows.map(({ selector, source, slots }, position) => ({
                selector,
                position,
                enabled: source.enabled,
                usable: source.usable,
                metadataStatus: metadataStatusOf(source),
                accessBlock: accessBlockOf(source),
                currentFor: slots,
                cooldownUntil: cooldownOf(source),
            }));
            try {
                options.observe({
                    generation: options.generation,
                    readSeq,
                    status: read.status,
                    accountsStatus: projected.overLimit !== null ? 'over-limit' : 'complete',
                    accounts,
                    retiredSelectors,
                });
            }
            catch {
                // A diagnostic observer cannot change the answer.
            }
        }
        return answer;
    };
    return {
        read(input) {
            const next = queue.then(() => readOnce(input), () => readOnce(input));
            queue = next.catch(() => undefined);
            return next;
        },
    };
}
/**
 * The location's `/antigravity` menu: the shared core menu in repository
 * mode over this activation's repository and runtime. Accounts are acted on
 * by the menu's own opaque item ids, each bound to one exact credential;
 * Routing, Limits and Diagnostics read and write this location's settings
 * controller and dump switch. `commands` must be the module whose
 * `parseApplyRequest` the RPC activation uses.
 */
export function createGaLocationMenu(input) {
    const runtime = input.runtime;
    return createAntigravityCommandMenu({
        source: 'repository',
        commands: input.commands,
        accounts: input.repository,
        settings: operatorMenuSettings(runtime.operatorSettings),
        diagnostics: diagnosticsMenuSection({
            settings: runtime.operatorSettings,
            dump: runtime.dump,
            applyLogLevel: () => runtime.applyOperatorSettings(),
        }),
        accountLimits: createStoreAccountLimits({
            repository: input.repository,
            settings: runtime.operatorSettings,
        }),
        ...(input.refreshQuota ? { refreshQuota: input.refreshQuota } : {}),
        ...(input.reauthorize ? { reauthorize: input.reauthorize } : {}),
        ...(input.vault ? { extras: [input.vault] } : {}),
    });
}
/** The menu invocation for one RPC scope; its notices are queued there. */
function scopeInvocation(scope, notify) {
    return {
        ...(scope.kind === 'session' ? { sessionId: scope.sessionID } : {}),
        notify(message, kind) {
            notify(scope, {
                command: ANTIGRAVITY_MENU_COMMAND,
                notify: { message, kind: kind ?? 'info' },
            });
        },
    };
}
/**
 * The menu service over the location's menu. Each request (already accepted
 * by the library's own parser) runs through the menu with an invocation for
 * its scope, whose notices are queued for that scope; once the activation's
 * signal aborts, no new action starts. After every apply, `afterApply`
 * brings the routing state up to date with what the action wrote; its
 * failure is reported to the scope but does not change the menu's answer.
 */
export function createGaMenuCommandService(input) {
    return {
        async apply({ request, scope, signal }) {
            if (signal.aborted)
                throw abortError(signal);
            const result = await input.menu.apply(request, scopeInvocation(scope, input.notify));
            if (input.afterApply) {
                try {
                    await input.afterApply();
                }
                catch {
                    input.notify(scope, {
                        command: ANTIGRAVITY_MENU_COMMAND,
                        notify: {
                            message: 'The change was saved, but routing has not picked it up yet.',
                            kind: 'warning',
                        },
                    });
                }
            }
            return result;
        },
        async open({ scope, signal }) {
            if (signal.aborted)
                throw abortError(signal);
            const payload = await input.menu.open(scopeInvocation(scope, input.notify));
            if (signal.aborted)
                throw abortError(signal);
            input.notify(scope, payload);
        },
    };
}
/**
 * The account items' Reauthorize action for a GA location: a browser
 * sign-in whose result replaces exactly the credential the item was opened
 * for (through the account adapters' repository access service, which also
 * refuses a sign-in to a different Google account and clears the row's
 * access blocks). The action answers once the sign-in has started and the
 * callback listener is waiting; the rest finishes in the background and is
 * reported to the invoking session. `afterChange` brings routing up to date
 * with the new credential.
 *
 * Without an override, the redirect is received by this package's own
 * callback listener on the registered redirect address, which accepts only
 * the state of the sign-in it was started for.
 */
export function createGaReauthorize(input) {
    const authorize = input.overrides.oauth?.authorize ?? authorizeAntigravity;
    const exchange = input.overrides.oauth?.exchange ?? exchangeAntigravity;
    const waitForCode = input.overrides.oauth?.waitForCode;
    const access = createRepositoryAccountAccessService({
        repository: input.repository,
        // A GA location has no terminal: it opens no browser itself and asks
        // no account question; the sign-in link is shown in the menu instead.
        openBrowser: async () => false,
        prompt: {
            selectAccount: async () => undefined,
            confirmOpenVerificationUrl: async () => false,
        },
    });
    const listeners = new Set();
    const continuations = new Set();
    const shutdown = new AbortController();
    let disposed = false;
    const waitForRedirect = (code) => new Promise((resolve, reject) => {
        const detach = () => shutdown.signal.removeEventListener('abort', abort);
        const abort = () => {
            detach();
            reject(shutdown.signal.reason);
        };
        if (shutdown.signal.aborted)
            reject(shutdown.signal.reason);
        else
            shutdown.signal.addEventListener('abort', abort, { once: true });
        void code.then((value) => {
            detach();
            resolve(value);
        }, (error) => {
            detach();
            reject(error);
        });
    });
    /** Return the callback promise inside an object so setup can finish before the browser login. */
    const startWaiting = async (expectedState) => {
        if (waitForCode)
            return { code: waitForCode(expectedState) };
        const listener = await startOAuthListener();
        if (disposed) {
            await listener.close();
            throw shutdown.signal.reason;
        }
        listeners.add(listener);
        const code = (async () => {
            try {
                const url = await listener.waitForCallback();
                if (url.searchParams.get('state') !== expectedState)
                    throw new Error('The sign-in answered for a different request');
                const code = url.searchParams.get('code');
                if (!code)
                    throw new Error('The sign-in returned no code');
                return code;
            }
            finally {
                listeners.delete(listener);
                await listener.close();
            }
        })();
        return { code };
    };
    return {
        async run(ref, invocation) {
            if (disposed)
                return {
                    ok: false,
                    text: 'The location is shutting down.',
                    code: 'refused',
                };
            await input.assertAdmission?.();
            const authorization = await authorize();
            if (disposed)
                throw shutdown.signal.reason;
            const state = new URL(authorization.url).searchParams.get('state');
            if (!state)
                return {
                    ok: false,
                    text: 'The sign-in could not be started.',
                    code: 'action-failed',
                };
            const waiting = await startWaiting(state);
            const continuation = (async () => {
                try {
                    const code = await waitForRedirect(waiting.code);
                    await input.assertAdmission?.();
                    if (disposed)
                        throw shutdown.signal.reason;
                    const result = await exchange(code, state);
                    if (result.type !== 'success') {
                        invocation.notify('The sign-in was not completed.', 'error');
                        return;
                    }
                    await access.reauthorizeAccount(ref, result);
                    await input.afterChange();
                    invocation.notify('Account reauthorized.', 'info');
                }
                catch {
                    if (!disposed)
                        invocation.notify('The account could not be reauthorized.', 'error');
                }
            })();
            continuations.add(continuation);
            void continuation.then(() => continuations.delete(continuation), () => continuations.delete(continuation));
            return `Sign in with the browser to reauthorize this account:\n${authorization.url}\nWaiting for the browser…`;
        },
        async dispose() {
            disposed = true;
            shutdown.abort(new Error('The location is shutting down.'));
            const open = [...listeners];
            listeners.clear();
            const results = await Promise.allSettled(open.map((listener) => listener.close()));
            while (continuations.size > 0)
                await Promise.allSettled([...continuations]);
            const failure = results.find((result) => result.status === 'rejected');
            if (failure?.status === 'rejected')
                throw failure.reason;
        },
    };
}
/**
 * Reads the OpenCode 2 host's own sign-in for `integrationID` in the shape
 * the vault library classifies: an OAuth credential as
 * `{ type: 'oauth', refresh, access, expires }`, a key credential as
 * `{ type: 'api', key }`, and no active connection as `undefined` (empty).
 * An active connection whose credential cannot be resolved, or a credential
 * of another shape, rejects: custody is then refused, never decided on a
 * slot read as empty by mistake.
 */
export function createGaHostSlotReader(connections, integrationID) {
    return async () => {
        const connection = await connections.active(integrationID);
        if (connection === undefined)
            return undefined;
        const credential = await connections.resolve(connection);
        if (typeof credential !== 'object' || credential === null)
            throw new Error('The host sign-in could not be resolved');
        if ('type' in credential &&
            credential.type === 'oauth' &&
            'refresh' in credential &&
            typeof credential.refresh === 'string' &&
            'access' in credential &&
            typeof credential.access === 'string' &&
            'expires' in credential &&
            typeof credential.expires === 'number')
            return {
                type: 'oauth',
                refresh: credential.refresh,
                access: credential.access,
                expires: credential.expires,
            };
        if ('type' in credential &&
            credential.type === 'key' &&
            'key' in credential &&
            typeof credential.key === 'string')
            return { type: 'api', key: credential.key };
        throw new Error('The host sign-in has an unknown shape');
    };
}
// ---------------------------------------------------------------------------
// Location services factory
// ---------------------------------------------------------------------------
/** The legacy account file name inside a location directory. */
export const GA_ACCOUNTS_FILE = 'antigravity-accounts.json';
/**
 * The repository's token exchange: the core OAuth refresh, or the test
 * override. It returns the bare tokens; the repository stores them.
 */
function tokenExchange(overrides) {
    const refresh = overrides.refreshAccessToken ?? refreshAntigravityToken;
    return async ({ refreshToken }) => {
        const result = await refresh(refreshToken);
        return {
            accessToken: result.access,
            refreshToken: result.refresh,
            expiresAt: result.expires,
        };
    };
}
function storeRefusal(status) {
    return new Error(status.status === 'initialization-required'
        ? 'The Antigravity account store is not initialized; initialize it with the antigravity-auth CLI.'
        : status.status === 'error'
            ? `The Antigravity account store cannot be opened: ${status.reason}`
            : `The Antigravity account store is ${status.status}; finish its migration or rollback with \`antigravity-auth migrate --offline\` or \`antigravity-auth rollback --offline\`.`);
}
/**
 * Opens the location's account repository on the migration's canonical
 * binding: a completed generation the repository may open, including to
 * resume its own pending clear or replace work. Binding is not permission
 * to route; `assertServingAdmission` checks that before any credential is
 * used. Initialization and migration are offline CLI operations, never a
 * side effect of activation.
 */
async function openLocationRepository(directory, bindings, overrides) {
    const legacyPath = bindings.resolveAccountFile(directory);
    const modules = await bindings.loadStoreModules();
    const binding = await readAccountStoreBinding(legacyPath, modules, bindings.now);
    if (binding.status !== 'bound')
        throw storeRefusal(binding);
    return {
        repository: createAccountRepositoryFactory(modules)({
            paths: binding.paths,
            now: bindings.now,
            exchange: tokenExchange(overrides),
        }),
        legacyPath,
        generation: binding.receipt.id,
        modules,
    };
}
/**
 * Serving needs the full admission of the same generation the repository
 * was bound to: healthy current rows and no pending management work.
 */
async function assertServingAdmission(location, now) {
    const admission = await readAccountStoreAdmission(location.legacyPath, location.modules, now, location.generation);
    if (admission.status === 'active')
        return;
    if (admission.status === 'pending' && admission.phase === 'activate')
        throw new Error('An Antigravity account operation is still finishing; reopen the session once it completes.');
    throw storeRefusal(admission);
}
// ---------------------------------------------------------------------------
// Request pipeline (local account repository)
// ---------------------------------------------------------------------------
/**
 * How long a response body may stall before the transport destroys the
 * socket; the GA raw sender (`GA_RAW_IDLE_TIMEOUT_MS`) uses the same five
 * minutes. Declared here because the GA server module is imported for types
 * only.
 */
const GA_TRANSPORT_IDLE_TIMEOUT_MS = 300_000;
/**
 * Local credentials for a repository-backed GA location, in the shared
 * engine's `local` domain. A refresh is of the selected account itself:
 * `refreshAccount` uses the ref the account was loaded with, so the
 * repository stores a successor token only for that exact credential and
 * refuses one whose row has since changed. Rows are never found again by
 * token.
 */
export function createGaLocalCredentials(manager, options) {
    const local = createLocalAccountCredentials(manager, {
        repository: options.repository,
        ...(options.overrides.ensureProjectContext
            ? { ensureProject: options.overrides.ensureProjectContext }
            : {}),
    });
    return {
        domain: 'local',
        toAuthDetails: (account) => manager.toAuthDetails(account),
        updateFromAuth: (account, auth) => manager.updateFromAuth(account, auth),
        removeAccount: (account) => manager.removeAccount(account),
        saveToDisk: () => manager.saveToDisk(),
        saveToDiskReplace: () => manager.saveToDiskReplace(),
        refresh: (account) => local.refresh(account),
        // Checking and resolution use the captured row ID, epoch and identity,
        // never whichever replacement the account object might later refer to.
        captureGrant: (grant) => local.captureGrant(grant),
        ensureProject: (auth) => local.ensureProject(auth),
        isInvalidGrant: (error) => local.isInvalidGrant(error),
        // The GA host keeps no OAuth credential of its own for this provider;
        // accounts live only in the repository, so there is nothing to clear.
        clearStoredAuth: async () => undefined,
        ...(options.refreshQuotaAfterSuccess
            ? { refreshQuotaAfterSuccess: options.refreshQuotaAfterSuccess }
            : {}),
    };
}
/** How close to expiry a stored access token is still used as is. */
const QUOTA_TOKEN_SKEW_MS = 60_000;
/**
 * Resolves the bearer for one quota check from the repository, by the
 * target's captured ref only. A row that no longer holds that exact
 * credential (replaced, re-identified or removed) is refused rather than
 * checked on its successor. An expired token is refreshed through the
 * repository's attributed refresh, never locally.
 */
export async function authorizeGaQuotaCheck(repository, target, now) {
    const ref = target.rowRef;
    if (ref === undefined)
        return { status: 'refused', reason: 'unattributed' };
    const read = await repository.read();
    if (read.status !== 'ready')
        return { status: 'refused', reason: 'not-ready' };
    const row = read.rows.find((candidate) => sameRowRef(candidate.ref, ref));
    if (row === undefined ||
        row.credential === undefined ||
        !row.enabled ||
        !row.usable ||
        row.metadata.status !== 'present')
        return { status: 'refused', reason: 'stale' };
    const metadata = row.metadata.status === 'present' ? row.metadata.metadata : undefined;
    const projects = {
        ...(metadata?.projectId ? { projectId: metadata.projectId } : {}),
        ...(metadata?.managedProjectId
            ? { managedProjectId: metadata.managedProjectId }
            : {}),
    };
    const stored = row.credential;
    if (stored.accessToken !== undefined &&
        stored.expiresAt !== undefined &&
        stored.expiresAt - QUOTA_TOKEN_SKEW_MS > now()) {
        return {
            status: 'authorized',
            ref,
            auth: {
                type: 'oauth',
                refresh: formatRefreshParts({
                    refreshToken: stored.refreshToken,
                    ...projects,
                }),
                access: stored.accessToken,
                expires: stored.expiresAt,
            },
        };
    }
    const outcome = await repository.refresh(ref);
    if (outcome.status !== 'rotated')
        return { status: 'refused', reason: 'refresh-refused' };
    const after = await repository.read();
    const successor = after.status === 'ready'
        ? after.rows.find((candidate) => sameRowRef(candidate.ref, outcome.ref))
        : undefined;
    if (successor?.credential === undefined ||
        !successor.enabled ||
        !successor.usable ||
        successor.metadata.status !== 'present')
        return { status: 'refused', reason: 'stale' };
    return {
        status: 'authorized',
        ref: outcome.ref,
        auth: {
            type: 'oauth',
            refresh: formatRefreshParts({
                refreshToken: successor.credential.refreshToken,
                ...(successor.metadata.metadata.projectId
                    ? { projectId: successor.metadata.metadata.projectId }
                    : {}),
                ...(successor.metadata.metadata.managedProjectId
                    ? { managedProjectId: successor.metadata.metadata.managedProjectId }
                    : {}),
            }),
            access: outcome.accessToken,
            expires: outcome.expiresAt,
        },
    };
}
function isRowRef(value) {
    return (typeof value === 'object' &&
        value !== null &&
        'id' in value &&
        typeof value.id === 'string' &&
        'credentialEpoch' in value &&
        typeof value.credentialEpoch === 'number' &&
        (!('identity' in value) ||
            value.identity === undefined ||
            typeof value.identity === 'string'));
}
/** The captured ref a quota target carries, when it carries a valid one. */
function rowRefOfTarget(account) {
    if (!('rowRef' in account))
        return undefined;
    return isRowRef(account.rowRef) ? account.rowRef : undefined;
}
/**
 * The GA location's quota fetcher. Each check is attributed to the target's
 * captured repository ref: the bearer comes from `authorizeGaQuotaCheck`
 * (stored token, or the repository's attributed refresh), and a target
 * without a ref, or whose credential has since changed, is answered with an
 * error result instead of being checked on another credential.
 */
export function createGaFetchAccountQuota(options) {
    const ensureProject = options.overrides.ensureProjectContext ?? ensureProjectContext;
    const quotaFetch = options.overrides.quotaFetch;
    return createAuthorizedFetchAccountQuota({
        logger: options.logger,
        ...(quotaFetch ? { transport: () => quotaFetch } : {}),
        async authorize(account) {
            // Captured before any await: the ref of exactly this target.
            const rowRef = rowRefOfTarget(account);
            await options.assertAdmission?.();
            const authorization = await authorizeGaQuotaCheck(options.repository, { rowRef }, options.now);
            if (authorization.status !== 'authorized')
                return { status: 'refused', reason: authorization.reason };
            const ref = authorization.ref;
            const accessToken = authorization.auth.access ?? '';
            await options.assertAdmission?.();
            const project = await ensureProject(authorization.auth);
            await options.assertAdmission?.();
            const managedProjectId = parseRefreshParts(project.auth.refresh).managedProjectId;
            return {
                status: 'authorized',
                domain: 'local',
                accessToken,
                projectId: project.effectiveProjectId,
                ...(managedProjectId ? { managedProjectId } : {}),
                // Before every request: the row must still hold exactly this
                // credential and this access token.
                confirmSend: async () => {
                    await options.assertAdmission?.();
                    const read = await options.repository.read();
                    const row = read.status === 'ready'
                        ? read.rows.find((candidate) => sameRowRef(candidate.ref, ref))
                        : undefined;
                    if (row === undefined ||
                        !row.enabled ||
                        !row.usable ||
                        row.metadata.status !== 'present')
                        return { status: 'stale', reason: 'credential changed' };
                    if (row.credential?.accessToken !== accessToken)
                        return { status: 'stale', reason: 'access token changed' };
                    await options.assertAdmission?.();
                    return { status: 'current' };
                },
            };
        },
    });
}
export function createGaRouteBook(limit = 256) {
    const routes = new Map();
    return {
        record(sessionId, entry) {
            routes.delete(sessionId);
            routes.set(sessionId, {
                accountId: entry.accountId,
                modelFamily: entry.modelFamily,
                headerStyle: entry.headerStyle,
                ...(entry.strategy ? { strategy: entry.strategy } : {}),
                updatedAt: entry.updatedAt,
            });
            while (routes.size > limit) {
                const oldest = routes.keys().next().value;
                if (oldest === undefined)
                    break;
                routes.delete(oldest);
            }
        },
        route(scope) {
            return scope.kind === 'session'
                ? (routes.get(scope.sessionID) ?? null)
                : null;
        },
    };
}
/** Runs one bridged job through the shared request engine. */
export function createGaJobExecutor(executor) {
    return (job, context) => executor.execute(job.url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: job.body,
        signal: context.signal,
    }, {
        session: {
            sessionId: job.sessionID,
            parentSessionId: job.parentSessionID,
        },
    });
}
/**
 * The shared request engine's collaborators that do not depend on where the
 * accounts' credentials live: this location's config, session registry,
 * operator settings, wire, debug log, dump switch and route book, and the
 * AGY transport with the GA raw sender's idle timeout and signal observer.
 */
function gaEngineCollaborators(input) {
    const runtime = input.runtime;
    const observe = input.overrides.observeRawSenderSignal;
    return {
        config: runtime.config.config,
        sessions: new AgySessionRegistry(runtime.directory),
        operatorSettings: runtime.operatorSettings,
        transport: (url, init, options) => {
            const transportOptions = {
                ...options,
                idleTimeoutMs: options?.idleTimeoutMs ?? GA_TRANSPORT_IDLE_TIMEOUT_MS,
            };
            if (observe && transportOptions.signal) {
                try {
                    observe(transportOptions.signal);
                }
                catch {
                    // A diagnostic failure must not change or delay the dispatch.
                }
            }
            return fetchWithAgyCliTransport(url, init, transportOptions);
        },
        fetchImpl: (request, init) => fetch(request, init),
        wire: {
            prepare: prepareAntigravityRequest,
            transformResponse: transformAntigravityResponse,
            buildThinkingWarmupBody,
            getImageModelLocalTitle,
            getLastCacheStats,
        },
        debug: runtime.debug,
        dump: runtime.dump,
        logger: input.logger,
        classifyAccessError: extractAccountAccessErrorDetails,
        onRouting: (sessionId, entry) => input.routes.record(sessionId, entry),
    };
}
/**
 * The shared request engine over a repository-backed account manager. The
 * engine is the same one OpenCode 1 uses; only its collaborators are this
 * location's.
 */
export async function createGaLocalRequestPipeline(input) {
    const runtime = input.runtime;
    await input.assertAdmission?.();
    const manager = await loadAccountManagerFromRepository(input.repository);
    input.accounts.current = manager;
    input.accounts.quotaLogger = runtime.logger.createLogger('quota');
    await runtime.replaceAccounts(manager);
    const logger = runtime.logger.createLogger('request');
    const executor = createRequestExecutor({
        ...gaEngineCollaborators({
            runtime,
            overrides: input.overrides,
            routes: input.routes,
            logger,
        }),
        accounts: manager,
        ...(input.assertAdmission
            ? { assertAdmission: input.assertAdmission }
            : {}),
        credentials: createGaLocalCredentials(manager, {
            repository: input.repository,
            overrides: input.overrides,
            refreshQuotaAfterSuccess: createLocalQuotaRefresh(manager, runtime.quotaManager, logger),
        }),
        // The trackers the manager selects with, so recorded outcomes steer
        // the next selection.
        trackers: {
            health: manager.healthTracker,
            token: manager.tokenTracker,
        },
    });
    // Local custody: the same store quota service the OpenCode 1 menu uses,
    // over this activation's manager and repository.
    const quotaFetch = input.overrides.quotaFetch;
    const storeQuota = createStoreQuotaService({
        manager,
        repository: input.repository,
        ...(input.assertAdmission
            ? {
                mayRun: async () => {
                    await input.assertAdmission?.();
                    return true;
                },
            }
            : {}),
        logger: runtime.logger.createLogger('store-quota'),
        ...(quotaFetch ? { transport: () => quotaFetch } : {}),
    });
    return {
        execute: createGaJobExecutor(executor),
        refreshQuota: (refs) => storeQuota.checkStoreQuota(refs),
        refreshAccounts: () => manager.refreshFromRepository(),
        async dispose() {
            await executor.dispose();
            await storeQuota.dispose();
            if (input.accounts.current === manager) {
                input.accounts.current = null;
                input.accounts.quotaLogger = null;
            }
            await runtime.replaceAccounts(null);
            await manager.dispose();
        },
    };
}
/**
 * The shared request engine for a location whose accounts are held by the
 * vault. Selection runs on the shared `AccountSelector` over the vault's
 * selectable routes (metadata rows, no credential); every physical send
 * takes a fresh receipt for the selected route through
 * `createVaultRequestCredentials`. Nothing is refreshed or cached locally.
 * `refreshAccounts` re-reads the vault roster and keeps each route's
 * selection state while its route, credential and asserted account stay
 * the same. With `state`, a route's selection state is restored from and
 * saved to the vault's provider-state file, attributed to the receipt that
 * last served it.
 */
export async function createGaVaultRequestPipeline(input) {
    const { pool } = input;
    await input.assertAdmission?.();
    await pool.sync();
    const logger = input.runtime.logger.createLogger('request');
    const executor = createRequestExecutor({
        ...gaEngineCollaborators({
            runtime: input.runtime,
            overrides: input.overrides,
            routes: input.routes,
            logger,
        }),
        accounts: pool.selector,
        ...(input.assertAdmission
            ? { assertAdmission: input.assertAdmission }
            : {}),
        credentials: pool.credentials,
        trackers: {
            health: pool.selector.healthTracker,
            token: pool.selector.tokenTracker,
        },
    });
    return {
        execute: async (job, context) => {
            await input.assertAdmission?.();
            await pool.sync();
            return createGaJobExecutor(executor)(job, context);
        },
        rows: () => pool.selector.rows,
        refreshAccounts: async () => {
            await input.assertAdmission?.();
            await pool.refresh();
        },
        async dispose() {
            await executor.dispose();
            await pool.flush();
        },
    };
}
// ---------------------------------------------------------------------------
// Vault custody location
// ---------------------------------------------------------------------------
/**
 * Opaque item and state selectors for vault routes, one per route,
 * credential and asserted account for the life of the activation.
 */
function vaultSelectors(createSelector) {
    const byKey = new Map();
    return (row) => {
        const key = vaultAccountRowKey(row);
        let selector = byKey.get(key);
        if (selector === undefined) {
            selector = createSelector();
            byKey.set(key, selector);
        }
        return selector;
    };
}
/**
 * The `state` source of a vault custody location: the vault's selectable
 * accounts as redaction rows with opaque selectors, read one at a time.
 * Vault rows carry no metadata or access blocks of this plugin's own.
 */
function createGaVaultStateSource(input) {
    let readSeq = 0;
    let queue = Promise.resolve();
    const readOnce = async (scope, signal) => {
        if (signal.aborted)
            throw abortError(signal);
        const rows = input.rows();
        const settings = input.settings();
        const route = input.route(scope);
        if (signal.aborted)
            throw abortError(signal);
        readSeq = input.nextReadSeq?.() ?? readSeq + 1;
        const overLimit = rows.length > ACCOUNT_LIMIT;
        const answer = {
            readSeq,
            accounts: overLimit
                ? { kind: 'over-limit', count: rows.length }
                : {
                    kind: 'complete',
                    rows: rows.map((row, position) => ({
                        selector: input.selectorOf(row),
                        row: {
                            index: position,
                            enabled: row.enabled,
                            current: false,
                            ...(row.coolingDownUntil !== undefined
                                ? { coolingDownUntil: row.coolingDownUntil }
                                : {}),
                            ...(row.cachedQuota !== undefined
                                ? { cachedQuota: row.cachedQuota }
                                : {}),
                        },
                    })),
                },
            route,
            status: {
                checkedAt: null,
                quotaBackoffUntil: null,
                routingAuthoritative: true,
            },
            settings,
        };
        if (input.observe) {
            try {
                input.observe({
                    generation: input.generation,
                    readSeq,
                    status: 'ready',
                    accountsStatus: overLimit ? 'over-limit' : 'complete',
                    accounts: overLimit
                        ? []
                        : rows.map((row, position) => ({
                            selector: input.selectorOf(row),
                            position,
                            enabled: row.enabled,
                            usable: row.enabled,
                            metadataStatus: 'absent',
                            accessBlock: { kind: 'unknown' },
                            currentFor: [],
                            cooldownUntil: row.coolingDownUntil ?? null,
                        })),
                    retiredSelectors: [],
                });
            }
            catch {
                // A diagnostic observer cannot change the answer.
            }
        }
        return answer;
    };
    return {
        read({ scope, signal }) {
            const next = queue.then(() => readOnce(scope, signal), () => readOnce(scope, signal));
            queue = next.catch(() => undefined);
            return next;
        },
    };
}
/**
 * A GA location whose accounts are held by the vault. No local account
 * store is opened. Saved Google logins stay dormant on disk. The vault
 * source is taken from custody, and requests go through
 * `createGaVaultRequestPipeline`, and the menu shows the vault's accounts,
 * this location's settings and the Vault section. The runtime keeps quota
 * snapshots in memory; it gets no account view, so its quota poller and
 * token refresh queue do not run for vault accounts.
 */
async function createGaVaultLocationServices(input) {
    const { custody, overrides } = input;
    await input.assertAdmission?.();
    const source = await custody.custodySource();
    const selectorOf = vaultSelectors(input.bindings.createSelector ?? defaultSelector);
    let pipeline = null;
    let disposed = null;
    return {
        runtime: {
            quotaSnapshots: createMemoryQuotaSnapshots(),
            // Never called: the runtime is given no account view for vault rows,
            // so neither its quota poller nor its refresh queue runs.
            fetchAccountQuota: async (account) => ({
                index: 0,
                email: account.email,
                status: 'error',
                disabled: false,
                error: 'vault accounts are not checked by this location',
            }),
            refreshToken: async () => undefined,
        },
        async start(start) {
            if (disposed)
                throw new Error('The location services are disposed');
            const location = start.runtime;
            const routes = createGaRouteBook();
            const vaultLogger = location.logger.createLogger('vault-state');
            const pool = createVaultAccountPool({
                source,
                durable: {
                    source,
                    readState: () => custody.readState(),
                    onError: (error) => vaultLogger.debug('vault-state-write-dropped', {
                        error: error instanceof Error ? error.name : 'unknown',
                    }),
                },
            });
            pipeline = await createGaVaultRequestPipeline({
                ...(input.assertAdmission
                    ? { assertAdmission: input.assertAdmission }
                    : {}),
                pool,
                runtime: location,
                overrides,
                routes,
            });
            const fetchVaultQuota = input.bindings.fetchVaultQuota;
            const quotaLogger = location.logger.createLogger('vault-quota');
            const checkQuota = fetchVaultQuota
                ? (signal) => checkVaultQuota({
                    pool,
                    fetchReading: async (ref, check) => {
                        await input.assertAdmission?.();
                        return fetchVaultQuota({
                            source,
                            ref,
                            signal: check,
                            logger: quotaLogger,
                            ...(overrides.quotaFetch
                                ? { transport: overrides.quotaFetch }
                                : {}),
                        });
                    },
                    signal,
                    onError: (error) => quotaLogger.debug('vault-quota-not-recorded', {
                        error: error instanceof Error ? error.name : 'unknown',
                    }),
                })
                : undefined;
            const started = pipeline;
            const settings = operatorMenuSettings(location.operatorSettings);
            const menu = createAntigravityCommandMenu({
                source: 'sections',
                commands: await loadCommonAuthCommands(),
                sections: {
                    ...createVaultAccountMenuSections(pool, selectorOf, checkQuota),
                    ...antigravitySettingsSections(settings),
                },
                diagnostics: diagnosticsMenuSection({
                    settings: location.operatorSettings,
                    dump: location.dump,
                    applyLogLevel: () => location.applyOperatorSettings(),
                }),
                extras: [custody.menuSection()],
            });
            input.bindRefresh?.(() => started.refreshAccounts());
            return {
                execute: started.execute,
                state: createGaVaultStateSource({
                    rows: () => started.rows(),
                    selectorOf,
                    ...(input.nextReadSeq ? { nextReadSeq: input.nextReadSeq } : {}),
                    generation: start.generation,
                    settings: () => gaSettingsOf(location.operatorSettings.get(), location.dump),
                    route: (scope) => routes.route(scope),
                    ...(overrides.observeAccountSnapshot
                        ? { observe: overrides.observeAccountSnapshot }
                        : {}),
                }),
                commands: createGaMenuCommandService({
                    menu,
                    notify: start.notify,
                    afterApply: () => input.afterApply ? input.afterApply() : started.refreshAccounts(),
                }),
            };
        },
        dispose() {
            disposed ??= (async () => {
                const active = pipeline;
                pipeline = null;
                input.bindRefresh?.(undefined);
                if (active)
                    await active.dispose();
            })();
            return disposed;
        },
    };
}
export function createGaLocationServicesFactory(bindings) {
    return async ({ directory, overrides }) => {
        const custody = bindings.custody?.({
            accountFile: bindings.resolveAccountFile(directory),
            overrides,
        });
        let closing = false;
        let started = false;
        let disposal;
        // Enrollment selects a binding, not its lifetime. Local files stay unopened
        // until a locally authorized operation needs them, and failures can retry.
        let repositoryPromise;
        let servingRepository;
        let localPromise;
        let vaultPromise;
        let vaultServices;
        let localPipeline;
        let reauthorize;
        let readSeq = 0;
        const inFlight = new Set();
        const run = (work) => {
            if (closing)
                return Promise.reject(new Error('The location services are disposed'));
            const pending = Promise.resolve().then(work);
            inFlight.add(pending);
            void pending.then(() => inFlight.delete(pending), () => inFlight.delete(pending));
            return pending;
        };
        const nextReadSeq = () => ++readSeq;
        const registry = createGaSelectorRegistry(bindings.createSelector);
        const authority = async () => {
            if (!custody)
                return 'local';
            const mode = await custody.readMode();
            return mode.ok
                ? mode.record.mode === 'custody'
                    ? 'vault'
                    : 'local'
                : 'unreadable';
        };
        const assertLocal = async () => {
            if (closing)
                throw new Error('The location services are disposed');
            const selected = await authority();
            if (closing)
                throw new Error('The location services are disposed');
            if (selected !== 'local')
                throw new Error(VAULT_ACCOUNT_REMEDY);
        };
        let refreshVaultBinding;
        const refreshSelectedSource = async () => {
            const selected = await authority();
            if (closing)
                throw new Error('The location services are disposed');
            if (selected === 'unreadable')
                throw new Error(VAULT_ACCOUNT_REMEDY);
            // A menu action may change sources. Refresh only the newly selected
            // account view, keeping both runtime bindings and their generation intact.
            if (selected === 'local') {
                await assertLocal();
                await localPipeline?.refreshAccounts();
            }
            else {
                if (vaultPromise)
                    await vaultPromise;
                await refreshVaultBinding?.();
            }
        };
        const getRepository = async () => {
            await assertLocal();
            repositoryPromise ??= openLocationRepository(directory, bindings, overrides).catch((error) => {
                repositoryPromise = undefined;
                throw error;
            });
            const repository = (await repositoryPromise).repository;
            if (!servingRepository) {
                const methods = new Map();
                const pendingAdmissions = new Set();
                const refusedWrites = [];
                servingRepository = new Proxy(repository, {
                    get(target, key) {
                        const value = Reflect.get(target, key, target);
                        if (typeof value !== 'function')
                            return value;
                        if (!methods.has(key)) {
                            methods.set(key, (...args) => {
                                if (key === 'flush' || key === 'settled' || key === 'dispose') {
                                    return (async () => {
                                        // Calls still awaiting the local-source check have not entered
                                        // the repository's queue. Wait for them before flushing it.
                                        await Promise.allSettled([...pendingAdmissions]);
                                        const result = await Reflect.apply(value, target, args);
                                        if (key !== 'settled' && refusedWrites.length > 0) {
                                            const failures = refusedWrites.splice(0);
                                            throw new AggregateError(failures, 'Local writes were refused by source authority');
                                        }
                                        return result;
                                    })();
                                }
                                const pending = (async () => {
                                    // A refresh that passed the local-source check saves its new
                                    // credentials inside this call. Later operations check again.
                                    try {
                                        await assertLocal();
                                    }
                                    catch (error) {
                                        if (key !== 'read')
                                            refusedWrites.push(error);
                                        throw error;
                                    }
                                    return Reflect.apply(value, target, args);
                                })();
                                pendingAdmissions.add(pending);
                                void pending.then(() => pendingAdmissions.delete(pending), () => pendingAdmissions.delete(pending));
                                return pending;
                            });
                        }
                        return methods.get(key);
                    },
                });
            }
            return servingRepository;
        };
        let runtime;
        try {
            const collaborators = bindings.runtime({
                directory,
                getRepository,
                assertAdmission: assertLocal,
                overrides,
            });
            const previousMayRun = collaborators.mayRun;
            runtime = {
                ...collaborators,
                mayRun: async () => !closing &&
                    (await authority()) === 'local' &&
                    (!previousMayRun || (await previousMayRun())),
            };
        }
        catch (error) {
            await custody?.dispose().catch(() => { });
            throw error;
        }
        return {
            runtime,
            async start(input) {
                if (closing)
                    throw new Error('The location services are disposed');
                if (started)
                    throw new Error('The location services already started');
                started = true;
                const location = input.runtime;
                const settings = operatorMenuSettings(location.operatorSettings);
                const recoveryMenu = createAntigravityCommandMenu({
                    source: 'sections',
                    commands: await loadCommonAuthCommands(),
                    sections: {
                        accounts: {
                            title: 'Accounts',
                            build: async () => ({
                                lines: [
                                    'Account access is unavailable. Open Vault to inspect or recover enrollment.',
                                ],
                                items: [],
                                actions: [],
                            }),
                        },
                        quota: {
                            title: 'Quota',
                            build: async () => ({
                                lines: ['No quota reading is available.'],
                                items: [],
                                actions: [],
                            }),
                        },
                        ...antigravitySettingsSections(settings),
                    },
                    diagnostics: diagnosticsMenuSection({
                        settings: location.operatorSettings,
                        dump: location.dump,
                        applyLogLevel: () => location.applyOperatorSettings(),
                    }),
                    ...(custody ? { extras: [custody.menuSection()] } : {}),
                });
                const recovery = {
                    execute: async () => {
                        throw new Error(VAULT_ACCOUNT_REMEDY);
                    },
                    state: {
                        read: async ({ signal }) => {
                            if (signal.aborted)
                                throw abortError(signal);
                            return {
                                readSeq: nextReadSeq(),
                                accounts: { kind: 'complete', rows: [] },
                                route: null,
                                status: {
                                    checkedAt: null,
                                    quotaBackoffUntil: null,
                                    routingAuthoritative: false,
                                },
                                settings: gaSettingsOf(location.operatorSettings.get(), location.dump),
                            };
                        },
                    },
                    commands: createGaMenuCommandService({
                        menu: recoveryMenu,
                        notify: input.notify,
                    }),
                };
                const local = () => {
                    localPromise ??= (async () => {
                        const repository = await getRepository();
                        const opened = await repositoryPromise;
                        if (!opened)
                            throw new Error('The local repository was not constructed');
                        await assertServingAdmission(opened, bindings.now);
                        await assertLocal();
                        let pipeline;
                        let pendingReauthorization;
                        try {
                            const routes = createGaRouteBook();
                            pipeline = await bindings.createPipeline({
                                repository,
                                runtime: location,
                                send: input.send,
                                generation: input.generation,
                                overrides,
                                routes,
                                assertAdmission: assertLocal,
                            });
                            const started = pipeline;
                            const refreshAccounts = async () => {
                                await assertLocal();
                                await started.refreshAccounts();
                            };
                            pendingReauthorization = createGaReauthorize({
                                repository,
                                assertAdmission: assertLocal,
                                overrides,
                                afterChange: refreshAccounts,
                            });
                            const checkQuota = started.refreshQuota;
                            const menu = createGaLocationMenu({
                                commands: await loadCommonAuthCommands(),
                                repository,
                                runtime: location,
                                reauthorize: pendingReauthorization,
                                ...(custody ? { vault: custody.menuSection() } : {}),
                                ...(checkQuota
                                    ? {
                                        refreshQuota: async (refs) => {
                                            await assertLocal();
                                            return checkQuota(refs);
                                        },
                                    }
                                    : {}),
                            });
                            localPipeline = started;
                            reauthorize = pendingReauthorization;
                            return {
                                state: createGaAccountStateSource({
                                    repository,
                                    registry,
                                    generation: input.generation,
                                    nextReadSeq,
                                    settings: () => gaSettingsOf(location.operatorSettings.get(), location.dump),
                                    status: () => ({
                                        checkedAt: null,
                                        quotaBackoffUntil: null,
                                        routingAuthoritative: true,
                                    }),
                                    route: (scope) => routes.route(scope),
                                    ...(overrides.observeAccountSnapshot
                                        ? { observe: overrides.observeAccountSnapshot }
                                        : {}),
                                }),
                                commands: createGaMenuCommandService({
                                    menu,
                                    notify: input.notify,
                                    afterApply: () => refreshSelectedSource(),
                                }),
                                execute: started.execute,
                            };
                        }
                        catch (error) {
                            await pendingReauthorization?.dispose().catch(() => { });
                            await pipeline?.dispose().catch(() => { });
                            await location.replaceAccounts(null).catch(() => { });
                            throw error;
                        }
                    })().catch((error) => {
                        localPromise = undefined;
                        throw error;
                    });
                    return localPromise;
                };
                const vault = () => {
                    if (!custody)
                        return Promise.reject(new Error('Vault custody is unavailable'));
                    vaultPromise ??= (async () => {
                        const created = await createGaVaultLocationServices({
                            custody,
                            overrides,
                            bindings,
                            nextReadSeq,
                            afterApply: refreshSelectedSource,
                            bindRefresh: (refresh) => {
                                refreshVaultBinding = refresh;
                            },
                            assertAdmission: async () => {
                                const selected = await authority();
                                if (closing || selected !== 'vault')
                                    throw new Error(VAULT_ACCOUNT_REMEDY);
                            },
                        });
                        try {
                            const serving = await created.start(input);
                            vaultServices = created;
                            return serving;
                        }
                        catch (error) {
                            await created.dispose().catch(() => { });
                            throw error;
                        }
                    })().catch((error) => {
                        vaultPromise = undefined;
                        throw error;
                    });
                    return vaultPromise;
                };
                const choose = async (purpose) => {
                    if (closing)
                        throw new Error('The location services are disposed');
                    const selected = await authority();
                    if (closing)
                        throw new Error('The location services are disposed');
                    if (selected === 'local')
                        return local();
                    if (selected === 'unreadable') {
                        if (purpose === 'execute')
                            throw new Error(VAULT_ACCOUNT_REMEDY);
                        return recovery;
                    }
                    try {
                        return await vault();
                    }
                    catch (error) {
                        if (purpose === 'execute')
                            throw error;
                        return recovery;
                    }
                };
                let reads = Promise.resolve();
                return {
                    execute: (job, context) => run(async () => {
                        if (context.signal.aborted)
                            throw context.signal.reason;
                        return (await choose('execute')).execute(job, context);
                    }),
                    commands: {
                        apply: (request) => run(async () => {
                            if (request.signal.aborted)
                                throw request.signal.reason;
                            return (await choose('view')).commands.apply(request);
                        }),
                        open: (request) => run(async () => {
                            if (request.signal.aborted)
                                throw request.signal.reason;
                            return (await choose('view')).commands.open(request);
                        }),
                    },
                    state: {
                        read(request) {
                            return run(() => {
                                const pending = reads.then(async () => {
                                    if (closing)
                                        throw new Error('The location services are disposed');
                                    if (request.signal.aborted)
                                        throw request.signal.reason;
                                    for (let attempt = 0; attempt < 2; attempt++) {
                                        const before = await authority();
                                        const answer = await (await choose('view')).state.read(request);
                                        if (before === (await authority()))
                                            return answer;
                                    }
                                    throw new Error('Account authority changed while reading state');
                                });
                                reads = pending.catch(() => undefined);
                                return pending;
                            });
                        },
                    },
                };
            },
            dispose() {
                closing = true;
                disposal ??= (async () => {
                    await Promise.allSettled([
                        localPromise,
                        vaultPromise,
                        repositoryPromise,
                    ]);
                    try {
                        const resources = Promise.allSettled([
                            reauthorize?.dispose(),
                            localPipeline?.dispose(),
                            vaultServices?.dispose(),
                        ]);
                        await Promise.allSettled([...inFlight]);
                        const results = await resources;
                        while (inFlight.size > 0)
                            await Promise.allSettled([...inFlight]);
                        const failure = results.find((result) => result.status === 'rejected');
                        if (failure?.status === 'rejected')
                            throw failure.reason;
                    }
                    finally {
                        try {
                            await custody?.dispose();
                        }
                        finally {
                            const opened = await repositoryPromise?.catch(() => undefined);
                            await opened?.repository.dispose();
                        }
                    }
                })();
                return disposal;
            },
        };
    };
}
/**
 * The runtime collaborators of a repository-backed GA location: quota
 * snapshots kept in memory (a GA location writes no sidebar file), the
 * ref-attributed quota fetcher, and a token refresher that refreshes the
 * account it is handed through this activation's manager.
 */
export function createGaRuntimeCollaborators(input) {
    return {
        quotaSnapshots: createMemoryQuotaSnapshots(),
        fetchAccountQuota: async (account, signal) => {
            const repository = await input.getRepository();
            return createGaFetchAccountQuota({
                repository,
                ...(input.assertAdmission
                    ? { assertAdmission: input.assertAdmission }
                    : {}),
                now: input.now,
                overrides: input.overrides,
                logger: {
                    debug: (...args) => input.accounts.quotaLogger?.debug(...args),
                },
            })(account, signal);
        },
        refreshToken: async (_auth, account) => {
            const manager = input.accounts.current;
            if (manager === null || !manager.getAccounts().includes(account))
                return undefined;
            const outcome = await manager.refreshAccount(account);
            return outcome.status === 'rotated'
                ? manager.toAuthDetails(account)
                : undefined;
        },
    };
}
/**
 * The production GA location services: the embedded common-auth store,
 * the system clock, the repository-backed request pipeline and the
 * collaborators above. Every activation gets its own repository, account
 * slot and pipeline. With `vault`, a location can also serve the vault's
 * accounts: its mode file decides, and the menu's Vault section switches.
 */
export function createGaLocationServicesForHost(vault) {
    return (input) => {
        const accounts = { current: null, quotaLogger: null };
        return createGaLocationServicesFactory({
            loadStoreModules: loadCommonAuthStoreModules,
            resolveAccountFile: getStoragePath,
            now: Date.now,
            runtime: ({ getRepository, assertAdmission, overrides }) => createGaRuntimeCollaborators({
                getRepository,
                assertAdmission,
                overrides,
                accounts,
                now: Date.now,
            }),
            createPipeline: (pipeline) => createGaLocalRequestPipeline({ ...pipeline, accounts }),
            ...(vault
                ? {
                    custody: ({ accountFile }) => createOpenCodeVaultCustody({
                        accountFile,
                        readHostSlot: vault.readHostSlot,
                        ...(vault.connectionFile
                            ? { connectionFile: vault.connectionFile }
                            : {}),
                        // The engine reads each send's HTTP status itself.
                        reporterSource: 'direct',
                    }),
                }
                : {}),
        })(input);
    };
}
/** The connection API belongs to this setup context, not a module-wide host. */
export const createGaLocationServices = (input) => {
    const readHostSlot = input.connections
        ? createGaHostSlotReader(input.connections, 'google')
        : async () => {
            throw new Error('The host integration connection API is unavailable');
        };
    return createGaLocationServicesForHost({ readHostSlot })(input);
};
//# sourceMappingURL=ga-location-services.js.map