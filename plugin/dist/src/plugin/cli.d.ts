import type { CooldownReason } from './accounts';
import type { FingerprintVersion } from './fingerprint';
import type { QuotaGroupSummary } from './quota';
import { type AccountStatus } from './ui/auth-menu';
export declare function promptProjectId(): Promise<string>;
export declare function promptAddAnotherAccount(currentCount: number): Promise<boolean>;
export type LoginMode = 'add' | 'fresh' | 'manage' | 'check' | 'doctor' | 'repair' | 'current' | 'switch-account' | 'restore-fingerprint' | 'verify' | 'verify-all' | 'cancel';
export interface ExistingAccountInfo {
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
export interface LoginMenuResult {
    mode: LoginMode;
    deleteAccountIndex?: number;
    refreshAccountIndex?: number;
    toggleAccountIndex?: number;
    verifyAccountIndex?: number;
    switchAccountIndex?: number;
    restoreFingerprintAccountIndex?: number;
    restoreFingerprintHistoryIndex?: number;
    verifyAll?: boolean;
    deleteAll?: boolean;
}
export declare function promptLoginMode(existingAccounts: ExistingAccountInfo[]): Promise<LoginMenuResult>;
export type { AccountStatus } from './ui/auth-menu';
export { isTTY } from './ui/auth-menu';
//# sourceMappingURL=cli.d.ts.map