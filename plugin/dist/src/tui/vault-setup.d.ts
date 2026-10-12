/**
 * The Vault section of the `/antigravity` menu: a credential-free view and
 * action model for setting up the Claustrum vault on OpenCode.
 *
 * The server owns everything with an effect (enrollment, switching the
 * account source, any credential the vault hands out). This module only
 * turns a non-secret status into the section's lines and decides which
 * actions are offered, and each action calls an injected server effect. It
 * imports nothing: no vault client, token, account store or OAuth code, so it
 * can sit next to the TUI without widening what the TUI can reach.
 *
 * The section's shape is the shared command menu's provider extra
 * (`PluginExtraSection` of `@cortexkit/common-auth/commands`), declared
 * structurally here so the server can pass it straight to
 * `createCommandMenu({ extras: [...] })`.
 */
/** The enrollment name this host registers with the vault. */
export declare const OPENCODE_VAULT_ENROLLMENT_NAME: "antigravity-auth-opencode";
/** Where requests take their Antigravity accounts from. */
export type VaultSourceMode = 'local' | 'custody';
/**
 * - `not-enrolled`: this host has never been enrolled.
 * - `pending`: an enrollment was started and waits for approval in the vault.
 * - `enrolled`: the vault knows this host.
 * - `revoked`: the vault withdrew this host's enrollment.
 * - `declined`: the vault refused the enrollment request.
 * - `unavailable`: the vault could not be reached when status was read.
 */
export type VaultEnrollmentState = 'not-enrolled' | 'pending' | 'enrolled' | 'revoked' | 'declined' | 'unavailable';
/** Why vault custody cannot be used even though enrollment may exist. */
export type VaultIneligibleReason = 'no-vault-configured' | 'host-login-present' | 'unsupported-host';
/** The non-secret facts the server reports about vault setup. */
export interface VaultSetupStatus {
    readonly mode: VaultSourceMode;
    readonly enrollment: VaultEnrollmentState;
    /** Present when custody cannot be selected; the reason is shown as-is. */
    readonly ineligible?: VaultIneligibleReason;
    /** Accounts the vault currently serves to this host, when enrolled. */
    readonly accounts?: number;
    /** When the status was read (ms since epoch). */
    readonly checkedAt: number;
}
/** What a vault action reports; `text` is shown to the user. */
export interface VaultActionOutcome {
    readonly ok: boolean;
    readonly text: string;
    readonly code?: string;
}
/**
 * The server effects behind the section's actions. Every one is owned by
 * the server; this model never performs an effect itself.
 */
export interface VaultSetupEffects {
    /** Reads the current, non-secret status. Called for every menu build. */
    status(): Promise<VaultSetupStatus>;
    /** Starts enrollment under {@link OPENCODE_VAULT_ENROLLMENT_NAME}. */
    enroll(): Promise<VaultActionOutcome>;
    /** Routes requests through vault custody. */
    useCustody(): Promise<VaultActionOutcome>;
    /** Routes requests through the local accounts again. */
    useLocal(): Promise<VaultActionOutcome>;
    /** Withdraws this host's enrollment. */
    disconnect(): Promise<VaultActionOutcome>;
}
export interface VaultSectionAction {
    readonly id: string;
    readonly label: string;
    readonly description?: string;
    readonly irreversible?: boolean;
    readonly confirm?: string;
    run(input: unknown): Promise<VaultActionOutcome>;
}
export interface VaultSectionContent {
    readonly lines: string[];
    readonly actions: VaultSectionAction[];
    readonly facts: Record<string, string | number>;
}
export interface VaultExtraSection {
    readonly id: 'vault';
    readonly title: string;
    build(invocation: unknown): Promise<VaultSectionContent>;
}
/**
 * Checks a status from the server field by field. A status with any other
 * field (a token, an email, a receipt) is refused rather than shown, so a
 * server change that starts passing secrets cannot reach the menu.
 */
export declare function parseVaultSetupStatus(value: unknown): VaultSetupStatus | undefined;
export interface VaultSetupView {
    readonly lines: string[];
    /** Ids of the actions offered for this status, in display order. */
    readonly actions: Array<'enroll' | 'use-custody' | 'use-local' | 'disconnect'>;
}
/** The lines and the offered actions for one status. */
export declare function vaultSetupView(status: VaultSetupStatus | undefined): VaultSetupView;
/** The Vault provider extra for the server's `/antigravity` menu. */
export declare function createVaultSection(effects: VaultSetupEffects): VaultExtraSection;
//# sourceMappingURL=vault-setup.d.ts.map