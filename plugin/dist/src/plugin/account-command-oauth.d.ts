import type { AntigravityAuthorization, AntigravityTokenExchangeResult } from '../antigravity/oauth';
import type { CommandAccountRow } from './command-data';
type OAuthSuccess = Extract<AntigravityTokenExchangeResult, {
    type: 'success';
}>;
export interface AccountCommandOAuthServiceOptions {
    authorize: () => Promise<AntigravityAuthorization>;
    exchange: (code: string, state: string) => Promise<AntigravityTokenExchangeResult>;
    persist: (result: OAuthSuccess) => Promise<void>;
    listAccounts: () => Promise<CommandAccountRow[]>;
    /**
     * Optional hook invoked AFTER persist completes successfully. The plugin
     * uses it to refresh the live AccountManager so the new account is
     * visible to routing immediately, without waiting for an auth reload.
     * Failures are swallowed — the OAuth flow still reports success and the
     * next periodic AccountManager reload picks up the new account.
     */
    onAfterPersist?: (result: OAuthSuccess) => Promise<void> | void;
    now?: () => number;
}
export interface AccountCommandOAuthService {
    start(sessionId: string): Promise<{
        url: string;
        accounts: CommandAccountRow[];
    }>;
    finish(sessionId: string, callbackInput: string, label?: string): Promise<{
        text: string;
        accounts: CommandAccountRow[];
    }>;
    dispose(): void;
}
export declare function createAccountCommandOAuthService(options: AccountCommandOAuthServiceOptions): AccountCommandOAuthService;
export {};
//# sourceMappingURL=account-command-oauth.d.ts.map