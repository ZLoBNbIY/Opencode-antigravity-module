import { type AccountRepository, type AccountRow, type RowRef } from '@cortexkit/antigravity-auth-core';
import type { AntigravityTokenExchangeResult } from '../antigravity/oauth';
import { type AccountAccessBlock, type VerificationProbeResult } from './account-blocks';
import { fetchWithAgyCliTransport } from './agy-transport';
import type { AccountMetadataV3, AccountStorageV4 } from './storage';
import { refreshAccessToken } from './token';
import type { PluginClient } from './types';
export type { VerificationProbeResult };
export interface AccountIdentity {
    refreshToken?: string;
    email?: string;
}
export interface AccountAccessStore {
    load(): Promise<AccountStorageV4 | null>;
    mutate(mutate: (current: AccountStorageV4) => AccountStorageV4 | undefined | Promise<AccountStorageV4 | undefined>): Promise<AccountStorageV4>;
    clear(): Promise<void>;
    persistAccountPool(results: Array<Extract<AntigravityTokenExchangeResult, {
        type: 'success';
    }>>, replaceAll: boolean): Promise<void>;
    /**
     * Which source serves the location's accounts: the pool file before
     * migration, else the account store's repository. Absent: the pool file.
     */
    source?(): Promise<'pool-file' | AccountRepository>;
}
export interface AccountAccessPrompt {
    selectAccount(accounts: Array<{
        email?: string;
        index: number;
    }>): Promise<number | undefined>;
    confirmOpenVerificationUrl(): Promise<boolean>;
}
export interface AccountAccessService {
    loadAccounts(): Promise<AccountStorageV4 | null>;
    mutateAccounts(mutate: (current: AccountStorageV4) => AccountStorageV4 | undefined | Promise<AccountStorageV4 | undefined>): Promise<AccountStorageV4>;
    clearAccounts(): Promise<void>;
    persistAccountPool(results: Array<Extract<AntigravityTokenExchangeResult, {
        type: 'success';
    }>>, replaceAll: boolean): Promise<void>;
    verifyAccount(account: {
        refreshToken: string;
        email?: string;
        projectId?: string;
        managedProjectId?: string;
    }): Promise<VerificationProbeResult>;
    applyVerificationResult(identity: AccountIdentity, result: VerificationProbeResult): Promise<void>;
    clearAccessBlocks(identity: AccountIdentity, enableIfBlocked?: boolean): Promise<{
        changed: boolean;
        wasAccessBlocked: boolean;
    }>;
    selectAccount(accounts: Array<{
        email?: string;
        index: number;
    }>): Promise<number | undefined>;
    openVerificationUrl(url: string): Promise<boolean>;
    /** The store's `source`: the pool file, or the account store's repository. */
    source(): Promise<'pool-file' | AccountRepository>;
    /**
     * The ref-addressed access operations over the account store's
     * repository, with this service's prompt, browser and transport. Store-mode
     * callers use these instead of the pool-file operations above.
     */
    repositoryAccess(repository: AccountRepository): RepositoryAccountAccessService;
}
interface AccountAccessDependencies {
    refreshAccessToken: typeof refreshAccessToken;
    transport: typeof fetchWithAgyCliTransport;
}
interface CreateAccountAccessServiceOptions {
    client: PluginClient;
    providerId: string;
    store: AccountAccessStore;
    openBrowser(url: string): Promise<boolean>;
    prompt: AccountAccessPrompt;
    dependencies?: Partial<AccountAccessDependencies>;
}
export declare function normalizeGoogleVerificationUrl(rawUrl: string): string | undefined;
export declare function selectBestVerificationUrl(urls: string[]): string | undefined;
export declare function extractAccountAccessErrorDetails(bodyText: string): {
    validationRequired: boolean;
    accountIneligible: boolean;
    message?: string;
    verifyUrl?: string;
};
export declare function buildAccountAccessProbeRequest(projectId: string): Record<string, unknown>;
export declare function interpretAccountAccessProbeResponse(response: Response): Promise<VerificationProbeResult>;
type VerificationStoredAccount = AccountMetadataV3;
export declare function markStoredAccountVerificationRequired(account: VerificationStoredAccount, reason: string, verifyUrl?: string): boolean;
export declare function markStoredAccountIneligible(account: VerificationStoredAccount, reason: string): boolean;
export declare function clearStoredAccountAccessBlocks(account: VerificationStoredAccount, enableIfBlocked?: boolean): {
    changed: boolean;
    wasAccessBlocked: boolean;
};
export declare function createAccountAccessService({ client, providerId, store, openBrowser, prompt, dependencies, }: CreateAccountAccessServiceOptions): AccountAccessService;
/** Exact text shown when a re-authentication lost its row. */
export declare const ACCOUNT_CHANGED_DURING_REAUTHORIZATION_MESSAGE = "Account changed during reauthorization. Reopen the account dialog.";
/**
 * Thrown when a re-authentication cannot land on the row it was started
 * for: the row was removed, re-added or given another credential since the
 * dialog captured it, or the browser signed in to a different account than
 * the row holds. Nothing is written.
 */
