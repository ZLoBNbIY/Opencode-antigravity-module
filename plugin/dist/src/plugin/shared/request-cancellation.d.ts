export interface RequestCancellation {
    readonly signal: AbortSignal;
    release(): void;
}
/** Keep caller and final-shutdown cancellation independent without requiring AbortSignal.any. */
export declare function createRequestCancellation(signals: readonly AbortSignal[]): RequestCancellation;
/** Headers do not end a request: keep cancellation alive until its body ends or is cancelled. */
export declare function retainResponseLifetime(response: Response, cancellation: RequestCancellation): Promise<{
    response: Response;
    settled: Promise<void>;
}>;
//# sourceMappingURL=request-cancellation.d.ts.map