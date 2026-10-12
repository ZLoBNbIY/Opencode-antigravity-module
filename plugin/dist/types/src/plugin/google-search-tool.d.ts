import type { GetAuth, PluginClient, PluginTool } from './types.js';
type GoogleSearchAuthLoader = () => Promise<Awaited<ReturnType<GetAuth>> | null | undefined>;
export declare function createGoogleSearchTool({ getAuth, client, providerId, mayStartLocalWork, }: {
    mayStartLocalWork?: () => Promise<boolean>;
    getAuth: GoogleSearchAuthLoader;
    client: PluginClient;
    providerId: string;
}): PluginTool;
export {};
//# sourceMappingURL=google-search-tool.d.ts.map