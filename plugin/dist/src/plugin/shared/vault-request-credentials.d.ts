/**
 * Vault-held accounts for the shared request engine, used by OpenCode 1 and
 * OpenCode 2 alike: selection rows built from the vault's selectable routes,
 * the engine's `vault` credential domain over a vault account source, and
 * the rows' durable selection state in the vault's credential-free
 * provider-state file.
 *
 * A row carries the route and selection bookkeeping only; no token, refresh
 * token, project or local repository reference. Every physical send asks
 * the source for a fresh receipt for the selected row's route and uses that
 * receipt's token and project for that send only; a 401 is reported against
 * the exact receipt that served it. Nothing is refreshed locally, cached or
 * written to a row.
 *
 * The module imports no host SDK and no composition root: the source is the
 * core vault account source (or anything with the same operations).
 */
import { AccountSelector, type AntigravityQuotaCheckReport, type AntigravityVaultAccountSource, type QuotaState, type QuotaSummary, type SelectableAccount, type SelectionSink, type VaultProviderStateCommitResult, type VaultProviderStateFile, type VaultRouteRef, type VaultStateAttribution } from '@cortexkit/antigravity-auth-core';
import type { VaultRequestCredentials } from './request-services.ts';
/** The vault account source operations a vault request path uses. */
export type VaultRequestSource = Pick<AntigravityVaultAccountSource, 'refresh' | 'routes' | 'admit' | 'reportServedStatus'>;
/** The vault account source operations durable selection state uses. */
export type VaultStateSource = Pick<AntigravityVaultAccountSource, 'attribution' | 'commitState'>;
/**
 * A vault-backed pool row: selection metadata plus the vault route it was
 * listed under.
 */
export type VaultAccountRow = SelectableAccount & {
    route: VaultRouteRef;
};
/**
 * Selection rows for the vault's selectable routes, in roster order, with
 * no selection history.
 */
export declare function vaultAccountRows(routes: readonly VaultRouteRef[]): VaultAccountRow[];
/**
 * A vault row's identity for `AccountSelector.replaceAccounts`: its route,
 * credential and asserted account. A route that now names another
 * credential or account is a different row.
 */
export declare function vaultAccountRowKey(row: VaultAccountRow): string;
/**
 * Keeps a vault row's in-memory selection state across a roster re-read and
 * takes only the route's display fields from the fresh roster. A kept row's
 * in-memory state is the newest there is; stored state (see
 * `createVaultSelectionState`) is restored only onto rows that are new.
 */
export declare function refreshVaultAccountRow(prior: VaultAccountRow, fresh: VaultAccountRow): void;
/**
 * The shared engine's `vault` credential domain over a vault account source.
 * `onAdmitted` receives each receipt's non-secret attribution, taken by the
 * same source, with the row it was taken for (see
 * `createVaultSelectionState`).
 */
export declare function createVaultRequestCredentials(source: Pick<VaultRequestSource, 'admit' | 'reportServedStatus'>, onAdmitted?: {
    readonly source: Pick<VaultStateSource, 'attribution'>;
    admitted(row: VaultAccountRow, attribution: VaultStateAttribution): void;
}): VaultRequestCredentials<VaultAccountRow>;
export interface VaultSelectionStateOptions {
    /** The vault source's attribution-fenced state commit. */
    readonly source: Pick<VaultStateSource, 'commitState'>;
    /** Reads the provider-state file the source commits to. */
    readonly readState: () => Promise<VaultProviderStateFile>;
    readonly now?: () => number;
    /** Receives a refused or failed write; the observation is then dropped. */
    readonly onError?: (error: unknown) => void;
}
export interface VaultSelectionState {
    /** The selector's sink: every reported transition marks its row changed. */
    readonly sink: SelectionSink<VaultAccountRow>;
    /** Records the receipt attribution that last served `row`. */
    admitted(row: VaultAccountRow, attribution: VaultStateAttribution): void;
    /**
     * Restores stored selection state onto fresh rows. A row takes state only
     * when that state was last written for the same asserted account, route
     * and credential; state of another account, route or credential is left
     * alone.
     */
    hydrate(rows: readonly VaultAccountRow[]): Promise<void>;
    /**
     * Writes each changed row's selection state, attributed to the receipt
     * that last served it. A row not yet served in this process has no
     * attribution and stays changed until it is. The source refuses a write
     * whose credential, account or record version the vault no longer serves,
     * and the change is dropped rather than re-attributed.
     */
    flush(): Promise<void>;
    /** Records a quota reading taken with the receipt `attribution` names. */
    recordQuota(attribution: VaultStateAttribution, quota: QuotaState): Promise<VaultProviderStateCommitResult>;
}
/**
 * Durable selection state for vault rows, kept in the vault source's
 * credential-free provider-state file by asserted account. The selector
 * stays the only selection policy: this only saves and restores the fields
 * it already maintains.
 */
