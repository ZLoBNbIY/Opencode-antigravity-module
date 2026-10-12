/**
 * Host-neutral projection of the redacted Antigravity sidebar data into the
 * rows both TUIs draw.
 *
 * Input is the already-redacted account shape: the OpenCode 1 sidebar
 * snapshot (`SidebarAccountState`) and the GA `state` answer's accounts carry
 * the same fields (ordinal id and label, enabled/current, health, cooldown,
 * per-pool remaining percentages, plan tier). Output is plain text and a
 * tone name per row; each host maps tones onto its own theme, so nothing
 * here chooses a color or assumes a dark background.
 *
 * This module imports nothing: no sidebar file, RPC, account store, OAuth or
 * credential code, so the GA build can use it without the OpenCode 1
 * filesystem primitives.
 */
export type ProjectionTone = 'ok' | 'warn' | 'err' | 'muted' | 'text';
export type ProjectionQuotaKey = 'gemini' | 'non-gemini';
export interface ProjectionQuotaWindow {
    readonly window: 'weekly' | '5h';
    readonly remainingPercent: number;
    readonly checkedAt?: number;
    readonly resetAt?: number;
}
export interface ProjectionQuotaEntry {
    readonly remainingPercent: number;
    readonly checkedAt?: number;
    readonly resetAt?: number;
    readonly windows?: readonly ProjectionQuotaWindow[];
}
/** The redacted account fields the sidebar may show, and nothing else. */
export interface ProjectionAccount {
    readonly id: string;
    readonly label: string;
    readonly enabled: boolean;
    readonly health: number;
    readonly current: boolean;
    readonly cooldownUntil?: number;
    readonly quota: {
        readonly gemini?: ProjectionQuotaEntry;
        readonly 'non-gemini'?: ProjectionQuotaEntry;
    };
    readonly tier?: {
        readonly id: string;
        readonly paidId?: string;
    };
}
export interface ProjectionRoute {
    readonly accountId: string;
    readonly modelFamily: 'claude' | 'gemini';
    readonly headerStyle: 'antigravity' | 'gemini-cli';
    readonly strategy?: 'sticky' | 'round-robin' | 'hybrid' | null;
}
export interface ProjectionStatus {
    readonly checkedAt: number | null;
    readonly quotaBackoffUntil: number | null;
}
export interface ProjectedQuotaRow {
    readonly label: string;
    /** Remaining percent 0–100, or null when no reading is cached. */
    readonly remaining: number | null;
    readonly figure: string;
    readonly tone: ProjectionTone;
    /** "reset in" text, empty without a cached reset time. */
    readonly reset: string;
}
export type AccountStatusWord = 'active' | 'idle' | 'cooling' | 'off';
export interface ProjectedAccount {
    readonly id: string;
    readonly label: string;
    readonly status: AccountStatusWord;
    readonly statusTone: ProjectionTone;
    readonly quota: readonly ProjectedQuotaRow[];
    /** Health and, while cooling, the remaining wait. */
    readonly health: string;
}
export interface ProjectedSidebar {
    readonly accounts: readonly ProjectedAccount[];
    /** `Account N · gemini · antigravity`, or null without a route. */
    readonly route: string | null;
    /** Lines describing a degraded state (backoff, no reading yet). */
    readonly notices: readonly string[];
}
export declare const QUOTA_POOL_LABELS: Readonly<Record<ProjectionQuotaKey, string>>;
/** Remaining-percent tone: low remaining is a warning, near-empty an error. */
export declare function remainingTone(remaining: number | null): ProjectionTone;
/** `12m`, `3h20m`, `2d4h`; `now` once passed; empty without a reset time. */
export declare function formatResetIn(resetAt: number | undefined, now: number): string;
/** `45s`, `3m`, `3m 20s`. */
export declare function formatWait(ms: number): string;
/**
 * Status word, first match wins: `off` when disabled, `cooling` while a
 * cooldown runs, `active` for the current account, `idle` otherwise.
 */
export declare function projectAccount(account: ProjectionAccount, now: number): ProjectedAccount;
/** The whole sidebar body for one state reading. */
export declare function projectSidebar(input: {
    readonly accounts: readonly ProjectionAccount[];
    readonly route: ProjectionRoute | null;
    readonly status: ProjectionStatus;
    readonly now: number;
}): ProjectedSidebar;
//# sourceMappingURL=sidebar-projection.d.ts.map