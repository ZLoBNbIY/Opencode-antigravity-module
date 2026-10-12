/**
 * RPC contract between this plugin's server side and its clients (the TUI and
 * test tools) on OpenCode 2. "OpenCode 2" means the 2.x host line; this
 * contract targets its 2.0.22 release, whose plugin API lets a server plugin
 * register named RPC methods. "OpenCode 1" is the 1.x host line, where the
 * same dialogs talk to this plugin through its own loopback HTTP RPC
 * (`src/rpc/`).
 *
 * `antigravity-auth`, protocol version 1, and the methods `state` and `apply`
 * are names this plugin defines. They are not existing host or provider APIs.
 * The OpenCode 2.0.22 host routes `POST /api/rpc/:rpcID/:method` with body
 * `{ input }` to the definition registered under that id at the requested
 * location, and answers `{ output? }` (its generated client's `rpc.call`).
 * The host validates input before calling the handler, and validates output
 * before answering, with the schemas in the definition. It accepts Standard
 * Schema V1 objects as schemas, so every schema below is a Standard Schema
 * object backed by a strict hand-written validator.
 *
 * Portability: this module has no runtime imports. Clients can bundle it
 * without pulling in server, account, OAuth or credential code. Its imports
 * are type-only: the request, result and payload types of the Antigravity
 * menu (`/antigravity`), defined by `@cortexkit/common-auth/commands` and
 * carried by the OpenCode 1 RPC as well, and core's name for that command.
 *
 * Contract rules (each has a test in `protocol.test.ts`):
 *
 * - Version: every input and output carries `version: 1`. Any other value,
 *   including the string `"1"`, is refused before any effect.
 * - Generation: each server activation (one plugin setup at one location) has
 *   an opaque generation token. `state` with `generation: null` asks for the
 *   current one. A `state` with a different generation is answered with
 *   `reset: 'generation-changed'` and the scope's notifications restart at
 *   cursor 0. `apply` requires the current generation and is answered with
 *   `kind: 'stale-generation'` and no effect otherwise.
 * - Scope: `{ kind: 'session', sessionID }` or `{ kind: 'sessionless' }`.
 *   Scopes are disjoint: a session scope sees only that session's
 *   notifications and route; the sessionless scope sees only notifications
 *   raised without a session. Omitting a session never widens access.
 * - Cursor: a non-negative safe integer per scope. Notifications carry
 *   cursors starting at 1. Sending cursor `c` acknowledges everything up to
 *   `c`; the answer holds the next notifications after `c`, at most
 *   `MAX_NOTIFICATIONS_PER_STATE`, with `more` set when further ones remain.
 *   A cursor ahead of the scope's last issued cursor is answered with
 *   `reset: 'cursor-ahead'` and delivery from cursor 0. `dropped` counts
 *   notifications evicted before the client acknowledged them.
 * - Disposal: once an activation is disposed, both methods answer
 *   `kind: 'disposed'` with that activation's generation, and a late
 *   completion from it never touches a newer activation.
 * - Redaction: accounts are ordinal (`acct-<n>`, `Account <n+1>`) and carry
 *   only enabled/current/health/cooldown/quota percentages and plan tier.
 *   There is no field for an email, token, project id, fingerprint, profile
 *   name or upstream error text, and unknown keys are refused, so a live
 *   account object spread into a DTO fails validation.
 * - Menu: the GA `apply` input carries one action of the Antigravity menu,
 *   a `CommandApplyRequest` of `@cortexkit/common-auth/commands` without
 *   `sessionId`; the server sets `sessionId` from the input's scope. The
 *   answer is that module's `CommandApplyResult`, which holds the refreshed
 *   menu. A notification carries either the Antigravity menu payload (the
 *   client opens the menu) or a message for a toast. Menu actions name an
 *   account by the opaque item id the menu issued for its current
 *   credential; account positions and `acct-<n>` ids are never targets.
 * - Selectors: each account in a snapshot carries an opaque random
 *   `selector` naming its current credential, so a client can tell a
 *   replaced credential from the same one across reads.
 * - Account limit: a roster larger than `ANTIGRAVITY_RPC_LIMITS.accounts` is
 *   answered with `accountsStatus: over-limit` and no accounts, never with a
 *   shortened list.
 * - Settings: every snapshot carries the location's current operator
 *   settings, so a client never needs an `apply` to read them.
 * - Validation never coerces: `true`, `"5"`, `5.5`, `-1`, `-0`, `NaN` and
 *   `Infinity` are not cursors, and no value is passed through `Number()`.
 *   Issue messages name the field, never the received value, so a rejected
 *   menu value (which can hold a pasted OAuth code) is not echoed back.
 */
