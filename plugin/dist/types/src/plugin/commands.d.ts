/**
 * The single `/antigravity` slash command of OpenCode 1.
 *
 * The command opens the shared Antigravity menu built by the core
 * `createAntigravityCommandMenu` over the location's account store: the
 * server pushes the menu payload to the TUI over the private RPC queue, and
 * the TUI sends each chosen action back to the RPC server, which hands it to
 * the same menu's `apply`. The menu (common-auth's public `./commands`
 * entry) owns confirmation, redaction, per-invocation isolation and action
 * dispatch; this module supplies the OpenCode-specific sections (settings,
 * diagnostics, sign-in) and the host hook.
 */
import { ANTIGRAVITY_MENU_COMMAND, type AntigravityMenuAccounts, type AntigravityMenuSections, type AntigravityRepositoryMenuOptions, type CommonAuthCommandsModule, createAntigravityCommandMenu } from '@cortexkit/antigravity-auth-core';
import type { NotifyKind, RpcNotificationPayload } from '../rpc/protocol.js';
import type { AccountCommandOAuthService } from './account-command-oauth.js';
import type { OperatorSettings, OperatorSettingsController } from './operator-settings.js';
import type { PluginClient, PluginResult } from './types.js';
/** The one slash command this plugin registers. */
export { ANTIGRAVITY_MENU_COMMAND };
/** Queues one RPC notification for a session (or every session). */
export type PushMenuNotification = (payload: RpcNotificationPayload, sessionId?: string) => void;
/**
 * The menu invocation for one session: the menu's notifications become
 * toast notifications for that session. common-auth copies these fields
 * when a call starts, so later work reports to the session that began it.
 */
export declare function menuInvocation(push: PushMenuNotification, sessionId: string | undefined): {
    sessionId?: string;
    notify(message: string, kind?: NotifyKind): void;
};
/**
 * What opening the menu yields for a session: the menu payload, or the
 * reason the menu cannot be shown (for example a location whose accounts
 * have not been migrated to the account store yet).
 */
export type MenuOpening = {
    readonly kind: 'menu';
    readonly payload: RpcNotificationPayload;
} | {
    readonly kind: 'unavailable';
    readonly message: string;
};
export interface CommandConnectionState {
    isTuiConnected(sessionId?: string): boolean;
}
/**
 * The host's `command.execute.before` for `/antigravity`: open the menu,
 * queue its payload for the TUI, and stop the host from sending the command
 * text as a prompt. Without a TUI listening, the outcome is written into the
 * session as an ignored message instead. Every other command is left alone.
 */
export declare function createAntigravityCommandExecuteBefore(options: {
    readonly client: PluginClient;
    readonly open: (sessionId: string) => Promise<MenuOpening>;
    readonly push: PushMenuNotification;
    readonly connection?: CommandConnectionState;
}): PluginResult['command.execute.before'];
type CommonAuthMenuOptions = Parameters<CommonAuthCommandsModule['createCommandMenu']>[0];
type MenuPluginExtraSection = NonNullable<CommonAuthMenuOptions['extras']>[number];
/**
 * The Sign in section: the OpenCode 1 OAuth add flow. Starting returns the
 * authorization URL for this session; finishing takes the redirect URL (or
 * its code) the browser ends on, and the account service admits the login
 * into the account store.
 */
export declare function signInMenuSection(oauth: Pick<AccountCommandOAuthService, 'start' | 'finish'>): MenuPluginExtraSection;
/**
 * The OpenCode 1 `/antigravity` menu over the account store, built with
 * the shared core factory in repository mode. The host registers it as
 * its one slash command and carries its payloads over its own RPC.
 */
