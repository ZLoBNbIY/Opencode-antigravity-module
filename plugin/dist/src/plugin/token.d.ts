import { type AccountTokenExchange } from '@cortexkit/antigravity-auth-core';
import type { OAuthAuthDetails, PluginClient } from './types';
export declare class AntigravityTokenRefreshError extends Error {
    code?: string;
    description?: string;
    status: number;
    statusText: string;
    constructor(options: {
        message: string;
        code?: string;
        description?: string;
        status: number;
        statusText: string;
    });
}
/**
 * Whether `error`, or an error it was caused by, is Google's `invalid_grant`
 * answer: the refresh token is revoked and the account needs signing in
 * again. Repository refresh failures wrap the exchange's error as their
 * cause, so the chain is followed (a bounded number of steps).
 */
export declare function isInvalidGrantFailure(error: unknown): boolean;
/**
 * The token exchange an account repository refreshes rows with. It is
 * handed the row's bare refresh token and performs only the HTTP grant;
 * the repository commits the result under the row's credential fence, so
 * this function never writes anything. Project ids are not touched here: a
 * refresh keeps the row's stored projects.
 */
export declare function createAntigravityTokenExchange(options?: {
    now?: () => number;
}): AccountTokenExchange;
/**
 * Refreshes a host OAuth credential (refresh token packed with its project
 * ids) and returns the updated credential without persisting it. Returns
 * `undefined` for a credential without a refresh token and for failures
 * other than an error answer from Google, which is thrown as
 * `AntigravityTokenRefreshError`.
 */
export declare function refreshAccessToken(auth: OAuthAuthDetails, _client: PluginClient, _providerId: string): Promise<OAuthAuthDetails | undefined>;
//# sourceMappingURL=token.d.ts.map