import { type EnrollmentAuthority } from '@cortexkit/antigravity-auth-core';
import type { Plugin } from '@opencode/plugin';
import type { Registration } from '@opencode/plugin/promise/registration';
export declare const GA_VAULT_METHOD_ID = "antigravity-vault";
/** Adds one native vault activation method without modifying Google's existing login methods. */
export declare function registerGaVaultActivation(context: {
    integration: Pick<Plugin.Context['integration'], 'transform'>;
}, authority?: () => Promise<EnrollmentAuthority>): Promise<Registration>;
//# sourceMappingURL=auth.d.ts.map