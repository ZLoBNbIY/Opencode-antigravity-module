/**
 * Host-path adapter for account storage.
 *
 * Resolves the on-disk path for the OpenCode config directory, handles
 * the legacy Windows migration, and keeps the .gitignore in sync. All
 * data operations are delegated to `@cortexkit/antigravity-auth-core`'s
 * lock-held account-storage engine.
 *
 * The split keeps this module harness-specific (it knows about
 * `OPENCODE_CONFIG_DIR`, `%APPDATA%`, and OpenCode-specific gitignore
 * entries) while the schema, migrations, and lock semantics live in
 * core.
 */
import type { AccountMetadataV2, AccountMetadataV3, AccountModelFamily, AccountStorageUnreadableReason, AccountStorageV2, AccountStorageV4, AnyAccountStorage, CooldownReason, HeaderStyle, RateLimitStateV2, RateLimitStateV3 } from '@cortexkit/antigravity-auth-core';
import { type AccountMigrationModules, type AccountMigrationOutcome, type AccountRepository, AccountStorageUnreadableError, type AccountStoreAdmission, type AccountStoreAdmissionModules, type AccountStoreBinding, type AccountTokenExchange, type CreateAccountRepository, deduplicateAccountsByEmail as coreDeduplicateAccountsByEmail, mergeAccountStorage as coreMergeAccountStorage, migrateV2ToV3 as coreMigrateV2ToV3, mutateAccountStorage as coreMutateAccountStorage } from '@cortexkit/antigravity-auth-core';
/**
 * @deprecated use `AccountModelFamily` from `@cortexkit/antigravity-auth-core`.
 * Retained under the old name so existing call sites continue to compile.
 */
export type ModelFamily = AccountModelFamily;
export type { AccountMetadataV2, AccountMetadataV3, AccountStorageUnreadableReason, AccountStorageV2, AccountStorageV4, AnyAccountStorage, CooldownReason, HeaderStyle, RateLimitStateV2, RateLimitStateV3, };
/**
 * Re-export the typed unreadable-storage error so consumers can
 * `instanceof`-check without pulling core into their own dependency
 * graph. When the on-disk accounts file exists but cannot be parsed
 * as a valid v4 (corrupt JSON, schema mismatch, unknown version, or
 * an I/O error other than ENOENT), every read/write here throws this
 * — never silently overwrites the user's data.
 */
export { AccountStorageUnreadableError };
/**
 * Backward-compat re-exports for harnesses still importing
 * `deduplicateAccountsByEmail` / `mergeAccountStorage` / `migrateV2ToV3`
 * from `./storage`. The definitions live in core; the adapter exposes
 * them so legacy test files compile without modification.
 */
export declare const deduplicateAccountsByEmail: typeof coreDeduplicateAccountsByEmail;
export declare const mergeAccountStorage: typeof coreMergeAccountStorage;
export declare const migrateV2ToV3: typeof coreMigrateV2ToV3;
/**
 * The pre-store engine's mutation of the legacy pool file at `path`, run
 * while holding that file's lock; refused once the account store owns the
 * accounts (see `assertLegacyPoolInUse`).
 */
export declare const mutateAccountStorage: typeof coreMutateAccountStorage;
/**
 * Files/directories that should be gitignored in the config directory.
 * These contain sensitive data or machine-specific state.
 */
export declare const GITIGNORE_ENTRIES: string[];
/**
 * Ensures a .gitignore file exists in the config directory with entries
 * for sensitive files. Creates the file if missing, or appends missing
 * entries if it already exists.
 */
export declare function ensureGitignore(configDir: string): Promise<void>;
/**
 * Synchronous version of ensureGitignore for use in sync code paths.
 */
export declare function ensureGitignoreSync(configDir: string): void;
/**
 * Gets the config directory path, with the following precedence:
 * 1. OPENCODE_CONFIG_DIR env var (if set)
 * 2. ~/.config/opencode (all platforms, including Windows)
 *
 * On Windows, also checks for legacy %APPDATA%\opencode path for migration.
 */
declare function getConfigDir(): string;
export declare function getStoragePath(): string;
/**
 * Gets the config directory path. Exported for use by other modules.
 */
export { getConfigDir };
/**
 * Thrown by every pre-store reader and writer of the pool file once the
 * account store owns the accounts: a published store generation whose
 * journal is not an inactive rollback, or successor files without a
 * journal. A write then would land in a file the migration captured or
 * retired, and a read would serve accounts the store no longer agrees with.
 * The decision is the migration's own (`assertLegacyAccountStorageWritable`);
 * `cause` carries its reason, which never contains a credential.
 */
export declare class LegacyAccountPoolRetiredError extends Error {
    readonly legacyPath: string;
    constructor(legacyPath: string, options?: {
        cause?: unknown;
    });
}
/**
 * Refuses pool-file access once the account store owns the accounts. Any
 * failure of the check (an unreadable pointer or journal included) refuses
 * too: it is not proof that the store is absent.
 */
