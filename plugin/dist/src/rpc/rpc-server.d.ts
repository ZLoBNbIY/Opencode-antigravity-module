import type * as Commands from '../common-auth-embedded/commands/index.js';
import type { CommandApplyRequest, CommandApplyResult, RpcNotification } from './protocol';
export interface StartRpcServerOptions {
    dir: string;
    /**
     * Use the `parseApplyRequest` of the same common-auth commands module that
     * built the menu `apply` runs against. Passing it in means this server
     * loads no second copy of the commands module and keeps no request schema
     * of its own. Every `/rpc/apply` body goes through this parser before
     * `apply` runs; a body the parser refuses is answered 400 and `apply` is
     * not called.
     */
    parseApplyRequest: typeof Commands.parseApplyRequest;
    /** Runs one parsed menu action and returns the refreshed menu. */
    apply(request: CommandApplyRequest): Promise<CommandApplyResult> | CommandApplyResult;
    drain(lastReceivedId: number, sessionId?: string): Promise<RpcNotification[]> | RpcNotification[];
}
export interface RpcServerHandle {
    port: number;
    token: string;
    stop(): Promise<void>;
}
export declare function startRpcServer(options: StartRpcServerOptions): Promise<RpcServerHandle>;
//# sourceMappingURL=rpc-server.d.ts.map