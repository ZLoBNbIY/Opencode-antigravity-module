import { type EnrollmentAuthority } from '@cortexkit/antigravity-auth-core';
import type { AuthMethod } from './types.js';
export declare const V1_VAULT_ACTIVATION_LABEL = "Activate approved Antigravity vault";
export declare function nativeOpenCodeAuthPath(env?: NodeJS.ProcessEnv, home?: string): string;
/** Activate a fresh host slot without a Google login or a local account write. */
export declare function createV1VaultActivationMethod(input: {
    providerId: string;
    readAuthority: () => Promise<EnrollmentAuthority>;
    authFile?: () => string;
}): AuthMethod;
//# sourceMappingURL=vault-activation.d.ts.map