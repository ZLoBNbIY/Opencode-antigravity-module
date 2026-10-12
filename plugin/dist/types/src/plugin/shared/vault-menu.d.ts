import { type AntigravityMenuSections, type AntigravityQuotaCheckReport } from '@cortexkit/antigravity-auth-core';
import type { VaultAccountPool, VaultAccountRow } from './vault-request-credentials.js';
/** Show accounts and quotas from the same vault account pool that selects request routes. */
export declare function createVaultAccountMenuSections(pool: Pick<VaultAccountPool, 'selector'>, selectorOf: (row: VaultAccountRow) => string, checkQuota?: (signal: AbortSignal) => Promise<AntigravityQuotaCheckReport>): Pick<AntigravityMenuSections, 'accounts' | 'quota'>;
//# sourceMappingURL=vault-menu.d.ts.map