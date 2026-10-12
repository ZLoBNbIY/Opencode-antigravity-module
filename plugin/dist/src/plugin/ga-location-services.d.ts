/**
 * The OpenCode 2 (GA host) location services: account state for the
 * `antigravity-auth` RPC `state` method, the shared `/antigravity` menu
 * behind `apply`, and `createGaLocationServicesFactory`, which builds a
 * location's services from the bound account repository and the shared
 * request pipeline.
 *
 * Accounts come from the location's account repository, read once per
 * `state` call. Each account in a state answer carries an opaque selector: a
 * random string issued for one exact credential (row id, credential epoch
 * and recorded identity), kept across reads and reorders and retired when
 * that credential is replaced, re-identified or removed. Account actions run
 * through the shared menu, whose own opaque item ids are bound the same way;
 * an account position is never accepted as a target.
 *
 * Everything a location needs (repository, settings controller, dump switch,
 * logger) arrives explicitly; nothing here reads a process-global binding.
 * The GA server module is imported for types only, so it can import this
 * module's factory without a cycle.
 */
import { type AccountManager, type AccountRepository, type AccountRow, type AccountStoreModules, type AntigravityMenuAccounts, type AntigravityQuotaCheckReport, type AntigravityRepositoryMenuOptions, type AntigravityVaultAccountSource, type CommonAuthCommandsModule, type FetchAccountQuota, type ManagedAccount, type OAuthAuthDetails, type RowRef, type VaultRouteRef } from '@cortexkit/antigravity-auth-core';
import type { AntigravityRpcScope, AntigravitySettingsDto, AntigravityStatusDto } from '../ga/rpc/protocol.ts';
import type { GaCommandService, GaJobExecutor, GaLocationServices, GaLocationServicesFactory, GaPluginOverrides, GaRpcActivation, GaRuntimeCollaborators, GaStateSource, HarnessAccessBlock, ObserveAccountSnapshot } from '../ga/server/index.ts';
import type { SidebarRoutingEntry } from '../sidebar-state.ts';
import type { GeminiDumpState } from './gemini-dump.ts';
import type { Logger } from './logger.ts';
import type { OperatorSettings } from './operator-settings.ts';
import { type AntigravityRequestExecutor, type LocalRequestCredentials, type RequestRoutingEntry } from './shared/request-services.ts';
import { type LocationRuntime } from './shared/runtime.ts';
import { type VaultAccountPool, type VaultAccountRow, type VaultQuotaAnswer, type VaultRequestSource, type VaultStateSource } from './shared/vault-request-credentials.ts';
import { type OpenCodeVaultCustody } from './vault-custody.ts';
/** What a selector names, as the registry resolves it. */
export type GaSelectorResolution = {
    readonly kind: 'live';
    readonly ref: RowRef;
} | {
    readonly kind: 'retired';
    readonly ref: RowRef;
} | {
    readonly kind: 'unknown';
};
/**
 * Selectors issued for one activation. A selector is bound to one exact
 * `RowRef` for life: the same credential keeps its selector across reads,
 * and a credential that changes gets a new one while the old one retires.
 */
export interface GaSelectorRegistry {
    /**
     * The selectors one read would show, without changing the registry.
     * `commit` makes them current; an aborted read simply drops the plan.
     */
    plan(refs: readonly RowRef[]): GaSelectorPlan;
    resolve(selector: string): GaSelectorResolution;
}
export interface GaSelectorPlan {
    /** One selector per input ref, in input order. */
    readonly selectors: readonly string[];
    /** Makes this plan current; returns the selectors it retired. */
    commit(): readonly string[];
}
export declare function createGaSelectorRegistry(createSelector?: () => string): GaSelectorRegistry;
/**
 * The access block the row's metadata records. Absent or dropped metadata
 * cannot rule a block out, so it is `unknown`, never `none`.
 */
