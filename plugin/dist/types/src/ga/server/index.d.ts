/**
 * OpenCode 2 (2.0.22) server plugin. It sends the host's Google model
 * requests for this plugin's models to Antigravity accounts through a
 * loopback bridge, and serves the `antigravity-auth` v1 RPC with each
 * location's account state and commands. `createGaAntigravityPlugin` is the
 * plugin the host loads; `createGaPluginFromServices` builds one over a
 * given location-services factory. Host SDK imports are type-only.
 */
import { type authorizeAntigravity, type ensureProjectContext, type exchangeAntigravity, type FetchAvailableModelsOptions, type loadManagedProject, type OAuthAuthDetails, type OpencodeModelDefinition, type refreshAntigravityToken } from '@cortexkit/antigravity-auth-core';
import type { Model, Plugin } from '@opencode/plugin';
import type { ProviderEditor } from '@opencode/plugin/promise/provider';
import type { persistAccountPool } from '../../plugin/persist-account-pool.js';
import { type LocationRuntime, type LocationRuntimeOptions } from '../../plugin/shared/runtime.js';
import type { CommandApplyRequest, CommandApplyResult, RpcNotificationPayload } from '../../rpc/protocol.js';
import { type SidebarAccountRedactionInput, type SidebarRoutingEntry } from '../../sidebar-state.js';
import { type LoopbackProxyEnv } from '../proxy-guard.js';
import { type AntigravityApplyOutput, type AntigravityChangedEvent, type AntigravityRpcIssue, type AntigravityRpcScope, type AntigravitySettingsDto, type AntigravityStateOutput, type AntigravityStatusDto } from '../rpc/protocol.js';
/**
 * The host's request kinds for a model request, declared without the SDK so
 * the override types stay SDK-free. The binding below checks it equals the
 * SDK's `SessionRequestKind`.
 */
export type GaRequestKind = 'primary' | 'compaction' | 'title' | 'generate';
/**
 * Synchronous diagnostic that receives the AbortSignal handed to the
 * production raw sender. Its return type is `undefined`, not `void`, so an
 * async function (`Promise<undefined>`) is not assignable to it.
 */
export type ObserveRawSenderSignal = (signal: AbortSignal) => undefined;
/**
 * The fixed fields of one Antigravity request envelope as it goes on the
 * wire. The shared request pipeline builds it; the sender only serializes it.
 */
export interface GaAgyEnvelope {
    readonly project: string;
    readonly requestId: string;
    readonly request: Readonly<Record<string, unknown>>;
    readonly model: string;
    readonly userAgent: 'antigravity';
    readonly requestType: 'agent';
}
export interface GaSendInput {
    readonly envelope: GaAgyEnvelope;
    readonly auth: OAuthAuthDetails;
    /** One of the Antigravity endpoint origins, without a trailing path. */
    readonly endpoint: string;
    readonly signal: AbortSignal;
    readonly kind: GaRequestKind;
}
/** Waits for the OAuth redirect carrying `expectedState`; resolves the code. */
export type GaWaitForOAuthCode = (expectedState: string, options?: {
    port?: number;
    timeoutMs?: number;
}) => Promise<string>;
/** How the account's provider metadata looked in the read. */
export type HarnessMetadataStatus = 'present' | 'absent' | 'dropped-uncovered' | 'dropped-invalid';
/**
 * The account's access block. `unknown` when the metadata is absent or was
 * dropped, so a block cannot be ruled out; `invalid` when the flags are not
 * booleans or both blocks are set at once.
 */
export type HarnessAccessBlock = {
    readonly kind: 'none';
} | {
    readonly kind: 'verification-required';
    readonly reason: 'validation-required' | 'other' | 'unrecorded';
} | {
    readonly kind: 'ineligible';
    readonly reason: 'account-ineligible' | 'other' | 'unrecorded';
} | {
    readonly kind: 'unknown';
} | {
    readonly kind: 'invalid';
};
/**
 * One account as an out-of-process test harness observes it. It carries no
 * email, label, token, project id, identity, row id or credential epoch.
 */
