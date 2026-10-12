import { AccountManager as CoreAccountManager, sameRowRef, } from '@cortexkit/antigravity-auth-core';
import { debugLogToFile } from './debug';
import { ensureProjectContext } from './project';
import { LocalGrantSupersededError, StaleLocalGrantError, } from './shared/local-grant';
import { getStoragePath, loadAccounts, saveAccounts, saveAccountsReplace, } from './storage';
import { isInvalidGrantFailure } from './token';
export { calculateBackoffMs, computeSoftQuotaCacheTtlMs, parseRateLimitReason, resolveQuotaGroup, } from '@cortexkit/antigravity-auth-core';
/**
 * The pre-store pool-file binding. Every function it calls first runs the
 * migration's `assertLegacyAccountStorageWritable`, which refuses
 * (`LegacyAccountPoolRetiredError`) once a canonical store pointer is
 * published and its journal is not an inactive rollback, or when store
 * files exist without a journal. A manager built on it never writes a
 * retired pool file.
 */
const openCodeStore = {
    load: async () => loadAccounts(),
    saveMerged: async (_path, next) => {
        await saveAccounts(next);
        return next;
    },
    mutate: async (_path, fn) => {
        const current = (await loadAccounts()) ?? {
            version: 4,
            accounts: [],
            activeIndex: 0,
        };
        const next = (await fn(current)) ?? current;
        await saveAccountsReplace(next);
        return next;
    },
    clear: async () => { },
};
function defaultDiagnostic(message, fields) {
    debugLogToFile(fields ? `${message} ${JSON.stringify(fields)}` : message);
}
/**
 * Thrown when the account store cannot serve accounts: a migration or a
 * multi-row operation is pending, or a store file is unreadable. Routing
 * must stop here; nothing falls back to the pool file or to an empty pool.
 */
export class AccountStoreNotReadyError extends Error {
    read;
    constructor(read) {
        super(read.status === 'error'
            ? `The account store's ${read.file} file cannot be read: ${read.reason}`
            : read.status === 'management-pending'
                ? `An account ${read.management.kind} operation is pending; resume it before using the accounts`
                : 'The account store is waiting for its migration to finish; run `antigravity-auth migrate --offline`');
        this.name = 'AccountStoreNotReadyError';
        this.read = read;
    }
}
/**
 * Builds a manager over the account repository from one read. Every account
 * the manager holds carries the `RowRef` of the row it was read from: the
 * row id, the credential epoch and the exact recorded identity (an absent
 * identity matches only an absent one). Every write the manager makes about
 * the account is fenced on that ref, so a write for a credential the row
 * has since replaced is refused; positions are never used.
 * Refreshes go through `refreshAccount`, the repository's per-account
 * refresh, so different accounts refresh concurrently while one account's
 * refreshes are serialized.
 */
export async function loadAccountManagerFromRepository(repository, options = {}) {
    const read = await repository.read();
    if (read.status !== 'ready')
        throw new AccountStoreNotReadyError(read);
    return CoreAccountManager.fromRepository(read, {
        repository,
        now: options.now,
        random: options.random,
        pid: options.pid ?? process.pid,
        onDiagnostic: options.onDiagnostic ?? defaultDiagnostic,
    });
}
/** The selected account no longer holds the credential a grant was made for. */
export class StaleAccountGrantError extends StaleLocalGrantError {
    constructor() {
        super();
        this.name = 'StaleAccountGrantError';
    }
}
export function createLocalAccountCredentials(manager, dependencies) {
    const heldLocally = (account, ref) => account.ref !== undefined &&
        sameRowRef(account.ref, ref) &&
        account.enabled !== false &&
        manager.getAccounts().includes(account);
    const readCurrentRow = async (ref) => {
        const read = await dependencies.repository.read();
        const row = read.status === 'ready'
            ? read.rows.find((candidate) => sameRowRef(candidate.ref, ref))
            : undefined;
        if (row === undefined ||
            !row.enabled ||
            !row.usable ||
            row.credential === undefined ||
            row.metadata.status !== 'present')
            throw new StaleAccountGrantError();
        return row;
    };
    const local = {
        captureGrant({ account, accessToken }) {
            const ref = account.ref === undefined
                ? undefined
                : Object.freeze({ ...account.ref });
            return {
                source: 'store',
                check: () => {
                    if (ref === undefined)
                        throw new StaleAccountGrantError();
                    return local.assertGrantCurrent({ account, accessToken, ref });
                },
                async resolveCurrent() {
                    if (ref === undefined || !heldLocally(account, ref))
                        throw new StaleAccountGrantError();
                    const row = await readCurrentRow(ref);
                    if (!heldLocally(account, ref) ||
                        !manager.adoptCurrentRow(account, row))
                        throw new StaleAccountGrantError();
                },
            };
        },
        async refresh(account) {
            const outcome = await manager.refreshAccount(account);
            if (outcome.status !== 'rotated')
                return undefined;
            return manager.toAuthDetails(account);
        },
        ensureProject: dependencies.ensureProject ?? ensureProjectContext,
        isInvalidGrant: isInvalidGrantFailure,
        async assertGrantCurrent({ account, accessToken, ref }) {
            if (!heldLocally(account, ref))
                throw new StaleAccountGrantError();
            const row = await readCurrentRow(ref);
            // Recheck the selected account and its original row ref after the read.
            // Checking cannot adopt a newer stored token or change a prepared bearer.
            if (!heldLocally(account, ref))
                throw new StaleAccountGrantError();
            if (row.credential?.accessToken !== accessToken)
                throw new LocalGrantSupersededError();
            if (account.access !== accessToken)
                throw new StaleAccountGrantError();
        },
    };
    return local;
}
export class AccountManager extends CoreAccountManager {
    constructor(authFallback, stored, options = {}) {
        super(authFallback, stored, {
            store: options.store ?? openCodeStore,
            storagePath: options.storagePath ?? getStoragePath(),
            now: options.now,
            random: options.random,
            pid: options.pid ?? process.pid,
            onDiagnostic: options.onDiagnostic ?? defaultDiagnostic,
        });
    }
    static async loadFromDisk(authFallback) {
        return new AccountManager(authFallback, await loadAccounts());
    }
}
//# sourceMappingURL=accounts.js.map