export declare function accessBlockOf(row: AccountRow): HarnessAccessBlock;
/**
 * The settings DTO from the location's live controller and dump switch. It
 * only reads; per-account killswitch overrides stay out because their keys
 * derive from refresh tokens.
 */
export declare function gaSettingsOf(settings: OperatorSettings, dump: Pick<GeminiDumpState, 'isEnabled'>): AntigravitySettingsDto;
export interface GaAccountStateOptions {
    readonly repository: Pick<AccountRepository, 'read'>;
    readonly registry: GaSelectorRegistry;
    readonly nextReadSeq?: () => number;
    readonly generation: string;
    /** Read fresh for every answer, after the repository read. */
    readonly settings: () => AntigravitySettingsDto;
    readonly status: () => AntigravityStatusDto;
    /** The requesting session's route; `null` when there is none. */
    readonly route: (scope: AntigravityRpcScope) => SidebarRoutingEntry | null;
    /** Health score for a row, when the location tracks one. */
    readonly health?: (row: AccountRow) => number | undefined;
    readonly observe?: ObserveAccountSnapshot;
}
/**
 * Builds the `state` source. Reads run one at a time, so `readSeq` follows
 * the order answers are built in; an aborted read leaves the selector
 * registry unchanged. The diagnostic observer, when present, is called
 * synchronously with a view of the same read.
 */
export declare function createGaAccountStateSource(options: GaAccountStateOptions): GaStateSource;
type GaMenuOptions = Parameters<CommonAuthCommandsModule['createCommandMenu']>[0];
type GaMenuExtraSection = NonNullable<GaMenuOptions['extras']>[number];
/** The shared `/antigravity` menu, as the core factory builds it. */
export type GaCommandMenu = ReturnType<CommonAuthCommandsModule['createCommandMenu']>;
/**
 * The location's `/antigravity` menu: the shared core menu in repository
 * mode over this activation's repository and runtime. Accounts are acted on
 * by the menu's own opaque item ids, each bound to one exact credential;
 * Routing, Limits and Diagnostics read and write this location's settings
 * controller and dump switch. `commands` must be the module whose
 * `parseApplyRequest` the RPC activation uses.
 */
export declare function createGaLocationMenu(input: {
    readonly commands: CommonAuthCommandsModule;
    readonly repository: AntigravityMenuAccounts & Pick<AccountRepository, 'updateMetadata'>;
    readonly runtime: Pick<LocationRuntime, 'operatorSettings' | 'dump' | 'applyOperatorSettings'>;
    readonly refreshQuota?: AntigravityRepositoryMenuOptions['refreshQuota'];
    readonly reauthorize?: AntigravityRepositoryMenuOptions['reauthorize'];
    /** The Vault section, when the location has vault custody available. */
    readonly vault?: GaMenuExtraSection;
}): GaCommandMenu;
/**
 * The location's menu service: `apply` for the RPC `apply` method, and
 * `open` for the native `/antigravity` command, which queues the menu that
 * opens the drawer in the invoking session's scope.
 */
export interface GaMenuCommandService extends GaCommandService {
    open(input: {
        readonly scope: AntigravityRpcScope;
        readonly signal: AbortSignal;
    }): Promise<void>;
}
/**
 * The menu service over the location's menu. Each request (already accepted
 * by the library's own parser) runs through the menu with an invocation for
 * its scope, whose notices are queued for that scope; once the activation's
 * signal aborts, no new action starts. After every apply, `afterApply`
 * brings the routing state up to date with what the action wrote; its
 * failure is reported to the scope but does not change the menu's answer.
 */
