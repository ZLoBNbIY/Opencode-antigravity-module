import { createWriteStream, mkdirSync, readdirSync, statSync, unlinkSync, } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { env } from 'node:process';
import { deriveDebugPolicy, formatAccountContextLabel, formatAccountLabel, formatBodyPreviewForLog, formatErrorForLog, isTruthyFlag, redactBodyForLog, redactSensitive, redactSensitiveFields, truncateTextForLog, } from './logging-utils';
import { ensureGitignoreSync } from './storage';
const MAX_BODY_PREVIEW_CHARS = 12000;
const MAX_BODY_LOG_CHARS = 50000;
export const DEBUG_MESSAGE_PREFIX = '[opencode-antigravity-auth debug]';
/**
 * Debug log files currently open in this process. Two locations that enable
 * file debug in the same millisecond would otherwise derive the same
 * timestamped name and interleave lines in one file, and log cleanup must
 * never delete a file another live location is still writing.
 */
const liveLogFilePaths = new Set();
/**
 * Get the OS-specific config directory.
 */
function getConfigDir() {
    const platform = process.platform;
    if (platform === 'win32') {
        return join(env.APPDATA || join(homedir(), 'AppData', 'Roaming'), 'opencode');
    }
    const xdgConfig = env.XDG_CONFIG_HOME || join(homedir(), '.config');
    return join(xdgConfig, 'opencode');
}
/**
 * Returns the logs directory, creating it if needed.
 */
function getLogsDir(customLogDir) {
    const logsDir = customLogDir || join(getConfigDir(), 'antigravity-logs');
    try {
        // Debug logs can contain prompt/response bodies — keep them user-only.
        mkdirSync(logsDir, { recursive: true, mode: 0o700 });
    }
    catch {
        // Directory may already exist or we don't have permission
    }
    return logsDir;
}
/**
 * Builds a timestamped log file path that no live location already owns.
 */
function createLogFilePath(customLogDir) {
    const logsDir = getLogsDir(customLogDir);
    cleanupOldLogs(logsDir, 25);
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    let candidate = join(logsDir, `antigravity-debug-${timestamp}.log`);
    for (let suffix = 2; liveLogFilePaths.has(candidate); suffix++) {
        candidate = join(logsDir, `antigravity-debug-${timestamp}-${suffix}.log`);
    }
    return candidate;
}
/**
 * Cleans up old log files, keeping only the most recent maxFiles. Files a
 * live location is writing are never deleted.
 */
function cleanupOldLogs(logsDir, maxFiles) {
    try {
        const files = readdirSync(logsDir)
            .filter((file) => file.startsWith('antigravity-debug-') && file.endsWith('.log'))
            .map((file) => join(logsDir, file));
        if (files.length <= maxFiles) {
            return;
        }
        const sortedFiles = files
            .map((file) => ({
            file,
            mtime: statSync(file).mtimeMs,
        }))
            .sort((a, b) => b.mtime - a.mtime);
        for (let i = maxFiles; i < sortedFiles.length; i++) {
            const file = sortedFiles[i].file;
            if (liveLogFilePaths.has(file))
                continue;
            try {
                unlinkSync(file);
            }
            catch {
                // Ignore deletion errors
            }
        }
    }
    catch {
        // Ignore directory read errors
    }
}
/**
 * Creates a log writer function that writes to a file.
 */
function createLogWriter(filePath) {
    if (!filePath) {
        return { writer: () => { }, stream: null };
    }
    try {
        const stream = createWriteStream(filePath, { flags: 'a', mode: 0o600 });
        stream.on('error', () => { });
        liveLogFilePaths.add(filePath);
        return {
            stream,
            writer: (line) => {
                const timestamp = new Date().toISOString();
                const formatted = `[${timestamp}] ${line}`;
                stream.write(`${formatted}\n`);
            },
        };
    }
    catch {
        return { writer: () => { }, stream: null };
    }
}
/**
 * Derive debug state from the optional configuration plus the debug
 * environment variables; with no configuration, the environment variables
 * alone decide.
 */
