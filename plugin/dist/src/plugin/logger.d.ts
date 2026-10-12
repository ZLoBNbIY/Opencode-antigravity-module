/**
 * Structured Logger for Antigravity Plugin
 *
 * Logging behavior:
 * - debug controls file logs only (via debug.ts)
 * - debug_tui controls the host log destination only
 * - either sink can be enabled independently
 * - OPENCODE_ANTIGRAVITY_CONSOLE_LOG=1 → console output (independent of debug flags)
 * - operator.log_level filters the level at which log entries are emitted
 *
 * Every server location builds its own logger with `createLocationLogger`:
 * its own level, host sink and debug_tui policy, over its own instance of the
 * embedded public logger (same scrubber and provider key policy). Creating a
 * location logger never installs the core package's process-wide log sink;
 * a location hands `coreLogSink` to the core objects it constructs instead.
 *
 * The module-level `initLogger`, `setRuntimeLogLevel` and `createLogger`
 * below serve the existing OpenCode 1 callers through one module-level
 * logger; no location logger reads or writes it.
 */
import type { OperatorSettings } from './config/operator-settings-schema';
import type { AppLogClient, LocationLogRecord, LocationLogSink } from './neutral-types';
export interface Logger {
    debug(message: string, extra?: Record<string, unknown>): void;
    info(message: string, extra?: Record<string, unknown>): void;
    warn(message: string, extra?: Record<string, unknown>): void;
    error(message: string, extra?: Record<string, unknown>): void;
}
export interface LocationLoggerOptions {
    /**
     * Host destination for this location's records. Without one, records reach
     * only the environment-gated console fallback.
     */
    sink?: LocationLogSink;
    /**
     * This location's debug_tui policy, read on every record: the sink receives
     * a record only while it returns true.
     */
    sinkEnabled: () => boolean;
    /** Initial operator log level. Without one the floor is debug. */
    level?: OperatorSettings['log_level'];
}
export interface LocationLogger {
    /**
     * A logger for a static module name, such as refresh-queue. Channel names
     * are not scrubbed; do not put account or session IDs in them.
     */
    createLogger(module: string): Logger;
    /** Apply this location's operator log level to its next records. */
    setLevel(level: OperatorSettings['log_level']): void;
    /**
     * Sink for core-package objects this location constructs (for example an
     * account manager's `logSink` option). Records are scrubbed and routed
     * through this location's level and destinations, never another's.
     */
    readonly coreLogSink: (record: LocationLogRecord) => void;
}
/** Build one location's independent logger. */
export declare function createLocationLogger(options: LocationLoggerOptions): LocationLogger;
/**
 * Adapt a host client's `app.log` into a location log sink (OpenCode 1).
 * A client without `app.log` makes the sink a no-op.
 */
export declare function createAppLogSink(client: AppLogClient): LocationLogSink;
/**
 * Set the OpenCode 1 logger's level from the supplied operator level
 * (`trace` becomes `debug`). Existing channels use the updated level on their
 * next log call.
 */
export declare function setRuntimeLogLevel(level: OperatorSettings['log_level']): void;
/**
 * Bind the OpenCode 1 logger to the plugin client.
 * Called during OpenCode 1 plugin initialization to enable TUI logging.
 * Server locations use `createLocationLogger` and never call this.
 */
export declare function initLogger(client: AppLogClient): void;
/**
 * Create an OpenCode 1 logger for a static module name, such as
 * refresh-queue. Its debug, info, warn and error methods share the current
 * minimum level.
 */
export declare function createLogger(module: string): Logger;
//# sourceMappingURL=logger.d.ts.map