export declare class AccountChangedDuringReauthorizationError extends Error {
    readonly rowId: string;
    constructor(rowId: string, options?: {
        cause?: unknown;
    });
}
/**
 * Thrown when the account store cannot list accounts (pending migration or
 * management operation, unreadable file). Nothing falls back to the pool
 * file or to an empty list.
 */
export declare class AccountStoreUnavailableError extends Error {
    readonly status: 'pending-migration' | 'management-pending' | 'error';
    constructor(status: AccountStoreUnavailableError['status'], detail: string);
}
/**
 * One account as an access dialog shows it. `ref` is captured when the list
 * is read; every later action on the entry uses it, never the position, so
 * an entry whose row was reordered, removed or re-authenticated meanwhile
 * is refused rather than redirected to whatever row sits there now.
 */
export interface AccountAccessView {
    ref: RowRef;
    /** Roster position at read time; presentation only. */
    index: number;
    email?: string;
    label?: string;
    enabled: boolean;
    block: AccountAccessBlock;
    projectId?: string;
    managedProjectId?: string;
}
export type VerificationOutcome = {
    /** The probe ran with a bearer refreshed for exactly `ref`. */
    status: 'probed';
    ref: RowRef;
    result: VerificationProbeResult;
    observedAt: number;
} | {
    /** No bearer was obtained; nothing about access was learnt. */
    status: 'not-probed';
    ref: RowRef;
    result: Extract<VerificationProbeResult, {
        status: 'error';
    }>;
};
export type AccessVerdictOutcome = {
    status: 'applied';
    ref: RowRef;
    declined: boolean;
}
/** The probe proved nothing about access, so nothing was written. */
 | {
    status: 'no-verdict';
}
/** The row no longer holds the probed credential; nothing was written. */
 | {
    status: 'stale';
    rowId: string;
};
export interface RepositoryAccountAccessService {
    listAccounts(): Promise<AccountAccessView[]>;
    verifyAccount(account: Pick<AccountAccessView, 'ref'>): Promise<VerificationOutcome>;
    applyVerificationResult(outcome: VerificationOutcome, options?: {
        enableIfBlocked?: boolean;
    }): Promise<AccessVerdictOutcome>;
    reauthorizeAccount(expected: RowRef, result: Extract<AntigravityTokenExchangeResult, {
        type: 'success';
    }>): Promise<{
        ref: RowRef;
    }>;
    selectAccount(accounts: Array<{
        email?: string;
        index: number;
    }>): Promise<number | undefined>;
    openVerificationUrl(url: string): Promise<boolean>;
}
interface CreateRepositoryAccountAccessServiceOptions {
    repository: AccountRepository;
    openBrowser(url: string): Promise<boolean>;
    prompt: AccountAccessPrompt;
    now?: () => number;
    transport?: typeof fetchWithAgyCliTransport;
}
/**
 * A pool-file shaped view of account-store rows, for menus and listings that
 * still render the pool-file record. Each view's position equals the row's
 * index in `rows`, so a caller that keeps `rows[i].ref` beside it acts on
 * the exact row the user picked. The view is for display; it is never
 * written back.
 */
export declare function storageViewOfRows(rows: readonly AccountRow[]): AccountStorageV4;
/**
 * The access service over the account repository. Every operation names its
 * row by the `RowRef` captured when the account list was read:
 * - verification refreshes the bearer through `AccountRepository.refresh`
 *   on that ref (the stored credential, fenced by the store), never with a
 *   token copied out of an earlier read;
 * - the verdict is recorded with `recordAccessVerdict` on the ref the
 *   refresh confirmed, timestamped when the answer arrived, so a late
 *   verdict cannot undo newer evidence and a verdict about a replaced or
 *   re-added credential is refused;
 * - re-authentication replaces the credential of exactly that ref
 *   (`replaceCredential`), keeping a user's disabled choice.
 */
export declare function createRepositoryAccountAccessService({ repository, openBrowser, prompt, now, transport, }: CreateRepositoryAccountAccessServiceOptions): RepositoryAccountAccessService;
export declare function promptAccountIndexForVerification(accounts: Array<{
    email?: string;
    index: number;
}>): Promise<number | undefined>;
export declare function promptOpenVerificationUrl(): Promise<boolean>;
//# sourceMappingURL=account-access.d.ts.map