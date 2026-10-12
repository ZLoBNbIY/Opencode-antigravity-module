/**
 * The Vault section of the `/antigravity` menu: a credential-free view and
 * action model for setting up the Claustrum vault on OpenCode.
 *
 * The server owns everything with an effect (enrollment, switching the
 * account source, any credential the vault hands out). This module only
 * turns a non-secret status into the section's lines and decides which
 * actions are offered, and each action calls an injected server effect. It
 * imports nothing: no vault client, token, account store or OAuth code, so it
 * can sit next to the TUI without widening what the TUI can reach.
 *
 * The section's shape is the shared command menu's provider extra
 * (`PluginExtraSection` of `@cortexkit/common-auth/commands`), declared
 * structurally here so the server can pass it straight to
 * `createCommandMenu({ extras: [...] })`.
 */
/** The enrollment name this host registers with the vault. */
export const OPENCODE_VAULT_ENROLLMENT_NAME = 'antigravity-auth-opencode';
const ENROLLMENT_TEXT = {
    'not-enrolled': 'Not enrolled',
    pending: 'Enrollment waiting for approval in the vault',
    enrolled: 'Enrolled',
    revoked: 'Enrollment revoked by the vault',
    declined: 'Enrollment declined by the vault',
    unavailable: 'Vault unreachable; status unknown',
};
const INELIGIBLE_TEXT = {
    'no-vault-configured': 'No vault is configured for this machine.',
    'host-login-present': 'An OpenCode login for this provider is present; remove it before using vault custody.',
    'unsupported-host': 'This OpenCode version cannot use vault custody.',
};
const MODES = ['local', 'custody'];
const STATES = Object.keys(ENROLLMENT_TEXT);
const REASONS = Object.keys(INELIGIBLE_TEXT);
const STATUS_KEYS = [
    'mode',
    'enrollment',
    'ineligible',
    'accounts',
    'checkedAt',
];
/**
 * Checks a status from the server field by field. A status with any other
 * field (a token, an email, a receipt) is refused rather than shown, so a
 * server change that starts passing secrets cannot reach the menu.
 */
export function parseVaultSetupStatus(value) {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        return undefined;
    }
    const record = value;
    if (Object.keys(record).some((key) => !STATUS_KEYS.includes(key))) {
        return undefined;
    }
    if (!MODES.includes(record.mode))
        return undefined;
    if (!STATES.includes(record.enrollment)) {
        return undefined;
    }
    if (record.ineligible !== undefined &&
        !REASONS.includes(record.ineligible)) {
        return undefined;
    }
    if (record.accounts !== undefined &&
        !(Number.isSafeInteger(record.accounts) && record.accounts >= 0)) {
        return undefined;
    }
    if (!Number.isFinite(record.checkedAt))
        return undefined;
    return {
        mode: record.mode,
        enrollment: record.enrollment,
        ...(record.ineligible === undefined
            ? {}
            : { ineligible: record.ineligible }),
        ...(record.accounts === undefined
            ? {}
            : { accounts: record.accounts }),
        checkedAt: record.checkedAt,
    };
}
/** The lines and the offered actions for one status. */
export function vaultSetupView(status) {
    if (!status) {
        return {
            lines: ['Vault status could not be read; no vault action is offered.'],
            actions: [],
        };
    }
    const lines = [
        `Accounts come from: ${status.mode === 'custody' ? 'vault custody' : 'local accounts'}`,
        `Host enrollment (${OPENCODE_VAULT_ENROLLMENT_NAME}): ${ENROLLMENT_TEXT[status.enrollment]}`,
    ];
    if (status.enrollment === 'enrolled' && status.accounts !== undefined) {
        lines.push(`Vault accounts for this host: ${status.accounts}`);
    }
    if (status.ineligible)
        lines.push(INELIGIBLE_TEXT[status.ineligible]);
    const actions = [];
    if (status.enrollment === 'unavailable') {
        // Nothing can be decided while the vault cannot be reached; only the
        // way back to local accounts stays open.
        if (status.mode === 'custody')
            actions.push('use-local');
        return { lines, actions };
    }
    if (!status.ineligible &&
        (status.enrollment === 'not-enrolled' ||
            status.enrollment === 'revoked' ||
            status.enrollment === 'declined')) {
        actions.push('enroll');
    }
    if (status.enrollment === 'enrolled' &&
        status.mode === 'local' &&
        !status.ineligible) {
        actions.push('use-custody');
    }
    if (status.mode === 'custody')
        actions.push('use-local');
    if (status.enrollment === 'enrolled' || status.enrollment === 'pending') {
        actions.push('disconnect');
    }
    return { lines, actions };
}
const UNREADABLE = {
    ok: false,
    text: 'The vault action did not complete.',
    code: 'vault-failed',
};
async function guarded(run) {
    try {
        const outcome = await run();
        return typeof outcome?.text === 'string' && typeof outcome.ok === 'boolean'
            ? {
                ok: outcome.ok,
                text: outcome.text,
                ...(outcome.code ? { code: outcome.code } : {}),
            }
            : UNREADABLE;
    }
    catch {
        // The effect's own error text may quote a request or a credential, so it
        // is never shown; the server logs it on its side.
        return UNREADABLE;
    }
}
/** The Vault provider extra for the server's `/antigravity` menu. */
export function createVaultSection(effects) {
    return {
        id: 'vault',
        title: 'Vault',
        async build() {
            let status;
            try {
                status = parseVaultSetupStatus(await effects.status());
            }
            catch {
                status = undefined;
            }
            const view = vaultSetupView(status);
            const definitions = {
                enroll: {
                    id: 'enroll',
                    label: 'Set up vault for this host',
                    description: `Request enrollment as ${OPENCODE_VAULT_ENROLLMENT_NAME}; approve it in the vault.`,
                    run: () => guarded(() => effects.enroll()),
                },
                'use-custody': {
                    id: 'use-custody',
                    label: 'Use vault accounts',
                    description: 'Send requests with accounts the vault serves to this host.',
                    confirm: 'Switch this host to vault custody? Local accounts stay on disk but are not used.',
                    run: () => guarded(() => effects.useCustody()),
                },
                'use-local': {
                    id: 'use-local',
                    label: 'Use local accounts',
                    description: 'Send requests with the accounts stored on this machine.',
                    run: () => guarded(() => effects.useLocal()),
                },
                disconnect: {
                    id: 'disconnect',
                    label: 'Disconnect vault',
                    description: 'Withdraw this host from the vault.',
                    irreversible: true,
                    confirm: 'Withdraw this host from the vault? Setting it up again needs a new approval.',
                    run: () => guarded(() => effects.disconnect()),
                },
            };
            return {
                lines: view.lines,
                actions: view.actions.map((action) => definitions[action]),
                facts: {},
            };
        },
    };
}
//# sourceMappingURL=vault-setup.js.map