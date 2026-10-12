import { RpcRequestError, startRpcServer as startPublicRpcServer, } from '../common-auth-embedded/rpc/index.js';
export async function startRpcServer(options) {
    // JavaScript callers get no compile-time check for this required option.
    // Without the guard, a missing parser would only surface as a failure on
    // the first apply, after the server had started and published its port
    // file. Refuse before anything is created instead.
    if (typeof options.parseApplyRequest !== 'function') {
        throw new TypeError('startRpcServer needs parseApplyRequest from the common-auth commands module');
    }
    const parseApply = (value) => {
        const request = options.parseApplyRequest(value);
        if (request === undefined) {
            throw new RpcRequestError(400, 'Invalid apply request');
        }
        return request;
    };
    const server = await startPublicRpcServer({
        dir: options.dir,
        secureDir: true,
        // Do not set sweepRoot: this adapter manages no other project directories
        // or their RPC files.
        isManagedDir: () => false,
        receiptTimeoutMs: 2_000,
        applyDeadlineMs: 120_000,
        timeoutMs: 0,
        parsePending,
        apply: (async (request) => options.apply(parseApply(request))),
        // Use only the asynchronous overload, including for synchronous producers.
        drainAsync: (async (cursor, session) => Promise.resolve(options.drain(cursor, session))),
    });
    let stopping;
    return {
        port: server.port,
        token: server.token,
        stop() {
            stopping ??= server.stop();
            return stopping;
        },
    };
}
function isRecord(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function parsePending(value) {
    if (!isRecord(value) ||
        typeof value.lastReceivedId !== 'number' ||
        !Number.isSafeInteger(value.lastReceivedId) ||
        value.lastReceivedId < 0 ||
        (value.sessionId !== undefined && typeof value.sessionId !== 'string')) {
        throw new RpcRequestError(400, 'Invalid pending-notifications request');
    }
    return {
        lastReceivedId: value.lastReceivedId,
        ...(value.sessionId === undefined ? {} : { sessionId: value.sessionId }),
    };
}
//# sourceMappingURL=rpc-server.js.map