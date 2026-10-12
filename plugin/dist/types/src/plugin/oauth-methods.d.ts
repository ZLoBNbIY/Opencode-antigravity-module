import { authorizeAntigravity as defaultAuthorizeAntigravity, exchangeAntigravity as defaultExchangeAntigravity } from '../antigravity/oauth.js';
import type { AccountAccessService } from './account-access.js';
import { promptAddAnotherAccount as defaultPromptAddAnotherAccount, promptLoginMode as defaultPromptLoginMode, promptProjectId as defaultPromptProjectId } from './cli.js';
import type { AntigravityConfig } from './config/index.js';
import type { PluginLifecycle } from './lifecycle.js';
import { type QuotaManager } from './quota.js';
import { startOAuthListener as defaultStartOAuthListener } from './server.js';
import type { AuthDetails, AuthMethod, PluginClient } from './types.js';
export { type AntigravityTokenExchangeSuccess, type OAuthLoginDependencies, type OAuthLoginRequest, performOAuthLogin, } from './oauth-login.js';
export interface OAuthMethodDependencies {
    authorize: typeof defaultAuthorizeAntigravity;
    exchange: typeof defaultExchangeAntigravity;
    startListener: typeof defaultStartOAuthListener;
    promptProjectId: typeof defaultPromptProjectId;
    promptAddAnotherAccount: typeof defaultPromptAddAnotherAccount;
    promptLoginMode: typeof defaultPromptLoginMode;
    promptCallback(message: string): Promise<string>;
    openBrowser(url: string): Promise<boolean>;
    shouldSkipLocalServer(): boolean;
    isHeadless(): boolean;
    confirmOpenVerificationUrl(): Promise<boolean>;
}
interface CreateOAuthMethodsOptions {
    mayStartLocalWork?: () => Promise<boolean>;
    client: PluginClient;
    providerId: string;
    config: AntigravityConfig;
    lifecycle: PluginLifecycle;
    accountAccess: AccountAccessService;
    quotaManager?: QuotaManager;
    getAuth?: (() => Promise<AuthDetails | undefined>) | null;
    dependencies?: Partial<OAuthMethodDependencies>;
}
type OAuthCallbackParams = {
    code: string;
    state: string;
};
export declare function openBrowserWithSystem(url: string): Promise<boolean>;
export declare function parseOAuthCallbackInput(value: string, fallbackState: string): OAuthCallbackParams | {
    error: string;
};
export declare function createOAuthMethods({ client, providerId, config: _config, lifecycle, accountAccess, quotaManager: injectedQuotaManager, getAuth, dependencies, mayStartLocalWork, }: CreateOAuthMethodsOptions): AuthMethod[];
//# sourceMappingURL=oauth-methods.d.ts.map