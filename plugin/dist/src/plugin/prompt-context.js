function isRecord(value) {
    return typeof value === 'object' && value !== null;
}
function extractMessages(response) {
    if (Array.isArray(response))
        return response;
    if (isRecord(response) && Array.isArray(response.data))
        return response.data;
    return [];
}
function getRole(message) {
    if (!isRecord(message) || !isRecord(message.info))
        return undefined;
    return typeof message.info.role === 'string' ? message.info.role : undefined;
}
function extractFromMessage(message) {
    if (!isRecord(message) || !isRecord(message.info))
        return null;
    const info = message.info;
    const modelInfo = isRecord(info.model) ? info.model : undefined;
    const agent = typeof info.agent === 'string' ? info.agent : undefined;
    const providerID = typeof modelInfo?.providerID === 'string'
        ? modelInfo.providerID
        : typeof info.providerID === 'string'
            ? info.providerID
            : undefined;
    const modelID = typeof modelInfo?.modelID === 'string'
        ? modelInfo.modelID
        : typeof info.modelID === 'string'
            ? info.modelID
            : undefined;
    const variant = typeof modelInfo?.variant === 'string'
        ? modelInfo.variant
        : typeof info.variant === 'string'
            ? info.variant
            : undefined;
    if (!agent && (!providerID || !modelID) && !variant)
        return null;
    const context = {};
    if (agent)
        context.agent = agent;
    if (providerID && modelID)
        context.model = { providerID, modelID };
    if (variant)
        context.variant = variant;
    return context;
}
function mergeContexts(base, patch) {
    return {
        agent: base.agent ?? patch.agent,
        model: base.model ?? patch.model,
        variant: base.variant ?? patch.variant,
    };
}
function isComplete(context) {
    return Boolean(context.agent && context.model && context.variant);
}
export async function resolvePromptContext(client, sessionId) {
    if (!client || !sessionId)
        return null;
    const typedClient = client;
    if (typeof typedClient.session?.messages !== 'function')
        return null;
    let messages = [];
    try {
        messages = extractMessages(await Promise.resolve(typedClient.session.messages({
            path: { id: sessionId },
            query: { limit: 100 },
        })));
    }
    catch {
        return null;
    }
    if (messages.length === 0)
        return null;
    let result = {};
    for (let index = messages.length - 1; index >= 0; index--) {
        if (getRole(messages[index]) !== 'assistant')
            continue;
        const context = extractFromMessage(messages[index]);
        if (!context)
            continue;
        result = mergeContexts(result, context);
        if (isComplete(result))
            return result;
    }
    for (let index = messages.length - 1; index >= 0; index--) {
        const context = extractFromMessage(messages[index]);
        if (!context)
            continue;
        result = mergeContexts(result, context);
        if (isComplete(result))
            return result;
    }
    if (!result.agent && !result.model && !result.variant)
        return null;
    return result;
}
//# sourceMappingURL=prompt-context.js.map