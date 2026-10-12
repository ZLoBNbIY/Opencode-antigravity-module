/** @jsxImportSource @opentui/solid */
/**
 * OpenCode GA adapter for the shared `/antigravity` drawer and sidebar.
 *
 * Everything goes through the host's native location RPC: the server plugin
 * registers `antigravity-auth` (version 1) with the methods `state` and
 * `apply` at its location, and this adapter calls them with the host
 * client's `rpc.call`, naming the location explicitly. There is no port
 * file, no PID discovery, no private HTTP port and no sidebar file here.
 *
 * Contract rules this client keeps (the server enforces the same ones):
 *
 * - Generation: the first `state` sends `generation: null`; every later call
 *   sends the generation the server last answered with. When the server
 *   answers with a different one (`reset: 'generation-changed'`) the client
 *   rebinds: every scope's cursor restarts at 0. An `apply` answered with
 *   `stale-generation` or `disposed` changed nothing; the drawer says so and
 *   the next `state` rebinds.
 * - Scope: the current session (`{ kind: 'session', sessionID }`) or the
 *   sessionless scope on the home screen. Each scope has its own cursor. A
 *   drawer applies in the scope its menu arrived in, never the scope that
 *   happens to be current when the user chooses.
 * - Cursor: the client sends the highest cursor it has handled; the answer
 *   holds the next notifications and the cursor to send next.
 * - Disposal: after cleanup, or after the client rebinds, an answer to a
 *   request sent earlier is dropped unread, so a late completion can never
 *   open a dialog, show a toast or change the sidebar.
 *
 * Every answer is validated field by field before use; an answer that does
 * not match is refused and logged by field name only.
 *
 * The wire shapes mirror the facade's `ga/rpc/protocol.ts` (clean v1:
 * accounts carry opaque `selector`s, typed account actions name accounts
 * only by selector, every snapshot carries the location's settings). GA
 * notifications name a dialog command only, so this host builds the
 * `/antigravity` menu from the latest snapshot and the shared drawer renders
 * it; after every apply the menu is rebuilt from a fresh `state` read.
 *
 * Nothing here imports account storage, tokens, OAuth, the vault client or
 * server code, and nothing writes to the terminal or forces a theme.
 */
