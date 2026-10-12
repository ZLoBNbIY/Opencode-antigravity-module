/**
 * Account access blocks (Google "verification required" and "account
 * ineligible") as plain data, with no host SDK, client or storage import,
 * so any host composition can share them.
 *
 * Two kinds of record carry the same block fields: the pre-store pool
 * file's `AccountMetadataV3` (fields absent or set) and the repository's
 * `ProviderMetadata` (fields absent, `null` or set). Readers here accept
 * both; a `null` means the same as an absent field.
 *
 * The two blocks are mutually exclusive: marking one clears the other.
 * For repository rows the rule is applied by the repository itself, under
 * the row lock, from an `AccessVerdict`; `accessVerdictFromProbe` builds
 * that verdict. The `markLegacy*`/`clearLegacy*` helpers below apply the
 * same rule in place to a pre-store record.
 */
import type { AccessVerdict } from '@cortexkit/antigravity-auth-core';
/** The block fields both record kinds share. */
export interface AccessBlockFields {
    enabled?: boolean | null;
    verificationRequired?: boolean | null;
    verificationRequiredAt?: number | null;
    verificationRequiredReason?: string | null;
    verificationUrl?: string | null;
    accountIneligible?: boolean | null;
    accountIneligibleAt?: number | null;
    accountIneligibleReason?: string | null;
    eligibilityStateUpdatedAt?: number | null;
}
export type AccountAccessBlock = {
    kind: 'none';
} | {
    kind: 'verification-required';
    reason?: string;
    verificationUrl?: string;
    at?: number;
} | {
    kind: 'ineligible';
    reason?: string;
    at?: number;
};
/** The outcome of one access probe against the Antigravity endpoint. */
export type VerificationProbeResult = {
    status: 'ok';
    message: string;
} | {
    status: 'ineligible';
    message: string;
} | {
    status: 'verification-required';
    message: string;
    verifyUrl?: string;
} | {
    status: 'error';
    message: string;
};
/**
 * The block a record shows. Ineligibility wins when a record written by an
 * older build carries both flags, because it is the stronger refusal.
 */
export declare function accessBlockOf(fields: AccessBlockFields | undefined): AccountAccessBlock;
export declare function isAccessBlocked(fields: AccessBlockFields | undefined): boolean;
/**
 * The repository verdict for a probe result observed at `observedAt`, or
 * `undefined` when the probe proved nothing about access (`error`). An `ok`
 * probe clears both blocks; `enableIfBlocked` asks the repository to
 * re-enable the row only when it was disabled by a block, never a row the
 * user disabled.
 */
export declare function accessVerdictFromProbe(result: VerificationProbeResult, observedAt: number, enableIfBlocked: boolean): AccessVerdict | undefined;
/** A pre-store record the legacy helpers change in place. */
export interface LegacyAccessBlockRecord {
    enabled?: boolean;
    verificationRequired?: boolean;
    verificationRequiredAt?: number;
    verificationRequiredReason?: string;
    verificationUrl?: string;
    accountIneligible?: boolean;
    accountIneligibleAt?: number;
    accountIneligibleReason?: string;
    eligibilityStateUpdatedAt?: number;
}
/**
 * Marks a pre-store record as needing verification and disables it,
 * clearing any ineligibility. Returns whether anything changed.
 */
export declare function markLegacyVerificationRequired(account: LegacyAccessBlockRecord, reason: string, verifyUrl: string | undefined, now: number): boolean;
/**
 * Marks a pre-store record ineligible and disables it, clearing any
 * verification requirement. Returns whether anything changed.
 */
export declare function markLegacyIneligible(account: LegacyAccessBlockRecord, reason: string, now: number): boolean;
/**
 * Clears both blocks on a pre-store record. With `enableIfBlocked` it
 * re-enables the record only when a block was set, so a record the user
 * disabled stays disabled.
 */
export declare function clearLegacyAccessBlocks(account: LegacyAccessBlockRecord, enableIfBlocked: boolean, now: number): {
    changed: boolean;
    wasAccessBlocked: boolean;
};
//# sourceMappingURL=account-blocks.d.ts.map