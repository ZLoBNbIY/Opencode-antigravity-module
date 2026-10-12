import { formatRefreshParts, isOAuthAuth, parseRefreshParts } from './auth';
function isAccountEnabled(account) {
    return account.enabled !== false;
}
export function selectRestorableAccount(storage) {
    if (!storage || storage.accounts.length === 0) {
        return undefined;
    }
    const activeAccount = storage.accounts[storage.activeIndex];
    if (activeAccount && isAccountEnabled(activeAccount)) {
        return activeAccount;
    }
    return storage.accounts.find(isAccountEnabled);
}
export function buildAuthFromStoredAccount(account) {
    return {
        type: 'oauth',
        refresh: formatRefreshParts({
            refreshToken: account.refreshToken,
            projectId: account.projectId,
            managedProjectId: account.managedProjectId,
        }),
        access: '',
        expires: 0,
    };
}
export function detectAuthStorageDrift(auth, storage) {
    if (!storage || storage.accounts.length === 0) {
        return {
            status: 'unavailable',
            reason: 'no-account-storage',
        };
    }
    const restorableAccount = selectRestorableAccount(storage);
    if (!restorableAccount) {
        return {
            status: 'unavailable',
            reason: 'no-enabled-accounts',
        };
    }
    if (!auth) {
        return {
            status: 'restorable',
            reason: 'missing-opencode-auth',
            account: restorableAccount,
        };
    }
    if (!isOAuthAuth(auth)) {
        return {
            status: 'restorable',
            reason: 'non-oauth-opencode-auth',
            account: restorableAccount,
        };
    }
    const authRefreshToken = parseRefreshParts(auth.refresh).refreshToken;
    const matchedAccount = storage.accounts.find((account) => account.refreshToken === authRefreshToken);
    if (matchedAccount) {
        return {
            status: 'healthy',
            reason: 'auth-matches-storage',
            account: matchedAccount,
        };
    }
    return {
        status: 'drifted',
        reason: 'refresh-token-not-in-storage',
        account: restorableAccount,
    };
}
//# sourceMappingURL=auth-drift.js.map