/**
 * Vault-held accounts for the shared request engine, used by OpenCode 1 and
 * OpenCode 2 alike: selection rows built from the vault's selectable routes,
 * the engine's `vault` credential domain over a vault account source, and
 * the rows' durable selection state in the vault's credential-free
 * provider-state file.
 *
 * A row carries the route and selection bookkeeping only; no token, refresh
 * token, project or local repository reference. Every physical send asks
 * the source for a fresh receipt for the selected row's route and uses that
 * receipt's token and project for that send only; a 401 is reported against
 * the exact receipt that served it. Nothing is refreshed locally, cached or
 * written to a row.
 *
 * The module imports no host SDK and no composition root: the source is the
 * core vault account source (or anything with the same operations).
 */
import { AccountSelector, } from '@cortexkit/antigravity-auth-core';
/**
 * Selection rows for the vault's selectable routes, in roster order, with
 * no selection history.
 */
export function vaultAccountRows(routes) {
    return routes.map((route, index) => ({
        index,
        enabled: true,
        lastUsed: 0,
        rateLimitResetTimes: {},
        touchedForQuota: {},
        route,
        ...(route.email !== undefined ? { email: route.email } : {}),
    }));
}
/**
 * A vault row's identity for `AccountSelector.replaceAccounts`: its route,
 * credential and asserted account. A route that now names another
 * credential or account is a different row.
 */
export function vaultAccountRowKey(row) {
    return JSON.stringify([
        row.route.routeId,
        row.route.credentialId,
        row.route.accountIdentity,
    ]);
}
/**
 * Keeps a vault row's in-memory selection state across a roster re-read and
 * takes only the route's display fields from the fresh roster. A kept row's
 * in-memory state is the newest there is; stored state (see
 * `createVaultSelectionState`) is restored only onto rows that are new.
 */
export function refreshVaultAccountRow(prior, fresh) {
    prior.route = fresh.route;
    if (fresh.email === undefined)
        delete prior.email;
    else
        prior.email = fresh.email;
}
/**
 * One physical send's grant from one vault receipt. The access token is a
 * non-enumerable property, as the source served it, so spreading or
 * serializing a grant never copies it.
 */
class VaultSendGrant {
    credentialId;
    accountIdentity;
    recordVersion;
    projectId;
    report401;
    constructor(admission, report) {
        Object.defineProperty(this, 'accessToken', {
            value: admission.accessToken,
            enumerable: false,
        });
        this.credentialId = admission.credentialId;
        this.accountIdentity = admission.accountIdentity;
        this.recordVersion = admission.recordVersion;
        this.projectId = admission.projectId;
        this.report401 = report;
    }
}
/**
 * The shared engine's `vault` credential domain over a vault account source.
 * `onAdmitted` receives each receipt's non-secret attribution, taken by the
 * same source, with the row it was taken for (see
 * `createVaultSelectionState`).
 */
