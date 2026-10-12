import { randomUUID } from "node:crypto";
import { watch } from "node:fs";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";
import {
  clearTimeout as nativeClearTimeout,
  setTimeout as nativeSetTimeout
} from "node:timers";
import { acquireFencedFileLock } from "@cortexkit/antigravity-auth-core/file-lock";
import { applyEdits, modify, parse } from "jsonc-parser";
export const TUI_PREFS_FILE_ENV = "OPENCODE_TUI_PREFERENCES_FILE";
const FILE_NAME = "tui-preferences.jsonc", PREFERENCES_LOCK_NAME = "preferences", PREFERENCES_LOCK_TTL_MS = 1e4, PREFERENCES_LOCK_TIMEOUT_MS = 2000, PREFERENCES_LOCK_RETRY_MS = 25;
export function getTuiPreferencesFile() {
  const override = process.env[TUI_PREFS_FILE_ENV];
  if (override)
    return override;
  const configDir = process.env.OPENCODE_CONFIG_DIR || join(process.env.XDG_CONFIG_HOME || join(homedir(), ".config"), "opencode");
  return join(configDir, FILE_NAME);
}
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
export async function readTuiPreferencesFile() {
  try {
    const raw = await readFile(getTuiPreferencesFile(), "utf8"), errors = [], root = parse(raw, errors, { allowTrailingComma: !0 });
    if (errors.length > 0)
      return {};
    return isRecord(root) ? root : {};
  } catch {
    return {};
  }
}
export const PLUGIN_KEY = "antigravity-auth", DEFAULT_SLOT_ORDER = 160, DEFAULT_PREFS = {
  forceToTop: !1,
  order: DEFAULT_SLOT_ORDER,
  startCollapsed: !1,
  rememberCollapsed: !0,
  collapsed: null,
  pollMs: 1500,
  refreshDebounceMs: 200,
  header: { label: "ANTIGRAVITY", showVersion: !0 },
  sections: {
    quota: !0,
    fallbackAccounts: !0,
    routing: !0,
    health: !0
  },
  appearance: {
    barWidth: 10,
    barFilledChar: "\u2588",
    barEmptyChar: "\u2591",
    warnThreshold: 50,
    errorThreshold: 80
  }
};
function bool(value, fallback) {
  return typeof value === "boolean" ? value : fallback;
}
function int(value, fallback, min, max) {
  if (typeof value !== "number" || !Number.isFinite(value))
    return fallback;
  return Math.min(Math.max(Math.round(value), min), max);
}
function label(value, fallback, maxLength) {
  if (typeof value !== "string" || value.length === 0)
    return fallback;
  return value.slice(0, maxLength);
}
function char(value, fallback) {
  if (typeof value !== "string")
    return fallback;
  return [...value][0] ?? fallback;
}
export function resolveAntigravityAuthPrefs(root) {
  const entry = root[PLUGIN_KEY];
  if (!isRecord(entry))
    return structuredClone(DEFAULT_PREFS);
  const d = DEFAULT_PREFS, header = isRecord(entry.header) ? entry.header : {}, sections = isRecord(entry.sections) ? entry.sections : {}, appearance = isRecord(entry.appearance) ? entry.appearance : {}, configuredWarnThreshold = int(appearance.warnThreshold, d.appearance.warnThreshold, 0, 99), configuredErrorThreshold = int(appearance.errorThreshold, d.appearance.errorThreshold, 0, 100), [warnThreshold, errorThreshold] = configuredErrorThreshold < configuredWarnThreshold ? [100 - configuredWarnThreshold, 100 - configuredErrorThreshold] : [
    configuredWarnThreshold,
    Math.max(configuredErrorThreshold, Math.min(configuredWarnThreshold + 1, 100))
  ];
  return {
    forceToTop: bool(entry.forceToTop, d.forceToTop),
    order: int(entry.order, d.order, -1e4, 1e4),
    startCollapsed: bool(entry.startCollapsed, d.startCollapsed),
    rememberCollapsed: bool(entry.rememberCollapsed, d.rememberCollapsed),
    collapsed: typeof entry.collapsed === "boolean" ? entry.collapsed : null,
    pollMs: int(entry.pollMs, d.pollMs, 500, 30000),
    refreshDebounceMs: int(entry.refreshDebounceMs, d.refreshDebounceMs, 50, 5000),
    header: {
      label: label(header.label, d.header.label, 20),
      showVersion: bool(header.showVersion, d.header.showVersion)
    },
    sections: {
      quota: bool(sections.quota, d.sections.quota),
      fallbackAccounts: bool(sections.fallbackAccounts, d.sections.fallbackAccounts),
      routing: bool(sections.routing, d.sections.routing),
      health: bool(sections.health, d.sections.health)
    },
    appearance: {
      barWidth: int(appearance.barWidth, d.appearance.barWidth, 4, 40),
      barFilledChar: char(appearance.barFilledChar, d.appearance.barFilledChar),
      barEmptyChar: char(appearance.barEmptyChar, d.appearance.barEmptyChar),
      warnThreshold,
      errorThreshold
    }
  };
}
const FORCE_TOP_BASE = -1e5;
export function computeEffectiveOrder(root, pluginKey, defaultOrder) {
  const entry = root[pluginKey];
  if (!isRecord(entry))
    return defaultOrder;
  if (entry.forceToTop === !0)
    return FORCE_TOP_BASE + Object.keys(root).indexOf(pluginKey);
  return int(entry.order, defaultOrder, -1e4, 1e4);
}
const TEMPLATE = `// Shared preferences for opencode TUI plugins.
// One top-level key per plugin (short name). See each plugin's README for
// its supported settings. This file is safe to hand-edit; plugins update
// individual keys in place and preserve comments.
{}
`;
async function acquirePreferencesLock(file) {
  const deadline = Date.now() + PREFERENCES_LOCK_TIMEOUT_MS;
  for (;; ) {
    const lock = await acquireFencedFileLock({
      path: file,
      name: PREFERENCES_LOCK_NAME,
      ttlMs: PREFERENCES_LOCK_TTL_MS,
      renew: !0
    });
    if (lock)
      return lock;
    if (Date.now() >= deadline)
      throw Error(`Timed out acquiring TUI preferences lock: ${file}`);
    await new Promise((resolve) => nativeSetTimeout(resolve, PREFERENCES_LOCK_RETRY_MS));
  }
}
async function writePreference(pluginKey, path, value) {
  const file = getTuiPreferencesFile();
  await mkdir(dirname(file), { recursive: !0 });
  const lock = await acquirePreferencesLock(file), tmp = `${file}.${process.pid}.${randomUUID()}.tmp`;
  try {
    let text;
    try {
      text = await readFile(file, "utf8");
    } catch {
      text = "";
    }
    if (text.trim() === "")
      text = TEMPLATE;
    const edits = modify(text, [pluginKey, ...path], value, {
      formattingOptions: { insertSpaces: !0, tabSize: 2 }
    }), next = applyEdits(text, edits);
    await writeFile(tmp, next, { encoding: "utf8", mode: 384 });
    await lock.assertOwned();
    await rename(tmp, file);
  } finally {
    await rm(tmp, { force: !0 }).catch(() => {});
    await lock.release();
  }
}
let writeChain = Promise.resolve();
export function queueTuiPreferenceUpdate(pluginKey, path, value) {
  writeChain = writeChain.then(() => writePreference(pluginKey, path, value)).catch(() => {});
  return writeChain;
}
const WATCH_DEBOUNCE_MS = 150, WATCH_POLL_MS = 100;
export function watchTuiPreferences(onChange) {
  const file = getTuiPreferencesFile(), name = basename(file);
  let timer = null, lastSeen = null, observedEvent = !1, disposed = !1;
  const checkForChange = async () => {
    const text = await readFile(file, "utf8").catch(() => null);
    if (disposed || text === null)
      return;
    if (text === lastSeen)
      return;
    lastSeen = text;
    onChange();
  }, scheduleCheck = () => {
    observedEvent = !0;
    if (timer)
      nativeClearTimeout(timer);
    timer = nativeSetTimeout(() => {
      timer = null;
      checkForChange();
    }, WATCH_DEBOUNCE_MS);
  };
  readFile(file, "utf8").then((text) => {
    if (!observedEvent && lastSeen === null)
      lastSeen = text;
  }).catch(() => {});
  try {
    const watcher = watch(dirname(file), (_event, filename) => {
      const isOurs = filename === name || filename?.startsWith(`${name}.`) && filename.endsWith(".tmp");
      if (filename != null && !isOurs)
        return;
      scheduleCheck();
    });
    let pollTimer = null, pollInFlight = !1;
    const schedulePoll = () => {
      if (disposed || pollTimer)
        return;
      pollTimer = nativeSetTimeout(() => {
        pollTimer = null;
        if (disposed || pollInFlight)
          return;
        pollInFlight = !0;
        checkForChange().finally(() => {
          pollInFlight = !1;
          schedulePoll();
        });
      }, WATCH_POLL_MS);
      pollTimer.unref?.();
    };
    schedulePoll();
    return () => {
      disposed = !0;
      if (timer)
        nativeClearTimeout(timer);
      if (pollTimer)
        nativeClearTimeout(pollTimer);
      watcher.close();
    };
  } catch {
    return () => {};
  }
}
