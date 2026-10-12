/**
 * File-backed logger for the OpenTUI sidebar tree.
 *
 * The TUI renders directly into the host terminal. Any stray write to the
 * terminal from inside the render path (or any module it imports) corrupts
 * the frame buffer — a single byte out of place shoves every subsequent
 * cell right and breaks the sidebar.
 *
 * This logger writes to a rotating file under the host's log directory and
 * never touches stdout/stderr. The plugin already wires up the same kind of
 * file logger via `debug.ts`; the sidebar gets its own file so log lines
 * from this tree are easy to attribute.
 */
export type TuiLogLevel = 'debug' | 'info' | 'warn' | 'error';
export interface TuiLogger {
    debug(message: string, extra?: Record<string, unknown>): void;
    info(message: string, extra?: Record<string, unknown>): void;
    warn(message: string, extra?: Record<string, unknown>): void;
    error(message: string, extra?: Record<string, unknown>): void;
    /** Resolve the path the logger writes to. `undefined` when file logging is disabled. */
    getLogPath(): string | undefined;
}
interface FileLoggerOptions {
    filePath: string;
    maxBytes?: number;
}
/**
 * Resolve the on-disk path for the TUI's log file.
 *
 * - `ANTIGRAVITY_AUTH_TUI_LOG_FILE` wins when set (used by tests so they
 *   never touch a real user log file).
 * - Otherwise write under `<xdg-state>/cortexkit/antigravity-auth/tui.log`.
 *
 * There is no temporary-file fallback. The writer silently drops lines when
 * the resolved destination cannot be written.
 */
export declare function resolveTuiLogPath(): string;
export declare function createTuiFileLogger(options?: Partial<FileLoggerOptions>): TuiLogger;
export {};
//# sourceMappingURL=file-logger.d.ts.map