import { type JSX } from 'solid-js';
import { type ProjectionAccount, type ProjectionRoute, type ProjectionStatus } from '../../sidebar-projection';
import { type MenuApplyRequest, type MenuApplyResult, type MenuModel, type MenuParseResult, type MenuUi } from '../../tui/host-api';
export declare const GA_TUI_ID: "cortexkit.antigravity-auth";
export declare const GA_RPC_ID: "antigravity-auth";
export declare const GA_RPC_VERSION: 1;
/** How often the TUI pulls state and notifications from its location. */
export declare const GA_SIDEBAR_PULL_MS = 1000;
export interface GaLocationRef {
    readonly directory: string;
    readonly workspaceID?: string;
}
export interface GaRpcCallInput {
    readonly rpcID: string;
    readonly method: string;
    readonly location?: GaLocationRef;
    readonly input: unknown;
}
export interface GaSelectOption {
    readonly title: string;
    readonly value: string;
    readonly description?: string;
}
export type GaRoute = {
    readonly type: 'home';
} | {
    readonly type: 'session';
    readonly sessionID: string;
} | {
    readonly type: 'plugin';
    readonly id: string;
    readonly name: string;
};
export interface GaSlotClaim {
    readonly append: 'sidebar.content';
    readonly render: (input: {
        readonly sessionID: string;
    }) => JSX.Element;
}
/** The parts of the GA TUI `Context` this adapter uses. */
export interface GaTuiContext {
    readonly location: GaLocationRef | undefined;
    readonly client: {
        readonly rpc: {
            call(input: GaRpcCallInput): Promise<unknown>;
        };
    };
    readonly renderer?: {
        copyToClipboardOSC52?(text: string): boolean;
    };
    readonly ui: {
        readonly dialog: {
            set(options: {
                readonly size?: 'medium' | 'large' | 'xlarge';
            }): void;
            clear(): void;
            alert(options: {
                readonly title: string;
                readonly message: string;
            }): Promise<void>;
            confirm(options: {
                readonly title: string;
                readonly message: string;
            }): Promise<boolean | undefined>;
            prompt(options: {
                readonly title: string;
                readonly description?: string;
                readonly placeholder?: string;
                readonly value?: string;
            }): Promise<string | undefined>;
            select<Value>(options: {
                readonly title: string;
                readonly options: readonly {
                    readonly title: string;
                    readonly value: Value;
                    readonly description?: string;
                    readonly category?: string;
                    readonly footer?: string;
                }[];
                readonly current?: Value;
            }): Promise<Value | undefined>;
        };
        readonly toast: {
            show(options: {
                readonly message: string;
                readonly variant?: 'info' | 'success' | 'warning' | 'error';
            }): void;
        };
        readonly router: {
            current(): GaRoute;
        };
        readonly slot: (claim: GaSlotClaim) => () => void;
    };
}
export interface GaLogger {
    warn(message: string, detail?: Record<string, unknown>): void;
}
export type GaScope = {
    readonly kind: 'session';
    readonly sessionID: string;
} | {
    readonly kind: 'sessionless';
};
/** The dialog commands the server names in notifications and text applies. */
export declare const GA_COMMANDS: readonly ["antigravity-quota", "antigravity-account", "antigravity-routing", "antigravity-killswitch", "antigravity-dump", "antigravity-logging"];
export type GaCommand = (typeof GA_COMMANDS)[number];
export declare const GA_LOG_LEVELS: readonly ["error", "warn", "info", "debug", "trace"];
export type GaLogLevel = (typeof GA_LOG_LEVELS)[number];
export interface GaNotification {
    readonly cursor: number;
    readonly type: 'open-dialog';
    readonly command: GaCommand;
    readonly text: string;
}
/** A redacted account plus the opaque selector that names its credential. */
export interface GaAccount extends ProjectionAccount {
    readonly selector: string;
}
/** The location's operator settings, read fresh for every `state` answer. */
export interface GaSettings {
    readonly routing: {
        readonly cliFirst: boolean;
        readonly quotaStyleFallback: boolean;
    };
    readonly killswitch: {
        readonly enabled: boolean;
        readonly minimumRemainingPercent: number;
    };
    readonly logLevel: GaLogLevel;
    readonly dump: {
        readonly enabled: boolean;
    };
}
export type GaAccountsStatus = {
    readonly kind: 'complete';
} | {
    readonly kind: 'over-limit';
    readonly count: number;
    readonly limit: 64;
};
export interface GaSnapshot {
    readonly kind: 'snapshot';
    readonly generation: string;
    readonly scope: GaScope;
    readonly reset: 'initial' | 'generation-changed' | 'cursor-ahead' | null;
    readonly cursor: number;
    readonly dropped: number;
    readonly more: boolean;
    readonly notifications: readonly GaNotification[];
    readonly readSeq: number;
    readonly accountsStatus: GaAccountsStatus;
    readonly accounts: readonly GaAccount[];
    readonly route: ProjectionRoute | null;
    readonly status: ProjectionStatus & {
        readonly routingAuthoritative: boolean;
    };
    readonly settings: GaSettings;
}
export type GaStateOutput = GaSnapshot | {
    readonly kind: 'disposed';
    readonly generation: string;
};
/** A typed account action; accounts are named only by selector. */
export type GaAccountAction = {
    readonly kind: 'select';
    readonly selector: string;
    readonly target: 'active' | 'claude' | 'gemini';
} | {
    readonly kind: 'enable';
    readonly selector: string;
} | {
    readonly kind: 'disable';
    readonly selector: string;
} | {
    readonly kind: 'remove';
    readonly selector: string;
};
/** What the client sends besides version, generation and scope. */
export type GaApplyBody = {
    readonly command: GaCommand;
    readonly arguments: string;
} | {
    readonly command: 'antigravity-account';
    readonly action: GaAccountAction;
};
export type GaTargetOutcome = 'applied' | 'stale-target' | 'unknown-target' | 'unsupported-index-action' | 'failed';
/** The command result fields this TUI reads; the rest are validated only. */
export interface GaCommandResult {
    readonly command: GaCommand;
    readonly status: 'applied' | 'rejected' | 'failed';
    readonly text: string;
    readonly authorizationUrl?: string | null;
    readonly targetOutcome?: GaTargetOutcome | null;
}
export type GaApplyOutput = {
    readonly kind: 'applied';
    readonly generation: string;
    readonly scope: GaScope;
    readonly result: GaCommandResult;
} | {
    readonly kind: 'stale-generation';
    readonly generation: string;
} | {
    readonly kind: 'disposed';
    readonly generation: string;
};
/** Validates a `state` answer (the host's `{ output }` wrapper included). */
export declare function parseGaStateAnswer(raw: unknown): MenuParseResult<GaStateOutput>;
/** Validates an `apply` answer (the host's `{ output }` wrapper included). */
export declare function parseGaApplyAnswer(raw: unknown): MenuParseResult<GaApplyOutput>;
/** The server restarted or was disposed; the action did nothing. */
export declare class GaStaleError extends Error {
    readonly reason: 'stale-generation' | 'disposed' | 'not-bound';
    constructor(reason: 'stale-generation' | 'disposed' | 'not-bound');
}
/** This client was disposed; its answers are no longer read. */
export declare class GaClientDisposedError extends Error {
    constructor();
}
export declare function scopeKey(scope: GaScope): string;
export type GaPullResult = {
    readonly kind: 'snapshot';
    readonly snapshot: GaSnapshot;
} | {
    readonly kind: 'server-disposed';
}
/** The answer arrived after a rebind or disposal and was dropped unread. */
 | {
    readonly kind: 'dropped';
};
export interface GaLocationClient {
    /** The generation the client is bound to, or null before the first answer. */
    generation(): string | null;
    /** The next cursor this client sends for `scope`. */
    cursor(scope: GaScope): number;
    pull(scope: GaScope): Promise<GaPullResult>;
    apply(scope: GaScope, body: GaApplyBody): Promise<GaCommandResult>;
    dispose(): void;
    disposed(): boolean;
}
export declare function createGaLocationClient(options: {
    readonly call: (input: GaRpcCallInput) => Promise<unknown>;
    readonly location: GaLocationRef | undefined;
    readonly logger?: GaLogger;
}): GaLocationClient;
export declare function sectionForCommand(command: GaCommand): string;
export declare function buildGaMenu(snapshot: GaSnapshot, now: number): MenuModel;
/** Why a drawer choice could not be turned into a native apply. */
export declare class GaMenuChoiceError extends Error {
    constructor(message: string);
}
/**
 * The native apply for one drawer choice. Explicit target values are sent
 * ("turn on"), never a toggle, so a repeated or late choice cannot flip a
 * setting back. An account item sends its selector exactly as the server
 * issued it; a malformed one is refused here rather than guessed at.
 */
