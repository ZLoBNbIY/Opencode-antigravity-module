export declare const GEMINI_DUMP_COMMAND_NAME = "gemini-dump";
export type GeminiDumpCommandAction = {
    type: 'status';
} | {
    type: 'enable';
} | {
    type: 'disable';
} | {
    type: 'usage';
};
export interface GeminiDumpContext {
    id: string;
    files: {
        request: string;
        response: string;
        metadata: string;
    };
    metadata: Record<string, unknown>;
}
export interface GeminiDumpRequestInput {
    originalUrl: string;
    resolvedUrl: string;
    method?: string;
    headers?: HeadersInit | Headers;
    body?: BodyInit | null;
    streaming: boolean;
    requestedModel?: string;
    effectiveModel?: string;
    sessionId?: string;
    projectId?: string;
}
/**
 * One location's dump switch. `/gemini-dump on` in one location never
 * enables dumping for another, and each location's requests consult only
 * their own switch.
 */
export interface GeminiDumpState {
    isEnabled(): boolean;
    setEnabled(enabled: boolean): void;
    /** Dump a request when this location's switch is on; null otherwise. */
    dumpRequest(input: GeminiDumpRequestInput): GeminiDumpContext | null;
    /** Status text reflecting this location's switch unless `enabled` is given. */
    buildStatusSummary(input?: {
        enabled?: boolean;
    }): string;
    /** Command reply reflecting this location's switch unless `enabled` is given. */
    executeCommand(input: {
        argumentsText: string;
        enabled?: boolean;
    }): string;
}
/** Build one location's dump switch, defaulting to the environment flag. */
export declare function createGeminiDumpState(options?: {
    enabled?: boolean;
}): GeminiDumpState;
export declare function isGeminiDumpEnabled(): boolean;
export declare function setGeminiDumpEnabled(enabled: boolean): void;
export declare function resetGeminiDumpState(): void;
export declare function getGeminiDumpDirectory(): string;
export declare function parseGeminiDumpCommandAction(argumentsText: string): GeminiDumpCommandAction;
export declare function buildGeminiDumpStatusSummary(input?: {
    enabled?: boolean;
}): string;
export declare function executeGeminiDumpCommand(input: {
    argumentsText: string;
    enabled?: boolean;
}): string;
export declare function dumpGeminiRequest(input: GeminiDumpRequestInput): GeminiDumpContext | null;
export declare function noteGeminiDumpResponse(context: GeminiDumpContext | null | undefined, response: Pick<Response, 'status' | 'statusText' | 'headers'>): void;
export declare function appendGeminiDumpResponseText(context: GeminiDumpContext | null | undefined, text: string): void;
export declare function createGeminiDumpResponseTransform(context: GeminiDumpContext | null | undefined): TransformStream<Uint8Array, Uint8Array> | null;
//# sourceMappingURL=gemini-dump.d.ts.map