import type { CommandApplyRequest, CommandApplyResult, RpcNotificationPayload } from '../../rpc/protocol.js';
/** The RPC id this adapter registers. Chosen by this adapter, not the host. */
export declare const ANTIGRAVITY_RPC_ID: "antigravity-auth";
/** The only protocol version this module accepts and produces. */
export declare const ANTIGRAVITY_RPC_VERSION: 1;
export declare const ANTIGRAVITY_RPC_METHODS: readonly ["state", "apply"];
export type AntigravityRpcMethod = (typeof ANTIGRAVITY_RPC_METHODS)[number];
/** Event published to the location when a notification is queued. */
export declare const ANTIGRAVITY_RPC_EVENTS: readonly ["changed"];
export type AntigravityRpcEvent = (typeof ANTIGRAVITY_RPC_EVENTS)[number];
/** The shared menu's slash command; every menu request and payload names it. */
export declare const ANTIGRAVITY_MENU_COMMAND_NAME: "antigravity";
export declare const ANTIGRAVITY_LOG_LEVELS: readonly ["error", "warn", "info", "debug", "trace"];
export type AntigravityLogLevel = (typeof ANTIGRAVITY_LOG_LEVELS)[number];
export declare const ANTIGRAVITY_RPC_LIMITS: {
    /** Generation tokens: 1–64 characters of `[A-Za-z0-9_-]`. */
    readonly generationMaxLength: 64;
    /** Session ids: 1–256 visible ASCII characters (0x21–0x7E). */
    readonly sessionIDMaxLength: 256;
    /** Menu ids (command, section, item, action, knob, choice values). */
    readonly menuIdMaxLength: 256;
    /** Knob values in one menu request. */
    readonly menuValues: 64;
    /** Sections in one menu. */
    readonly menuSections: 16;
    /** Items in one menu section. */
    readonly menuItemsPerSection: 512;
    /** Actions on one section or item. */
    readonly menuActions: 64;
    /** Knobs on one action. */
    readonly menuKnobs: 64;
    /** Choices of one `choice` knob. */
    readonly menuChoices: 256;
    /** Read-only lines of one section. */
    readonly menuLines: 256;
    /** Entries in one `facts` record. */
    readonly menuFacts: 64;
    /** Nesting depth of a `facts` value. */
    readonly menuFactsDepth: 4;
    /** Any user-facing text in an output. */
    readonly textMaxLength: 4096;
    /** Notifications returned by one `state` call. */
    readonly notificationsPerState: 32;
    /** Accounts in one output. */
    readonly accounts: 64;
    /** Quota windows per pool entry. */
    readonly quotaWindows: 4;
    /** Maximum length of a plan tier id. */
    readonly tierIDMaxLength: 128;
    /** OAuth authorization URLs handed to the user. */
    readonly authorizationURLMaxLength: 4096;
};
export declare const MAX_NOTIFICATIONS_PER_STATE: 32;
export type AntigravityRpcScope = {
    readonly kind: 'session';
    readonly sessionID: string;
} | {
    readonly kind: 'sessionless';
};
export interface AntigravityStateInput {
    readonly version: typeof ANTIGRAVITY_RPC_VERSION;
    /** The generation the client last saw, or `null` on first contact. */
    readonly generation: string | null;
    readonly scope: AntigravityRpcScope;
    /** Highest notification cursor the client has received in this scope. */
    readonly cursor: number;
}
/**
 * The `request` of a GA `apply` input: one Antigravity menu action, as
 * `@cortexkit/common-auth/commands`' `CommandApplyRequest` for the
 * `antigravity` command without `sessionId`. The server derives `sessionId`
 * from the input's scope; a request that names one itself is refused.
 */
