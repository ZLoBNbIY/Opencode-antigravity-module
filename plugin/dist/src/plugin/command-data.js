/**
 * Privacy-safe data service for the data-first slash-command dialogs.
 *
 * `/antigravity-quota` (this task) and the future `/antigravity-account`
 * dialogs (Tasks 10-11) read from a single shared service so they
 * never touch raw account storage, never see the email PII field, and
 * never run quota network I/O during the dialog's open path — the
 * Refresh action is the only path that performs a live fetch.
 *
 * Why this is a separate module:
 *
 * - `commands.ts` owns the slash-command orchestration; mixing the row
 *   projection + quota refresh logic in there would balloon the surface
 *   for what is fundamentally a small read/refresh service.
 * - The row type (`CommandAccountRow`) is the projection that crosses
 *   the PII firewall into the dialog payload. Defining it here (next
 *   to the code that constructs it) keeps the firewall reviewable.
 * - Tests can pin the read-vs-refresh boundary, the email redaction, and
 *   the refresh-token-keyed persistence in one file rather than chasing
 *   them across the dispatcher + RPC + apply layers.
 *
 * Cache-only opening contract (Task 9 operator requirement):
 *
 *   `listAccounts()` is a pure read of the live AccountManager view
 *   the auth-loader materialized at session start. It performs
 *   ZERO quota manager calls — opening the dialog must be instant even
 *   when the network is unreachable, and quota refresh must remain an
 *   explicit user-driven action so the cached percentages never quietly
 *   rewrite themselves behind the user's back.
 *
 * Refresh-token-keyed persistence (Task 9 plan trap):
 *
 *   `refreshQuota()` runs the shared quota manager across every enabled
 *   account and folds the results back into the live AccountManager +
 *   storage. Concurrent OAuth can renumber the flat `accounts[]` array
 *   between read and write, so we re-read under the lock and key the
 *   update by `refreshToken` (the canonical identity) rather than the
 *   array index. This way a successful OAuth add that lands between
 *   the read and the write cannot cause the refresh to overwrite the
 *   wrong account.
 */
import { createHash } from 'node:crypto';
import { buildSidebarMachineStateFromAccounts, normalizeLegacyCachedQuota, setSidebarMachineState, toCapturedTier, } from '../sidebar-state';
/**
 * Quota display label for each supported quota group. Kept here so the
 * dialog and the quota manager agree on the same vocabulary.
 */
const QUOTA_GROUP_LABELS = {
    gemini: 'Gemini',
    'non-gemini': 'Non-Gemini',
};
const SUPPORTED_QUOTA_KEYS = [
    'gemini',
    'non-gemini',
];
function toCommandAccountRow(entry) {
    // Stamp mismatch: the cached quota was captured for a different account
    // (the refresh token changed, or an index shift placed another account's
    // snapshot at this position). Drop the stale cache rather than rendering
    // the wrong account's quota percentages.
    const rawCached = entry.cachedQuotaAccountId &&
        entry.cachedQuotaAccountId !== quotaAccountIdentity(entry.refreshToken)
        ? undefined
        : entry.cachedQuota;
    // Normalize legacy pool keys (gemini-pro, gemini-flash, claude, gpt-oss)
    // to canonical keys before the SUPPORTED_QUOTA_KEYS loop. Without this
    // a legacy snapshot produces empty quota rows, and writeSidebar would
    // permanently re-emit legacy keys on every dialog open until the next
    // real quota refresh rewrites the on-disk snapshot.
    const cached = normalizeLegacyCachedQuota(rawCached);
    const quota = [];
    for (const key of SUPPORTED_QUOTA_KEYS) {
        const cachedEntry = cached?.[key];
        if (!cachedEntry)
            continue;
        const fraction = cachedEntry.remainingFraction;
        const remainingPercent = typeof fraction === 'number' && Number.isFinite(fraction)
            ? Math.round(fraction * 100)
            : null;
        let resetAt;
        if (typeof cachedEntry.resetTime === 'string' &&
            cachedEntry.resetTime.length > 0) {
            const parsed = Date.parse(cachedEntry.resetTime);
            if (Number.isFinite(parsed))
                resetAt = parsed;
        }
        // Carry per-window breakdown when the cache was populated from the
        // windowed RUQS path — the sidebar writer projects through here.
        const windows = cachedEntry.windows?.length
            ? cachedEntry.windows.map((w) => ({
                window: w.window,
                remainingPercent: Math.round(w.remainingFraction * 100),
                resetAt: typeof w.resetTime === 'string' && w.resetTime.length > 0
                    ? (() => {
                        const parsed = Date.parse(w.resetTime);
                        return Number.isFinite(parsed) ? parsed : undefined;
                    })()
                    : undefined,
            }))
            : undefined;
        quota.push({
            key,
            label: QUOTA_GROUP_LABELS[key],
            remainingPercent,
            resetAt,
            windows,
        });
    }
    const label = `Account ${entry.index + 1}`;
    return {
        id: `acct-${entry.index}`,
        index: entry.index,
        label,
        enabled: entry.enabled,
        current: entry.active,
        coolingDownUntil: entry.coolingDownUntil,
        healthScore: entry.healthScore,
        cachedQuotaUpdatedAt: entry.cachedQuotaUpdatedAt,
        quota,
        tier: toCapturedTier(entry),
    };
}
/**
 * Opaque identity derived from a refresh token. Antigravity refresh tokens
 * are stable (they do not rotate), so this hash is a durable, prunable
 * identity to detect a stale cached quota after an account-index shift.
 */