export interface HarnessAccountObservation {
    readonly selector: string;
    readonly position: number;
    readonly enabled: boolean;
    readonly usable: boolean;
    readonly metadataStatus: HarnessMetadataStatus;
    readonly accessBlock: HarnessAccessBlock;
    /** Routing slots whose stored account reference is exactly this row's. */
    readonly currentFor: readonly ('active' | 'claude' | 'gemini')[];
    readonly cooldownUntil: number | null;
}
/**
 * Diagnostic view of one `state` read, built from the same repository read
 * as the answer with the same `readSeq`.
 */
export interface HarnessAccountsObservation {
    readonly generation: string;
    readonly readSeq: number;
    readonly status: 'ready' | 'pending-migration' | 'management-pending' | 'error';
    readonly accountsStatus: 'complete' | 'over-limit';
    readonly accounts: readonly HarnessAccountObservation[];
    /** Selectors that stopped working at this read. */
    readonly retiredSelectors: readonly string[];
}
/**
 * Synchronous diagnostic receiving each `state` read's observation. Like
 * `ObserveRawSenderSignal`, it returns `undefined` so an async function is
 * not assignable; a throw is ignored.
 */
export type ObserveAccountSnapshot = (observation: HarnessAccountsObservation) => undefined;
/** Dependency overrides for tests; production passes none. */
export interface GaPluginOverrides {
    /**
     * Replaces the production raw sender. When given, the production sender is
     * never called, so `observeRawSenderSignal` is never invoked.
     */
    send?: (input: GaSendInput) => Promise<Response>;
    /**
     * Observes the exact AbortSignal on the transport-options object that the
     * production raw sender receives. Called synchronously, never awaited; a
     * throw is ignored and cannot change the dispatch. Only the default sender
     * branch calls it.
     */
    observeRawSenderSignal?: ObserveRawSenderSignal;
    /**
     * Receives a redacted observation of each `state` read, for test
     * harnesses that drive a real host. Absent in normal operation; the
     * location's services call it synchronously from the same read.
     */
    observeAccountSnapshot?: ObserveAccountSnapshot;
    persistAccountPool?: typeof persistAccountPool;
    refreshAccessToken?: typeof refreshAntigravityToken;
    ensureProjectContext?: typeof ensureProjectContext;
    loadManagedProject?: typeof loadManagedProject;
    oauth?: {
        authorize?: typeof authorizeAntigravity;
        exchange?: typeof exchangeAntigravity;
        waitForCode?: GaWaitForOAuthCode;
    };
    /** Transport for quota and model-list fetches. */
    quotaFetch?: NonNullable<FetchAvailableModelsOptions['fetchVia']>;
}
/**
 * How long a response body may stall with no bytes before the raw sender
 * destroys the socket: five minutes, unchanged from the retired OpenCode 2
 * beta adapter this plugin replaces.
 */
export declare const GA_RAW_IDLE_TIMEOUT_MS = 300000;
/** The Antigravity streaming endpoint path appended to an endpoint origin. */
export declare const GA_STREAM_PATH = "/v1internal:streamGenerateContent?alt=sse";
export type GaRawSender = (input: GaSendInput) => Promise<Response>;
/**
 * Choose the dispatch for one activation. With a `send` override, requests
 * go to it and the observer is never called. Otherwise each request builds
 * one transport-options object, hands its `signal` property to the observer
 * synchronously, and passes that same object to the unchanged production
 * sender. The observer cannot change the dispatch: its result is ignored
 * and a synchronous throw is swallowed.
 */
export declare function createGaRawSender(overrides?: Pick<GaPluginOverrides, 'send' | 'observeRawSenderSignal'>): GaRawSender;
/**
 * Native Google content requests the request hook may rewrite: POST to
 * `…/models/<id>:generateContent` or `…:streamGenerateContent`.
 */
