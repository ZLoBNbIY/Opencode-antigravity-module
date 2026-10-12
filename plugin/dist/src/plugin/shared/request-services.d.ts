/**
 * Shared Antigravity request engine: account selection, retries, endpoint
 * and quota fallback, warmups and response handling for one plugin location.
 *
 * OpenCode 1's `createFetchInterceptor` and the GA location services both
 * call `createRequestExecutor`, so there is exactly one retry loop. Every
 * collaborator with state (accounts, credentials, session metadata, operator
 * settings, wire state, debug log, dump switch, logger, health and token
 * trackers) arrives through `RequestServicesDeps`; this module never reads a
 * module-level OpenCode 1 binding or a host SDK client. Host-only effects
 * (toasts, the sidebar routing file, clearing host-stored OAuth credentials)
 * are optional or explicit callbacks the host binding supplies.
 *
 * The wire rules themselves (payload transformation, header and envelope
 * order, SSE handling) stay in `../request`. The engine receives them as
 * `RequestWire`, which `createRequestWire` binds to one location's signature
 * cache, debug log and logger; the raw sender is called unchanged.
 */
import { type AgyTransportOptions, type AccountManager as CoreAccountManager, type Fingerprint, type HealthScoreTracker, type ManagedAccount, type OAuthAuthDetails, type ProjectContextResult, type QuotaGroup, type QuotaGroupSummary, type QuotaManager, type TokenBucketTracker } from '@cortexkit/antigravity-auth-core';
import { type HeaderStyle } from '../../constants';
import type { AntigravityConfig } from '../config';
import type { LocationDebug } from '../debug';
import { type GeminiDumpState } from '../gemini-dump';
import type { Logger } from '../logger';
import type { OperatorSettingsController } from '../operator-settings';
import type { buildThinkingWarmupBody, getImageModelLocalTitle, getLastCacheStats, PrepareRequestOptions, prepareAntigravityRequest, transformAntigravityResponse } from '../request';
import { type AgySessionRegistry, type OpenCodeSessionIdentity } from '../session-context';
import { type CapturedLocalGrant } from './local-grant';
/** Raw Antigravity sender: the core CLI transport or a test double. */
export type RequestTransport = (url: string, init?: RequestInit, options?: AgyTransportOptions) => Promise<Response>;
/**
 * Standard fetch, used for `gemini-cli` header-style sends and their warmups;
 * `antigravity` header-style sends use the raw HTTP/1.1 AGY sender instead.
 */
export type RequestFetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
/**
 * The fields of a pool row the engine reads: selection, logging, killswitch
 * and backoff metadata only. A row carries no credential. OpenCode 1's rows
 * are core `ManagedAccount`s; a vault location supplies metadata-only rows.
 */
