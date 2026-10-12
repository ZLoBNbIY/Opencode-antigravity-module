import type { AccountMetadataV3, AccountStorageV4 } from './storage';
import type { AuthDetails, OAuthAuthDetails } from './types';
export type AuthStorageDriftStatus = 'healthy' | 'restorable' | 'drifted' | 'unavailable';
export type AuthStorageDriftReason = 'auth-matches-storage' | 'missing-opencode-auth' | 'non-oauth-opencode-auth' | 'refresh-token-not-in-storage' | 'no-account-storage' | 'no-enabled-accounts';
export interface AuthStorageDriftReport {
    status: AuthStorageDriftStatus;
    reason: AuthStorageDriftReason;
    account?: AccountMetadataV3;
}
export declare function selectRestorableAccount(storage: AccountStorageV4 | null | undefined): AccountMetadataV3 | undefined;
export declare function buildAuthFromStoredAccount(account: AccountMetadataV3): OAuthAuthDetails;
export declare function detectAuthStorageDrift(auth: AuthDetails | undefined | null, storage: AccountStorageV4 | null | undefined): AuthStorageDriftReport;
//# sourceMappingURL=auth-drift.d.ts.map