export declare const GA_GOOGLE_CONTENT_PATH: RegExp;
/** A registered job the host never dispatched is dropped after this long. */
export declare const GA_UNCLAIMED_JOB_TTL_MS = 60000;
export declare function isGaGoogleContentRequest(request: Request): boolean;
/** What the request hook recorded about one Google request it rewrote. */
export interface GaBridgeJob {
    readonly sessionID: string;
    /** Set only when the host supplied a parent session. */
    readonly parentSessionID: string | null;
    readonly kind: GaRequestKind;
    readonly modelID: string;
    /**
     * The selected variant of a registered model, from the host's model
     * reference; `null` for the default variant and for title requests on
     * models this plugin did not register.
     */
    readonly variant: string | null;
    /** The host's original request URL. */
    readonly url: string;
    /** The host's original JSON body, unmodified. */
    readonly body: string;
}
export interface GaJobContext {
    /**
     * Aborts when the host abandons the loopback request or the activation is
     * disposed. The executor passes it to `send`.
     */
    readonly signal: AbortSignal;
    readonly send: GaRawSender;
}
/**
 * Runs one job: request transformation, account selection, retries and the
 * response adaptation to native Gemini SSE or JSON. The shared request
 * pipeline provides it. A thrown error before a Response exists becomes an
 * HTTP 502 answer; a Response is streamed back unchanged.
 */
export type GaJobExecutor = (job: GaBridgeJob, context: GaJobContext) => Promise<Response>;
export interface GaLoopbackBridge {
    readonly port: number;
    /** `http://127.0.0.1:<port>` */
    readonly origin: string;
    /**
     * Register a job and build its replacement request. The proxy guard runs
     * first, against the actual bridge URL; a refusal throws
     * `LoopbackProxyGuardError` and registers nothing. The replacement copies
     * no original header, has only `content-type: application/json`, body
     * `{}`, and the original request's AbortSignal.
     */
    rewrite(original: Request, job: GaBridgeJob, env: LoopbackProxyEnv): Request;
    /**
     * For the host's `http.response` hook. When `request` is one of this
     * bridge's job requests, return a response whose body reads the original
     * bytes and then, if the upstream body failed after headers, fails with
     * the error the bridge captured for that job (the genuine upstream cause)
     * instead of ending. Any other request returns `null` and its response is
     * left alone.
     */
    adaptResponse(request: Request, response: Response): Response | null;
    /** Jobs registered or running (diagnostics and tests). */
    pendingJobs(): number;
    /**
     * Stop accepting connections, abort every running job, close every
     * socket and wait for the server to close. Idempotent.
     */
    dispose(): Promise<void>;
}
export interface GaLoopbackBridgeOptions {
    execute: GaJobExecutor;
    send: GaRawSender;
    /** Receives bridge failures; never request bodies or credentials. */
    onError?: (message: string) => void;
}
/** The HTTP 502 answer for a terminal failure before upstream headers. */
export declare function gaPreHeaderFailureResponse(error: unknown): Response;
export declare function startGaLoopbackBridge(options: GaLoopbackBridgeOptions): Promise<GaLoopbackBridge>;
/** Accept only job IDs produced by request rewrite. */
export declare function isGaJobId(value: string): boolean;
/** Context capabilities setup requires, by property path. */
export declare const GA_REQUIRED_CONTEXT_CAPABILITIES: readonly ["location.directory", "session.hook", "rpc.register", "provider.transform", "command.transform"];
export declare class GaSetupContextError extends Error {
    readonly missing: readonly string[];
    readonly name = "GaSetupContextError";
    constructor(missing: readonly string[]);
}
/**
 * Validate host setup capabilities before allocating resources. Only
 * `session` and `location` are read before deciding:
 * - neither present: `'legacy'`, an OpenCode 1 core loader; setup returns
 *   `undefined` with no side effect;
 * - exactly one present, or both with a required capability missing: throws
 *   `GaSetupContextError` naming what is missing;
 * - otherwise `'ga'`.
 */
export declare function classifyGaSetupContext(context: object): 'legacy' | 'ga';
/**
 * A new opaque generation token. Each activation gets its own, so a client
 * still holding an older activation's token is detected and reset.
 */
export declare function createGaGeneration(): string;
/**
 * Read side of one location's state, supplied by the location's services.
 * Rows are the sidebar projection's input; the activation redacts them with
 * `redactAccountForSidebar`, so raw account records never reach a client.
 */