function createDebugState(config) {
    if (!config) {
        const { debugEnabled } = deriveDebugPolicy({
            configDebug: false,
            configDebugTui: false,
            envDebugFlag: env.OPENCODE_ANTIGRAVITY_DEBUG,
            envDebugTuiFlag: env.OPENCODE_ANTIGRAVITY_DEBUG_TUI,
        });
        const debugTuiEnabled = isTruthyFlag(env.OPENCODE_ANTIGRAVITY_DEBUG_TUI);
        const logFilePath = debugEnabled ? createLogFilePath() : undefined;
        const { writer: logWriter, stream: logStream } = createLogWriter(logFilePath);
        return {
            debugEnabled,
            debugTuiEnabled,
            logFilePath,
            logWriter,
            logStream,
        };
    }
    // Config takes precedence, but env var can force enable for debugging
    const envDebugFlag = env.OPENCODE_ANTIGRAVITY_DEBUG ?? '';
    const { debugEnabled } = deriveDebugPolicy({
        configDebug: config.debug,
        configDebugTui: config.debug_tui,
        envDebugFlag,
        envDebugTuiFlag: env.OPENCODE_ANTIGRAVITY_DEBUG_TUI,
    });
    const debugTuiEnabled = config.debug_tui || isTruthyFlag(env.OPENCODE_ANTIGRAVITY_DEBUG_TUI);
    const logFilePath = debugEnabled
        ? createLogFilePath(config.log_dir)
        : undefined;
    const { writer: logWriter, stream: logStream } = createLogWriter(logFilePath);
    if (debugEnabled) {
        ensureGitignoreSync(getConfigDir());
    }
    return {
        debugEnabled,
        debugTuiEnabled,
        logFilePath,
        logWriter,
        logStream,
    };
}
/** Close a state's stream without waiting (state replacement path). */
function endDebugStream(state) {
    const current = state?.logStream;
    if (!current || !state)
        return;
    state.logStream = null;
    if (state.logFilePath)
        liveLogFilePaths.delete(state.logFilePath);
    try {
        current.end();
    }
    catch {
        // best-effort; the stream is already detached
    }
}
/**
 * Close a state's stream and resolve once all buffered writes have been
 * flushed to disk. Lines logged afterwards are dropped.
 */