export interface RequestAccountRow {
    readonly index: number;
    readonly email?: string;
    readonly fingerprint?: Fingerprint;
    /** Reset to 0 by the engine after a successful send. */
    consecutiveFailures?: number;
    readonly rateLimitResetTimes: {
        readonly claude?: number;
        readonly gemini?: number;
    };
    readonly cachedQuota?: Partial<Record<QuotaGroup, QuotaGroupSummary>>;
    readonly cachedQuotaUpdatedAt?: number;
}
type CoreArgs<K extends keyof CoreAccountManager> = CoreAccountManager[K] extends (...args: infer P) => unknown ? P : never;
type CoreArgsAfterAccount<K extends keyof CoreAccountManager> = CoreArgs<K> extends [unknown, ...infer Rest] ? Rest : never;
type CoreResult<K extends keyof CoreAccountManager> = CoreAccountManager[K] extends (...args: never[]) => infer R ? R : never;
/**
 * Selection, rate-limit, toast and usage bookkeeping over one location's
 * rows. It has no credential operation. The arguments and results are the
 * core `AccountManager`'s, with its row type replaced by `A`, so a core
 * manager is a `RequestAccountPool<ManagedAccount>` as is.
 *
 * Account selection stays Antigravity's own policy. It is not delegated to
 * the `@cortexkit/common-auth` `./routing` entry, whose published semantics
 * differ in four ways that would change which account serves a request:
 *
 * 1. Cold start: `admit()` refuses an OAuth row with no quota reading, a
 *    missing window or an unknown reset (`dist/routing/admission.d.ts`,
 *    refusals `needs-first-reading`, `unknown-window`, `unknown-reset`).
 *    Antigravity selection and its killswitch pass such a row.
 * 2. Rate limits: admission keeps one mark per row (`rateLimitMarks` in
 *    `ExclusionInputs`, same file). Antigravity keeps marks per quota key
 *    (family, model and header style) and switches between the two Gemini
 *    quota pools.
 * 3. Strategies: the library routes only `ordered` or `sticky-balanced`
 *    (`RoutingMode`, `dist/routing/ordered.d.ts`), and both routes run
 *    admission (`OrderedRouteInput` and `StickyRouteInput` extend
 *    `AdmissionInput`). Antigravity uses sticky, round-robin and hybrid
 *    (health and token-bucket) selection with PID offset and per-session and
 *    parent-session pinning.
 * 4. Soft quota: Antigravity excludes accounts over
 *    `soft_quota_threshold_percent`, never the only usable account, and
 *    waits for the soonest reset. The library has no admission equivalent;
 *    `reservePercent` only weights sticky selection
 *    (`dist/routing/sticky.d.ts`).
 *
 * The killswitch verdict is a per-row boolean on both sides, but every
 * library route that accepts it also runs the admission gates above.
 */
export interface RequestAccountPool<A extends RequestAccountRow> {
    areAllAccountsOverSoftQuota(...args: CoreArgs<'areAllAccountsOverSoftQuota'>): boolean;
    getAccountCount(): number;
    getAccounts(): A[];
    getAccountsSnapshot(): A[];
    getEnabledAccounts(): A[];
    getAvailableHeaderStyle(account: A, ...rest: CoreArgsAfterAccount<'getAvailableHeaderStyle'>): CoreResult<'getAvailableHeaderStyle'>;
    getCurrentOrNextForFamily(...args: CoreArgs<'getCurrentOrNextForFamily'>): A | null;
    getDailyRequestCounts(...args: CoreArgs<'getDailyRequestCounts'>): CoreResult<'getDailyRequestCounts'>;
    getMinWaitTimeForFamily(...args: CoreArgs<'getMinWaitTimeForFamily'>): number;
    getMinWaitTimeForSoftQuota(...args: CoreArgs<'getMinWaitTimeForSoftQuota'>): number | null;
    getSessionSummary(): CoreResult<'getSessionSummary'>;
    getTotalDailyRequests(...args: CoreArgs<'getTotalDailyRequests'>): number;
    hasOtherAccountWithAntigravityAvailable(...args: CoreArgs<'hasOtherAccountWithAntigravityAvailable'>): boolean;
    isRateLimitedForHeaderStyle(account: A, ...rest: CoreArgsAfterAccount<'isRateLimitedForHeaderStyle'>): boolean;
    markAccountCoolingDown(account: A, ...rest: CoreArgsAfterAccount<'markAccountCoolingDown'>): void;
    markAccountIneligible(...args: CoreArgs<'markAccountIneligible'>): boolean;
    markAccountUsed(...args: CoreArgs<'markAccountUsed'>): void;
    markAccountVerificationRequired(...args: CoreArgs<'markAccountVerificationRequired'>): boolean;
    markRateLimited(account: A, ...rest: CoreArgsAfterAccount<'markRateLimited'>): void;
    markRateLimitedWithReason(account: A, ...rest: CoreArgsAfterAccount<'markRateLimitedWithReason'>): number;
    markToastShown(...args: CoreArgs<'markToastShown'>): void;
    proactivelyRotateForFamily(...args: CoreArgs<'proactivelyRotateForFamily'>): A | null;
    recordRequest(...args: CoreArgs<'recordRequest'>): void;
    recordSessionUsage(...args: CoreArgs<'recordSessionUsage'>): void;
    regenerateAccountFingerprint(...args: CoreArgs<'regenerateAccountFingerprint'>): CoreResult<'regenerateAccountFingerprint'>;
    requestSaveToDisk(): void;
    shouldProactivelyRotate(...args: CoreArgs<'shouldProactivelyRotate'>): boolean;
    shouldShowAccountToast(...args: CoreArgs<'shouldShowAccountToast'>): boolean;
    wasUsedInSession(...args: CoreArgs<'wasUsedInSession'>): boolean;
}
/**
 * Credentials kept on the location's own pool rows (OpenCode 1, or a GA
 * location on its local account repository): the selected row's stored
 * token is refreshed when expired, its project is resolved, and the result
 * is written back to the pool. One token and project serve every send of
 * that selection.
 */