export declare function createGaMenuCommandService(input: {
    readonly menu: GaCommandMenu;
    readonly notify: GaRpcActivation['notify'];
    readonly afterApply?: () => Promise<void>;
}): GaMenuCommandService;
/** The menu's reauthorize option, as the shared core menu takes it. */
type GaReauthorize = NonNullable<AntigravityRepositoryMenuOptions['reauthorize']>;
/**
 * The account items' Reauthorize action for a GA location: a browser
 * sign-in whose result replaces exactly the credential the item was opened
 * for (through the account adapters' repository access service, which also
 * refuses a sign-in to a different Google account and clears the row's
 * access blocks). The action answers once the sign-in has started and the
 * callback listener is waiting; the rest finishes in the background and is
 * reported to the invoking session. `afterChange` brings routing up to date
 * with the new credential.
 *
 * Without an override, the redirect is received by this package's own
 * callback listener on the registered redirect address, which accepts only
 * the state of the sign-in it was started for.
 */
export declare function createGaReauthorize(input: {
    readonly assertAdmission?: () => Promise<void>;
    readonly repository: AccountRepository;
    readonly overrides: GaPluginOverrides;
    readonly afterChange: () => Promise<void>;
}): GaReauthorize & {
    dispose(): Promise<void>;
};
/**
 * The parts of the host's integration API (`context.integration.connection`
 * in the OpenCode 2 plugin SDK) that read the active credential of one
 * integration. Declared without the SDK so this module stays SDK-free.
 */
export interface GaIntegrationConnections<C> {
    active(integrationID: string): Promise<C | undefined>;
    resolve(connection: C): Promise<unknown>;
}
/**
 * Reads the OpenCode 2 host's own sign-in for `integrationID` in the shape
 * the vault library classifies: an OAuth credential as
 * `{ type: 'oauth', refresh, access, expires }`, a key credential as
 * `{ type: 'api', key }`, and no active connection as `undefined` (empty).
 * An active connection whose credential cannot be resolved, or a credential
 * of another shape, rejects: custody is then refused, never decided on a
 * slot read as empty by mistake.
 */
export declare function createGaHostSlotReader<C>(connections: GaIntegrationConnections<C>, integrationID: string): () => Promise<unknown>;
/** The legacy account file name inside a location directory. */
export declare const GA_ACCOUNTS_FILE = "antigravity-accounts.json";
/** What `start` hands the request pipeline binding. */
export interface GaRequestPipelineInput {
    readonly repository: AccountRepository;
    readonly assertAdmission?: () => Promise<void>;
    readonly runtime: GaStartInput['runtime'];
    readonly send: GaStartInput['send'];
    readonly generation: string;
    readonly overrides: GaPluginOverrides;
    /** Where the engine records each session's route for `state`. */
    readonly routes: GaRouteBook;
}
/** The request pipeline for one activation, as the shared engine builds it. */
export interface GaRequestPipeline {
    readonly execute: GaJobExecutor;
    /**
     * The menu's manual quota check over this pipeline's accounts; absent
     * when the pipeline's custody has no such check.
     */
    readonly refreshQuota?: (refs: readonly RowRef[]) => Promise<AntigravityQuotaCheckReport>;
    /** Brings the routing accounts up to date with the account store. */
    refreshAccounts(): Promise<void>;
    dispose(): Promise<void>;
}
type GaStartInput = Parameters<GaLocationServices['start']>[0];
export interface GaLocationServicesBindings {
    /** The common-auth `./store` and `./fs` modules the repository is built on. */
    readonly loadStoreModules: () => Promise<AccountStoreModules>;
    /** Resolve the shared pool; a new workspace must not create a separate account store. */
    readonly resolveAccountFile: (directory: string) => string;
    readonly now: () => number;
    readonly createSelector?: () => string;
    /** The location runtime's collaborators (sidebar file, quota, refresh). */
    readonly runtime: (input: {
        readonly directory: string;
        readonly getRepository: () => Promise<AccountRepository>;
        readonly assertAdmission: () => Promise<void>;
        readonly overrides: GaPluginOverrides;
    }) => GaRuntimeCollaborators;
    /** Builds the shared request engine over the location's repository. */
    readonly createPipeline: (input: GaRequestPipelineInput) => Promise<GaRequestPipeline>;
    /**
     * The location's vault custody, for the account file the location
     * resolves. Without it the location serves its local account store only.
     */
    readonly custody?: (input: {
        readonly accountFile: string;
        readonly overrides: GaPluginOverrides;
    }) => GaLocationCustody;
    /**
     * One vault account's quota check through the vault (the shared vault
     * quota helper). Without it a vault location offers no quota check.
     */
    readonly fetchVaultQuota?: (input: {
        readonly source: Pick<AntigravityVaultAccountSource, 'send' | 'attribution'>;
        readonly ref: VaultRouteRef;
        readonly signal: AbortSignal;
        readonly logger: Pick<Logger, 'debug'>;
        readonly transport?: NonNullable<GaPluginOverrides['quotaFetch']>;
    }) => Promise<VaultQuotaAnswer>;
}
/** The vault source operations a GA vault location uses. */
export type GaVaultCustodySource = VaultRequestSource & VaultStateSource & Pick<AntigravityVaultAccountSource, 'send'>;
/** The vault custody operations a GA location uses. */
export interface GaLocationCustody extends Pick<OpenCodeVaultCustody, 'readMode' | 'menuSection' | 'dispose' | 'readState'> {
    custodySource(): Promise<GaVaultCustodySource>;
}
/**
 * Local credentials for a repository-backed GA location, in the shared
 * engine's `local` domain. A refresh is of the selected account itself:
 * `refreshAccount` uses the ref the account was loaded with, so the
 * repository stores a successor token only for that exact credential and
 * refuses one whose row has since changed. Rows are never found again by
 * token.
 */
