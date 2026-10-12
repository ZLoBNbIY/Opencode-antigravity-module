export interface RpcRequestOptions {
    timeoutMs?: number;
}
/**
 * The wire envelope of one queued notification, after this client's check:
 * exactly `{id, payload, sessionId?}`, with `payload` a JSON object. `payload` is still unchecked JSON; the
 * renderer must validate it as a menu or notify payload before showing
 * anything from it.
 */
export interface ReceivedNotification {
    id: number;
    payload: object;
    sessionId?: string;
}
export interface RpcClient {
    /**
     * Sends one menu action, given as the JSON object the renderer built (a
     * `CommandApplyRequest`); the server parses it and refuses anything else
     * with 400. Resolves the server's answer as unchecked JSON, which the
     * renderer must validate as a `CommandApplyResult` before using it, or
     * `undefined` when there was no answer object: no server published
     * for `expectedPid` (the process ID of the OpenCode process hosting the
     * server), a refusal or other non-2xx status, a timeout, or a body that is
     * not a JSON object.
     */
    apply(request: unknown, options?: RpcRequestOptions): Promise<object | undefined>;
    /**
     * Notifications after `lastReceivedId`. Resolves `[]` when the call fails
     * or when any message in the answer has a malformed envelope.
     */
    pendingNotifications(lastReceivedId: number, sessionId?: string, options?: RpcRequestOptions): Promise<ReceivedNotification[]>;
}
export declare function createRpcClient(dir: string, expectedPid?: number): RpcClient;
//# sourceMappingURL=rpc-client.d.ts.map