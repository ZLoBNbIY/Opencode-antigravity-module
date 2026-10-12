import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { AgyRequestSessionStore, } from './agy-request-metadata';
const FALLBACK_SESSION_KEY = '__default__';
export function extractOpenCodeSessionIdentity(headers) {
    const normalized = new Headers(headers);
    return {
        sessionId: normalized.get('x-session-affinity') ??
            normalized.get('x-opencode-session-id') ??
            normalized.get('x-session-id'),
        parentSessionId: normalized.get('x-opencode-parent-session-id') ??
            normalized.get('x-parent-session-id'),
    };
}
export class AgySessionRegistry {
    requestSessions;
    parentSessionIds = new Map();
    constructor(directory, options = {}) {
        const workspaceUri = directory ? pathToFileURL(resolve(directory)).href : '';
        this.requestSessions = new AgyRequestSessionStore(workspaceUri, options);
    }
    getOrCreate(identity) {
        const key = identity.sessionId ?? FALLBACK_SESSION_KEY;
        const request = this.requestSessions.getOrCreate(key);
        this.recordParent(key, identity.parentSessionId);
        this.pruneParentRelationships();
        return request;
    }
    beginRequest(identity) {
        const key = identity.sessionId ?? FALLBACK_SESSION_KEY;
        const scope = this.requestSessions.beginRequest(key);
        this.recordParent(key, identity.parentSessionId);
        this.pruneParentRelationships();
        return scope;
    }
    register(sessionId, parentSessionId = null) {
        this.getOrCreate({ sessionId, parentSessionId });
    }
    getParentSessionId(sessionId) {
        if (!this.requestSessions.has(sessionId)) {
            this.parentSessionIds.delete(sessionId);
            return null;
        }
        return this.parentSessionIds.get(sessionId) ?? null;
    }
    delete(sessionId) {
        this.requestSessions.delete(sessionId);
        this.parentSessionIds.delete(sessionId);
    }
    clear() {
        this.requestSessions.clear();
        this.parentSessionIds.clear();
    }
    get size() {
        return this.requestSessions.size;
    }
    recordParent(key, parentSessionId) {
        if (parentSessionId || !this.parentSessionIds.has(key)) {
            this.parentSessionIds.set(key, parentSessionId);
        }
    }
    pruneParentRelationships() {
        for (const sessionId of this.parentSessionIds.keys()) {
            if (!this.requestSessions.has(sessionId)) {
                this.parentSessionIds.delete(sessionId);
            }
        }
    }
}
//# sourceMappingURL=session-context.js.map