export declare function createGaLocalCredentials(manager: AccountManager, options: {
    /** Supplies the manager's account rows and current credential checks. */
    readonly repository: Pick<AccountRepository, 'read'>;
    readonly overrides: GaPluginOverrides;
    readonly refreshQuotaAfterSuccess?: LocalRequestCredentials<ManagedAccount>['refreshQuotaAfterSuccess'];
}): LocalRequestCredentials<ManagedAccount>;
/**
 * A quota check's account, carrying the repository ref captured when the
 * account list was taken. Without a ref the account cannot be attributed
 * and is refused.
 */
export interface GaQuotaTarget {
    /** Same field as the core manager's quota-check target. */
    readonly rowRef?: RowRef;
}
/** The bearer a quota check may use, for exactly the captured credential. */
export type GaQuotaAuthorization = {
    readonly status: 'authorized';
    readonly ref: RowRef;
    readonly auth: OAuthAuthDetails;
} | {
    readonly status: 'refused';
    readonly reason: 'unattributed' | 'stale' | 'not-ready' | 'refresh-refused';
};
/**
 * Resolves the bearer for one quota check from the repository, by the
 * target's captured ref only. A row that no longer holds that exact
 * credential (replaced, re-identified or removed) is refused rather than
 * checked on its successor. An expired token is refreshed through the
 * repository's attributed refresh, never locally.
 */
export declare function authorizeGaQuotaCheck(repository: Pick<AccountRepository, 'read' | 'refresh'>, target: GaQuotaTarget, now: () => number): Promise<GaQuotaAuthorization>;
/**
 * The GA location's quota fetcher. Each check is attributed to the target's
 * captured repository ref: the bearer comes from `authorizeGaQuotaCheck`
 * (stored token, or the repository's attributed refresh), and a target
 * without a ref, or whose credential has since changed, is answered with an
 * error result instead of being checked on another credential.
 */