export interface LocalRequestCredentials<A extends RequestAccountRow> {
    readonly domain: 'local';
    /** The stored OAuth record of a row. */
    toAuthDetails(account: A): OAuthAuthDetails;
    /** Write a refreshed or project-resolved record back to its row. */
    updateFromAuth(account: A, auth: OAuthAuthDetails): void;
    /** Drop a row whose refresh token was revoked; true when it was removed. */
    removeAccount(account: A): boolean;
    saveToDisk(): Promise<void>;
    saveToDiskReplace(): Promise<void>;
    /**
     * Refresh the selected row's expired access token. The row itself is
     * passed; an implementation refreshes exactly that row (a repository
     * adapter captures the row's ref before its first await) and never looks a
     * row up by refresh token. It returns the refreshed record as stored for
     * that row, so later grant checks see the successor credential; undefined
     * means the refresh failed.
     */
    refresh(account: A): Promise<OAuthAuthDetails | undefined>;
    /** Resolve the project the request is sent under. */
    ensureProject(auth: OAuthAuthDetails): Promise<ProjectContextResult>;
    /** True when a refresh error means the refresh token was revoked. */
    isInvalidGrant(error: unknown): boolean;
    /** Clear host-stored OAuth credentials once the last account is removed. */
    clearStoredAuth(): Promise<void>;
    /**
     * Capture the bearer and original row reference before any save, project
     * lookup or other await. For store accounts the ref includes row ID, the
     * credential replacement epoch, and authenticated identity; a refresh does
     * not advance that epoch. Later account changes cannot replace this ref.
     *
     * check() runs immediately before main sends, thinking warmups and cache
     * probes. It rejects unavailable metadata or a removed, disabled, replaced
     * or token-superseded credential. A store resolver can separately adopt the
     * current token at the original ref. This request executor may then capture
     * a new grant and rebuild once per request, without modifying the captured
     * check or penalizing the account for an ordinary token change.
     */
    captureGrant(grant: {
        readonly account: A;
        readonly accessToken: string;
    }): CapturedLocalGrant;
    /**
     * Started without awaiting after a successful send, with the selected row
     * and `quota_refresh_interval_minutes`. `createLocalQuotaRefresh` builds
     * it for a core account manager. Absent: no refresh from the request path.
     */
    refreshQuotaAfterSuccess?(account: A, intervalMinutes: number): Promise<void>;
}
/**
 * Credentials held by a vault: the engine never sees a stored token. Every
 * physical send (each endpoint attempt, retry and fallback) asks for a fresh
 * admission and uses that admission's token and project for that one send
 * only; nothing is refreshed, cached or written to a pool row.
 */