export type AntigravityMenuRequest = Omit<CommandApplyRequest, 'command' | 'sessionId'> & {
    readonly command: typeof ANTIGRAVITY_MENU_COMMAND_NAME;
};
export interface AntigravityApplyInput {
    readonly version: typeof ANTIGRAVITY_RPC_VERSION;
    /**
     * Must equal the generation of the activation serving this location;
     * anything else is answered `stale-generation` without an effect.
     */
    readonly generation: string;
    readonly scope: AntigravityRpcScope;
    readonly request: AntigravityMenuRequest;
}
export interface AntigravityQuotaWindowDto {
    readonly window: 'weekly' | '5h';
    readonly remainingPercent: number;
    readonly checkedAt?: number;
    readonly resetAt?: number;
}
export interface AntigravityQuotaEntryDto {
    readonly remainingPercent: number;
    readonly checkedAt?: number;
    readonly resetAt?: number;
    readonly windows?: readonly AntigravityQuotaWindowDto[];
}
/**
 * One account as the sidebar shows it: the redacted, ordinal shape that
 * `redactAccountForSidebar` produces from a live account. Optional keys may
 * be absent or `undefined`.
 */
export interface AntigravityAccountDto {
    /**
     * Opaque value naming this account's current credential. It is random,
     * carries no account data, and changes when the credential is replaced or
     * its identity changes.
     */
    readonly selector: string;
    readonly id: string;
    readonly label: string;
    readonly enabled: boolean;
    readonly health: number;
    readonly current: boolean;
    readonly cooldownUntil?: number;
    readonly quota: {
        readonly gemini?: AntigravityQuotaEntryDto;
        readonly 'non-gemini'?: AntigravityQuotaEntryDto;
    };
    readonly tier?: {
        readonly id: string;
        readonly paidId?: string;
        readonly capturedAt: number;
    };
}
/** The requesting session's active route; never another session's. */
export interface AntigravityRouteDto {
    readonly accountId: string;
    readonly modelFamily: 'claude' | 'gemini';
    readonly headerStyle: 'antigravity' | 'gemini-cli';
    readonly strategy: 'sticky' | 'round-robin' | 'hybrid' | null;
    readonly updatedAt: number;
}
export interface AntigravityStatusDto {
    /** When quota was last checked, or `null` if never. */
    readonly checkedAt: number | null;
    /** End of the current quota backoff, or `null` without one. */
    readonly quotaBackoffUntil: number | null;
    readonly routingAuthoritative: boolean;
}
/**
 * The location's operator settings, read fresh for every `state` answer.
 * Per-account killswitch overrides are left out: their keys are derived from
 * refresh tokens.
 */
export interface AntigravitySettingsDto {
    readonly routing: {
        readonly cliFirst: boolean;
        readonly quotaStyleFallback: boolean;
    };
    readonly killswitch: {
        readonly enabled: boolean;
        readonly minimumRemainingPercent: number;
    };
    readonly logLevel: AntigravityLogLevel;
    readonly dump: {
        readonly enabled: boolean;
    };
}
/**
 * Whether `accounts` is the whole roster. When the roster is larger than
 * `ANTIGRAVITY_RPC_LIMITS.accounts`, the answer carries no accounts at all
 * rather than a silently shortened list.
 */
export type AntigravityAccountsStatus = {
    readonly kind: 'complete';
} | {
    readonly kind: 'over-limit';
    readonly count: number;
    readonly limit: (typeof ANTIGRAVITY_RPC_LIMITS)['accounts'];
};
/**
 * One queued notification: the Antigravity menu payload the client opens,
 * or a message for a toast (the same payloads the OpenCode 1 RPC queues).
 */
