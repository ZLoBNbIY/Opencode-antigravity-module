import type { CooldownReason } from '../accounts';
import type { FingerprintVersion } from '../fingerprint';
import type { QuotaGroupSummary } from '../quota';
export type AccountStatus = 'active' | 'rate-limited' | 'expired' | 'verification-required' | 'ineligible' | 'unknown';
export interface AccountInfo {
    email?: string;
    index: number;
    addedAt?: number;
    lastUsed?: number;
    status?: AccountStatus;
    isCurrentAccount?: boolean;
    enabled?: boolean;
    quotaSummary?: string;
    cooldownMs?: number;
    cooldownReason?: CooldownReason;
    cachedQuota?: Partial<Record<string, QuotaGroupSummary>>;
    cachedPerModelQuota?: {
        modelId: string;
        displayName?: string;
        group: string | null;
        remainingFraction: number;
        resetTime?: string;
    }[];
    fingerprintHistory?: FingerprintVersion[];
}
export type AuthMenuAction = {
    type: 'add';
} | {
    type: 'select-account';
    account: AccountInfo;
} | {
    type: 'delete-all';
} | {
    type: 'check';
} | {
    type: 'doctor';
} | {
    type: 'repair';
} | {
    type: 'current';
} | {
    type: 'verify';
} | {
    type: 'verify-all';
} | {
    type: 'configure-models';
} | {
    type: 'cancel';
};
export type AccountAction = 'back' | 'delete' | 'refresh' | 'toggle' | 'verify' | 'restore-fingerprint' | 'switch-account' | 'cancel';
export interface FingerprintRestoreResult {
    action: 'restore-fingerprint';
    historyIndex: number;
}
export declare function showAuthMenu(accounts: AccountInfo[]): Promise<AuthMenuAction>;
export declare function showFingerprintHistory(history: FingerprintVersion[], accountLabel: string): Promise<number | null>;
export declare function showAccountDetails(account: AccountInfo): Promise<AccountAction>;
export { isTTY } from './ansi';
//# sourceMappingURL=auth-menu.d.ts.map