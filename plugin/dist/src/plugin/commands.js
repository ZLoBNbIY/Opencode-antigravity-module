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
import { ANTIGRAVITY_MENU_COMMAND, antigravitySettingsSections, createAntigravityCommandMenu, loadCommonAuthCommands, } from '@cortexkit/antigravity-auth-core';
import { isTuiConnected as defaultIsTuiConnected } from '../rpc/notifications';
import { diagnosticsMenuSection, operatorMenuSettings } from './command-apply';
import { resolvePromptContext } from './prompt-context';
/** The one slash command this plugin registers. */
export { ANTIGRAVITY_MENU_COMMAND };
const HANDLED_COMMAND_SENTINEL = 'ANTIGRAVITY_COMMAND_HANDLED';
async function sendIgnoredMessage(client, sessionID, text) {
    const session = client.session;
    const promptContext = await resolvePromptContext(client, sessionID);
    const request = {
        path: { id: sessionID },
        body: {
            noReply: true,
            parts: [{ type: 'text', text, ignored: true }],
            ...(promptContext?.agent ? { agent: promptContext.agent } : {}),
            ...(promptContext?.model ? { model: promptContext.model } : {}),
            ...(promptContext?.variant ? { variant: promptContext.variant } : {}),
        },
    };
    if (typeof session?.promptAsync === 'function') {
        await session.promptAsync(request);
        return;
    }
    if (typeof session?.prompt === 'function') {
        await Promise.resolve(session.prompt(request));
        return;
    }
    throw new Error('OpenCode session prompt API is unavailable for ignored replies.');
}
function throwHandledCommandSentinel() {
    throw new Error(HANDLED_COMMAND_SENTINEL);
}
/**
 * The menu invocation for one session: the menu's notifications become
 * toast notifications for that session. common-auth copies these fields
 * when a call starts, so later work reports to the session that began it.
 */
export function menuInvocation(push, sessionId) {
    return {
        ...(sessionId !== undefined ? { sessionId } : {}),
        notify(message, kind) {
            push({
                command: ANTIGRAVITY_MENU_COMMAND,
                notify: { message, kind: kind ?? 'info' },
            }, sessionId);
        },
    };
}
/**
 * The host's `command.execute.before` for `/antigravity`: open the menu,
 * queue its payload for the TUI, and stop the host from sending the command
 * text as a prompt. Without a TUI listening, the outcome is written into the
 * session as an ignored message instead. Every other command is left alone.
 */
export function createAntigravityCommandExecuteBefore(options) {
    const connection = options.connection ?? {
        isTuiConnected: defaultIsTuiConnected,
    };
    return async (input) => {
        if (input.command !== ANTIGRAVITY_MENU_COMMAND)
            return;
        const opening = await options.open(input.sessionID);
        if (opening.kind === 'menu') {
            options.push(opening.payload, input.sessionID);
        }
        else {
            options.push({
                command: ANTIGRAVITY_MENU_COMMAND,
                notify: { message: opening.message, kind: 'warning' },
            }, input.sessionID);
        }
        if (!connection.isTuiConnected(input.sessionID)) {
            await sendIgnoredMessage(options.client, input.sessionID, opening.kind === 'menu'
                ? 'The Antigravity menu opens in the OpenCode terminal interface.'
                : opening.message);
        }
        throwHandledCommandSentinel();
    };
}
/**
 * The Sign in section: the OpenCode 1 OAuth add flow. Starting returns the
 * authorization URL for this session; finishing takes the redirect URL (or
 * its code) the browser ends on, and the account service admits the login
 * into the account store.
 */
