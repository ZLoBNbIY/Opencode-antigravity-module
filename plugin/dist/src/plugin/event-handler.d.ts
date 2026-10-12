import type { AntigravityConfig } from './config';
import type { Logger } from './logger';
import type { PluginClient } from './types';
type EventInput = {
    event: {
        type: string;
        properties?: unknown;
    };
};
type SessionSummary = {
    durationMinutes: number;
    totalClaude: number;
    totalGemini: number;
    requestsPerHour: number;
    accountsUsed: number;
};
type EventAccountManager = {
    getSessionSummary(): SessionSummary;
    deleteSessionState(sessionId: string): void;
};
type EventLifecycle = {
    getAccountManager(): EventAccountManager | null;
};
type EventSessionRegistry = {
    register(sessionId: string, parentSessionId: string | null): void;
    delete(sessionId: string): void;
    getParentSessionId(sessionId: string): string | null;
};
type EventSessionRecovery = {
    isRecoverableError(error: unknown): boolean;
    handleSessionRecovery(info: {
        id?: string;
        role: 'assistant';
        sessionID?: string;
        error: unknown;
    }): Promise<boolean>;
};
type EventUpdateChecker = {
    event(input: EventInput): void | Promise<void>;
};
export interface CreateEventHandlerOptions {
    client: PluginClient;
    config: Pick<AntigravityConfig, 'auto_resume' | 'resume_text' | 'toast_scope'>;
    directory: string;
    lifecycle: EventLifecycle;
    sessionRegistry: EventSessionRegistry;
    sessionRecovery: EventSessionRecovery | null;
    updateChecker: EventUpdateChecker;
    logger: Pick<Logger, 'debug'>;
}
export declare function createEventHandler({ client, config, directory, lifecycle, sessionRegistry, sessionRecovery, updateChecker, logger, }: CreateEventHandlerOptions): (input: EventInput) => Promise<void>;
export {};
//# sourceMappingURL=event-handler.d.ts.map