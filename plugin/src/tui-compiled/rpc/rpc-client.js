import { createRpcClient as createPublicRpcClient } from "../common-auth-embedded/rpc/client.js";
const DEFAULT_TIMEOUT_MS = 2000, PENDING_FALLBACK = [];
export function createRpcClient(dir, expectedPid) {
  const client = createPublicRpcClient(dir, expectedPid, void 0, {
    exactPid: !0
  });
  return {
    async apply(request, options) {
      try {
        const result = await client.apply(request, options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
        return isRecord(result) && !isPublicApplyFailure(result) ? result : void 0;
      } catch {
        return;
      }
    },
    async pendingNotifications(lastReceivedId, sessionId, options) {
      try {
        const messages = await client.pending(lastReceivedId, sessionId, options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
        return Array.isArray(messages) && messages.every(isNotification) ? messages : PENDING_FALLBACK;
      } catch {
        return PENDING_FALLBACK;
      }
    }
  };
}
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isPublicApplyFailure(value) {
  return Object.keys(value).length === 2 && value.text === "apply failed" && isRecord(value.knobs) && Object.keys(value.knobs).length === 0;
}
const ENVELOPE_KEYS = new Set(["id", "payload", "sessionId"]);
function isNotification(value) {
  return isRecord(value) && Object.keys(value).every((key) => ENVELOPE_KEYS.has(key)) && typeof value.id === "number" && Number.isSafeInteger(value.id) && value.id >= 1 && (value.sessionId === void 0 || typeof value.sessionId === "string") && isRecord(value.payload);
}
