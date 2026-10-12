import { type AccountManagerOptions, type AccountRepository, type AccountRepositoryRead, AccountManager as CoreAccountManager, type ManagedAccount as CoreManagedAccount, type OAuthAuthDetails as CoreOAuthAuthDetails, type ProjectContextResult, type RowRef } from '@cortexkit/antigravity-auth-core';
import { type CapturedLocalGrant, StaleLocalGrantError } from './shared/local-grant.js';
import { loadAccounts } from './storage.js';
import type { OAuthAuthDetails } from './types.js';
export type { AccountModelFamily as ModelFamily, AccountSessionIdentity, CooldownReason, HeaderStyle, ManagedAccount, RateLimitReason, } from '@cortexkit/antigravity-auth-core';
export { calculateBackoffMs, computeSoftQuotaCacheTtlMs, parseRateLimitReason, resolveQuotaGroup, } from '@cortexkit/antigravity-auth-core';
/**
 * Thrown when the account store cannot serve accounts: a migration or a
 * multi-row operation is pending, or a store file is unreadable. Routing
 * must stop here; nothing falls back to the pool file or to an empty pool.
 */
export declare class AccountStoreNotReadyError extends Error {
    readonly read: Exclude<AccountRepositoryRead, {
        status: 'ready';
    }>;
    constructor(read: Exclude<AccountRepositoryRead, {
        status: 'ready';
    }>);
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
export declare function loadAccountManagerFromRepository(repository: AccountRepository, options?: Partial<Omit<AccountManagerOptions, 'store' | 'storagePath' | 'repository'>>): Promise<CoreAccountManager>;
/**
 * Token and project operations for accounts of a repository-backed manager,
 * for the shared request engine's local source: the refresh token is stored
 * locally and refreshed here. A vault-backed location never uses these; it
 * obtains a fresh token and project for every send.
 */
export interface LocalAccountCredentials {
    /** Capture the selected row; resolution may adopt only that row's current credential. */
    captureGrant(request: {
        account: CoreManagedAccount;
        accessToken: string;
    }): Extract<CapturedLocalGrant, {
        source: 'store';
    }>;
    /**
     * Refreshes the locally stored refresh token of `account` through the
     * repository, fenced on the ref the account was loaded with, and returns
     * its updated credential. A refresh
     * the store refused, or one where Google answered for another account,
     * returns `undefined`: no bearer is handed out for it. Failures (Google's
     * error answers included, see `isInvalidGrant`) are thrown.
     */
    refresh(account: CoreManagedAccount): Promise<CoreOAuthAuthDetails | undefined>;
    /** Resolves the Antigravity project a request is sent under, using the cached project context. */
    ensureProject(auth: CoreOAuthAuthDetails): Promise<ProjectContextResult>;
    /** True when a refresh failure is `invalid_grant`: the refresh token is invalid or revoked. */
    isInvalidGrant(error: unknown): boolean;
    /**
     * Check a captured bearer immediately before sending it. `ref` is the
     * original row ID, credential epoch and authenticated identity captured
     * with that token, not the account object's potentially changed ref.
     *
     * The manager must still hold the enabled selected account at that ref.
     * One fresh repository read must show the same enabled row, a credential
     * the native store marks usable, and present Antigravity provider metadata.
     * Recheck the held account after the read because it may change during it.
     * A different stored token at the unchanged ref raises
     * `LocalGrantSupersededError`; other refusals raise `StaleAccountGrantError`.
     * The held account must also still carry the captured token.
     *
     * This is a dispatch snapshot, not a lease or network lock. It never changes
     * the prepared bearer, and the row can still change after the check returns.
     */
    assertGrantCurrent(request: {
        account: CoreManagedAccount;
        accessToken: string;
        ref: RowRef;
    }): Promise<void>;
}
/** The selected account no longer holds the credential a grant was made for. */
export declare class StaleAccountGrantError extends StaleLocalGrantError {
    constructor();
}
export declare function createLocalAccountCredentials(manager: CoreAccountManager, dependencies: {
    /** The repository `manager` was loaded from. */
    repository: Pick<AccountRepository, 'read'>;
    ensureProject?: (auth: CoreOAuthAuthDetails) => Promise<ProjectContextResult>;
}): LocalAccountCredentials;
export declare class AccountManager extends CoreAccountManager {
    constructor(authFallback?: OAuthAuthDetails, stored?: Awaited<ReturnType<typeof loadAccounts>>, options?: Partial<AccountManagerOptions>);
    static loadFromDisk(authFallback?: OAuthAuthDetails): Promise<AccountManager>;
}
//# sourceMappingURL=accounts.d.ts.map