function closeDebugStream(state) {
    const current = state?.logStream;
    if (!current || !state)
        return Promise.resolve();
    // Detach the reference so a later close or replacement won't double-close.
    state.logStream = null;
    state.logWriter = () => { };
    if (state.logFilePath)
        liveLogFilePaths.delete(state.logFilePath);
    return new Promise((resolve) => {
        current.once('close', () => resolve());
        current.once('error', () => resolve());
        try {
            current.end();
        }
        catch {
            resolve();
        }
    });
}
function createDebugHandle(readState, counter, closeState) {
    const logDebug = (line) => {
        readState().logWriter(line);
    };
    const runWithDebugEnabled = (action) => {
        if (!readState().debugEnabled)
            return;
        action();
    };
    return {
        isDebugEnabled: () => readState().debugEnabled,
        isDebugTuiEnabled: () => readState().debugTuiEnabled,
        getLogFilePath: () => readState().logFilePath,
        startAntigravityDebugRequest(meta) {
            const state = readState();
            if (!state.debugEnabled) {
                return null;
            }
            const id = `ANTIGRAVITY-${++counter.value}`;
            const method = meta.method ?? 'GET';
            logDebug(`[Antigravity Debug ${id}] pid=${process.pid} ${method} ${meta.resolvedUrl}`);
            if (meta.originalUrl && meta.originalUrl !== meta.resolvedUrl) {
                logDebug(`[Antigravity Debug ${id}] Original URL: ${meta.originalUrl}`);
            }
            if (meta.projectId) {
                logDebug(`[Antigravity Debug ${id}] Project: ${redactSensitive(meta.projectId)}`);
            }
            logDebug(`[Antigravity Debug ${id}] Streaming: ${meta.streaming ? 'yes' : 'no'}`);
            logDebug(`[Antigravity Debug ${id}] Headers: ${JSON.stringify(maskHeaders(meta.headers))}`);
            // The request body embeds raw project IDs — redact credential-shaped
            // fields before the verbatim preview hits the log.
            const bodyPreview = formatBodyPreviewForLog(redactBodyForLog(meta.body), MAX_BODY_PREVIEW_CHARS);
            if (bodyPreview) {
                logDebug(`[Antigravity Debug ${id}] Body Preview: ${bodyPreview}`);
            }
            return { id, streaming: meta.streaming, startedAt: Date.now() };
        },
        logAntigravityDebugResponse(context, response, meta = {}) {
            const state = readState();
            if (!state.debugEnabled || !context) {
                return;
            }
            const durationMs = Date.now() - context.startedAt;
            logDebug(`[Antigravity Debug ${context.id}] Response ${response.status} ${response.statusText} (${durationMs}ms)`);
            logDebug(`[Antigravity Debug ${context.id}] Response Headers: ${JSON.stringify(maskHeaders(meta.headersOverride ?? response.headers))}`);
            if (meta.note) {
                logDebug(`[Antigravity Debug ${context.id}] Note: ${meta.note}`);
            }
            if (meta.error) {
                logDebug(`[Antigravity Debug ${context.id}] Error: ${formatErrorForLog(meta.error)}`);
            }
            if (meta.body) {
                logDebug(`[Antigravity Debug ${context.id}] Response Body Preview: ${truncateTextForLog(meta.body, MAX_BODY_PREVIEW_CHARS)}`);
            }
        },
        logAccountContext(label, info) {
            runWithDebugEnabled(() => {
                const accountLabel = formatAccountContextLabel(info.email, info.index);
                const indexLabel = info.index >= 0
                    ? `${info.index + 1}/${info.totalAccounts}`
                    : `-/${info.totalAccounts}`;
                let rateLimitInfo = '';
                if (info.rateLimitState &&
                    Object.keys(info.rateLimitState).length > 0) {
                    const now = Date.now();
                    const activeRateLimits = {};
                    for (const [key, resetTime] of Object.entries(info.rateLimitState)) {
                        if (typeof resetTime === 'number' && resetTime > now) {
                            const remainingSec = Math.ceil((resetTime - now) / 1000);
                            activeRateLimits[key] = `${remainingSec}s`;
                        }
                    }
                    if (Object.keys(activeRateLimits).length > 0) {
                        rateLimitInfo = ` rateLimits=${JSON.stringify(activeRateLimits)}`;
                    }
                }
                logDebug(`[Account] ${label}: ${accountLabel} (${indexLabel}) family=${info.family}${rateLimitInfo}`);
            });
        },
        logRateLimitEvent(accountIndex, email, family, status, retryAfterMs, bodyInfo) {
            runWithDebugEnabled(() => {
                const accountLabel = formatAccountLabel(email, accountIndex);
                logDebug(`[RateLimit] ${status} on ${accountLabel} family=${family} retryAfterMs=${retryAfterMs}`);
                if (bodyInfo.message) {
                    logDebug(`[RateLimit] message: ${bodyInfo.message}`);
                }
                if (bodyInfo.quotaResetTime) {
                    logDebug(`[RateLimit] quotaResetTime: ${bodyInfo.quotaResetTime}`);
                }
                if (bodyInfo.retryDelayMs !== undefined &&
                    bodyInfo.retryDelayMs !== null) {
                    logDebug(`[RateLimit] body retryDelayMs: ${bodyInfo.retryDelayMs}`);
                }
                if (bodyInfo.reason) {
                    logDebug(`[RateLimit] reason: ${bodyInfo.reason}`);
                }
            });
        },
        logRateLimitSnapshot(family, accounts) {
            runWithDebugEnabled(() => {
                const now = Date.now();
                const entries = accounts.map((account) => {
                    const label = formatAccountLabel(account.email, account.index);
                    const reset = account.rateLimitResetTimes?.[family];
                    if (typeof reset !== 'number') {
                        return `${label}=ready`;
                    }
                    const remaining = Math.max(0, reset - now);
                    const seconds = Math.ceil(remaining / 1000);
                    return `${label}=wait ${seconds}s`;
                });
                logDebug(`[RateLimit] snapshot family=${family} ${entries.join(' | ')}`);
            });
        },
        async logResponseBody(context, response, status) {
            const state = readState();
            if (!state.debugEnabled || !context)
                return undefined;
            try {
                const text = await response.clone().text();
                const preview = truncateTextForLog(text, MAX_BODY_LOG_CHARS);
                logDebug(`[Antigravity Debug ${context.id}] Response Body (${status}): ${preview}`);
                return text;
            }
            catch (e) {
                logDebug(`[Antigravity Debug ${context.id}] Failed to read response body: ${formatErrorForLog(e)}`);
                return undefined;
            }
        },
        logModelFamily(url, extractedModel, family) {
            runWithDebugEnabled(() => {
                logDebug(`[ModelFamily] url=${url} model=${extractedModel ?? 'unknown'} family=${family}`);
            });
        },
        debugLogToFile(message) {
            runWithDebugEnabled(() => {
                logDebug(message);
            });
        },
        logToast(message, variant) {
            runWithDebugEnabled(() => {
                const variantLabel = variant.toUpperCase();
                logDebug(`[Toast/${variantLabel}] ${message}`);
            });
        },
        logRetryAttempt(attempt, maxAttempts, reason, delayMs) {
            runWithDebugEnabled(() => {
                const delayInfo = delayMs !== undefined ? ` delay=${delayMs}ms` : '';
                const maxInfo = maxAttempts < 0 ? '∞' : maxAttempts.toString();
                logDebug(`[Retry] Attempt ${attempt}/${maxInfo} reason=${reason}${delayInfo}`);
            });
        },
        logCacheStats(model, cacheReadTokens, cacheWriteTokens, totalInputTokens) {
            runWithDebugEnabled(() => {
                const cacheHitRate = totalInputTokens > 0
                    ? Math.round((cacheReadTokens / totalInputTokens) * 100)
                    : 0;
                const status = cacheReadTokens > 0 ? 'HIT' : cacheWriteTokens > 0 ? 'WRITE' : 'MISS';
                logDebug(`[Cache] ${status} model=${model} read=${cacheReadTokens} write=${cacheWriteTokens} total=${totalInputTokens} hitRate=${cacheHitRate}%`);
            });
        },
        logQuotaStatus(accountEmail, accountIndex, quotaPercent, family) {
            runWithDebugEnabled(() => {
                const accountLabel = formatAccountLabel(accountEmail, accountIndex);
                const familyInfo = family ? ` family=${family}` : '';
                const status = quotaPercent <= 0 ? 'EXHAUSTED' : quotaPercent < 20 ? 'LOW' : 'OK';
                logDebug(`[Quota] ${accountLabel} remaining=${quotaPercent.toFixed(1)}% status=${status}${familyInfo}`);
            });
        },
        logQuotaFetch(event, accountCount, details) {
            runWithDebugEnabled(() => {
                const countInfo = accountCount !== undefined ? ` accounts=${accountCount}` : '';
                const detailsInfo = details ? ` ${details}` : '';
                logDebug(`[QuotaFetch] ${event.toUpperCase()}${countInfo}${detailsInfo}`);
            });
        },
        logModelUsed(requestedModel, actualModel, accountEmail) {
            runWithDebugEnabled(() => {
                const accountInfo = accountEmail ? ` account=${accountEmail}` : '';
                if (requestedModel !== actualModel) {
                    logDebug(`[Model] requested=${requestedModel} actual=${actualModel}${accountInfo}`);
                }
                else {
                    logDebug(`[Model] ${actualModel}${accountInfo}`);
                }
            });
        },
        close: closeState,
    };
}
/**
 * Build one server location's debug sinks from its own configuration. The
 * handle owns its log file and request counter; it never reads or replaces
 * the OpenCode 1 module-level debug state below, and closing it leaves every
 * other location's file open.
 */
