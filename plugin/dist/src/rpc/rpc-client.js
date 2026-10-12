// This client-only public entry point keeps server and writer modules out of
// the TUI's dependency graph. This file imports nothing else, not even types:
// the TUI build copies every relative module a file imports, type-only ones
// included, so importing `./protocol` here would bring the commands, store
// and fs modules into the TUI. The client is a raw JSON transport; the
// renderer builds and validates the menu shapes, and the server parses every
// apply request with the commands module before acting on it.
import { createRpcClient as createPublicRpcClient } from '../common-auth-embedded/rpc/client.js';
const DEFAULT_TIMEOUT_MS = 2_000;
const PENDING_FALLBACK = [];
export function createRpcClient(dir, expectedPid) {
    const client = createPublicRpcClient(dir, expectedPid, undefined, {
        exactPid: true,
    });
    return {
        async apply(request, options) {
            try {
                const result = await client.apply(request, options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
                return isRecord(result) && !isPublicApplyFailure(result)
                    ? result
                    : undefined;
            }
            catch {
                return undefined;
            }
        },
        async pendingNotifications(lastReceivedId, sessionId, options) {
            try {
                const messages = await client.pending(lastReceivedId, sessionId, options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
                return Array.isArray(messages) && messages.every(isNotification)
                    ? messages
                    : PENDING_FALLBACK;
            }
            catch {
                return PENDING_FALLBACK;
            }
        },
    };
}
function isRecord(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
// When an apply gets no answer (no server for the PID, a non-2xx status, a
// timeout or an unparseable body), the public client resolves the fixed
// object `{text: 'apply failed', knobs: {}}` instead of a server answer: the
// failure result of the older per-command dialogs, whose results were
// `{text, knobs}`. A menu result always carries `command`, `ok` and `menu`,
// so it cannot match.
function isPublicApplyFailure(value) {
    return (Object.keys(value).length === 2 &&
        value.text === 'apply failed' &&
        isRecord(value.knobs) &&
        Object.keys(value.knobs).length === 0);
}
const ENVELOPE_KEYS = new Set(['id', 'payload', 'sessionId']);
// Checks only the envelope: exactly the keys `id`, `payload` and optional
// `sessionId`. Any other key, such as the `type: 'open-dialog'` field of the
// older per-command dialog notifications, refuses the message.
function isNotification(value) {
    return (isRecord(value) &&
        Object.keys(value).every((key) => ENVELOPE_KEYS.has(key)) &&
        typeof value.id === 'number' &&
        Number.isSafeInteger(value.id) &&
        value.id >= 1 &&
        (value.sessionId === undefined || typeof value.sessionId === 'string') &&
        isRecord(value.payload));
}
//# sourceMappingURL=rpc-client.js.map