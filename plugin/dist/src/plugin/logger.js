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
import { setLogSink } from '@cortexkit/antigravity-auth-core';
import { createLoggerInstance } from '../common-auth-embedded/logger/index.js';
import { isProviderSecretKey } from '../logging/provider-key-policy';
import { isDebugTuiEnabled } from './debug';
import { isTruthyFlag, writeConsoleLog } from './logging-utils';
const ENV_CONSOLE_LOG = 'OPENCODE_ANTIGRAVITY_CONSOLE_LOG';
const LOG_LEVEL_FROM_OPERATOR = {
    error: 'error',
    warn: 'warn',
    info: 'info',
    debug: 'debug',
    trace: 'debug',
};
/** Build one location's independent logger. */
export function createLocationLogger(options) {
    let configuredLevel = options.level
        ? (LOG_LEVEL_FROM_OPERATOR[options.level] ?? 'debug')
        : 'debug';
    const emit = (record) => {
        // Host destination: sent only while the caller's sinkEnabled policy
        // returns true.
        if (options.sink && options.sinkEnabled()) {
            try {
                const pending = options.sink(record);
                if (isThenable(pending)) {
                    pending.then(undefined, () => {
                        // Silently ignore logging errors
                    });
                }
            }
            catch {
                // A synchronous host failure must not suppress the independent console.
            }
        }
        // Console fallback: when env var is set (independent of debug flags)
        if (isConsoleLogEnabled()) {
            const prefix = `[${record.service}]`;
            const args = record.extra
                ? [prefix, record.message, record.extra]
                : [prefix, record.message];
            try {
                writeConsoleLog(record.level, ...args);
            }
            catch {
                // Logging failures must not escape into provider operations.
            }
        }
        // If neither destination is enabled, the record is silently discarded.
    };
    // The library scrubs records before forwarding them to the capture sink;
    // it owns no file buffer or timer. Each channel reads the current level.
    const engine = createLoggerInstance({
        level: () => configuredLevel,
        extraSecretKeys: isProviderSecretKey,
        captureSink: ({ channel, level, message, data }) => {
            const extra = data !== null && typeof data === 'object' && !Array.isArray(data)
                ? Object.fromEntries(Object.entries(data))
                : undefined;
            emit({
                service: channel,
                level: level === 'trace' ? 'debug' : level,
                message,
                extra,
            });
        },
    });
    return {
        createLogger(module) {
            const channel = engine.createLogger(`antigravity.${module}`);
            return {
                debug: (message, extra) => channel.debug(message, extra),
                info: (message, extra) => channel.info(message, extra),
                warn: (message, extra) => channel.warn(message, extra),
                error: (message, extra) => channel.error(message, extra),
            };
        },
        setLevel(level) {
            configuredLevel = LOG_LEVEL_FROM_OPERATOR[level] ?? 'debug';
        },
        coreLogSink: ({ service, level, message, extra }) => {
            engine.createLogger(service)[level](message, extra);
        },
    };
}
/**
 * Adapt a host client's `app.log` into a location log sink (OpenCode 1).
 * A client without `app.log` makes the sink a no-op.
 */
export function createAppLogSink(client) {
    return (record) => {
        const app = client.app;
        if (app && typeof app.log === 'function') {
            return app.log({ body: record });
        }
        return undefined;
    };
}
function isThenable(value) {
    return (value !== null &&
        (typeof value === 'object' || typeof value === 'function') &&
        typeof value.then === 'function');
}
function isConsoleLogEnabled() {
    return isTruthyFlag(process.env[ENV_CONSOLE_LOG]);
}
// Module-level logger used by the existing OpenCode 1 callers. Its sink
// policy is the module-level debug_tui state from ./debug.
let legacyClient = null;
let legacyLogger;
// Created on first use: debug/config/storage can create channels while this
// module is still being evaluated through an import cycle.
function getLegacyLogger() {
    legacyLogger ??= createLocationLogger({
        sink: (record) => legacyClient ? createAppLogSink(legacyClient)(record) : undefined,
        sinkEnabled: isDebugTuiEnabled,
    });
    return legacyLogger;
}
/**
 * Set the OpenCode 1 logger's level from the supplied operator level
 * (`trace` becomes `debug`). Existing channels use the updated level on their
 * next log call.
 */
export function setRuntimeLogLevel(level) {
    getLegacyLogger().setLevel(level);
}
/**
 * Bind the OpenCode 1 logger to the plugin client.
 * Called during OpenCode 1 plugin initialization to enable TUI logging.
 * Server locations use `createLocationLogger` and never call this.
 */
export function initLogger(client) {
    legacyClient = client;
    // Route core (@cortexkit/antigravity-auth-core) logs into the same TUI/console
    // sinks the OpenCode 1 logger uses, so logs from migrated core modules surface.
    setLogSink(getLegacyLogger().coreLogSink);
}
/**
 * Create an OpenCode 1 logger for a static module name, such as
 * refresh-queue. Its debug, info, warn and error methods share the current
 * minimum level.
 */
export function createLogger(module) {
    let channel;
    // Defer touching the engine until the first log (see getLegacyLogger).
    const log = (level, message, extra) => {
        channel ??= getLegacyLogger().createLogger(module);
        channel[level](message, extra);
    };
    return {
        debug: (message, extra) => log('debug', message, extra),
        info: (message, extra) => log('info', message, extra),
        warn: (message, extra) => log('warn', message, extra),
        error: (message, extra) => log('error', message, extra),
    };
}
//# sourceMappingURL=logger.js.map