function quotaAccountIdentity(refreshToken) {
    return createHash('sha256').update(refreshToken).digest('hex').slice(0, 16);
}
export function projectCommandAccountRows(storage) {
    if (!storage)
        return [];
    const activeIndex = storage.activeIndexByFamily?.claude ?? storage.activeIndex;
    return storage.accounts.map((entry, index) => toCommandAccountRow({
        index,
        refreshToken: entry.refreshToken,
        label: entry.label,
        enabled: entry.enabled !== false,
        active: index === activeIndex,
        cachedQuota: entry.cachedQuota,
        cachedQuotaUpdatedAt: entry.cachedQuotaUpdatedAt,
        cachedQuotaAccountId: entry.cachedQuotaAccountId,
    }));
}
/**
 * Build the data service.
 *
 * The factory form (instead of a module-level singleton) keeps the
 * service unit-testable: each test constructs its own dependencies
 * (storage stub, quota manager stub, fixed clock) without touching
 * the production quota path.
 */
export function createCommandDataService(options) {
    const { accountManagerView, quotaManager, sidebarStateFile, storage, now = () => Date.now(), } = options;
    const projectRows = () => accountManagerView.getAccounts().map(toCommandAccountRow);
    // Map a CommandAccountRow back to the SidebarAccountRedactionInput shape.
    // Extracted to prevent the "sixth dropped field" pattern: every field in
    // CommandAccountRow that must reach the sidebar lives here once, not as an
    // inline literal that a future author has to remember to update in two places.
    const toRedactionInput = (row) => {
        const gemini = row.quota.find((q) => q.key === 'gemini');
        const nonGemini = row.quota.find((q) => q.key === 'non-gemini');
        // Map a CommandAccountRow quota entry to cachedQuota pool shape
        // so projectQuotaPoolForSidebar (the canonical projection seam)
        // carries the per-window breakdown into the sidebar state.
        const toPool = (q) => {
            if (!q || q.remainingPercent == null)
                return undefined;
            return {
                remainingFraction: q.remainingPercent / 100,
                resetTime: typeof q.resetAt === 'number' && Number.isFinite(q.resetAt)
                    ? new Date(q.resetAt).toISOString()
                    : undefined,
                windows: q.windows?.map((w) => ({
                    window: w.window,
                    remainingFraction: w.remainingPercent / 100,
                    resetTime: typeof w.resetAt === 'number' && Number.isFinite(w.resetAt)
                        ? new Date(w.resetAt).toISOString()
                        : '',
                })),
            };
        };
        return {
            index: row.index,
            label: row.label,
            enabled: row.enabled,
            current: row.current,
            healthScore: row.healthScore,
            // Tier passes the redaction boundary unchanged (plan metadata, not PII).
            // The stamp check was already done by toCommandAccountRow.
            tier: row.tier,
            cachedQuotaUpdatedAt: row.cachedQuotaUpdatedAt,
            cachedQuota: {
                gemini: toPool(gemini),
                'non-gemini': toPool(nonGemini),
            },
        };
    };
    const writeSidebar = (rows) => {
        const accounts = rows.map(toRedactionInput);
        // Fire-and-forget -- the sidebar writer is fenced by its own queue,
        // so a transient lock contention cannot block the dialog response.
        void setSidebarMachineState(buildSidebarMachineStateFromAccounts(accounts, { checkedAt: now() }), { stateFile: sidebarStateFile }).catch(() => {
            // Sidebar writes are best-effort; the next command or quota refresh
            // will publish the current snapshot.
        });
    };
    return {
        async listAccounts() {
            return projectRows();
        },
        async refreshQuota() {
            const accountsForQuota = accountManagerView.getAccountsForQuotaCheck();
            if (accountsForQuota.length === 0) {
                // Empty pool: still push a clean sidebar so the TUI drops any
                // stale snapshot left over from a previous session.
                writeSidebar([]);
                return [];
            }
            const results = await quotaManager.refreshAccounts(accountsForQuota, {
                indexFor: (account) => accountsForQuota.indexOf(account),
                force: true,
            });
            const refreshedAt = now();
            const updates = [];
            for (const result of results) {
                const refreshToken = result.updatedAccount?.refreshToken ??
                    accountsForQuota[result.index]?.refreshToken;
                if (!refreshToken)
                    continue;
                const groups = result.status === 'ok' && result.quota?.groups
                    ? result.quota.groups
                    : undefined;
                updates.push({ refreshToken, groups });
            }
            // Resolve live indexes only after the network request. Numeric indexes
            // from the quota result refer to the original input array and may now
            // identify a different account after a concurrent add/remove.
            const liveIndexByRefreshToken = new Map();
            for (const entry of accountManagerView.getAccounts()) {
                liveIndexByRefreshToken.set(entry.refreshToken, entry.index);
            }
            let liveQuotaChanged = false;
            for (const update of updates) {
                const liveIndex = liveIndexByRefreshToken.get(update.refreshToken);
                if (liveIndex === undefined || !update.groups)
                    continue;
                accountManagerView.updateQuotaCache(liveIndex, update.groups, update.refreshToken);
                liveQuotaChanged = true;
            }
            if (liveQuotaChanged)
                accountManagerView.requestSaveToDisk();
            // Persist by canonical refresh token against the latest locked snapshot.
            // A removed account is skipped rather than falling back to its old index.
            if (storage) {
                const updateByRefreshToken = new Map(updates.map((update) => [update.refreshToken, update]));
                const writeResult = storage.mutate((current) => ({
                    ...current,
                    accounts: current.accounts.map((entry) => {
                        const update = updateByRefreshToken.get(entry.refreshToken);
                        if (!update)
                            return entry;
                        if (update.groups) {
                            return {
                                ...entry,
                                cachedQuota: update.groups,
                                // Stamp the persisted quota with an opaque identity derived
                                // from the refresh token so a later projection can detect
                                // a stale snapshot after an account-index shift.
                                cachedQuotaAccountId: quotaAccountIdentity(entry.refreshToken),
                                cachedQuotaUpdatedAt: refreshedAt,
                            };
                        }
                        // Error result keeps the previous cached percentage and only
                        // records that a refresh was attempted.
                        return {
                            ...entry,
                            cachedQuotaUpdatedAt: refreshedAt,
                        };
                    }),
                }));
                await Promise.resolve(writeResult).catch(() => {
                    // The live AccountManager already carries successful refreshes; its
                    // next save can reconcile a transient storage-lock failure.
                });
            }
            // Re-read the live view post-mutate so the rows reflect the
            // freshly persisted percentages.
            const rows = projectRows();
            writeSidebar(rows);
            return rows;
        },
        async refreshQuotaRespectingBackoff() {
            const accountsForQuota = accountManagerView.getAccountsForQuotaCheck();
            if (accountsForQuota.length === 0)
                return;
            // Non-forced: the quota manager's per-account backoff and dedup
            // apply. Accounts that are fresh or in backoff are skipped. Unlike
            // the earlier fire-and-forget path, successful results ARE folded
            // into the live cache so the sidebar snapshot reflects fresh data
            // immediately — the dialog renders ONLY from the sidebar file, and
            // the quota manager's push path does not update AccountManager
            // entries for this caller.
            let results;
            try {
                results = await quotaManager.refreshAccounts(accountsForQuota, {
                    indexFor: (account) => accountsForQuota.indexOf(account),
                    force: false,
                });
            }
            catch {
                // Non-critical: dialog open must never fail because a background
                // refresh check encountered backoff or a transient error.
                return;
            }
            // Build updates akin to the forced refresh path — resolve live
            // indexes after the network call (a concurrent add/remove may have
            // shifted positions), fold successful results into the live cache,
            // then push a sidebar snapshot.
            const updates = [];
            for (const result of results) {
                const refreshToken = result.updatedAccount?.refreshToken ??
                    accountsForQuota[result.index]?.refreshToken;
                if (!refreshToken)
                    continue;
                const groups = result.status === 'ok' && result.quota?.groups
                    ? result.quota.groups
                    : undefined;
                updates.push({ refreshToken, groups });
            }
            if (updates.length === 0)
                return;
            const liveIndexByRefreshToken = new Map();
            for (const entry of accountManagerView.getAccounts()) {
                liveIndexByRefreshToken.set(entry.refreshToken, entry.index);
            }
            let liveQuotaChanged = false;
            for (const update of updates) {
                const liveIndex = liveIndexByRefreshToken.get(update.refreshToken);
                if (liveIndex === undefined || !update.groups)
                    continue;
                accountManagerView.updateQuotaCache(liveIndex, update.groups, update.refreshToken);
                liveQuotaChanged = true;
            }
            if (liveQuotaChanged)
                accountManagerView.requestSaveToDisk();
            // Push a fresh sidebar snapshot — the live view now carries the
            // just-refreshed quota plus any skipped (backoff/fresh) accounts
            // whose cached percentages are unchanged.
            const rows = projectRows();
            writeSidebar(rows);
        },
        async setCurrentAccount(index) {
            return mutateLiveAndStorage({ action: 'setCurrent', index });
        },
        async toggleAccountEnabled(index) {
            return mutateLiveAndStorage({ action: 'toggleEnabled', index });
        },
        async removeAccount(index) {
            return mutateLiveAndStorage({ action: 'remove', index });
        },
    };
    async function mutateLiveAndStorage(args) {
        const { index, action } = args;
        const target = accountManagerView.getAccounts()[index];
        if (!target)
            return null;
        const refreshToken = accountManagerView.getRefreshTokenAt(index) ?? target.refreshToken;
        if (!refreshToken)
            return null;
        if (action === 'toggleEnabled' &&
            target.enabled === false &&
            target.accountIneligible === true) {
            throw new Error('This account is ineligible and cannot be enabled until eligibility is rechecked.');
        }
        if (!storage) {
            throw new Error('CommandDataService is missing a locked-storage adapter; account mutations are disabled.');
        }
        // Capture the live view's current-account identity per family BEFORE
        // the storage mutation. The remove action must persist the index that
        // the same account will occupy AFTER the removal — unconditionally
        // resetting to 0 made a non-current removal promote whichever account
        // shifted into slot 0 to "active" on the next restart. Each model's
        // cursor is tracked independently, so collapse-tokens does not work
        // here: a Claude-active account and a Gemini-active account can
        // point at different rows.
        const liveCurrentTokens = {};
        if (action === 'remove') {
            const liveAccounts = accountManagerView.getAccounts();
            const liveIndexes = accountManagerView.getActiveIndexByFamily();
            liveCurrentTokens.claude =
                liveAccounts[liveIndexes.claude]?.refreshToken ?? undefined;
            liveCurrentTokens.gemini =
                liveAccounts[liveIndexes.gemini]?.refreshToken ?? undefined;
        }
        let foundInStorage = false;
        let desiredEnabled;
        let previousEnabled;
        let nextActiveIndex = 0;
        let nextActiveIndexByFamily = {
            claude: 0,
            gemini: 0,
        };
        await storage.mutate((current) => {
            const tokenIdx = current.accounts.findIndex((entry) => entry.refreshToken === refreshToken);
            if (tokenIdx === -1)
                return current;
            foundInStorage = true;
            if (action === 'setCurrent') {
                return {
                    ...current,
                    activeIndex: tokenIdx,
                    activeIndexByFamily: { claude: tokenIdx, gemini: tokenIdx },
                };
            }
            if (action === 'toggleEnabled') {
                const entry = current.accounts[tokenIdx];
                if (!entry)
                    return current;
                previousEnabled = entry.enabled !== false;
                desiredEnabled = entry.enabled === false;
                if (desiredEnabled && entry.accountIneligible === true) {
                    throw new Error('This account is ineligible and cannot be enabled until eligibility is rechecked.');
                }
                return {
                    ...current,
                    accounts: current.accounts.map((account) => account.refreshToken === refreshToken
                        ? { ...account, enabled: desiredEnabled }
                        : account),
                };
            }
            // remove: build the post-removal account list, then resolve the
            // current-account's NEW index in that list. If the removed
            // account was the live current, the captured token falls out of
            // the list — the live AccountManager leaves the numeric current
            // cursor at the SAME index (now occupied by whichever account
            // shifted in), so the persisted index must follow that numeric
            // slot rather than resetting to 0.
            const nextAccounts = current.accounts.filter((account) => account.refreshToken !== refreshToken);
            const resolveNextIndex = (liveToken, legacyIndex) => {
                if (!liveToken)
                    return Math.max(0, Math.min(legacyIndex, nextAccounts.length - 1));
                const found = nextAccounts.findIndex((account) => account.refreshToken === liveToken);
                if (found !== -1)
                    return found;
                // The captured current token was the one removed. Mirror the
                // core's in-memory semantics: keep the cursor at the removed
                // slot when it still exists in the new array; when the removed
                // slot was the last position and no longer exists, persist 0
                // (the core's buildStorageSnapshot clamps negative sentinels
                // to 0, and auth-doctor treats a negative activeIndex as
                // corruption — cf. auth-doctor.ts:149-156).
                //
                // Use tokenIdx (the storage-snapshot position) rather than the
                // outer-scope `index` (live-read position): a concurrent mutation
                // between the live read and the lock can diverge the two, and the
                // storage-level cursor must match the storage-level array.
                return tokenIdx < nextAccounts.length ? tokenIdx : 0;
            };
            const legacyClaude = current.activeIndexByFamily?.claude ?? current.activeIndex;
            const legacyGemini = current.activeIndexByFamily?.gemini ?? current.activeIndex;
            nextActiveIndex = resolveNextIndex(liveCurrentTokens.claude, legacyClaude);
            nextActiveIndexByFamily = {
                claude: resolveNextIndex(liveCurrentTokens.claude, legacyClaude),
                gemini: resolveNextIndex(liveCurrentTokens.gemini, legacyGemini),
            };
            return {
                ...current,
                accounts: nextAccounts,
                activeIndex: nextActiveIndex,
                activeIndexByFamily: nextActiveIndexByFamily,
            };
        });
        if (!foundInStorage)
            return null;
        // Re-resolve the live index by canonical identity after the awaited disk
        // transaction. A concurrent OAuth add/remove may have shifted every index.
        const liveIndex = accountManagerView
            .getAccounts()
            .findIndex((account) => account.refreshToken === refreshToken);
        let applied = action === 'remove' && liveIndex === -1;
        if (liveIndex !== -1) {
            if (action === 'setCurrent') {
                applied = accountManagerView.setAccountCurrent(liveIndex);
            }
            else if (action === 'toggleEnabled') {
                applied = accountManagerView.setAccountEnabled(liveIndex, desiredEnabled === true);
                if (!applied) {
                    applied =
                        accountManagerView.getAccounts()[liveIndex]?.enabled ===
                            desiredEnabled;
                }
            }
            else {
                applied = accountManagerView.removeAccountByIndex(liveIndex);
            }
        }
        if (!applied && action !== 'remove') {
            if (action === 'toggleEnabled' && previousEnabled !== undefined) {
                await storage.mutate((current) => ({
                    ...current,
                    accounts: current.accounts.map((account) => account.refreshToken === refreshToken
                        ? { ...account, enabled: previousEnabled }
                        : account),
                }));
            }
            throw new Error('The account changed while the operation was being applied; reopen the dialog and try again.');
        }
        await accountManagerView.flushSaveToDisk().catch(() => {
            // The locked storage mutation already committed; a later periodic flush
            // can reconcile transient AccountManager lock contention.
        });
        const rows = projectRows();
        writeSidebar(rows);
        return rows;
    }
}
//# sourceMappingURL=command-data.js.map