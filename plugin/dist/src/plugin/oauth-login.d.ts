import type { AntigravityTokenExchangeResult, authorizeAntigravity, exchangeAntigravity } from '@cortexkit/antigravity-auth-core';
import type { startOAuthListener } from './server';
export type AntigravityTokenExchangeSuccess = Extract<AntigravityTokenExchangeResult, {
    type: 'success';
}>;
export interface OAuthLoginRequest {
    projectId?: string;
    noBrowser: boolean;
    isHeadless: boolean;
    refreshAccountIndex?: number;
    accounts: AntigravityTokenExchangeSuccess[];
    startFresh: boolean;
}
export interface OAuthLoginDependencies {
    authorize: typeof authorizeAntigravity;
    exchange: typeof exchangeAntigravity;
    startListener: typeof startOAuthListener;
    openBrowser(url: string): Promise<void>;
    upsert(result: AntigravityTokenExchangeSuccess): Promise<void>;
}
export declare function performOAuthLogin(request: OAuthLoginRequest, deps: OAuthLoginDependencies): Promise<AntigravityTokenExchangeSuccess>;
//# sourceMappingURL=oauth-login.d.ts.map