export interface AntigravityNotificationDto {
    readonly cursor: number;
    readonly payload: RpcNotificationPayload;
}
export type AntigravityStateReset = 'initial' | 'generation-changed' | 'cursor-ahead';
export declare const ANTIGRAVITY_STATE_RESETS: readonly ["initial", "generation-changed", "cursor-ahead"];
export interface AntigravityStateSnapshot {
    readonly version: typeof ANTIGRAVITY_RPC_VERSION;
    readonly kind: 'snapshot';
    readonly generation: string;
    readonly scope: AntigravityRpcScope;
    /** `null` when the client's generation and cursor were both current. */
    readonly reset: AntigravityStateReset | null;
    /** Send this cursor next time; it acknowledges what this answer holds. */
    readonly cursor: number;
    /** Notifications evicted in this scope before they were acknowledged. */
    readonly dropped: number;
    /** True when notifications after `cursor` are still waiting. */
    readonly more: boolean;
    readonly notifications: readonly AntigravityNotificationDto[];
    /**
     * Increases with every `state` answer of this activation, so an answer can
     * be matched with diagnostics recorded for the same read.
     */
    readonly readSeq: number;
    readonly accountsStatus: AntigravityAccountsStatus;
    /** Empty unless `accountsStatus.kind` is `complete`. */
    readonly accounts: readonly AntigravityAccountDto[];
    readonly route: AntigravityRouteDto | null;
    readonly status: AntigravityStatusDto;
    readonly settings: AntigravitySettingsDto;
}
/** Answer from an activation that has been disposed. */
export interface AntigravityDisposedOutput {
    readonly version: typeof ANTIGRAVITY_RPC_VERSION;
    readonly kind: 'disposed';
    readonly generation: string;
}
export type AntigravityStateOutput = AntigravityStateSnapshot | AntigravityDisposedOutput;
export interface AntigravityAppliedOutput {
    readonly version: typeof ANTIGRAVITY_RPC_VERSION;
    readonly kind: 'applied';
    readonly generation: string;
    readonly scope: AntigravityRpcScope;
    /** The menu's answer: the message, failure code and refreshed menu. */
    readonly result: CommandApplyResult;
}
export interface AntigravityStaleGenerationOutput {
    readonly version: typeof ANTIGRAVITY_RPC_VERSION;
    readonly kind: 'stale-generation';
    /** The activation's current generation; nothing was applied. */
    readonly generation: string;
}
export type AntigravityApplyOutput = AntigravityAppliedOutput | AntigravityStaleGenerationOutput | AntigravityDisposedOutput;
/**
 * A type alias rather than an interface: the host requires an event schema's
 * output to be assignable to a plain string-keyed record, which TypeScript
 * grants to object type aliases but not to interfaces.
 */
export type AntigravityChangedEvent = {
    readonly version: typeof ANTIGRAVITY_RPC_VERSION;
    readonly generation: string;
};
export interface AntigravityRpcIssue {
    readonly message: string;
    readonly path: readonly (string | number)[];
}
export type AntigravityRpcParseResult<T> = {
    readonly ok: true;
    readonly value: T;
} | {
    readonly ok: false;
    readonly issues: readonly AntigravityRpcIssue[];
};
/**
 * The Standard Schema V1 interface (https://standardschema.dev). The
 * specification asks implementers to copy these types rather than import
 * them, so this module needs no schema library.
 */
export interface StandardSchemaV1<Input = unknown, Output = Input> {
    readonly '~standard': {
        readonly version: 1;
        readonly vendor: string;
        readonly validate: (value: unknown) => StandardSchemaV1Result<Output> | Promise<StandardSchemaV1Result<Output>>;
        readonly types?: {
            readonly input: Input;
            readonly output: Output;
        };
    };
}
export type StandardSchemaV1Result<Output> = {
    readonly value: Output;
    readonly issues?: undefined;
} | {
    readonly issues: readonly {
        readonly message: string;
        readonly path?: readonly (PropertyKey | {
            readonly key: PropertyKey;
        })[];
    }[];
};
/** A strict validator usable both directly and as a Standard Schema. */
export interface AntigravityRpcSchema<T> extends StandardSchemaV1<T, T> {
    readonly parse: (value: unknown) => AntigravityRpcParseResult<T>;
}
export declare const AntigravityStateInputSchema: AntigravityRpcSchema<AntigravityStateInput>;
export declare const AntigravityStateOutputSchema: AntigravityRpcSchema<AntigravityStateOutput>;
export declare const AntigravityApplyInputSchema: AntigravityRpcSchema<AntigravityApplyInput>;
export declare const AntigravityApplyOutputSchema: AntigravityRpcSchema<AntigravityApplyOutput>;
export declare const AntigravityChangedEventSchema: AntigravityRpcSchema<AntigravityChangedEvent>;
export declare const AntigravityAccountsSchema: AntigravityRpcSchema<readonly AntigravityAccountDto[]>;
export declare const AntigravityApplyResultSchema: AntigravityRpcSchema<CommandApplyResult>;
export declare const AntigravityNotificationPayloadSchema: AntigravityRpcSchema<RpcNotificationPayload>;
/**
 * The definition the server registers and clients call. Its shape is the one
 * the OpenCode 2.0.22 RPC registry reads: `id`, `methods.<name>.{input,
 * output}` and `events.<name>.schema`. This module imports nothing from the
 * host SDK, so the check against the SDK's `Rpc.PortableDefinition` type
 * happens where the server passes this object to `rpc.register`.
 */