export interface GaStateSource {
    /**
     * One snapshot for one `state` call, from a single repository read. The
     * source serializes its reads per activation, so `readSeq` increases in
     * the order the answers are built. `signal` aborts when the activation is
     * disposed or the client gives up; an aborted read must not change the
     * source's selector registry.
     */
    read(input: {
        readonly scope: AntigravityRpcScope;
        readonly signal: AbortSignal;
    }): Promise<GaStateRead>;
}
/** The accounts of one read: the whole roster, or only its size. */
export type GaAccountsRead = {
    readonly kind: 'complete';
    /** At most `ANTIGRAVITY_RPC_LIMITS.accounts` rows, in roster order. */
    readonly rows: readonly {
        readonly selector: string;
        readonly row: SidebarAccountRedactionInput;
    }[];
}
/** The roster is larger than the limit; no selectors were issued. */
 | {
    readonly kind: 'over-limit';
    readonly count: number;
};
export interface GaStateRead {
    /** Strictly increasing per activation; sent to the client unchanged. */
    readonly readSeq: number;
    readonly accounts: GaAccountsRead;
    /** The requesting session's route; `null` for the sessionless scope. */
    readonly route: SidebarRoutingEntry | null;
    readonly status: AntigravityStatusDto;
    /** Read from the same location's runtime after the repository read. */
    readonly settings: AntigravitySettingsDto;
}
/**
 * One Antigravity menu action for this location's command service.
 * `request` has passed the `parseApplyRequest` of the same
 * `@cortexkit/common-auth/commands` module the location's menu was built
 * with; for a session scope its `sessionId` was set from the GA apply
 * input's scope.
 */
export interface GaApplyRequest {
    readonly request: CommandApplyRequest;
    readonly scope: AntigravityRpcScope;
    /**
     * Aborts when the activation is disposed. The service must not start new
     * effects once it aborts.
     */
    readonly signal: AbortSignal;
}
/**
 * The per-location command service: it runs one action through this
 * location's Antigravity menu and returns the menu's answer. The activation
 * that owns this location's generation validates the answer before it
 * reaches a client.
 */
export interface GaCommandService {
    apply(request: GaApplyRequest): Promise<CommandApplyResult>;
}
/**
 * Opens the Antigravity menu for the native `/antigravity` command: the
 * location's menu is built for `scope` and queued there as a notification,
 * which the client pulls with its next `state` request.
 */
export interface GaMenuOpener {
    open(input: {
        readonly scope: AntigravityRpcScope;
        /** Aborts when the activation is disposed. */
        readonly signal: AbortSignal;
    }): Promise<void>;
}
export interface GaRpcActivationOptions {
    state: GaStateSource;
    commands: GaCommandService;
    /**
     * `parseApplyRequest` of the `@cortexkit/common-auth/commands` module
     * the location's Antigravity menu was built with. Every GA apply request
     * passes it after the wire schema, so the menu receives only what that
     * module itself accepts.
     */
    parseApplyRequest: (value: unknown) => CommandApplyRequest | undefined;
    /** Defaults to `createGaGeneration()`. */
    generation?: string;
    /** Called after a notification is queued, e.g. to emit `changed`. */
    onChanged?: (event: AntigravityChangedEvent) => void;
    now?: () => number;
    /** Notifications retained per scope before the oldest are evicted. */
    notificationsPerScope?: number;
    /** Scopes retained before the least recently used is forgotten. */
    maxScopes?: number;
}
/** Raised for input that fails the portable schema; carries no input value. */
export declare class GaRpcInputError extends Error {
    readonly issues: readonly AntigravityRpcIssue[];
    readonly name = "GaRpcInputError";
    constructor(issues: readonly AntigravityRpcIssue[]);
}
/** Raised when a collaborator produced a value that fails the contract. */
export declare class GaRpcContractError extends Error {
    readonly name = "GaRpcContractError";
}
/** Account state and RPC handlers belong to this location activation. */
export interface GaRpcActivation {
    readonly generation: string;
    /**
     * The two RPC handlers, taking raw (unvalidated) input and the host call's
     * abort signal.
     */
    readonly handlers: {
        state(input: unknown, signal?: AbortSignal): Promise<AntigravityStateOutput>;
        apply(input: unknown, signal?: AbortSignal): Promise<AntigravityApplyOutput>;
    };
    /**
     * Queue a notification (the Antigravity menu payload, or a toast) in one
     * scope and return its cursor. A payload that fails the wire contract is
     * refused with `GaRpcContractError`. After disposal it does nothing and
     * returns `null`.
     */
    notify(scope: AntigravityRpcScope, payload: RpcNotificationPayload): number | null;
    /** Whether a client pulled this scope's state within the last 3 s. */
    isConnected(scope: AntigravityRpcScope): boolean;
    readonly disposed: boolean;
    /**
     * Stop serving: later calls answer `disposed`, running state reads and
     * applies are aborted and awaited, and queued notifications are
     * discarded. Idempotent.
     */
    dispose(): Promise<void>;
}
export declare function createGaRpcActivation(options: GaRpcActivationOptions): GaRpcActivation;
/** The plugin id this adapter registers with the host. */
export declare const GA_PLUGIN_ID = "cortexkit.antigravity-auth";
/** The host provider whose requests the hooks handle. */
export declare const GA_PROVIDER_ID = "google";
/**
 * What the location runtime needs from the account service: the quota
 * snapshot store (in memory for an OpenCode 2 location) and the functions
 * that use credentials to fetch quota, look up the plan tier and refresh
 * tokens.
 */