export declare function createGaFetchAccountQuota(options: {
    readonly assertAdmission?: () => Promise<void>;
    readonly repository: Pick<AccountRepository, 'read' | 'refresh'>;
    readonly now: () => number;
    readonly overrides: GaPluginOverrides;
    readonly logger: Pick<Logger, 'debug'>;
}): FetchAccountQuota;
/** The route each session's last request was dispatched on, in memory. */
export interface GaRouteBook {
    record(sessionId: string, entry: RequestRoutingEntry): void;
    route(scope: AntigravityRpcScope): SidebarRoutingEntry | null;
}
export declare function createGaRouteBook(limit?: number): GaRouteBook;
/** Runs one bridged job through the shared request engine. */
export declare function createGaJobExecutor(executor: Pick<AntigravityRequestExecutor, 'execute'>): GaJobExecutor;
/**
 * The shared request engine over a repository-backed account manager. The
 * engine is the same one OpenCode 1 uses; only its collaborators are this
 * location's.
 */
export declare function createGaLocalRequestPipeline(input: GaRequestPipelineInput & {
    /** This activation's account slot, read by its runtime's token refresher. */
    readonly accounts: GaAccountSlot;
}): Promise<GaRequestPipeline>;
/**
 * The shared request engine for a location whose accounts are held by the
 * vault. Selection runs on the shared `AccountSelector` over the vault's
 * selectable routes (metadata rows, no credential); every physical send
 * takes a fresh receipt for the selected route through
 * `createVaultRequestCredentials`. Nothing is refreshed or cached locally.
 * `refreshAccounts` re-reads the vault roster and keeps each route's
 * selection state while its route, credential and asserted account stay
 * the same. With `state`, a route's selection state is restored from and
 * saved to the vault's provider-state file, attributed to the receipt that
 * last served it.
 */
export declare function createGaVaultRequestPipeline(input: {
    readonly assertAdmission?: () => Promise<void>;
    readonly pool: VaultAccountPool;
    readonly runtime: GaStartInput['runtime'];
    readonly overrides: GaPluginOverrides;
    readonly routes: GaRouteBook;
}): Promise<GaRequestPipeline & {
    rows(): readonly VaultAccountRow[];
}>;
export declare function createGaLocationServicesFactory(bindings: GaLocationServicesBindings): GaLocationServicesFactory;
/**
 * One activation's account manager, shared by its request pipeline and its
 * runtime's proactive token refresher. Each activation has its own slot.
 */
export interface GaAccountSlot {
    current: AccountManager | null;
    /** The activation's quota logger, from its location runtime once built. */
    quotaLogger: Pick<Logger, 'debug'> | null;
}
/**
 * The runtime collaborators of a repository-backed GA location: quota
 * snapshots kept in memory (a GA location writes no sidebar file), the
 * ref-attributed quota fetcher, and a token refresher that refreshes the
 * account it is handed through this activation's manager.
 */
export declare function createGaRuntimeCollaborators(input: {
    readonly assertAdmission?: () => Promise<void>;
    readonly getRepository: () => Promise<AccountRepository>;
    readonly overrides: GaPluginOverrides;
    readonly accounts: GaAccountSlot;
    readonly now: () => number;
}): GaRuntimeCollaborators;
/** What the OpenCode 2 host supplies for vault custody of its locations. */
export interface GaVaultHost {
    /**
     * The host's own Google sign-in, read through its public integration API
     * (see `createGaHostSlotReader`); rejects when it cannot be read.
     */
    readonly readHostSlot: () => Promise<unknown>;
    /**
     * The vault's connection file; defaults to the vault client library's
     * own resolution of it.
     */
    readonly connectionFile?: () => string | Promise<string>;
}
/**
 * The production GA location services: the embedded common-auth store,
 * the system clock, the repository-backed request pipeline and the
 * collaborators above. Every activation gets its own repository, account
 * slot and pipeline. With `vault`, a location can also serve the vault's
 * accounts: its mode file decides, and the menu's Vault section switches.
 */
export declare function createGaLocationServicesForHost(vault?: GaVaultHost): GaLocationServicesFactory;
/** The connection API belongs to this setup context, not a module-wide host. */
export declare const createGaLocationServices: GaLocationServicesFactory;
export {};
//# sourceMappingURL=ga-location-services.d.ts.map