export declare function createOpenCodeAntigravityMenu(options: {
    readonly accounts: AntigravityMenuAccounts;
    readonly settings: Pick<OperatorSettingsController, 'get' | 'update'>;
    readonly dump: {
        isEnabled(): boolean;
        setEnabled(enabled: boolean): void;
    };
    readonly applyLogLevel: (level: OperatorSettings['log_level']) => void;
    readonly refreshQuota?: AntigravityRepositoryMenuOptions['refreshQuota'];
    readonly accountLimits?: AntigravityRepositoryMenuOptions['accountLimits'];
    readonly login?: AntigravityRepositoryMenuOptions['login'];
    /** The OAuth add flow, shown as the Sign in section. */
    readonly signIn?: Pick<AccountCommandOAuthService, 'start' | 'finish'>;
    /** The Vault section (OpenCode vault custody setup). */
    readonly vault?: MenuPluginExtraSection;
    readonly commands?: CommonAuthCommandsModule;
}): Promise<ReturnType<typeof createAntigravityCommandMenu>>;
/** The account-store opening, as the auth loader reports it. */
interface AccountStoreOpeningView {
    readonly status: string;
    readonly repository?: unknown;
    readonly message?: string;
}
/** The auth loader's single account-store opening and its fresh-install step. */
export interface AccountTargetsLoader<O extends AccountStoreOpeningView> {
    accountStore(): Promise<O>;
    usesPoolFile(opening: O): boolean;
    initializeFreshStore(): Promise<O>;
}
type RepositoryOf<O> = O extends {
    readonly status: 'ready';
    readonly repository: infer R;
} ? R : never;
/**
 * Where OpenCode 1 reads accounts and admits new logins, from the auth
 * loader's single account-store opening.
 *
 * - `accountSource`: the account store, the pool file of a location not
 *   yet migrated, or nothing on a fresh installation; any other store
 *   state refuses.
 * - `loginTarget`: a fresh installation first gets its explicit empty
 *   account store (`initializeFreshStore`), so the first login is admitted
 *   by the store and never written to a new pool file; a location still on
 *   its pool file keeps it until it is migrated; any other store state
 *   (pending migration or recovery, an unreadable store) refuses the login.
 *   Nothing is initialized over an existing pool file or store.
 */
export declare function createAccountTargets<O extends AccountStoreOpeningView & {
    readonly status: string;
}>(loader: AccountTargetsLoader<O>): {
    accountSource(): Promise<{
        kind: "store";
        repository: RepositoryOf<O>;
    } | {
        kind: "pool-file";
    } | {
        kind: "none";
    }>;
    loginTarget(): Promise<RepositoryOf<O> | "pool-file">;
};
/** A request path the auth loader installs: the host-facing fetch and its release. */
export interface RequestPath {
    fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
    dispose(): void;
}
/**
 * The OpenCode 1 request path that follows the vault mode file: each
 * request re-reads the mode, so the Vault section's switches take effect on
 * the next request. In custody the vault path serves, built for the vault
 * source custody hands out (a new source after a switch rebuilds it); in
 * local mode the local path serves and any vault path is released. An
 * unreadable mode file refuses the request rather than picking a path.
 */
export declare function createCustodyAwareRequestPath<S>(options: {
    readonly readMode: () => Promise<{
        readonly ok: true;
        readonly record: {
            readonly mode: 'local' | 'custody';
        };
    } | {
        readonly ok: false;
        readonly reason: string;
    }>;
    readonly local: RequestPath;
    /** The vault source for a custody request; refuses when custody cannot serve. */
    readonly custodySource: () => Promise<S>;
    readonly vault: (source: S) => RequestPath;
}): RequestPath;
/** The same command dispatcher over vault sections, without a local repository or sign-in flow. */
export declare function createOpenCodeVaultAntigravityMenu(options: Pick<Parameters<typeof createOpenCodeAntigravityMenu>[0], 'settings' | 'dump' | 'applyLogLevel' | 'commands' | 'vault'> & {
    readonly sections: Pick<AntigravityMenuSections, 'accounts' | 'quota'>;
}): Promise<ReturnType<typeof createAntigravityCommandMenu>>;
//# sourceMappingURL=commands.d.ts.map