export declare function assertLegacyPoolInUse(legacyPath: string): Promise<void>;
export declare const UNMIGRATED_ACCOUNT_MESSAGE = "Antigravity accounts require offline migration. Stop OpenCode, then run `npx @cortexkit/opencode-antigravity-auth@3.0.0 migrate --offline`.";
type NotServing = Exclude<AccountStoreAdmission, {
    status: 'active';
} | {
    status: 'initialization-required';
}>;
/** What opening the account store for serving found. */
export type AccountStoreOpening = {
    status: 'ready';
    repository: AccountRepository;
    admission: Extract<AccountStoreAdmission, {
        status: 'active';
    }>;
}
/**
 * Neither a pool file nor a store exists. Nothing is created: a genuinely
 * fresh installation calls `initializeFreshAccountStoreFor` explicitly,
 * then opens again.
 */
 | {
    status: 'initialization-required';
}
/** A pool file exists and no store generation is published. */
 | {
    status: 'migration-required';
    message: string;
}
/**
 * A published generation is bound but cannot serve: repository work (a
 * clear or a pool replacement) is pending. Its owner resumes it through
 * `openAccountStoreForRecovery`; nothing is served meanwhile.
 */
 | {
    status: 'recovery-required';
    binding: Extract<AccountStoreBinding, {
        status: 'bound';
    }>;
    message: string;
}
/**
 * The store cannot serve: a migration or rollback is pending, the store
 * was rolled back (inactive), or its pointer, journal, backups or files
 * failed validation. Nothing falls back to the pool file or to an empty
 * pool.
 */
 | {
    status: 'refused';
    admission: NotServing;
    message: string;
};
export interface OpenAccountStoreOptions {
    /** The genuine public common-auth `./store` module; admission uses only its read methods. */
    modules: AccountStoreAdmissionModules;
    /**
     * Builds the repository for the verified generation's paths;
     * `createAccountRepositoryFactory(modules)`.
     */
    createRepository: CreateAccountRepository;
    exchange: AccountTokenExchange;
    now?: () => number;
    /** Defaults to the resolved pool-file path (`getStoragePath`). */
    legacyPath?: string;
}
/**
 * Opens the account store for serving. The generation is first bound
 * through the migration's canonical binding, then admitted for serving
 * (healthy current rows, no pending repository work) on that same
 * generation. The repository is built only for an admitted generation;
 * every other result is returned, never repaired: no implicit fresh store,
 * no reset after a corrupt or unavailable store and no fall-through to the
 * pool file.
 */
export declare function openAccountStore(options: OpenAccountStoreOptions): Promise<AccountStoreOpening>;
/**
 * Opens the bound generation's repository to resume interrupted repository
 * work (`clear`, `replacePool`), which the repository finishes from its own
 * journal. The repository refuses every ordinary operation while that work
 * is pending, so this never serves accounts; use `openAccountStore` for
 * serving.
 */
export declare function openAccountStoreForRecovery(options: OpenAccountStoreOptions): Promise<{
    status: 'bound';
    repository: AccountRepository;
    binding: Extract<AccountStoreBinding, {
        status: 'bound';
    }>;
} | Exclude<AccountStoreOpening, {
    status: 'ready' | 'recovery-required';
}>>;
/**
 * Creates an empty account store for a genuinely fresh installation (no
 * pool file), as an explicit step the caller takes after `openAccountStore`
 * answered `initialization-required`. The migration's
 * `initializeFreshAccountStore` refuses
 * when a pool file exists or appears, or when unrelated store files exist.
 */
export declare function initializeFreshAccountStoreFor(modules: AccountMigrationModules, options?: {
    legacyPath?: string;
    now?: () => number;
}): Promise<AccountMigrationOutcome>;
export declare function loadAccounts(): Promise<AccountStorageV4 | null>;
/**
 * Merge `storage` into the persisted pool. Use this for non-destructive
 * writes (quota cache, eligibility, last-used) so concurrent writers
 * do not silently drop each other's data.
 */
export declare function saveAccounts(storage: AccountStorageV4): Promise<void>;
/**
 * Save accounts storage by replacing the entire file (no merge).
 * Required for destructive operations like delete where the next-state
 * must replace — never be merged with — what is on disk.
 */
export declare function saveAccountsReplace(storage: AccountStorageV4): Promise<void>;
export declare function clearAccounts(): Promise<void>;
/**
 * Locate a stored account by its refresh token under the lock-held
 * mutator and apply `mutate(account)`. Returns the (possibly mutated)
 * account, or `undefined` when the token no longer matches any stored
 * account. Concurrent writers that add/remove accounts will not
 * disturb the lookup — the read happens while the lock is held.
 *
 * `mutate` may mutate `account` in place and return `true` to commit
 * the change; returning `false` is treated as "no change" and skips
 * the write.
 */
export declare function mutateAccountByRefreshToken(refreshToken: string, mutate: (account: AccountMetadataV3) => boolean): Promise<AccountMetadataV3 | undefined>;
//# sourceMappingURL=storage.d.ts.map