export declare const ANTIGRAVITY_RPC_DEFINITION: {
    readonly id: "antigravity-auth";
    readonly methods: {
        readonly state: {
            readonly input: AntigravityRpcSchema<AntigravityStateInput>;
            readonly output: AntigravityRpcSchema<AntigravityStateOutput>;
        };
        readonly apply: {
            readonly input: AntigravityRpcSchema<AntigravityApplyInput>;
            readonly output: AntigravityRpcSchema<AntigravityApplyOutput>;
        };
    };
    readonly events: {
        readonly changed: {
            readonly schema: AntigravityRpcSchema<AntigravityChangedEvent>;
        };
    };
};
/**
 * Arguments for the OpenCode 2 client's `rpc.call`. `location` is left out:
 * the client calling from a location adds it, and the server never routes
 * by a caller-supplied path.
 */
export interface AntigravityRpcCall<M extends AntigravityRpcMethod, I extends AntigravityStateInput | AntigravityApplyInput> {
    readonly rpcID: typeof ANTIGRAVITY_RPC_ID;
    readonly method: M;
    readonly input: I;
}
export declare function stateCall(input: AntigravityStateInput): AntigravityRpcCall<'state', AntigravityStateInput>;
export declare function applyCall(input: AntigravityApplyInput): AntigravityRpcCall<'apply', AntigravityApplyInput>;
export declare function readStateCallOutput(raw: unknown): AntigravityRpcParseResult<AntigravityStateOutput>;
export declare function readApplyCallOutput(raw: unknown): AntigravityRpcParseResult<AntigravityApplyOutput>;
/**
 * Every name, literal and limit of the serialized contract in one value.
 * A test checks its SHA-256, so any change to the wire contract also changes
 * that hash, and clients built against another version can detect it.
 */
