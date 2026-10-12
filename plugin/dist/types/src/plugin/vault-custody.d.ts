/**
 * Vault custody for the OpenCode host (OpenCode 1 and OpenCode 2 locations
 * alike): whether Antigravity accounts are served from the plugin's own
 * account store ("local") or from the Claustrum vault ("custody"), the
 * setup steps that switch between them, and the vault account source the
 * custody request path uses.
 *
 * Everything lives in an owner-only `antigravity-auth-vault` directory
 * beside the resolved account file: the non-secret mode file, the vault
 * roster and this host's enrollment files (written by the vault library).
 * The mode file holds only the mode; no token, project or account data is
 * written here. A missing mode file is local mode, so nothing connects to
 * the vault and no source starts while local custody is in force.
 *
 * Every custody entry re-reads the mode and checks the host's own auth slot
 * against it through the vault library: a real host login while the vault
 * holds the accounts refuses custody instead of silently picking one of the
 * two. The host supplies a reader for its slot; a slot that cannot be read
 * refuses custody rather than being treated as empty.
 */
import { type AntigravityVaultAccountSource, type CommonAuthClaustrumModule, type CommonAuthCommandsModule, type EnrollmentAuthority, type VaultLogger, type VaultProviderStateFile, type VaultReporterSource, type VaultScopedClient } from '@cortexkit/antigravity-auth-core';
/** The host auth slot this plugin's provider lives in on OpenCode. */
export declare const OPENCODE_VAULT_PROVIDER = "google";
/** The vault host name; one enrollment per host. */
export declare const OPENCODE_VAULT_HOST = "opencode";
/** The enrollment name the vault operator sees and approves. */
export declare const OPENCODE_VAULT_ENROLLMENT_NAME: "antigravity-auth-opencode" | "antigravity-auth-pi";
/** The vault directory's name, beside the resolved account file. */
export declare const OPENCODE_VAULT_DIR_NAME = "antigravity-auth-vault";
type Claustrum = CommonAuthClaustrumModule;
type EnrollmentStatus = Awaited<ReturnType<Claustrum['readClaustrumEnrollmentStatus']>>;
type EnrollmentConnection = Awaited<ReturnType<Claustrum['connectClaustrumEnrollmentClient']>>;
type HostSlotContent = ReturnType<Claustrum['classifyHostSlot']>;
type MenuOptions = Parameters<CommonAuthCommandsModule['createCommandMenu']>[0];
type MenuExtraSection = NonNullable<MenuOptions['extras']>[number];
export interface OpenCodeVaultPaths {
    readonly dir: string;
    readonly modeFile: string;
    readonly rosterFile: string;
    /** The vault accounts' credential-free provider state. */
    readonly stateFile: string;
}
/** The vault paths for one resolved account file. */
export declare function openCodeVaultPaths(accountFile: string): OpenCodeVaultPaths;
export type OpenCodeVaultMode = 'local' | 'custody';
export interface OpenCodeVaultModeRecord {
    readonly version: 1;
    readonly mode: OpenCodeVaultMode;
}
export type OpenCodeVaultModeRead = {
    readonly ok: true;
    readonly record: OpenCodeVaultModeRecord;
} | {
    readonly ok: false;
    readonly reason: string;
};
/**
 * Reads the mode file. A missing file is local mode. A file that exists but
 * cannot be read or understood is reported, never guessed: custody is then
 * refused, because the user's choice is unknown.
 */
export declare function readOpenCodeVaultMode(modeFile: string): Promise<OpenCodeVaultModeRead>;
/** A custody step refused before anything changed, with a message for the user. */
export declare class OpenCodeVaultCustodyError extends Error {
    constructor(message: string);
}
export interface OpenCodeVaultStatus {
    readonly mode: OpenCodeVaultMode | 'unreadable';
    readonly modeProblem?: string;
    readonly enrollment: EnrollmentStatus;
    /** `unreadable` when the host's slot reader failed. */
    readonly hostSlot: HostSlotContent | 'unreadable' | 'not-used';
}
export interface OpenCodeVaultCustodyOptions {
    readonly onAuthorityChanged?: (authority: EnrollmentAuthority) => void;
    readonly onRosterChanged?: () => void;
    /** The resolved account file the vault directory sits beside. */
    readonly accountFile: string;
    /**
     * The host's own auth slot for `google`, read through the host's public
     * API and shaped as the vault library classifies it (`oauth` or `api`).
     * It must reject when the slot cannot be read.
     */
    readonly readHostSlot: () => Promise<unknown>;
    /** Which side reads a send's HTTP status for 401 reports. */
    readonly reporterSource: VaultReporterSource;
    /**
     * The vault's connection file; defaults to the vault client library's own
     * resolution of it (core `resolveClaustrumConnectionPath`). Read only when
     * a vault client is opened.
     */
    readonly connectionFile?: () => string | Promise<string>;
    readonly loadClaustrum?: () => Promise<Claustrum>;
    /** Opens the request-path vault client; defaults to the connection file. */
    readonly connect?: () => Promise<VaultScopedClient>;
    /** Opens the setup-only enrollment client; defaults to the connection file. */
    readonly connectEnrollment?: () => Promise<EnrollmentConnection>;
    readonly logger?: VaultLogger;
    readonly now?: () => number;
}
export interface OpenCodeVaultCustody {
    /** Detect approval and disconnect with the existing enrollment-status poll, without another timer. Local mode opens no vault connection. */
    startObservation(): Promise<void>;
    readonly paths: OpenCodeVaultPaths;
    readMode(): Promise<OpenCodeVaultModeRead>;
    /**
     * The vault account source for a custody send path. Refused unless the
     * mode is custody, this host's enrollment is approved and the host slot
     * holds no real login. The source is created once and reused until
     * custody ends.
     */
    custodySource(): Promise<AntigravityVaultAccountSource>;
    status(): Promise<OpenCodeVaultStatus>;
    /** One enrollment step: propose this host to the vault, or poll the proposal. */
    requestAccess(): Promise<EnrollmentStatus>;
    /** Serve accounts from the vault from now on. */
    useVault(): Promise<void>;
    /** Serve accounts from the local account store again; ends the vault source. */
    useLocal(): Promise<void>;
    /** The Vault section of the `/antigravity` menu. */
    menuSection(): MenuExtraSection;
    /** The vault accounts' stored provider state (missing file: none). */
    readState(): Promise<VaultProviderStateFile>;
    /** Closes the vault source, if one was created. */
    dispose(): Promise<void>;
}
export declare function createOpenCodeVaultCustody(options: OpenCodeVaultCustodyOptions): OpenCodeVaultCustody;
/** Non-secret status lines: never a token, project or account address. */
export declare function statusLines(status: OpenCodeVaultStatus): string[];
export {};
//# sourceMappingURL=vault-custody.d.ts.map