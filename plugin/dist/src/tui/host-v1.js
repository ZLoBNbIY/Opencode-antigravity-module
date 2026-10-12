import { jsx as _jsx } from "@opentui/solid/jsx-runtime";
import { createRpcClient } from '../rpc/rpc-client';
import { MenuRefusedError, openAntigravityMenu } from './command-dialogs';
import { parseMenuApplyResult, parseMenuDialogPayload, parseMenuNotifyPayload, } from './host-api';
/**
 * An apply can start an OAuth sign-in or check quota for every account, so
 * it gets the long timeout the account-add flow always had.
 */
export const V1_APPLY_TIMEOUT_MS = 120_000;
/**
 * Raised when an apply got no answer object: no server for this process,
 * a refusal or other non-2xx status, a timeout, or a body that is not JSON.
 */
export class V1TransportError extends Error {
    constructor() {
        super('Antigravity RPC gave no answer');
        this.name = 'V1TransportError';
    }
}
/**
 * The drawer's transport over the OpenCode 1 RPC client for the server in
 * `dir` belonging to process `pid` (exact PID; no fallback to another
 * process's server). Tests pass a client of their own.
 */
export function createV1MenuTransport(dir, pid, client = createRpcClient(dir, pid)) {
    return {
        pending: (cursor, sessionId) => client.pendingNotifications(cursor, sessionId),
        async apply(request, sessionId) {
            const raw = await client.apply({ ...request, ...(sessionId === undefined ? {} : { sessionId }) }, { timeoutMs: V1_APPLY_TIMEOUT_MS });
            if (raw === undefined)
                throw new V1TransportError();
            const parsed = parseMenuApplyResult(raw);
            if (!parsed.ok)
                throw new MenuRefusedError(parsed.issues);
            return parsed.value;
        },
    };
}
/** `MenuUi` over the OpenCode 1 dialog components. */
export function createV1MenuUi(api) {
    return {
        select(input) {
            return new Promise((resolve) => {
                const DialogSelect = (api.ui.DialogSelect);
                let settled = false;
                const settle = (value) => {
                    if (settled)
                        return;
                    settled = true;
                    resolve(value);
                };
                api.ui.dialog.setSize('xlarge');
                api.ui.dialog.replace(() => (_jsx(DialogSelect, { title: input.title, options: input.options.map((option) => ({ ...option })), ...(input.current === undefined
                        ? {}
                        : { current: input.current }), onSelect: (option) => settle(String(option.value)) })), () => settle(undefined));
            });
        },
        prompt(input) {
            return new Promise((resolve) => {
                const DialogPrompt = api.ui.DialogPrompt;
                let settled = false;
                const settle = (value) => {
                    if (settled)
                        return;
                    settled = true;
                    resolve(value);
                };
                const description = input.description;
                api.ui.dialog.setSize('xlarge');
                api.ui.dialog.replace(() => (_jsx(DialogPrompt, { title: input.title, ...(description
                        ? { description: () => _jsx("text", { children: description }) }
                        : {}), placeholder: input.placeholder ?? '', value: input.value ?? '', onConfirm: (value) => settle(value), onCancel: () => settle(undefined) })), () => settle(undefined));
            });
        },
        confirm(input) {
            return new Promise((resolve) => {
                const DialogConfirm = api.ui.DialogConfirm;
                let settled = false;
                const settle = (value) => {
                    if (settled)
                        return;
                    settled = true;
                    resolve(value);
                };
                api.ui.dialog.setSize('xlarge');
                api.ui.dialog.replace(() => (_jsx(DialogConfirm, { title: input.title, message: input.message, onConfirm: () => settle(true), onCancel: () => settle(false) })), () => settle(false));
            });
        },
        alert(input) {
            return new Promise((resolve) => {
                const DialogAlert = api.ui.DialogAlert;
                let settled = false;
                const settle = () => {
                    if (settled)
                        return;
                    settled = true;
                    resolve();
                };
                api.ui.dialog.setSize('xlarge');
                api.ui.dialog.replace(() => (_jsx(DialogAlert, { title: input.title, message: input.message, onConfirm: settle })), settle);
            });
        },
        toast(message, kind = 'info') {
            api.ui.toast({ message, variant: kind });
        },
        clear() {
            api.ui.dialog.clear();
        },
    };
}
/**
 * Handles one notification: a menu payload opens the drawer, a notify
 * payload is a toast, anything else (including the retired per-command
 * dialog payloads) is refused with a visible toast and a log line naming
 * only the failing fields.
 */
export function dispatchV1Notification(api, transport, notification, logger) {
    const menu = parseMenuDialogPayload(notification.payload);
    if (menu.ok) {
        const sessionId = notification.sessionId;
        void openAntigravityMenu({
            ui: createV1MenuUi(api),
            apply: (request) => transport.apply(request, sessionId),
            copy: (text) => api.renderer.copyToClipboardOSC52(text),
            onError: (message, detail) => logger.warn(message, detail),
        }, menu.value).catch((error) => {
            logger.warn('menu-drawer-failed', {
                error: error instanceof Error ? error.name : typeof error,
            });
        });
        return;
    }
    const notify = parseMenuNotifyPayload(notification.payload);
    if (notify.ok) {
        api.ui.toast({
            message: notify.value.notify.message,
            variant: notify.value.notify.kind,
        });
        return;
    }
    logger.warn('menu-payload-refused', { issues: menu.issues });
    api.ui.toast({
        message: 'Antigravity sent a dialog this TUI does not understand; update the plugin so server and TUI match.',
        variant: 'error',
    });
}
//# sourceMappingURL=host-v1.js.map