export declare const ANTIGRAVITY_RPC_CONTRACT: {
    readonly id: "antigravity-auth";
    readonly version: 1;
    readonly methods: readonly ["state", "apply"];
    readonly events: readonly ["changed"];
    readonly menuCommand: "antigravity";
    readonly logLevels: readonly ["error", "warn", "info", "debug", "trace"];
    readonly scopeKinds: readonly ["session", "sessionless"];
    readonly stateKinds: readonly ["snapshot", "disposed"];
    readonly applyKinds: readonly ["applied", "stale-generation", "disposed"];
    readonly stateResets: readonly ["initial", "generation-changed", "cursor-ahead"];
    readonly menuSectionSlots: readonly ["accounts", "quota", "routing", "limits", "cache", "diagnostics", "extra"];
    readonly menuKnobKinds: readonly ["choice", "toggle", "number", "text"];
    readonly notifyKinds: readonly ["info", "warning", "error"];
    readonly menuIdPattern: "^[\\x21-\\x7e]+$";
    readonly accountsStatusKinds: readonly ["complete", "over-limit"];
    readonly selectorPattern: "^sel-[A-Za-z0-9_-]{32}$";
    readonly limits: {
        /** Generation tokens: 1–64 characters of `[A-Za-z0-9_-]`. */
        readonly generationMaxLength: 64;
        /** Session ids: 1–256 visible ASCII characters (0x21–0x7E). */
        readonly sessionIDMaxLength: 256;
        /** Menu ids (command, section, item, action, knob, choice values). */
        readonly menuIdMaxLength: 256;
        /** Knob values in one menu request. */
        readonly menuValues: 64;
        /** Sections in one menu. */
        readonly menuSections: 16;
        /** Items in one menu section. */
        readonly menuItemsPerSection: 512;
        /** Actions on one section or item. */
        readonly menuActions: 64;
        /** Knobs on one action. */
        readonly menuKnobs: 64;
        /** Choices of one `choice` knob. */
        readonly menuChoices: 256;
        /** Read-only lines of one section. */
        readonly menuLines: 256;
        /** Entries in one `facts` record. */
        readonly menuFacts: 64;
        /** Nesting depth of a `facts` value. */
        readonly menuFactsDepth: 4;
        /** Any user-facing text in an output. */
        readonly textMaxLength: 4096;
        /** Notifications returned by one `state` call. */
        readonly notificationsPerState: 32;
        /** Accounts in one output. */
        readonly accounts: 64;
        /** Quota windows per pool entry. */
        readonly quotaWindows: 4;
        /** Maximum length of a plan tier id. */
        readonly tierIDMaxLength: 128;
        /** OAuth authorization URLs handed to the user. */
        readonly authorizationURLMaxLength: 4096;
    };
    readonly keys: {
        readonly stateInput: readonly ["version", "generation", "scope", "cursor"];
        readonly applyInput: readonly ["version", "generation", "scope", "request"];
        readonly menuRequest: readonly ["command", "sectionId", "actionId", "itemId?", "values?", "confirmed?"];
        readonly stateSnapshot: readonly ["version", "kind", "generation", "scope", "reset", "cursor", "dropped", "more", "notifications", "readSeq", "accountsStatus", "accounts", "route", "status", "settings"];
        readonly notification: readonly ["cursor", "payload"];
        readonly notificationPayload: {
            readonly menu: readonly ["command", "menu"];
            readonly notify: readonly ["command", "notify"];
            readonly notifyBody: readonly ["message", "kind"];
        };
        readonly menu: readonly ["command", "title", "sections"];
        readonly menuSection: readonly ["id", "slot", "title", "lines", "items", "actions", "facts?"];
        readonly menuItem: readonly ["id", "label", "actions", "detail?", "account?", "facts?"];
        readonly menuAccount: readonly ["id", "enabled", "type", "label?", "identity?"];
        readonly menuAction: readonly ["id", "label", "knobs", "description?", "confirm?"];
        readonly menuConfirm: readonly ["message", "irreversible"];
        readonly menuKnob: {
            readonly choice: readonly ["kind", "id", "label", "choices", "value?"];
            readonly toggle: readonly ["kind", "id", "label", "value"];
            readonly number: readonly ["kind", "id", "label", "value?", "min?", "max?", "required?"];
            readonly text: readonly ["kind", "id", "label", "value?", "placeholder?", "masked?", "required?"];
        };
        readonly menuChoice: readonly ["value", "label"];
        readonly applyResult: readonly ["command", "ok", "text", "menu", "code?", "needsConfirmation?"];
        readonly account: readonly ["selector", "id", "label", "enabled", "health", "current", "cooldownUntil?", "quota", "tier?"];
        readonly accountsStatus: {
            readonly complete: readonly ["kind"];
            readonly 'over-limit': readonly ["kind", "count", "limit"];
        };
        readonly settings: {
            readonly root: readonly ["routing", "killswitch", "logLevel", "dump"];
            readonly routing: readonly ["cliFirst", "quotaStyleFallback"];
            readonly killswitch: readonly ["enabled", "minimumRemainingPercent"];
            readonly dump: readonly ["enabled"];
        };
        readonly route: readonly ["accountId", "modelFamily", "headerStyle", "strategy", "updatedAt"];
        readonly status: readonly ["checkedAt", "quotaBackoffUntil", "routingAuthoritative"];
        readonly changedEvent: readonly ["version", "generation"];
    };
};
//# sourceMappingURL=protocol.d.ts.map