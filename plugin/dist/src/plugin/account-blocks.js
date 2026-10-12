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
function present(value) {
    return value === null ? undefined : value;
}
/**
 * The block a record shows. Ineligibility wins when a record written by an
 * older build carries both flags, because it is the stronger refusal.
 */
export function accessBlockOf(fields) {
    if (fields === undefined)
        return { kind: 'none' };
    if (fields.accountIneligible === true) {
        const reason = present(fields.accountIneligibleReason);
        const at = present(fields.accountIneligibleAt);
        return {
            kind: 'ineligible',
            ...(reason !== undefined ? { reason } : {}),
            ...(at !== undefined ? { at } : {}),
        };
    }
    if (fields.verificationRequired === true) {
        const reason = present(fields.verificationRequiredReason);
        const verificationUrl = present(fields.verificationUrl);
        const at = present(fields.verificationRequiredAt);
        return {
            kind: 'verification-required',
            ...(reason !== undefined ? { reason } : {}),
            ...(verificationUrl !== undefined ? { verificationUrl } : {}),
            ...(at !== undefined ? { at } : {}),
        };
    }
    return { kind: 'none' };
}
export function isAccessBlocked(fields) {
    return accessBlockOf(fields).kind !== 'none';
}
/**
 * The repository verdict for a probe result observed at `observedAt`, or
 * `undefined` when the probe proved nothing about access (`error`). An `ok`
 * probe clears both blocks; `enableIfBlocked` asks the repository to
 * re-enable the row only when it was disabled by a block, never a row the
 * user disabled.
 */
export function accessVerdictFromProbe(result, observedAt, enableIfBlocked) {
    switch (result.status) {
        case 'verification-required': {
            const reason = result.message.trim();
            const url = result.verifyUrl?.trim();
            return {
                kind: 'verification-required',
                observedAt,
                ...(reason ? { reason } : {}),
                ...(url ? { verificationUrl: url } : {}),
            };
        }
        case 'ineligible':
            return { kind: 'ineligible', observedAt, reason: result.message };
        case 'ok':
            return { kind: 'cleared', observedAt, enable: enableIfBlocked };
        case 'error':
            return undefined;
    }
}
/**
 * Marks a pre-store record as needing verification and disables it,
 * clearing any ineligibility. Returns whether anything changed.
 */
export function markLegacyVerificationRequired(account, reason, verifyUrl, now) {
    let changed = false;
    const wasVerificationRequired = account.verificationRequired === true;
    if (!wasVerificationRequired) {
        account.verificationRequired = true;
        changed = true;
    }
    if (!wasVerificationRequired ||
        account.verificationRequiredAt === undefined) {
        account.verificationRequiredAt = now;
        changed = true;
    }
    if (account.accountIneligible === true ||
        account.accountIneligibleAt !== undefined ||
        account.accountIneligibleReason !== undefined) {
        account.accountIneligible = false;
        account.accountIneligibleAt = undefined;
        account.accountIneligibleReason = undefined;
        account.eligibilityStateUpdatedAt = now;
        changed = true;
    }
    if (account.accountIneligible === undefined) {
        account.accountIneligible = false;
        changed = true;
    }
    const normalizedReason = reason.trim();
    if (account.verificationRequiredReason !== normalizedReason) {
        account.verificationRequiredReason = normalizedReason;
        changed = true;
    }
    const normalizedUrl = verifyUrl?.trim();
    if (normalizedUrl && account.verificationUrl !== normalizedUrl) {
        account.verificationUrl = normalizedUrl;
        changed = true;
    }
    if (account.enabled !== false) {
        account.enabled = false;
        changed = true;
    }
    return changed;
}
/**
 * Marks a pre-store record ineligible and disables it, clearing any
 * verification requirement. Returns whether anything changed.
 */
export function markLegacyIneligible(account, reason, now) {
    const normalizedReason = reason.trim() || 'Google marked this account as ineligible.';
    const changed = account.accountIneligible !== true ||
        account.accountIneligibleReason !== normalizedReason ||
        account.verificationRequired === true ||
        account.verificationRequiredAt !== undefined ||
        account.verificationRequiredReason !== undefined ||
        account.verificationUrl !== undefined ||
        account.enabled !== false;
    account.accountIneligible = true;
    account.accountIneligibleAt = now;
    account.accountIneligibleReason = normalizedReason;
    account.eligibilityStateUpdatedAt = now;
    account.verificationRequired = false;
    account.verificationRequiredAt = undefined;
    account.verificationRequiredReason = undefined;
    account.verificationUrl = undefined;
    account.enabled = false;
    return changed;
}
/**
 * Clears both blocks on a pre-store record. With `enableIfBlocked` it
 * re-enables the record only when a block was set, so a record the user
 * disabled stays disabled.
 */
export function clearLegacyAccessBlocks(account, enableIfBlocked, now) {
    const wasVerificationRequired = account.verificationRequired === true;
    const wasIneligible = account.accountIneligible === true;
    const wasAccessBlocked = wasVerificationRequired || wasIneligible;
    let changed = false;
    if (account.verificationRequired !== false) {
        account.verificationRequired = false;
        changed = true;
    }
    if (account.verificationRequiredAt !== undefined) {
        account.verificationRequiredAt = undefined;
        changed = true;
    }
    if (account.verificationRequiredReason !== undefined) {
        account.verificationRequiredReason = undefined;
        changed = true;
    }
    if (account.verificationUrl !== undefined) {
        account.verificationUrl = undefined;
        changed = true;
    }
    if (account.accountIneligible !== false) {
        account.accountIneligible = false;
        changed = true;
    }
    if (account.accountIneligibleAt !== undefined) {
        account.accountIneligibleAt = undefined;
        changed = true;
    }
    if (account.accountIneligibleReason !== undefined) {
        account.accountIneligibleReason = undefined;
        changed = true;
    }
    if (wasIneligible || account.eligibilityStateUpdatedAt !== undefined) {
        account.eligibilityStateUpdatedAt = now;
        changed = true;
    }
    if (enableIfBlocked && wasAccessBlocked && account.enabled === false) {
        account.enabled = true;
        changed = true;
    }
    return { changed, wasAccessBlocked };
}
//# sourceMappingURL=account-blocks.js.map