export type GaRuntimeCollaborators = Omit<LocationRuntimeOptions, 'directory' | 'logSink'>;
/** What a location's services serve once the runtime is built. */
export interface GaServingServices {
    /** Runs one bridged request: transformation, account rotation, retries. */
    readonly execute: GaJobExecutor;
    /** Accounts, routes and status for the RPC `state` method. */
    readonly state: GaStateSource;
    /**
     * Applies Antigravity menu actions for the RPC `apply` method and opens
     * the menu for the native `/antigravity` command.
     */
    readonly commands: GaCommandService & GaMenuOpener;
}
/**
 * One activation's request, account and command services. The shared
 * request pipeline, account integration and command modules implement it;
 * `setupGaActivation` decides when they start and stop.
 */
export interface GaLocationServices {
    readonly runtime: GaRuntimeCollaborators;
    /**
     * Start serving on the built runtime. `notify` and `isConnected` belong to
     * this activation's RPC store, for opening the Antigravity menu and toasts.
     */
    start(input: {
        readonly runtime: LocationRuntime;
        /** This activation's generation, for diagnostics the services emit. */
        readonly generation: string;
        readonly send: GaRawSender;
        readonly notify: GaRpcActivation['notify'];
        readonly isConnected: GaRpcActivation['isConnected'];
    }): Promise<GaServingServices>;
    /** Release the services' own resources. Called after hooks and RPC stop. */
    dispose(): Promise<void>;
}
/** Builds one activation's services for a host-owned location directory. */
export type GaLocationServicesFactory = (input: {
    readonly directory: string;
    readonly overrides: GaPluginOverrides;
    readonly connections?: Pick<Plugin.Context['integration']['connection'], 'active' | 'resolve'>;
}) => Promise<GaLocationServices>;
/**
 * The fields the request hook reads and writes. The host's
 * `SessionHttpRequest` is passed in directly; `request` is the one field the
 * hook may replace.
 */
export interface GaHttpRequestEvent {
    readonly sessionID: string;
    readonly kind: GaRequestKind;
    readonly model: {
        readonly id: string;
        readonly providerID: string;
        readonly variant?: string | undefined;
    };
    request: Request;
}
/** The fields the response hook reads and writes (`SessionHttpResponse`). */
export interface GaHttpResponseEvent {
    readonly request: Request;
    response: Response;
}
/** The fields the retry hook reads and writes. */
export interface GaRetryEvent {
    readonly model: {
        readonly id: string;
        readonly providerID: string;
    };
    decision: {
        retry: false;
    } | {
        retry: true;
        delay: number;
    };
}
/**
 * Whether the plugin owns a Google request: every title request (the host
 * may pick an off-catalog title model) and any request for a model this
 * plugin registered. Everything else passes through untouched.
 */
export declare function isGaOwnedRequest(event: Pick<GaHttpRequestEvent, 'kind' | 'model'>, isRegisteredModel: (modelID: string) => boolean): boolean;
/**
 * Request hook body: record an owned Google content request as a bridge job
 * and replace it with the bridge request. The original body is read from a
 * clone, so the host's request is never consumed when the rewrite is
 * refused. A proxy-guard refusal throws before any replacement; the host
 * then records it as the request's error and dispatches nothing.
 */
