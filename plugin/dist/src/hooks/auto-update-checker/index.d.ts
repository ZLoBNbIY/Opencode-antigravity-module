import type { AutoUpdateCheckerOptions } from './types';
interface PluginClient {
    tui: {
        showToast(options: {
            body: {
                title?: string;
                message: string;
                variant: 'info' | 'warning' | 'success' | 'error';
                duration?: number;
            };
        }): Promise<unknown>;
    };
}
interface SessionCreatedEvent {
    type: 'session.created';
    properties?: {
        info?: {
            parentID?: string;
        };
    };
}
type PluginEvent = SessionCreatedEvent | {
    type: string;
    properties?: unknown;
};
export declare function createAutoUpdateCheckerHook(client: PluginClient, directory: string, options?: AutoUpdateCheckerOptions): {
    event: ({ event }: {
        event: PluginEvent;
    }) => void;
};
export { invalidateCache, invalidatePackage } from './cache';
export { checkForUpdate, getCachedVersion, getLatestVersion } from './checker';
export type { AutoUpdateCheckerOptions, UpdateCheckResult } from './types';
//# sourceMappingURL=index.d.ts.map