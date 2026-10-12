export function isTruthyFlag(flag) {
    return flag === '1' || flag?.toLowerCase() === 'true';
}
export function parseDebugLevel(flag) {
    const trimmed = flag.trim();
    if (trimmed === '2' || trimmed === 'verbose')
        return 2;
    if (trimmed === '1' || trimmed === 'true')
        return 1;
    return 0;
}
export function deriveDebugPolicy(input) {
    const envDebugFlag = input.envDebugFlag ?? '';
    const debugLevel = input.configDebug
        ? envDebugFlag === '2' || envDebugFlag === 'verbose'
            ? 2
            : 1
        : parseDebugLevel(envDebugFlag);
    const debugEnabled = debugLevel >= 1;
    const verboseEnabled = debugLevel >= 2;
    const debugTuiEnabled = debugEnabled &&
        (input.configDebugTui || isTruthyFlag(input.envDebugTuiFlag));
    return {
        debugLevel,
        debugEnabled,
        debugTuiEnabled,
        verboseEnabled,
    };
}
export function formatAccountLabel(email, accountIndex) {
    return email || `Account ${accountIndex + 1}`;
}
export function formatAccountContextLabel(email, accountIndex) {
    if (email) {
        return email;
    }
    if (accountIndex >= 0) {
        return `Account ${accountIndex + 1}`;
    }
    return 'All accounts';
}
export function formatErrorForLog(error) {
    if (error instanceof Error) {
        return error.stack ?? error.message;
    }
    try {
        return JSON.stringify(error);
    }
    catch {
        return String(error);
    }
}
export function truncateTextForLog(text, maxChars) {
    if (text.length <= maxChars) {
        return text;
    }
    return `${text.slice(0, maxChars)}... (truncated ${text.length - maxChars} chars)`;
}
export function formatBodyPreviewForLog(body, maxChars) {
    if (body == null) {
        return undefined;
    }
    if (typeof body === 'string') {
        return truncateTextForLog(body, maxChars);
    }
    if (body instanceof URLSearchParams) {
        return truncateTextForLog(body.toString(), maxChars);
    }
    if (typeof Blob !== 'undefined' && body instanceof Blob) {
        return `[Blob size=${body.size}]`;
    }
    if (typeof FormData !== 'undefined' && body instanceof FormData) {
        return '[FormData payload omitted]';
    }
    return `[${body.constructor?.name ?? typeof body} payload omitted]`;
}
export function writeConsoleLog(level, ...args) {
    switch (level) {
        case 'debug':
            console.debug(...args);
            break;
        case 'info':
            console.info(...args);
            break;
        case 'warn':
            console.warn(...args);
            break;
        case 'error':
            console.error(...args);
            break;
    }
}
/**
 * Mask all but the first 4 and last 4 characters of `value`. A short
 * value (≤ 8 chars) is masked entirely so the caller never leaks a
 * full identifier. Empty / non-string inputs collapse to an empty
 * marker so a debug line that ran the helper cannot accidentally
 * surface the original value.
 *
 * Pattern matches the `${start}****${end}` shape used by metrics teams
 * for opaque resource IDs; the implementation is intentionally simple
 * so a quick visual scan of a debug log still tells operators what
 * class of identifier they are looking at.
 */
export function redactSensitive(value) {
    if (typeof value !== 'string' || value.length === 0)
        return '';
    if (value.length <= 8)
        return '****';
    return `${value.slice(0, 4)}****${value.slice(-4)}`;
}
/**
 * Field-name pattern that flags a key as carrying a credential or
 * identifier. Matched case-insensitively against any JSON-like object
 * key the debug sink walks. `project` (not just `projectId`) so bare
 * `project` / `managedProjectId` request-body fields are masked too —
 * project IDs are account-correlating identifiers.
 */
const SENSITIVE_FIELD_PATTERN = /token|refresh|access|project|fingerprint|deviceId|sessionId|sessionToken|secret|password|apiKey|clientSecret/i;
/**
 * Walk a JSON-like value and redact every credential-shaped field.
 * Returns a NEW value — the original is never mutated. Strings inside
 * arrays are left untouched; only object keys whose name matches the
 * sensitive pattern have their string values masked.
 */
export function redactSensitiveFields(value) {
    if (value == null)
        return value;
    if (Array.isArray(value))
        return value.map(redactSensitiveFields);
    if (typeof value === 'object') {
        const record = value;
        const redacted = {};
        for (const [key, entry] of Object.entries(record)) {
            if (SENSITIVE_FIELD_PATTERN.test(key) && typeof entry === 'string') {
                redacted[key] = redactSensitive(entry);
            }
            else {
                redacted[key] = redactSensitiveFields(entry);
            }
        }
        return redacted;
    }
    return value;
}
/**
 * Redact credential-shaped fields (project IDs, tokens, …) out of a
 * serialized JSON request body. Returns the input untouched when it is
 * not parseable JSON or not an object/array — unstructured bodies have
 * no field names to key redaction off.
 */
export function redactJsonBodyString(body) {
    let parsed;
    try {
        parsed = JSON.parse(body);
    }
    catch {
        return body;
    }
    if (parsed == null || typeof parsed !== 'object')
        return body;
    return JSON.stringify(redactSensitiveFields(parsed));
}
/**
 * Redact a request body before it reaches a debug log or dump file.
 * String bodies are treated as JSON and field-redacted; every other
 * `BodyInit` shape passes through (those are summarized, not printed
 * verbatim, by the log formatters).
 */
export function redactBodyForLog(body) {
    if (typeof body === 'string')
        return redactJsonBodyString(body);
    return body;
}
//# sourceMappingURL=logging-utils.js.map