import { ANTIGRAVITY_PROVIDER_ID, enrollmentAuthority, loadCommonAuthClaustrum, } from '@cortexkit/antigravity-auth-core';
import { registerOpenCode2AuthMethods } from '../../common-auth-embedded/opencode2/index.js';
import { getStoragePath } from "../../plugin/storage.js";
import { OPENCODE_VAULT_ENROLLMENT_NAME, OPENCODE_VAULT_HOST, openCodeVaultPaths, } from "../../plugin/vault-custody.js";
export const GA_VAULT_METHOD_ID = 'antigravity-vault';
async function readAuthority() {
    const claustrum = await loadCommonAuthClaustrum();
    const paths = claustrum.hostEnrollmentPaths({
        stateDir: openCodeVaultPaths(getStoragePath()).dir,
        host: OPENCODE_VAULT_HOST,
    });
    return enrollmentAuthority(paths, OPENCODE_VAULT_ENROLLMENT_NAME, claustrum);
}
/** Adds one native vault activation method without modifying Google's existing login methods. */
export function registerGaVaultActivation(context, authority = readAuthority) {
    return registerOpenCode2AuthMethods(context, {
        integrationID: ANTIGRAVITY_PROVIDER_ID,
        methods: [],
        onLogin() {
            throw new Error('Vault activation does not accept local login results');
        },
        vault: {
            method: {
                id: GA_VAULT_METHOD_ID,
                type: 'oauth',
                label: 'Use approved Antigravity vault',
            },
            async activate() {
                if ((await authority()) !== 'vault') {
                    throw new Error('Approve Antigravity vault access before activating this connection');
                }
            },
        },
        label: 'Antigravity vault',
    });
}
//# sourceMappingURL=auth.js.map