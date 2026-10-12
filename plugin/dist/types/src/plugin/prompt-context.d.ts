/**
 * Resolve prompt context for synthetic OpenCode user messages.
 *
 * OpenCode records ignored/noReply prompt messages. If a plugin sends one
 * without the active model/variant, the next prompt can inherit the default
 * model and unexpectedly switch providers. Preserve the latest prompt context
 * for hidden slash-command replies.
 */
export interface ResolvedPromptContext {
    agent?: string;
    model?: {
        providerID: string;
        modelID: string;
    };
    variant?: string;
}
export declare function resolvePromptContext(client: unknown, sessionId: string): Promise<ResolvedPromptContext | null>;
//# sourceMappingURL=prompt-context.d.ts.map