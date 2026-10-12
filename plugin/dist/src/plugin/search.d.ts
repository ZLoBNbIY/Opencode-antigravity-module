export interface SearchArgs {
    query: string;
    urls?: string[];
    thinking?: boolean;
}
export interface SearchResult {
    text: string;
    sources: Array<{
        title: string;
        url: string;
    }>;
    searchQueries: string[];
    urlsRetrieved: Array<{
        url: string;
        status: string;
    }>;
}
/**
 * Execute a Google Search using the Gemini grounding API.
 *
 * This makes a SEPARATE API call with only googleSearch/urlContext tools,
 * which is required because these tools cannot be combined with function declarations.
 */
export declare function executeSearch(args: SearchArgs, accessToken: string, projectId: string, abortSignal?: AbortSignal): Promise<string>;
//# sourceMappingURL=search.d.ts.map