export function createLocationDebug(config) {
    const state = createDebugState(config);
    return createDebugHandle(() => state, { value: 0 }, () => closeDebugStream(state));
}
/**
 * Obscures sensitive headers and returns a plain object for logging.
 */
function maskHeaders(headers) {
    if (!headers) {
        return {};
    }
    const result = {};
    const SENSITIVE_HEADERS = new Set([
        'authorization',
        'x-api-key',
        'x-goog-api-key',
        'cookie',
        'set-cookie',
    ]);
    const parsed = headers instanceof Headers ? headers : new Headers(headers);
    parsed.forEach((value, key) => {
        if (SENSITIVE_HEADERS.has(key.toLowerCase())) {
            result[key] = '[redacted]';
        }
        else if (key.toLowerCase() === 'user-agent') {
            // Fingerprint User-Agent strings are stable identifiers that
            // could be replayed. Mask the body but keep the header shape
            // so the log still tells operators a UA was sent.
            result[key] = redactSensitive(value);
        }
        else {
            result[key] = value;
        }
    });
    return redactSensitiveFields(result);
}
// The existing module-level exported functions below share one module-level
// debug state, created from the environment on first use and replaced by
// `initializeDebug`. A handle from `createLocationDebug` is independent: it
// never reads or replaces this state.
let debugState = null;
const legacyRequestCounter = { value: 0 };
/**
 * Get the current OpenCode 1 debug state, initializing with defaults if
 * needed. This allows the module to work even before initializeDebug is
 * called.
 */
