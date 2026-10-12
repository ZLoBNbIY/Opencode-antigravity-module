/** @jsxImportSource @opentui/solid */
/**
 * OpenCode 1 adapter for the shared `/antigravity` drawer.
 *
 * Two jobs, both specific to OpenCode 1:
 *
 * - Transport: the plugin's own OpenCode 1 RPC client (`rpc/rpc-client`),
 *   which talks only to the loopback server published for this process's
 *   PID and checks each queued notification's envelope (`id`, `payload`,
 *   `sessionId`). The payloads and every apply answer are still unchecked
 *   JSON there; this adapter validates them with the host-api parsers before
 *   the drawer sees anything.
 * - Dialogs: `MenuUi` over the host's `DialogSelect`, `DialogPrompt`,
 *   `DialogConfirm` and `DialogAlert`, mounted through `dialog.replace`.
 *
 * The sidebar keeps reading the redacted sidebar snapshot file in
 * `tui.tsx`; nothing here reads account storage, tokens or OAuth state.
 */
import type { TuiPluginApi } from '@opencode-ai/plugin/tui';
import { type RpcClient } from '../rpc/rpc-client';
import type { TuiLogger } from './file-logger';
import { type MenuApplyRequest, type MenuApplyResult, type MenuUi } from './host-api';
/**
 * An apply can start an OAuth sign-in or check quota for every account, so
 * it gets the long timeout the account-add flow always had.
 */
export declare const V1_APPLY_TIMEOUT_MS = 120000;
/** One queued notification as the OpenCode 1 RPC returns it. */
export interface V1Notification {
    readonly id: number;
    readonly payload: unknown;
    readonly sessionId?: string;
}
export interface V1MenuTransport {
    pending(cursor: number, sessionId: string | undefined): Promise<V1Notification[]>;
    apply(request: MenuApplyRequest, sessionId: string | undefined): Promise<MenuApplyResult>;
}
/**
 * Raised when an apply got no answer object: no server for this process,
 * a refusal or other non-2xx status, a timeout, or a body that is not JSON.
 */
export declare class V1TransportError extends Error {
    constructor();
}
/**
 * The drawer's transport over the OpenCode 1 RPC client for the server in
 * `dir` belonging to process `pid` (exact PID; no fallback to another
 * process's server). Tests pass a client of their own.
 */
export declare function createV1MenuTransport(dir: string, pid: number, client?: RpcClient): V1MenuTransport;
/** `MenuUi` over the OpenCode 1 dialog components. */
export declare function createV1MenuUi(api: TuiPluginApi): MenuUi;
/**
 * Handles one notification: a menu payload opens the drawer, a notify
 * payload is a toast, anything else (including the retired per-command
 * dialog payloads) is refused with a visible toast and a log line naming
 * only the failing fields.
 */
export declare function dispatchV1Notification(api: TuiPluginApi, transport: V1MenuTransport, notification: V1Notification, logger: TuiLogger): void;
//# sourceMappingURL=host-v1.d.ts.map