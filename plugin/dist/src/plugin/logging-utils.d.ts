export type LogLevel = 'debug' | 'info' | 'warn' | 'error';
export interface DebugPolicyInput {
    configDebug: boolean;
    configDebugTui: boolean;
    envDebugFlag?: string;
    envDebugTuiFlag?: string;
}
export interface DebugPolicy {
    debugLevel: number;
    debugEnabled: boolean;
    debugTuiEnabled: boolean;
    verboseEnabled: boolean;
}
export declare function isTruthyFlag(flag?: string): boolean;
export declare function parseDebugLevel(flag: string): number;
export declare function deriveDebugPolicy(input: DebugPolicyInput): DebugPolicy;
export declare function formatAccountLabel(email: string | undefined, accountIndex: number): string;
export declare function formatAccountContextLabel(email: string | undefined, accountIndex: number): string;
export declare function formatErrorForLog(error: unknown): string;
export declare function truncateTextForLog(text: string, maxChars: number): string;
export declare function formatBodyPreviewForLog(body: BodyInit | null | undefined, maxChars: number): string | undefined;
export declare function writeConsoleLog(level: LogLevel, ...args: unknown[]): void;
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
export declare function redactSensitive(value: string | undefined | null): string;
/**
 * Walk a JSON-like value and redact every credential-shaped field.
 * Returns a NEW value — the original is never mutated. Strings inside
 * arrays are left untouched; only object keys whose name matches the
 * sensitive pattern have their string values masked.
 */
export declare function redactSensitiveFields(value: unknown): unknown;
/**
 * Redact credential-shaped fields (project IDs, tokens, …) out of a
 * serialized JSON request body. Returns the input untouched when it is
 * not parseable JSON or not an object/array — unstructured bodies have
 * no field names to key redaction off.
 */
export declare function redactJsonBodyString(body: string): string;
/**
 * Redact a request body before it reaches a debug log or dump file.
 * String bodies are treated as JSON and field-redacted; every other
 * `BodyInit` shape passes through (those are summarized, not printed
 * verbatim, by the log formatters).
 */
export declare function redactBodyForLog(body: BodyInit | null | undefined): BodyInit | null | undefined;
//# sourceMappingURL=logging-utils.d.ts.map