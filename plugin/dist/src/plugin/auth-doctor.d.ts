import type { AccountStorageV4 } from './storage';
import type { AuthDetails } from './types';
export type AuthDoctorStatus = 'ok' | 'warning' | 'repairable' | 'error';
export type AuthDoctorFindingCode = 'auth-matches-storage' | 'missing-opencode-auth' | 'non-oauth-opencode-auth' | 'refresh-token-not-in-storage' | 'no-account-storage' | 'no-enabled-accounts' | 'active-index-out-of-range' | 'active-account-disabled' | 'verification-required' | 'account-ineligible';
export type AuthDoctorRepair = 'restore-opencode-auth' | 'clamp-active-index' | 'select-enabled-account' | 'verify-account';
export interface AuthDoctorFinding {
    code: AuthDoctorFindingCode;
    severity: 'info' | 'warning' | 'error';
    message: string;
    repair?: AuthDoctorRepair;
    accountEmail?: string;
}
export interface AuthDoctorReport {
    status: AuthDoctorStatus;
    summary: string;
    findings: AuthDoctorFinding[];
    runtime?: AuthDoctorRuntimeMetadata;
}
export interface AuthDoctorRuntimeMetadata {
    antigravityVersion: string;
    antigravityVersionSource: string;
}
export interface CreateAuthDoctorReportInput {
    auth: AuthDetails | undefined | null;
    storage: AccountStorageV4 | null | undefined;
    runtime?: AuthDoctorRuntimeMetadata;
}
export declare function createAuthDoctorReport(input: CreateAuthDoctorReportInput): AuthDoctorReport;
export declare function formatAuthDoctorReport(report: AuthDoctorReport): string;
//# sourceMappingURL=auth-doctor.d.ts.map