export declare function gaApplyBody(request: MenuApplyRequest): GaApplyBody;
/**
 * Turns a native command result into the drawer's result. `ok` is true only
 * when the command applied and, for an account action, its target applied.
 * A sign-in link is shown in full: on GA the browser returns to this
 * machine's sign-in listener, so there is nothing to paste.
 */
export declare function gaMenuResult(result: GaCommandResult, menu: MenuModel): MenuApplyResult;
/**
 * `MenuUi` over the GA dialog API. After `isActive()` turns false every call
 * is inert: a select resolves as dismissed and nothing is shown.
 */
export declare function createGaMenuUi(context: GaTuiContext, isActive: () => boolean): MenuUi;
export declare function currentScope(route: GaRoute): GaScope;
export interface GaPollerOptions {
    readonly client: GaLocationClient;
    readonly scope: () => GaScope;
    readonly onSnapshot: (snapshot: GaSnapshot) => void;
    readonly onNotification: (notification: GaNotification, scope: GaScope) => void;
    readonly logger?: GaLogger;
}
/**
 * One poll tick: pull the current scope, hand every new notification over in
 * cursor order, and keep pulling (bounded) while the server says more are
 * waiting. Never throws; a failed pull is logged and the next tick retries.
 */
export declare function pollGaOnce(options: GaPollerOptions): Promise<void>;
export interface GaSetupOptions {
    readonly logger?: GaLogger;
    readonly now?: () => number;
    /** Replaces the interval timer (tests). Returns a function that stops it. */
    readonly schedule?: (tick: () => void, intervalMs: number) => () => void;
}
/**
 * GA TUI setup: claims the sidebar, starts the location poller and opens the
 * drawer for every menu the server pushes. Returns the cleanup that stops
 * all of it; after cleanup no answer, dialog or toast from this setup
 * reaches the host.
 */
export declare function setupGaTui(context: GaTuiContext, options?: GaSetupOptions): () => Promise<void>;
/**
 * The GA TUI plugin definition (`{ id, setup }`, the 2.0.22 TUI plugin
 * shape). Importing this module starts nothing; `setup` binds to the
 * context's location and returns the cleanup that stops everything it
 * started.
 */
declare const gaTuiPlugin: {
    id: "cortexkit.antigravity-auth";
    setup: (context: GaTuiContext) => (() => Promise<void>);
};
export default gaTuiPlugin;
//# sourceMappingURL=host-ga.d.ts.map