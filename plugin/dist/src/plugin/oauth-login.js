function expectedState(authorizationUrl) {
    try {
        return new URL(authorizationUrl).searchParams.get('state') ?? '';
    }
    catch {
        return '';
    }
}
function callbackParams(callbackUrl, expected) {
    const code = callbackUrl.searchParams.get('code');
    const state = callbackUrl.searchParams.get('state');
    if (!code || !state)
        throw new Error('Missing code or state in callback URL');
    if (expected && state !== expected)
        throw new Error('OAuth state mismatch');
    return { code, state };
}
export async function performOAuthLogin(request, deps) {
    const listener = await deps.startListener();
    try {
        const authorization = await deps.authorize(request.projectId ?? '');
        if (!request.noBrowser && !request.isHeadless) {
            await deps.openBrowser(authorization.url);
        }
        const params = callbackParams(await listener.waitForCallback(), expectedState(authorization.url));
        const result = await deps.exchange(params.code, params.state);
        if (result.type === 'failed')
            throw new Error(result.error);
        await deps.upsert(result);
        request.accounts.push(result);
        return result;
    }
    finally {
        await listener.close().catch(() => { });
    }
}
//# sourceMappingURL=oauth-login.js.map