function getDebugState() {
    debugState ??= createDebugState(null);
    return debugState;
}
const legacyDebug = createDebugHandle(getDebugState, legacyRequestCounter, () => closeDebugLog());
/**
 * Close the OpenCode 1 debug log stream and resolve once all buffered writes
 * have been flushed to disk. Tests use this to wait deterministically for
 * log lines before reading the log file.
 */
export function closeDebugLog() {
    const state = debugState;
    const current = state?.logStream;
    if (!state || !current)
        return Promise.resolve();
    // Detach the reference so reinitialization won't double-close.
    state.logStream = null;
    if (state.logFilePath)
        liveLogFilePaths.delete(state.logFilePath);
    return new Promise((resolve) => {
        current.once('close', () => resolve());
        current.once('error', () => resolve());
        try {
            current.end();
        }
        catch {
            resolve();
        }
    });
}
/**
 * Initialize or reinitialize the OpenCode 1 debug state with the given
 * config. Call this once at plugin startup after loading config.
 */
export function initializeDebug(config) {
    // Close any previously opened log stream so re-initialized state
    // does not leak file descriptors (each open writeStream keeps the
    // process alive through its duplex pair).
    endDebugStream(debugState);
    debugState = createDebugState(config);
}
export function isDebugEnabled() {
    return legacyDebug.isDebugEnabled();
}
export function isDebugTuiEnabled() {
    return legacyDebug.isDebugTuiEnabled();
}
export function getLogFilePath() {
    return legacyDebug.getLogFilePath();
}
/**
 * Begins a debug trace for an Antigravity request.
 */
export function startAntigravityDebugRequest(meta) {
    return legacyDebug.startAntigravityDebugRequest(meta);
}
/**
 * Logs response details for a previously started debug trace.
 */
export function logAntigravityDebugResponse(context, response, meta = {}) {
    legacyDebug.logAntigravityDebugResponse(context, response, meta);
}
export function logAccountContext(label, info) {
    legacyDebug.logAccountContext(label, info);
}
export function logRateLimitEvent(accountIndex, email, family, status, retryAfterMs, bodyInfo) {
    legacyDebug.logRateLimitEvent(accountIndex, email, family, status, retryAfterMs, bodyInfo);
}
export function logRateLimitSnapshot(family, accounts) {
    legacyDebug.logRateLimitSnapshot(family, accounts);
}
export async function logResponseBody(context, response, status) {
    return legacyDebug.logResponseBody(context, response, status);
}
export function logModelFamily(url, extractedModel, family) {
    legacyDebug.logModelFamily(url, extractedModel, family);
}
export function debugLogToFile(message) {
    legacyDebug.debugLogToFile(message);
}
/**
 * Logs a toast message to the debug file.
 * This helps correlate what the user saw with debug events.
 */
export function logToast(message, variant) {
    legacyDebug.logToast(message, variant);
}
/**
 * Logs retry attempt information.
 * @param maxAttempts - Use -1 for unlimited retries
 */
export function logRetryAttempt(attempt, maxAttempts, reason, delayMs) {
    legacyDebug.logRetryAttempt(attempt, maxAttempts, reason, delayMs);
}
/**
 * Logs cache hit/miss information from response usage metadata.
 */
export function logCacheStats(model, cacheReadTokens, cacheWriteTokens, totalInputTokens) {
    legacyDebug.logCacheStats(model, cacheReadTokens, cacheWriteTokens, totalInputTokens);
}
/**
 * Logs quota status for an account.
 */
export function logQuotaStatus(accountEmail, accountIndex, quotaPercent, family) {
    legacyDebug.logQuotaStatus(accountEmail, accountIndex, quotaPercent, family);
}
/**
 * Logs background quota fetch events.
 */
export function logQuotaFetch(event, accountCount, details) {
    legacyDebug.logQuotaFetch(event, accountCount, details);
}
/**
 * Logs which model is being used for a request.
 */
export function logModelUsed(requestedModel, actualModel, accountEmail) {
    legacyDebug.logModelUsed(requestedModel, actualModel, accountEmail);
}
//# sourceMappingURL=debug.js.map