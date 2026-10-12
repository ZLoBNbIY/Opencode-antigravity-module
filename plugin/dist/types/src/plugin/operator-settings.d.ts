/**
 * Persistent runtime operator settings.
 *
 * The /antigravity-* slash commands mutate this struct. The controller:
 *
 *   1. Loads the operator slice from the project config (if present)
 *      or the user config on first access, so a fresh plugin boot
 *      sees the user's previous choices.
 *   2. Updates the runtime settings immediately so the same plugin
 *      instance picks up the change without waiting for the file
 *      write to land.
 *   3. Serializes the change through `config/writer.ts` (fenced lock
 *      + atomic rename) so a crash mid-write cannot corrupt the
 *      persisted file.
 *   4. Exposes a single idempotent `dispose()` so it can be hooked
 *      into the plugin lifecycle without leaking timers or listeners.
 *
 * No raw OAuth refresh tokens ever live in this struct — killswitch
 * account overrides are keyed by sha256(refreshToken).slice(0,12).
 */
import { type OperatorSettings } from './config/operator-settings-schema.js';
export type { OperatorSettings } from './config/operator-settings-schema.js';
export { emptyOperatorSettings } from './config/operator-settings-schema.js';
export interface OperatorSettingsControllerOptions {
    projectConfigPath: string;
    userConfigPath: string;
}
export interface OperatorSettingsController {
    get(): OperatorSettings;
    update(mutator: (draft: OperatorSettings) => void): Promise<void>;
    dispose(): Promise<void>;
}
export declare function createOperatorSettingsController(options: OperatorSettingsControllerOptions): OperatorSettingsController;
/**
 * Process-wide table of shared operator-file controllers keyed by canonical
 * path. An entry lives while any location holds it and is dropped at the
 * last release, so a later acquisition reads the file afresh.
 */
export interface OperatorSettingsRegistry {
    /** Canonical paths with a live controller (diagnostics and tests). */
    livePaths(): string[];
}
export declare function createOperatorSettingsRegistry(): OperatorSettingsRegistry;
/** The registry every location in this process shares. */
export declare const processOperatorSettingsRegistry: OperatorSettingsRegistry;
export interface LocationOperatorSettingsOptions extends OperatorSettingsControllerOptions {
    /** Defaults to the process registry; tests pass an isolated one. */
    registry?: OperatorSettingsRegistry;
}
export interface LocationOperatorSettings extends OperatorSettingsController {
    /** Canonical path of the file this location currently reads. */
    sourcePath(): string;
}
/**
 * Acquire one location's operator settings.
 *
 * Reads come from the project file's operator block when it parses, else
 * the user file's block, else defaults. Writes go to the project file
 * whenever it exists (block or not), else the user file, keeping every other
 * field. Each file has one shared controller per process, so locations on
 * the same file see each other's updates and updates to one file serialize.
 * A location whose project file exists without a block reads through the
 * user file; its first mutation seeds a project block from its effective
 * values and rebinds it to the project file. Applying the values (log level,
 * routing, killswitch) is the caller's per-location concern.
 */
export declare function acquireLocationOperatorSettings(options: LocationOperatorSettingsOptions): LocationOperatorSettings;
/**
 * Hash a refresh token into the stable 12-char account key used by
 * the killswitch accounts override map. Centralizing the hash here
 * keeps the truncation invariant in one place.
 */
export declare function accountKeyForRefreshToken(refreshToken: string): string;
//# sourceMappingURL=operator-settings.d.ts.map