export interface VaultRequestCredentials<A extends RequestAccountRow> {
    readonly domain: 'vault';
    admit(request: {
        /** The metadata row selected for this send. */
        readonly account: A;
        readonly signal: AbortSignal | undefined;
    }): Promise<RequestSendAdmission>;
}
/** One vault admission, valid for exactly one physical send. */
export interface RequestSendAdmission {
    /** The vault credential this admission serves. */
    readonly credentialId: string;
    /** The account the vault asserted for this admission. */
    readonly accountIdentity: string;
    /** The record version served; a 401 is reported against it. */
    readonly recordVersion: number;
    readonly accessToken: string;
    /** The Antigravity project served with this same admission. */
    readonly projectId: string;
    /**
     * Reports a 401 served to this send against the exact record version
     * this admission carried. Called without awaiting the result; a rejection
     * is logged and ignored.
     */
    report401(status: number): Promise<unknown>;
}
/** Which store holds the selected row's credentials. */
export type RequestCredentials<A extends RequestAccountRow> = LocalRequestCredentials<A> | VaultRequestCredentials<A>;
/** Wire preparation and response handling, unchanged from `../request`. */
export interface RequestWire {
    prepare: typeof prepareAntigravityRequest;
    transformResponse: typeof transformAntigravityResponse;
    buildThinkingWarmupBody: typeof buildThinkingWarmupBody;
    getImageModelLocalTitle: typeof getImageModelLocalTitle;
    getLastCacheStats: typeof getLastCacheStats;
}
/** A prepared upstream request, as `RequestWire.prepare` returns it. */
export type PreparedAgyRequest = ReturnType<RequestWire['prepare']>;
/** What a Google 403 body says about the account that received it. */
export interface AccountAccessErrorDetails {
    validationRequired: boolean;
    accountIneligible: boolean;
    message?: string;
    verifyUrl?: string;
}
/** The account and header style a session's request was finally sent with. */
export interface RequestRoutingEntry {
    accountId: string;
    modelFamily: 'claude' | 'gemini';
    headerStyle: 'antigravity' | 'gemini-cli';
    strategy?: 'sticky' | 'round-robin' | 'hybrid';
    updatedAt: number;
}
export type RequestNoticeVariant = 'info' | 'warning' | 'success' | 'error';
/** One upstream send's wire inputs, taken from a single credential grant. */
export interface AgyWireRequestInput {
    /** The host's Generative Language URL (or Request). */
    readonly input: RequestInfo;
    readonly init?: RequestInit;
    readonly accessToken: string;
    readonly projectId: string;
    /** Antigravity endpoint for this attempt. */
    readonly endpoint?: string;
    readonly headerStyle?: HeaderStyle;
    /** Close the tool loop and retry after a corrupted-thinking rejection. */
    readonly forceThinkingRecovery?: boolean;
    readonly options?: PrepareRequestOptions;
}
/**
 * Prepares one upstream Antigravity request: payload transforms, AGY
 * metadata and envelope, header order and the endpoint URL. It is the single
 * entry point the engine uses for every send, and the rules are exactly
 * `RequestWire.prepare`'s.
 */
export declare function prepareAgyWireRequest(wire: Pick<RequestWire, 'prepare'>, request: AgyWireRequestInput): PreparedAgyRequest;
/** This location's debug-log methods the engine calls. */
export type RequestDebug = Pick<LocationDebug, 'isDebugEnabled' | 'logAccountContext' | 'logAntigravityDebugResponse' | 'logModelFamily' | 'logRateLimitEvent' | 'logRateLimitSnapshot' | 'logResponseBody' | 'startAntigravityDebugRequest'>;
/**
 * One location's collaborators for the shared request engine. `A` is the
 * location's pool row type; `credentials.domain` selects how a selected row
 * becomes a token and project.
 */