export declare function createVaultSelectionState(options: VaultSelectionStateOptions): VaultSelectionState;
export interface VaultAccountPoolOptions {
    readonly source: VaultRequestSource;
    /**
     * Makes the pool's selection state durable (see
     * `createVaultSelectionState`): the same source's attribution and fenced
     * commit, and a reader of the provider-state file it commits to. Without
     * it, selection state lives in memory only.
     */
    readonly durable?: {
        readonly source: VaultStateSource;
        readonly readState: () => Promise<VaultProviderStateFile>;
        /** Receives a refused or failed state write. */
        readonly onError?: (error: unknown) => void;
    };
    readonly now?: () => number;
}
/**
 * One host location's vault-held accounts for the shared request engine:
 * the one `AccountSelector` over the vault's routes, the engine's vault
 * credentials, and (with `readState`) the selector's durable state. Both
 * OpenCode hosts build their vault request path on this, so a location has
 * exactly one authoritative selector and one place its state is saved.
 */
export interface VaultAccountPool {
    readonly selector: AccountSelector<VaultAccountRow>;
    readonly credentials: VaultRequestCredentials<VaultAccountRow>;
    /** The durable selection state, when the pool has a state file. */
    readonly state: VaultSelectionState | undefined;
    /**
     * Brings the rows up to date with the source's roster: the first call
     * reads the roster from the vault (a failed read is retried by the next
     * call); later calls take the source's last committed routes. New rows
     * get their stored state; kept rows keep their in-memory state.
     */
    sync(): Promise<void>;
    /** Re-reads the roster from the vault now, then syncs the rows. */
    refresh(): Promise<void>;
    /** Writes pending selection state. */
    flush(): Promise<void>;
}
export declare function createVaultAccountPool(options: VaultAccountPoolOptions): VaultAccountPool;
/**
 * A quota reading for one vault account, as the vault quota check returns
 * it: the summary, and the credential-free attribution of the admission
 * whose answer produced it (absent when none did).
 */
export interface VaultQuotaAnswer {
    readonly quota: QuotaSummary;
    readonly quotaAttribution?: VaultStateAttribution;
}
/** The stored quota reading for a summary taken at `at`. */
export declare function vaultQuotaState(quota: QuotaSummary, at: number): QuotaState;
/**
 * Checks quota for every row of a durable vault pool and records each
 * reading through the source's provider-state commit, attributed to the
 * admission that produced it. A row counts as checked only when its reading
 * was written; a reading with an error, without an attribution, or whose
 * write the source refuses (another credential, account or a newer record
 * version) is not checked and is not shown. A written reading is also put
 * on the row that is still at that route, credential and account. An
 * aborted `signal` stops the check; the remaining rows are not checked.
 */
export declare function checkVaultQuota(input: {
    readonly pool: Pick<VaultAccountPool, 'selector' | 'state'>;
    /** One vault account's quota check (the shared vault quota helper). */
    readonly fetchReading: (ref: VaultRouteRef, signal: AbortSignal) => Promise<VaultQuotaAnswer>;
    readonly signal: AbortSignal;
    readonly now?: () => number;
    readonly onError?: (error: unknown) => void;
}): Promise<AntigravityQuotaCheckReport>;
//# sourceMappingURL=vault-request-credentials.d.ts.map