export function signInMenuSection(oauth) {
    return {
        id: 'sign-in',
        title: 'Sign in',
        build() {
            return {
                lines: [
                    'Start a sign-in, open the link, then paste the address the browser ends on.',
                ],
                actions: [
                    {
                        id: 'start',
                        label: 'Start sign-in',
                        run: async ({ invocation }) => {
                            const sessionId = invocation.sessionId;
                            if (sessionId === undefined)
                                return {
                                    ok: false,
                                    text: 'Sign-in needs a session; run /antigravity from one.',
                                    code: 'refused',
                                };
                            const started = await oauth.start(sessionId);
                            return `Open this link to sign in, then choose Finish sign-in:\n${started.url}`;
                        },
                    },
                    {
                        id: 'finish',
                        label: 'Finish sign-in',
                        knobs: [
                            {
                                kind: 'text',
                                id: 'callback',
                                label: 'Address or code from the browser',
                                masked: true,
                                required: true,
                            },
                            { kind: 'text', id: 'label', label: 'Label (optional)' },
                        ],
                        run: async ({ values, invocation }) => {
                            const sessionId = invocation.sessionId;
                            const callback = values.callback;
                            if (sessionId === undefined || typeof callback !== 'string')
                                return {
                                    ok: false,
                                    text: 'Paste the address the browser ended on.',
                                    code: 'invalid-input',
                                };
                            const label = typeof values.label === 'string' && values.label.trim() !== ''
                                ? values.label.trim()
                                : undefined;
                            const finished = label === undefined
                                ? await oauth.finish(sessionId, callback)
                                : await oauth.finish(sessionId, callback, label);
                            return finished.text;
                        },
                    },
                ],
            };
        },
    };
}
/**
 * The OpenCode 1 `/antigravity` menu over the account store, built with
 * the shared core factory in repository mode. The host registers it as
 * its one slash command and carries its payloads over its own RPC.
 */
export async function createOpenCodeAntigravityMenu(options) {
    return createAntigravityCommandMenu({
        source: 'repository',
        commands: options.commands ?? (await loadCommonAuthCommands()),
        accounts: options.accounts,
        settings: operatorMenuSettings(options.settings),
        diagnostics: diagnosticsMenuSection(options),
        ...(options.refreshQuota ? { refreshQuota: options.refreshQuota } : {}),
        ...(options.accountLimits ? { accountLimits: options.accountLimits } : {}),
        ...(options.login ? { login: options.login } : {}),
        extras: [
            ...(options.signIn ? [signInMenuSection(options.signIn)] : []),
            ...(options.vault ? [options.vault] : []),
        ],
    });
}
function storeRefusal(opening) {
    return new Error(opening.status === 'refused' && typeof opening.message === 'string'
        ? opening.message
        : 'The Antigravity account store cannot be opened');
}
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
export function createAccountTargets(loader) {
    const isReady = (opening) => opening.status === 'ready' && opening.repository !== undefined;
    return {
        async accountSource() {
            const opening = await loader.accountStore();
            if (isReady(opening))
                return { kind: 'store', repository: opening.repository };
            if (opening.status === 'initialization-required')
                return { kind: 'none' };
            if (loader.usesPoolFile(opening))
                return { kind: 'pool-file' };
            throw storeRefusal(opening);
        },
        async loginTarget() {
            const opening = await loader.initializeFreshStore();
            if (isReady(opening))
                return opening.repository;
            if (opening.status !== 'initialization-required' &&
                loader.usesPoolFile(opening))
                return 'pool-file';
            throw storeRefusal(opening);
        },
    };
}
/**
 * The OpenCode 1 request path that follows the vault mode file: each
 * request re-reads the mode, so the Vault section's switches take effect on
 * the next request. In custody the vault path serves, built for the vault
 * source custody hands out (a new source after a switch rebuilds it); in
 * local mode the local path serves and any vault path is released. An
 * unreadable mode file refuses the request rather than picking a path.
 */
export function createCustodyAwareRequestPath(options) {
    let vault = null;
    const releaseVault = () => {
        const current = vault;
        vault = null;
        current?.path.dispose();
    };
    return {
        async fetch(input, init) {
            const mode = await options.readMode();
            if (!mode.ok)
                throw new Error(`The Antigravity vault mode is unclear (${mode.reason}); choose a mode in the Vault section of the Antigravity menu.`);
            if (mode.record.mode === 'local') {
                releaseVault();
                return options.local.fetch(input, init);
            }
            const source = await options.custodySource();
            if (vault?.source !== source) {
                releaseVault();
                vault = { source, path: options.vault(source) };
            }
            return vault.path.fetch(input, init);
        },
        dispose() {
            releaseVault();
            options.local.dispose();
        },
    };
}
/** The same command dispatcher over vault sections, without a local repository or sign-in flow. */
export async function createOpenCodeVaultAntigravityMenu(options) {
    return createAntigravityCommandMenu({
        source: 'sections',
        commands: options.commands ?? (await loadCommonAuthCommands()),
        sections: {
            ...options.sections,
            ...antigravitySettingsSections(operatorMenuSettings(options.settings)),
        },
        diagnostics: diagnosticsMenuSection(options),
        extras: options.vault ? [options.vault] : [],
    });
}
//# sourceMappingURL=commands.js.map