export function createVaultRequestCredentials(source, onAdmitted) {
    return {
        domain: 'vault',
        async admit({ account, signal }) {
            const admission = await source.admit(account.route, signal);
            if (onAdmitted)
                onAdmitted.admitted(account, onAdmitted.source.attribution(admission));
            return new VaultSendGrant(admission, (status) => source.reportServedStatus(admission, status));
        },
    };
}
function present(value) {
    return value === null ? undefined : value;
}
function storedResets(resets) {
    const stored = {};
    for (const [key, at] of Object.entries(resets))
        if (typeof at === 'number')
            stored[key] = at;
    return stored;
}
/** The row's quota groups from a stored quota reading. */
function cachedQuotaOf(quota) {
    const groups = quota.cachedQuota;
    if (groups == null)
        return undefined;
    const out = {};
    for (const name of ['gemini', 'non-gemini']) {
        const group = groups[name];
        if (group === undefined)
            continue;
        out[name] = {
            modelCount: group.modelCount,
            ...(group.remainingFraction != null
                ? { remainingFraction: group.remainingFraction }
                : {}),
            ...(group.resetTime != null ? { resetTime: group.resetTime } : {}),
            ...(group.windows != null
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
/** The row's durable selection fields as provider metadata. */
function durableSelectionOf(row) {
    return {
        lastUsed: row.lastUsed,
        ...(row.lastSwitchReason !== undefined
            ? { lastSwitchReason: row.lastSwitchReason }
            : {}),
        rateLimitResetTimes: storedResets(row.rateLimitResetTimes),
        ...(row.coolingDownUntil !== undefined
            ? { coolingDownUntil: row.coolingDownUntil }
            : {}),
        ...(row.cooldownReason !== undefined
            ? { cooldownReason: row.cooldownReason }
            : {}),
        ...(row.fingerprint !== undefined
            ? { fingerprint: structuredClone(row.fingerprint) }
            : {}),
        ...(row.fingerprintHistory !== undefined
            ? { fingerprintHistory: structuredClone(row.fingerprintHistory) }
            : {}),
        ...(row.verificationRequired !== undefined
            ? { verificationRequired: row.verificationRequired }
            : {}),
        ...(row.verificationRequiredAt !== undefined
            ? { verificationRequiredAt: row.verificationRequiredAt }
            : {}),
        ...(row.verificationRequiredReason !== undefined
            ? { verificationRequiredReason: row.verificationRequiredReason }
            : {}),
        ...(row.verificationUrl !== undefined
            ? { verificationUrl: row.verificationUrl }
            : {}),
        ...(row.accountIneligible !== undefined
            ? { accountIneligible: row.accountIneligible }
            : {}),
        ...(row.accountIneligibleAt !== undefined
            ? { accountIneligibleAt: row.accountIneligibleAt }
            : {}),
        ...(row.accountIneligibleReason !== undefined
            ? { accountIneligibleReason: row.accountIneligibleReason }
            : {}),
        ...(row.eligibilityStateUpdatedAt !== undefined
            ? { eligibilityStateUpdatedAt: row.eligibilityStateUpdatedAt }
            : {}),
        ...(row.dailyRequestCounts !== undefined
            ? { dailyRequestCounts: { ...row.dailyRequestCounts } }
            : {}),
    };
}
/** Puts stored selection fields onto a fresh row. */
function applyDurableSelection(row, metadata) {
    row.lastUsed = metadata.lastUsed;
    const reason = present(metadata.lastSwitchReason);
    if (reason !== undefined)
        row.lastSwitchReason = reason;
    const resets = present(metadata.rateLimitResetTimes);
    if (resets !== undefined) {
        const copy = {};
        for (const [key, at] of Object.entries(resets))
            if (typeof at === 'number')
                copy[key] = at;
        row.rateLimitResetTimes = copy;
    }
    const until = present(metadata.coolingDownUntil);
    const cooldownReason = present(metadata.cooldownReason);
    if (until !== undefined && cooldownReason !== undefined) {
        row.coolingDownUntil = until;
        row.cooldownReason = cooldownReason;
    }
    const fingerprint = present(metadata.fingerprint);
    if (fingerprint !== undefined)
        row.fingerprint = structuredClone(fingerprint);
    const history = present(metadata.fingerprintHistory);
    if (history !== undefined)
        row.fingerprintHistory = structuredClone(history);
    const verification = present(metadata.verificationRequired);
    if (verification !== undefined)
        row.verificationRequired = verification;
    const verificationAt = present(metadata.verificationRequiredAt);
    if (verificationAt !== undefined)
        row.verificationRequiredAt = verificationAt;
    const verificationReason = present(metadata.verificationRequiredReason);
    if (verificationReason !== undefined)
        row.verificationRequiredReason = verificationReason;
    const verificationUrl = present(metadata.verificationUrl);
    if (verificationUrl !== undefined)
        row.verificationUrl = verificationUrl;
    const ineligible = present(metadata.accountIneligible);
    if (ineligible !== undefined)
        row.accountIneligible = ineligible;
    const ineligibleAt = present(metadata.accountIneligibleAt);
    if (ineligibleAt !== undefined)
        row.accountIneligibleAt = ineligibleAt;
    const ineligibleReason = present(metadata.accountIneligibleReason);
    if (ineligibleReason !== undefined)
        row.accountIneligibleReason = ineligibleReason;
    const eligibilityAt = present(metadata.eligibilityStateUpdatedAt);
    if (eligibilityAt !== undefined)
        row.eligibilityStateUpdatedAt = eligibilityAt;
    const counts = present(metadata.dailyRequestCounts);
    if (counts !== undefined)
        row.dailyRequestCounts = { ...counts };
}
/** Whether stored state was written for exactly this row's route and credential. */
function stateBelongsTo(state, row) {
    return (state.observed.routeId === row.route.routeId &&
        state.observed.credentialId === row.route.credentialId);
}
/**
 * Durable selection state for vault rows, kept in the vault source's
 * credential-free provider-state file by asserted account. The selector
 * stays the only selection policy: this only saves and restores the fields
 * it already maintains.
 */
export function createVaultSelectionState(options) {
    const now = options.now ?? (() => Date.now());
    const attributions = new WeakMap();
    const changed = new Set();
    let writing = Promise.resolve();
    const mark = (row) => {
        changed.add(row);
    };
    const report = (error) => {
        try {
            options.onError?.(error);
        }
        catch {
            // A diagnostic callback cannot change what was written.
        }
    };
    const writeRow = async (row) => {
        const attribution = attributions.get(row);
        if (attribution === undefined)
            return;
        changed.delete(row);
        const selection = durableSelectionOf(row);
        try {
            await options.source.commitState(attribution, (current) => ({
                metadata: {
                    ...(current?.metadata ?? { addedAt: now() }),
                    ...selection,
                },
                ...(current?.quota !== undefined ? { quota: current.quota } : {}),
                ...(current?.extensions !== undefined
                    ? { extensions: current.extensions }
                    : {}),
            }));
        }
        catch (error) {
            report(error);
        }
    };
    const flush = () => {
        writing = writing.then(async () => {
            for (const row of [...changed])
                await writeRow(row);
        });
        return writing;
    };
    return {
        sink: {
            rateLimit: mark,
            cooldown: mark,
            switched: mark,
            lastUsed: mark,
            usage: mark,
            accessVerdict: mark,
            fingerprint: mark,
            requestSave: () => {
                void flush();
            },
        },
        admitted(row, attribution) {
            attributions.set(row, attribution);
        },
        async hydrate(rows) {
            const file = await options.readState();
            for (const row of rows) {
                const identity = row.route.accountIdentity;
                if (!Object.hasOwn(file.accounts, identity))
                    continue;
                const state = file.accounts[identity];
                if (state === undefined || !stateBelongsTo(state, row))
                    continue;
                if (state.metadata !== undefined)
                    applyDurableSelection(row, state.metadata);
                if (state.quota !== undefined) {
                    const cached = cachedQuotaOf(state.quota);
                    if (cached !== undefined)
                        row.cachedQuota = cached;
                    const updatedAt = present(state.quota.cachedQuotaUpdatedAt);
                    if (updatedAt !== undefined)
                        row.cachedQuotaUpdatedAt = updatedAt;
                }
            }
        },
        flush,
        recordQuota(attribution, quota) {
            return options.source.commitState(attribution, (current) => ({
                ...(current?.metadata !== undefined
                    ? { metadata: current.metadata }
                    : {}),
                quota,
                ...(current?.extensions !== undefined
                    ? { extensions: current.extensions }
                    : {}),
            }));
        },
    };
}
export function createVaultAccountPool(options) {
    const { source, durable } = options;
    const state = durable
        ? createVaultSelectionState({
            source: durable.source,
            readState: durable.readState,
            ...(options.now ? { now: options.now } : {}),
            ...(durable.onError ? { onError: durable.onError } : {}),
        })
        : undefined;
    const selector = new AccountSelector({
        ...(options.now ? { now: options.now } : {}),
        ...(state ? { sink: state.sink } : {}),
    });
    const credentials = createVaultRequestCredentials(source, state && durable
        ? {
            source: durable.source,
            admitted: (row, attribution) => state.admitted(row, attribution),
        }
        : undefined);
    /** Fresh rows for the source's routes, with stored state on new ones. */
    const rowsFromSource = async () => {
        const rows = vaultAccountRows(source.routes());
        if (state) {
            const kept = new Set(selector.rows.map(vaultAccountRowKey));
            const added = rows.filter((row) => !kept.has(vaultAccountRowKey(row)));
            if (added.length > 0)
                await state.hydrate(added);
        }
        return rows;
    };
    const replace = async () => {
        selector.replaceAccounts(await rowsFromSource(), {
            keyOf: vaultAccountRowKey,
            refresh: refreshVaultAccountRow,
        });
    };
    let firstRead = null;
    const readOnce = () => {
        firstRead ??= (async () => {
            await source.refresh();
            selector.resetAccounts(await rowsFromSource());
        })().catch((error) => {
            firstRead = null;
            throw error;
        });
        return firstRead;
    };
    return {
        selector,
        credentials,
        state,
        async sync() {
            const pending = firstRead;
            await readOnce();
            // The first read just installed the rows; later calls re-sync.
            if (pending !== null)
                await replace();
        },
        async refresh() {
            await readOnce();
            await source.refresh();
            await replace();
        },
        flush: async () => {
            await state?.flush();
        },
    };
}
/** The stored quota reading for a summary taken at `at`. */
export function vaultQuotaState(quota, at) {
    const cachedQuota = {};
    for (const [name, group] of Object.entries(quota.groups)) {
        if (group === undefined)
            continue;
        cachedQuota[name] = {
            modelCount: group.modelCount,
            ...(group.remainingFraction !== undefined
                ? { remainingFraction: group.remainingFraction }
                : {}),
            ...(group.resetTime !== undefined ? { resetTime: group.resetTime } : {}),
            ...(group.windows !== undefined
                ? { windows: group.windows.map((window) => ({ ...window })) }
                : {}),
        };
    }
    return { schemaVersion: 1, cachedQuota, cachedQuotaUpdatedAt: at };
}
/**
 * Checks quota for every row of a durable vault pool and records each
 * reading through the source's provider-state commit, attributed to the
 * admission that produced it. A row counts as checked only when its reading
 * was written; a reading with an error, without an attribution, or whose
 * write the source refuses (another credential, account or a newer record
 * version) is not checked and is not shown. A written reading is also put
 * on the row that is still at that route, credential and account. An
 * aborted `signal` stops the check; the remaining rows are not checked.
 */
export async function checkVaultQuota(input) {
    const state = input.pool.state;
    const rows = [...input.pool.selector.rows];
    const now = input.now ?? (() => Date.now());
    let checked = 0;
    for (const row of rows) {
        if (input.signal.aborted || state === undefined)
            break;
        try {
            const answer = await input.fetchReading(row.route, input.signal);
            const attribution = answer.quotaAttribution;
            if (attribution === undefined || answer.quota.error !== undefined)
                continue;
            const reading = vaultQuotaState(answer.quota, now());
            const result = await state.recordQuota(attribution, reading);
            if (result.status !== 'written')
                continue;
            checked += 1;
            const live = input.pool.selector.rows.find((candidate) => candidate.route.routeId === attribution.routeId &&
                candidate.route.credentialId === attribution.credentialId &&
                candidate.route.accountIdentity === attribution.accountIdentity);
            if (live !== undefined) {
                const cached = cachedQuotaOf(reading);
                if (cached !== undefined)
                    live.cachedQuota = cached;
                live.cachedQuotaUpdatedAt = reading.cachedQuotaUpdatedAt ?? undefined;
            }
        }
        catch (error) {
            try {
                input.onError?.(error);
            }
            catch {
                // A diagnostic callback cannot change the report.
            }
        }
    }
    return { checked, notChecked: rows.length - checked };
}
//# sourceMappingURL=vault-request-credentials.js.map