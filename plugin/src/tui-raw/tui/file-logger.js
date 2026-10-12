import {
  appendFileSync,
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  statSync,
  writeFileSync
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { createLoggerInstance } from "../common-auth-embedded/logger/index.js";
import { isProviderSecretKey } from "../logging/provider-key-policy.js";
const LOG_PREFIX = "[opencode-antigravity-auth/tui]", DEFAULT_MAX_BYTES = 1e6, MAX_KEEP_LINES = 200, FILE_MODE = 384;
export function resolveTuiLogPath() {
  const override = process.env.ANTIGRAVITY_AUTH_TUI_LOG_FILE;
  if (override && override.trim().length > 0)
    return override;
  const base = process.env.XDG_STATE_HOME || join(homedir(), ".local", "state");
  return join(base, "cortexkit", "antigravity-auth", "tui.log");
}
export function createTuiFileLogger(options) {
  const filePath = options?.filePath ?? resolveTuiLogPath(), maxBytes = options?.maxBytes ?? DEFAULT_MAX_BYTES;
  return createFileLogger({ filePath, maxBytes });
}
function createFileLogger(options) {
  const { filePath, maxBytes = DEFAULT_MAX_BYTES } = options, rotateIfNeeded = () => {
    try {
      if (!existsSync(filePath))
        return;
      if (statSync(filePath).size < maxBytes)
        return;
      const lines = readFileSync(filePath, "utf-8").split(`
`), keepFrom = Math.max(0, lines.length - MAX_KEEP_LINES), tail = lines.slice(keepFrom).join(`
`);
      writeFileSync(filePath, tail, "utf-8");
      chmodSync(filePath, FILE_MODE);
    } catch {}
  }, write = (level, message, extra) => {
    try {
      rotateIfNeeded();
      mkdirSync(dirname(filePath), { recursive: !0, mode: 448 });
      chmodSync(dirname(filePath), 448);
      const payload = {
        ts: Date.now(),
        level,
        message
      };
      if (extra && Object.keys(extra).length > 0)
        payload.extra = extra;
      appendFileSync(filePath, `${LOG_PREFIX} ${JSON.stringify(payload)}
`, {
        encoding: "utf-8",
        mode: FILE_MODE
      });
      chmodSync(filePath, FILE_MODE);
    } catch {}
  }, channel = createLoggerInstance({
    level: "debug",
    extraSecretKeys: isProviderSecretKey,
    captureSink: ({ level, message, data }) => {
      const extra = data !== null && typeof data === "object" && !Array.isArray(data) ? Object.fromEntries(Object.entries(data)) : void 0;
      write(level === "trace" ? "debug" : level, message, extra);
    }
  }).createLogger("antigravity.tui");
  return {
    debug: channel.debug,
    info: channel.info,
    warn: channel.warn,
    error: channel.error,
    getLogPath: () => filePath
  };
}
