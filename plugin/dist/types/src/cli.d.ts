import { type AccountMetadataV3, type AccountMigrationOutcome, type AccountQuotaResult, type AccountRow, type AccountStorageV4 } from '@cortexkit/antigravity-auth-core';
import { type AntigravityTokenExchangeSuccess, type OAuthLoginRequest, performOAuthLogin } from './plugin/oauth-login.js';
interface WritableOutput {
    write(value: string): unknown;
}
export interface CliDependencies {
    stdout: WritableOutput;
    stderr: WritableOutput;
    prompt(message: string): Promise<string>;
    openBrowser(url: string): Promise<void>;
    isHeadless?(): boolean;
    performLogin(request: OAuthLoginRequest, openBrowser: (url: string) => Promise<void>): Promise<AntigravityTokenExchangeSuccess>;
    loadAccounts(): Promise<AccountStorageV4 | null>;
    getQuota(accounts: AccountMetadataV3[], options: {
        refresh: boolean;
    }): Promise<AccountQuotaResult[]>;
    /** Offline operations on the account store; see `AccountStoreOperations`. */
    accountStore: AccountStoreOperations;
}
/**
 * The offline account-store operations, each bound to the canonical
 * migration module. `migrate` and `rollback` run only after the operator
 * confirmed that every Antigravity process and timer has stopped; `init`
 * creates an empty store only where no account file exists.
 */
export interface AccountStoreOperations {
    /** The absolute path of the pre-store account file the store is derived from. */
    legacyPath(): string;
    migrate(legacyPath: string): Promise<AccountMigrationOutcome>;
    rollback(legacyPath: string): Promise<AccountMigrationOutcome>;
    initialize(legacyPath: string): Promise<AccountMigrationOutcome>;
    /** Reads the accounts list and quota show, without writing. */
    read(legacyPath: string): Promise<CliAccountsRead>;
}
/**
 * Where `list` and `quota` read accounts from. Once the account store is
 * active the pre-store file is retired, so the store is the only source;
 * before migration (or after a rollback) the pre-store file still is.
 */
export type CliAccountsRead = {
    kind: 'store';
    accounts: AccountMetadataV3[];
} | {
    kind: 'legacy';
} | {
    kind: 'uninitialized';
} | {
    kind: 'unavailable';
    reason: string;
};
export declare function runCli(argv: string[], deps: CliDependencies): Promise<number>;
export declare function createDefaultCliDependencies(): CliDependencies;
/**
 * One store row in the account shape `list` and `quota` print. Only display
 * fields and what a quota check needs; nothing is written back.
 */
export declare function cliAccountOf(row: AccountRow): AccountMetadataV3;
/**
 * The account-store operations over the embedded common-auth `./store` and
 * `./fs` modules. The operator's `--offline` flag and confirmation are what
 * `processesStopped` records; the migration module itself verifies the
 * pointer, journal and retired-writer state before it writes.
 */
export declare function createDefaultAccountStoreOperations(): AccountStoreOperations;
export { performOAuthLogin };
//# sourceMappingURL=cli.d.ts.map