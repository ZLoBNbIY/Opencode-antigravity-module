/**
 * Configuration loader for opencode-antigravity-auth plugin.
 *
 * Loads config from files.
 * Priority (lowest to highest):
 * 1. Schema defaults
 * 2. User config file
 * 3. Project config file
 */
import { type Logger } from '../logger.js';
import { type AntigravityConfig } from './schema.js';
/** The `warn` capability a location passes to receive invalid-file warnings. */
export type ConfigLoadLogger = Pick<Logger, 'warn'>;
/**
 * Get the user-level config file path.
 */
export declare function getUserConfigPath(): string;
/**
 * Get the project-level config file path.
 */
export declare function getProjectConfigPath(directory: string): string;
/**
 * Load the complete configuration, sending invalid-file warnings to the
 * shared module-level logger.
 *
 * @param directory - The project directory (for project-level config)
 * @returns Fully resolved configuration
 */
export declare function loadConfig(directory: string): AntigravityConfig;
/**
 * Check if a config file exists at the given path.
 */
export declare function configExists(path: string): boolean;
/**
 * Get the default logs directory.
 */
export declare function getDefaultLogsDir(): string;
/**
 * One server location's resolved configuration. Each location loads its own
 * from its own project directory; nothing here is process-wide, so a second
 * location never sees the first location's values.
 */
export interface LocationConfig {
    readonly directory: string;
    readonly config: AntigravityConfig;
    /**
     * keep_thinking: controls thought-content replay and signature persistence
     * (disk-cache initialization and ownership), not signature lookup or
     * extraction.
     */
    readonly keepThinking: boolean;
    readonly projectConfigPath: string;
    readonly userConfigPath: string;
}
/**
 * Load one location's configuration from its project directory. Invalid-file
 * warnings go only to the required location logger `options.logger`, never
 * to the shared module-level logger.
 */
export declare function createLocationConfig(directory: string, options: {
    logger: ConfigLoadLogger;
}): LocationConfig;
/**
 * Canonical identity for a file a process-shared controller owns: the
 * real path of the file, or of its nearest existing ancestor joined with
 * the missing remainder. Two spellings of one file (relative, symlinked
 * directory, `..` segments) therefore share one controller.
 */
export declare function canonicalizeOwnedPath(path: string): string;
export declare function initRuntimeConfig(config: AntigravityConfig): void;
export declare function getKeepThinking(): boolean;
//# sourceMappingURL=loader.d.ts.map