/**
 * Account pool persistence for OAuth flows.
 *
 * Merges a batch of successful OAuth token-exchange results into the
 * persisted pool. All reads + writes happen inside the core
 * `mutateAccountStorage` callback so the mutator sees the freshest
 * state read while the lock is held — without it, a concurrent add
 * would race the read-modify-write and silently disappear.
 *
 * Two upsert keys are honored, in priority order:
 *  1. email — survives refresh-token rotation for the same Google account
 *  2. refresh token — handles the no-email case and out-of-band rotations
 *
 * Destructive (`replaceAll: true`) writes start from an empty v4 inside
 * the same locked callback so a stale merge cannot resurrect a removed
 * account.
 *
 * `persistAccountPool` writes the pre-store pool file and is refused once
 * the account store has replaced it. `commitLogins` and `replacePoolLogins`
 * are the account-store equivalents.
 */
import { type AccountLoginInput, type AccountRepository, type ManagementReceipt, type RowRef } from '@cortexkit/antigravity-auth-core';
import type { AntigravityTokenExchangeResult } from '../antigravity/oauth';
export type TokenSuccess = Extract<AntigravityTokenExchangeResult, {
    type: 'success';
}>;
/**
 * Merge a batch of successful OAuth results into the persisted pool.
 *
 * - `replaceAll: true`   — start from empty (fresh login)
 * - `replaceAll: false`  — preserve existing accounts, upsert by email
 *                          then refresh token, bump `lastUsed`
 *
 * Both branches run their mutator INSIDE the locked callback. The
 * `replaceAll` branch seeds the mutator from an empty v4 rather than
 * reading the disk state, but the file lock is still required so the
 * write is atomic against concurrent writers — a deleted-account merge
 * would resurrect a stale account if we wrote without the lock.
 */
export declare function persistAccountPool(results: TokenSuccess[], replaceAll?: boolean): Promise<void>;
/**
 * The repository login input for one OAuth result: a fresh row id, the bare
 * refresh token (project ids live in metadata, never packed into the stored
 * secret) and the account fields the login established. No identity is
 * asserted: the OAuth email is display metadata, not the provider identity
 * a credential is fenced on. Returns `undefined`
 * for a result without a refresh token.
 */
export declare function loginInputOf(result: TokenSuccess, now: number, newId?: () => string): AccountLoginInput | undefined;
export type CommittedLogin = {
    status: 'committed';
    /** The authoritative ref of the row that now holds the login. */
    ref: RowRef;
    outcome: 'added' | 'added-disabled' | 'completed' | 'rotated';
} | {
    status: 'refused';
    kind: 'duplicate-identity' | 'duplicate-secret';
    rowId?: string;
    message: string;
} | {
    status: 'skipped';
    reason: 'no-refresh-token';
};
/**
 * Admits OAuth results into the account store one login at a time, in
 * order, through `AccountRepository.login`: each is matched by exact email,
 * then by secret, and committed under the repository's topology lease, the
 * same lease that orders `clear` and pool replacement. Unlike the
 * pre-store upsert, a login never overwrites the credential of an existing
 * row: an email already held under another credential is refused and must
 * go through re-authentication with that row's captured ref. Any other
 * failure (pending migration, contention, I/O) stops the batch and is
 * thrown; logins committed before it stay committed and their refs are on
 * the error's `committed` list.
 */
export declare function commitLogins(repository: AccountRepository, results: readonly TokenSuccess[], options?: {
    now?: () => number;
    newId?: () => string;
}): Promise<CommittedLogin[]>;
/** A login batch that stopped early; `committed` lists what landed first. */
export declare class LoginBatchError extends Error {
    readonly committed: readonly CommittedLogin[];
    constructor(committed: readonly CommittedLogin[], cause: unknown);
}
/**
 * Replaces the whole pool with fresh logins as one journaled repository
 * operation. The inputs stay in the repository's
 * private transfer file until the new rows are verified, so an interrupted
 * replacement resumes rather than losing them. `pending` means the journal
 * is waiting to be resumed; the caller must not serve the pool until a
 * later `replacePool`/resume completes. Results without a refresh token are
 * left out; a batch with none is refused rather than clearing the pool.
 */
export declare function replacePoolLogins(repository: AccountRepository, results: readonly TokenSuccess[], options?: {
    now?: () => number;
    newId?: () => string;
}): Promise<ManagementReceipt>;
//# sourceMappingURL=persist-account-pool.d.ts.map