export interface RequestServicesDeps<A extends RequestAccountRow> {
    /** Check the persistent account source before each operation that uses credentials. */
    readonly assertAdmission?: () => Promise<void>;
    readonly config: AntigravityConfig;
    readonly accounts: RequestAccountPool<A>;
    readonly credentials: RequestCredentials<A>;
    /** This location's AGY conversation/trajectory session metadata. */
    readonly sessions: AgySessionRegistry;
    /**
     * Live operator settings: routing overrides and the killswitch, which
     * excludes accounts whose remaining quota is below a threshold.
     */
    readonly operatorSettings?: Pick<OperatorSettingsController, 'get'>;
    /**
     * Raw HTTP/1.1 AGY sender for `antigravity` header-style sends. The engine
     * transforms the request first, then passes the prepared URL, init and
     * the caller's AbortSignal to it.
     */
    readonly transport: RequestTransport;
    /** Standard fetch for `gemini-cli` header-style sends and their warmups. */
    readonly fetchImpl: RequestFetch;
    readonly wire: RequestWire;
    readonly debug: RequestDebug;
    readonly dump: Pick<GeminiDumpState, 'dumpRequest'>;
    readonly logger: Logger;
    readonly trackers: {
        readonly health: Pick<HealthScoreTracker, 'recordFailure' | 'recordRateLimit' | 'recordSuccess'>;
        readonly token: Pick<TokenBucketTracker, 'consume' | 'refund'>;
    };
    /**
     * Recognises Google's ACCOUNT_INELIGIBLE and VALIDATION_REQUIRED 403
     * bodies. It does not classify quota errors.
     */
    classifyAccessError(bodyText: string): AccountAccessErrorDetails;
    /** Host notice (OpenCode 1 toast). Rejections and throws are ignored. */
    notify?(message: string, variant: RequestNoticeVariant): unknown;
    /**
     * Records the route a session's request was dispatched on. Called without
     * awaiting; the dispatch path never waits on it and a throw is ignored.
     */
    onRouting?(sessionId: string, entry: RequestRoutingEntry): void;
}
/** Per-request inputs the host supplies alongside the HTTP request. */
export interface RequestExecuteOptions {
    /**
     * The host session this request belongs to. When omitted, the OpenCode
     * session headers on the request are read.
     */
    readonly session?: OpenCodeSessionIdentity;
    /**
     * The host's request kind. `title` routes the request as a session title
     * (see `routeTitleModel`); every kind other than `primary` keeps its own
     * AGY session metadata. Omitted by OpenCode 1, which has no kind.
     */
    readonly kind?: RequestKind;
    /**
     * Raw sender for this request's `antigravity` header-style sends, in place
     * of `RequestServicesDeps.transport`. It receives the transformed request's
     * URL and init, and the caller's AbortSignal object itself.
     */
    readonly transport?: RequestTransport;
}
/** The request kinds an OpenCode 2 host reports for a model request. */
export type RequestKind = 'primary' | 'compaction' | 'title' | 'generate';
/**
 * The model a title request is sent to when the host selected one this
 * plugin does not serve as text: an unregistered model or an image model.
 */
export declare const TITLE_FALLBACK_MODEL = "gemini-3.5-flash-low";
/**
 * Routes a title request: a registered text model is kept; any other model
 * (unregistered, or an image model) is replaced in the URL by
 * `TITLE_FALLBACK_MODEL`. Everything else in the URL is unchanged.
 */
export declare function routeTitleModel(url: string): string;
/** The shared engine bound to one location. */
export interface AntigravityRequestExecutor {
    /**
     * Sends a Generative Language request through account selection, retries
     * and response transformation. Abort uses `init.signal` (or the Request's
     * signal) at every wait and send.
     */
    execute(input: RequestInfo | URL, init?: RequestInit, options?: RequestExecuteOptions): Promise<Response>;
    /**
     * Stops admitting requests without cancelling the ones already admitted:
     * later `execute` calls reject, while admitted requests keep their retries
     * and response bodies. Resolves once every admitted request and body has
     * finished, then releases retry and warmup bookkeeping. A later `dispose`
     * still aborts whatever is left.
     */
    retire(): Promise<void>;
    /**
     * Aborts every admitted request and response body, waits for them to
     * finish, then releases retry and warmup bookkeeping.
     */
    dispose(): Promise<void>;
}
/**
 * Background quota refresh after a successful send, for rows held in a core
 * account manager. It reads the row's refresh token, so it applies to local
 * credentials only. A reading for a row removed or replaced meanwhile is
 * dropped.
 */
export declare function createLocalQuotaRefresh(accountManager: Pick<CoreAccountManager, 'getAccounts' | 'getAccountsForQuotaCheck' | 'updateQuotaCache' | 'requestSaveToDisk'>, quotaManager: Pick<QuotaManager, 'refreshAccount' | 'hashedLogLabel'>, log: Logger): (account: ManagedAccount, intervalMinutes: number) => Promise<void>;
/**
 * Builds one location's request engine. Each executor owns its retry and
 * warmup bookkeeping, so disposing it releases every counter.
 */
export declare function createRequestExecutor<A extends RequestAccountRow>(deps: RequestServicesDeps<A>): AntigravityRequestExecutor;
export {};
//# sourceMappingURL=request-services.d.ts.map