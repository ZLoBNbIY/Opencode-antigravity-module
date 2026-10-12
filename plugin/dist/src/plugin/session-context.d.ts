import { type AgyRequestScope, type AgyRequestSessionContext, type AgyRequestSessionStoreOptions } from './agy-request-metadata';
export interface OpenCodeSessionIdentity {
    sessionId: string | null;
    parentSessionId: string | null;
}
export type AgySessionRegistryOptions = AgyRequestSessionStoreOptions;
export declare function extractOpenCodeSessionIdentity(headers?: HeadersInit): OpenCodeSessionIdentity;
export declare class AgySessionRegistry {
    private readonly requestSessions;
    private readonly parentSessionIds;
    constructor(directory: string, options?: AgySessionRegistryOptions);
    getOrCreate(identity: OpenCodeSessionIdentity): AgyRequestSessionContext;
    beginRequest(identity: OpenCodeSessionIdentity): AgyRequestScope;
    register(sessionId: string, parentSessionId?: string | null): void;
    getParentSessionId(sessionId: string): string | null;
    delete(sessionId: string): void;
    clear(): void;
    get size(): number;
    private recordParent;
    private pruneParentRelationships;
}
//# sourceMappingURL=session-context.d.ts.map