export declare function rewriteGaHttpRequest(event: GaHttpRequestEvent, input: {
    readonly bridge: Pick<GaLoopbackBridge, 'rewrite'>;
    readonly isRegisteredModel: (modelID: string) => boolean;
    readonly env: LoopbackProxyEnv;
}): Promise<void>;
/** Adapt only responses whose request belongs to a recognized bridge job. */
export declare function adaptGaHttpResponse(event: GaHttpResponseEvent, bridge: Pick<GaLoopbackBridge, 'adaptResponse'>): void;
/**
 * Retry hook body. The bridge's job runner rotates accounts and retries
 * endpoints itself; a host retry on top would repeat that whole sequence.
 * Only this plugin's registered models are affected.
 */
export declare function decideGaRetry(event: GaRetryEvent, isRegisteredModel: (modelID: string) => boolean): void;
/**
 * The parts of the host context setup uses, taken from the published
 * `Plugin.Context` type. Tests pass an object of this type; the host passes
 * its full context.
 */
export interface GaHostContext {
    readonly location: Pick<Plugin.Context['location'], 'directory'>;
    readonly session: Pick<Plugin.Context['session'], 'hook'>;
    readonly rpc: Pick<Plugin.Context['rpc'], 'register'>;
    readonly provider: Pick<Plugin.Context['provider'], 'transform' | 'reload'>;
    readonly command: Pick<Plugin.Context['command'], 'transform' | 'reload'>;
    readonly integration?: Pick<Plugin.Context['integration'], 'connection'> & Partial<Pick<Plugin.Context['integration'], 'transform'>>;
}
/**
 * Convert one shared public catalog entry to the host's model record for the
 * Google provider. Only enabled variants are offered; a variant carries only
 * its id, which reaches the request hook as the model reference's `variant`
 * and is resolved by the request pipeline, the same way the OpenCode 1
 * adapter resolves variant suffixes. Title wire aliases are not catalog
 * entries and are never registered.
 *
 * The host's branded id types are plain strings at runtime. This module
 * loads no host schema code, so the brands are applied by type assertion on
 * values taken from the shared catalog.
 */
export declare function toGaModelInfo(id: string, definition: OpencodeModelDefinition): Model.Info;
/** The host records for every public catalog model, keyed by model id. */
export declare function gaCatalogModels(): ReadonlyMap<string, Model.Info>;
/**
 * Provider transform body: add the catalog models to the Google provider,
 * keeping every model the provider already has under another id. When the
 * host has no Google provider record, nothing is registered.
 */
export declare function registerGaModels(editor: {
    get(providerID: string): {
        readonly models: ReadonlyMap<string, Model.Info>;
    } | undefined;
    readonly models: Pick<ProviderEditor['models'], 'set'>;
}, catalog: ReadonlyMap<string, Model.Info>): void;
/**
 * Set up one activation. Returns `undefined` with no side effect for a
 * legacy context without `session` and `location`, and throws
 * `GaSetupContextError` for a partial one. Otherwise it builds the services,
 * the location runtime, the RPC activation and the loopback bridge for the
 * host-owned location directory; registers the `antigravity-auth` RPC, the
 * public catalog models on the Google provider, the `http.request` rewrite,
 * the `http.response` post-header error adapter and the registered-model
 * retry policy (all scoped to the Google provider);
 * and returns a Cleanup that removes only this activation's hooks and RPC
 * and stops everything else: producers are stopped and awaited, queued
 * quota snapshot writes drain, and then the remaining handles close.
 *
 * Any failure before the Cleanup is returned releases everything acquired
 * so far before the error propagates, so a failed setup leaves no hook,
 * port, timer or file handle behind.
 */
export declare function setupGaActivation(context: GaHostContext, factory: GaLocationServicesFactory, overrides?: GaPluginOverrides): Promise<Plugin.Cleanup | undefined>;
/** Build the OpenCode 2 plugin over the given services factory. */
export declare function createGaPluginFromServices(factory: GaLocationServicesFactory, overrides?: GaPluginOverrides): Plugin.Plugin;
/**
 * The plugin the OpenCode 2 host loads: setup over the production location
 * services (`createGaLocationServices`), which open the location's account
 * store, keep its quota snapshots in memory and run the shared request
 * pipeline. `overrides` exist for tests; the host passes none.
 */
export declare function createGaAntigravityPlugin(overrides?: GaPluginOverrides): Plugin.Plugin;
//# sourceMappingURL=index.d.ts.map