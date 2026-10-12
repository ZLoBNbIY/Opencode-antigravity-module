import { mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { writeJsonAtomic } from "@cortexkit/antigravity-auth-core/atomic-write";
import {
  acquireFencedFileLock
} from "@cortexkit/antigravity-auth-core/file-lock";
import { xdgState } from "xdg-basedir";
export const SIDEBAR_STATE_VERSION = 1, DEFAULT_SIDEBAR_STATE = {
  version: SIDEBAR_STATE_VERSION,
  checkedAt: 0,
  accounts: [],
  activeRouting: {},
  routingAuthoritative: !1
}, SIDEBAR_STATE_ENV = "ANTIGRAVITY_AUTH_SIDEBAR_STATE_FILE";
const SIDEBAR_STATE_DIR = "cortexkit/antigravity-auth", SIDEBAR_STATE_FILENAME = "sidebar-state.json", ACTIVE_ROUTING_MAX_AGE_MS = 86400000, ACTIVE_ROUTING_MAX_ENTRIES = 100, SIDEBAR_LOCK_NAME = "sidebar", SIDEBAR_LOCK_TTL_MS = 1e4, SIDEBAR_LOCK_TIMEOUT_MS = 2000, SIDEBAR_LOCK_RETRY_BASE_MS = 25, SIDEBAR_LOCK_RETRY_CAP_MS = 75, SIDEBAR_LOCK_JITTER_MS = 25, SIDEBAR_STATE_DIR_MODE = 448, SIDEBAR_STATE_FILE_MODE = 384;

export class SidebarStateLockContentionError extends Error {
  details;
  constructor(stateFile, timeoutMs) {
    super(`Could not acquire sidebar-state lock at ${stateFile} within ${timeoutMs}ms`);
    this.name = "SidebarStateLockContentionError";
    this.details = { stateFile, timeoutMs };
  }
}
let sidebarMergeHooks = null;
export function setSidebarMergeHooks(hooks) {
  sidebarMergeHooks = hooks;
}
async function emitMergeStep(step) {
  await sidebarMergeHooks?.onStep?.(step);
}
export function getSidebarStateFile() {
  const override = process.env[SIDEBAR_STATE_ENV];
  if (override && override.trim().length > 0)
    return override;
  const base = xdgState ?? join(homedir(), ".local", "state");
  return join(base, SIDEBAR_STATE_DIR, SIDEBAR_STATE_FILENAME);
}
export function readSidebarState(path = getSidebarStateFile()) {
  let raw;
  try {
    raw = readFileSync(path, "utf-8");
  } catch {
    return { ...DEFAULT_SIDEBAR_STATE };
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { ...DEFAULT_SIDEBAR_STATE, lastError: "malformed-json" };
  }
  return normalizeSidebarState(parsed);
}
function normalizeSidebarState(input) {
  if (!isObject(input))
    return { ...DEFAULT_SIDEBAR_STATE, lastError: "shape" };
  const record = input, version = record.version;
  if (version !== SIDEBAR_STATE_VERSION)
    return {
      ...DEFAULT_SIDEBAR_STATE,
      lastError: `unsupported-version:${stringifySafe(version)}`
    };
  const accountsRaw = record.accounts, accounts = Array.isArray(accountsRaw) ? accountsRaw.map((entry) => normalizeAccount(entry)).filter((entry) => entry !== null) : [], routingRaw = record.activeRouting, activeRouting = {};
  if (isObject(routingRaw))
    for (const [sessionId, entry] of Object.entries(routingRaw)) {
      const normalized = normalizeRouting(entry);
      if (normalized)
        activeRouting[sessionId] = normalized;
    }
  const checkedAt = toFiniteNumber(record.checkedAt), routingAuthoritative = record.routingAuthoritative === !0, quotaBackoffUntil = toFiniteNumber(record.quotaBackoffUntil), lastError = typeof record.lastError === "string" ? record.lastError : void 0;
  return {
    version: SIDEBAR_STATE_VERSION,
    checkedAt: checkedAt ?? 0,
    accounts,
    activeRouting,
    routingAuthoritative,
    quotaBackoffUntil: quotaBackoffUntil ?? void 0,
    lastError
  };
}
function normalizeAccount(input) {
  if (!isObject(input))
    return null;
  const record = input, id = typeof record.id === "string" ? record.id : null, label = typeof record.label === "string" ? record.label : null;
  if (!id || !label)
    return null;
  const enabled = record.enabled !== !1, health = clampNumber(toFiniteNumber(record.health), 0, 100), current = record.current === !0, cooldownUntil = toFiniteNumber(record.cooldownUntil) ?? void 0, quotaRaw = record.quota, quota = {};
  if (isObject(quotaRaw))
    for (const key of ["gemini", "non-gemini"]) {
      const entry = quotaRaw[key], normalized = normalizeQuota(entry);
      if (normalized)
        quota[key] = normalized;
    }
  const tier = normalizeTier(record.tier);
  return {
    id,
    label,
    enabled,
    health,
    current,
    cooldownUntil,
    quota,
    ...tier !== void 0 ? { tier } : {}
  };
}
function normalizeTier(input) {
  if (!isObject(input))
    return;
  const record = input, id = typeof record.id === "string" && record.id.length > 0 ? record.id : null, capturedAt = toFiniteNumber(record.capturedAt);
  if (!id || capturedAt === null)
    return;
  const paidId = typeof record.paidId === "string" && record.paidId.length > 0 ? record.paidId : void 0;
  return { id, ...paidId ? { paidId } : {}, capturedAt };
}
function normalizeQuota(input) {
  if (!isObject(input))
    return null;
  const record = input, remaining = toFiniteNumber(record.remainingPercent);
  if (remaining === null)
    return null;
  const resetAt = toFiniteNumber(record.resetAt) ?? void 0, checkedAt = toFiniteNumber(record.checkedAt) ?? void 0, windowsRaw = record.windows;
  let windows;
  if (Array.isArray(windowsRaw)) {
    const parsed = windowsRaw.filter(isObject).map((w) => {
      const win = w.window, rp = toFiniteNumber(w.remainingPercent), ra = toFiniteNumber(w.resetAt), ca = toFiniteNumber(w.checkedAt);
      if (win !== "weekly" && win !== "5h" || rp === null)
        return null;
      return {
        window: win,
        remainingPercent: clampNumber(rp, 0, 100),
        resetAt: ra ?? void 0,
        ...ca !== null && ca >= 0 ? { checkedAt: ca } : {}
      };
    }).filter((v) => v !== null);
    if (parsed.length > 0)
      windows = parsed;
  }
  return {
    remainingPercent: clampNumber(remaining, 0, 100),
    resetAt,
    ...checkedAt !== void 0 ? { checkedAt } : {},
    windows
  };
}
function normalizeRouting(input) {
  if (!isObject(input))
    return null;
  const record = input, accountId = typeof record.accountId === "string" ? record.accountId : null, { modelFamily, headerStyle, strategy } = record, updatedAt = toFiniteNumber(record.updatedAt) ?? 0;
  if (!accountId || modelFamily !== "claude" && modelFamily !== "gemini" || headerStyle !== "antigravity" && headerStyle !== "gemini-cli")
    return null;
  return {
    accountId,
    modelFamily,
    headerStyle,
    strategy: strategy === "sticky" || strategy === "round-robin" || strategy === "hybrid" ? strategy : void 0,
    updatedAt
  };
}
function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function toFiniteNumber(value) {
  if (typeof value === "number" && Number.isFinite(value))
    return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
function clampNumber(value, min, max) {
  if (value === null)
    return min;
  if (value < min)
    return min;
  if (value > max)
    return max;
  return value;
}
function stringifySafe(value) {
  if (typeof value === "string")
    return value;
  try {
    return JSON.stringify(value) ?? "unknown";
  } catch {
    return "unknown";
  }
}
export function ensureSidebarStateDir(path = getSidebarStateFile()) {
  mkdirSync(dirname(path), { recursive: !0, mode: SIDEBAR_STATE_DIR_MODE });
}
export function pruneActiveRouting(map, now) {
  const cutoff = now - ACTIVE_ROUTING_MAX_AGE_MS, filtered = [];
  for (const [sessionId, entry] of Object.entries(map))
    if (entry.updatedAt >= cutoff)
      filtered.push([sessionId, entry]);
  filtered.sort((a, b) => b[1].updatedAt - a[1].updatedAt);
  if (filtered.length <= ACTIVE_ROUTING_MAX_ENTRIES)
    return Object.fromEntries(filtered);
  return Object.fromEntries(filtered.slice(0, ACTIVE_ROUTING_MAX_ENTRIES));
}
export function toCapturedTier(account) {
  return account.capturedTierId !== void 0 && account.capturedTierAt !== void 0 ? {
    id: account.capturedTierId,
    ...account.capturedPaidTierId !== void 0 ? { paidId: account.capturedPaidTierId } : {},
    capturedAt: account.capturedTierAt
  } : void 0;
}
export function normalizeLegacyCachedQuota(raw) {
  if (!raw)
    return raw;
  if (!(("gemini-pro" in raw) || ("gemini-flash" in raw) || ("claude" in raw) || ("gpt-oss" in raw)))
    return raw;
  const earlierResetTime = (a, b) => {
    if (!a)
      return b;
    if (!b)
      return a;
    return a < b ? a : b;
  }, minFraction = (a, b) => {
    if (!a)
      return b;
    if (!b)
      return a;
    const fa = a.remainingFraction ?? 1, fb = b.remainingFraction ?? 1, winner = fa <= fb ? a : b, loser = fa <= fb ? b : a;
    return {
      ...winner,
      resetTime: earlierResetTime(winner.resetTime, loser.resetTime)
    };
  }, gemini = minFraction(raw.gemini, minFraction(raw["gemini-pro"], raw["gemini-flash"])) ?? raw.gemini, nonGemini = minFraction(raw["non-gemini"], minFraction(raw.claude, raw["gpt-oss"])) ?? raw["non-gemini"];
  return {
    ...gemini !== void 0 ? { gemini } : {},
    ...nonGemini !== void 0 ? { "non-gemini": nonGemini } : {}
  };
}
export function projectQuotaPoolForSidebar(source, checkedAt) {
  const readingAt = typeof checkedAt === "number" && Number.isFinite(checkedAt) && checkedAt >= 0 ? checkedAt : void 0, fraction = source.remainingFraction;
  if (typeof fraction !== "number" || !Number.isFinite(fraction))
    return;
  const remainingPercent = clampNumber(Math.round(fraction * 100), 0, 100);
  let resetAt;
  if (typeof source.resetTime === "string" && source.resetTime.length > 0) {
    const parsed = Date.parse(source.resetTime);
    if (Number.isFinite(parsed))
      resetAt = parsed;
  }
  const windows = source.windows?.length ? source.windows.map((w) => ({
    window: w.window,
    ...readingAt !== void 0 ? { checkedAt: readingAt } : {},
    remainingPercent: clampNumber(Math.round(w.remainingFraction * 100), 0, 100),
    resetAt: typeof w.resetTime === "string" && w.resetTime.length > 0 ? (() => {
      const parsed = Date.parse(w.resetTime);
      return Number.isFinite(parsed) ? parsed : void 0;
    })() : void 0
  })) : void 0;
  return {
    remainingPercent,
    resetAt,
    windows,
    ...readingAt !== void 0 ? { checkedAt: readingAt } : {}
  };
}
export function isAccountCurrent(index, activeIndexByFamily) {
  return index === activeIndexByFamily.claude || index === activeIndexByFamily.gemini;
}
export function redactAccountForSidebar(source) {
  const id = `acct-${source.index}`, label = `Account ${source.index + 1}`, enabled = source.enabled !== !1, current = source.current === !0, cooldownUntil = typeof source.coolingDownUntil === "number" && Number.isFinite(source.coolingDownUntil) ? source.coolingDownUntil : void 0, health = clampNumber(typeof source.healthScore === "number" ? source.healthScore : 100, 0, 100), quota = {}, cached = typeof source.cachedQuotaAccountId === "string" && typeof source.currentQuotaAccountId === "string" && source.cachedQuotaAccountId !== source.currentQuotaAccountId ? void 0 : normalizeLegacyCachedQuota(source.cachedQuota);
  if (cached)
    for (const key of ["gemini", "non-gemini"]) {
      const entry = cached[key];
      if (!entry)
        continue;
      const projected = projectQuotaPoolForSidebar(entry, source.cachedQuotaUpdatedAt);
      if (projected)
        quota[key] = projected;
    }
  return {
    id,
    label,
    enabled,
    health,
    current,
    cooldownUntil,
    quota,
    ...source.tier !== void 0 ? { tier: source.tier } : {}
  };
}
export function buildSidebarMachineStateFromAccounts(accounts, options = {}) {
  return {
    checkedAt: options.checkedAt ?? Date.now(),
    accounts: accounts.map((entry) => redactAccountForSidebar(entry)),
    quotaBackoffUntil: options.quotaBackoffUntil,
    lastError: options.lastError,
    routingAuthoritative: options.routingAuthoritative
  };
}
let sidebarWriteChain = Promise.resolve();
function enqueueSidebarWrite(work) {
  const next = sidebarWriteChain.then(work, work);
  sidebarWriteChain = next.then(() => {
    return;
  }, () => {
    return;
  });
  return next;
}
export function drainSidebarWrites() {
  return sidebarWriteChain;
}
async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}
async function acquireSidebarLockWithRetry(stateFile) {
  const start = Date.now();
  let attempt = 0;
  while (!0) {
    await emitMergeStep("await-lock");
    const lock = await acquireFencedFileLock({
      path: stateFile,
      name: SIDEBAR_LOCK_NAME,
      ttlMs: SIDEBAR_LOCK_TTL_MS,
      renew: !0
    });
    if (lock) {
      await emitMergeStep("acquired-lock");
      return lock;
    }
    if (Date.now() - start >= SIDEBAR_LOCK_TIMEOUT_MS)
      throw new SidebarStateLockContentionError(stateFile, SIDEBAR_LOCK_TIMEOUT_MS);
    const backoff = Math.min(SIDEBAR_LOCK_RETRY_CAP_MS, SIDEBAR_LOCK_RETRY_BASE_MS + attempt * 10), jitter = Math.floor(Math.random() * SIDEBAR_LOCK_JITTER_MS);
    await sleep(backoff + jitter);
    attempt++;
  }
}
async function performSidebarWrite(stateFile, merge) {
  await enqueueSidebarWrite(async () => {
    ensureSidebarStateDir(stateFile);
    const lock = await acquireSidebarLockWithRetry(stateFile);
    try {
      await lock.assertOwned();
      const existing = readSidebarState(stateFile);
      await emitMergeStep("read-state");
      const merged = merge(existing);
      await emitMergeStep("merged-state");
      await writeJsonAtomic(stateFile, merged, {
        beforeRename: () => lock.assertOwned()
      });
      await emitMergeStep("wrote-state");
    } finally {
      await lock.release().catch(() => {});
    }
  });
}
function mergeMachineState(existing, next, retainedAccountIds) {
  if (next.checkedAt < existing.checkedAt)
    return {
      ...existing,
      activeRouting: pruneActiveRouting(existing.activeRouting, Date.now())
    };
  const routes = pruneActiveRouting(existing.activeRouting, Date.now()), retained = retainedAccountIds === void 0 ? void 0 : new Set(retainedAccountIds), activeRouting = retained === void 0 ? routes : Object.fromEntries(Object.entries(routes).filter(([, entry]) => retained.has(entry.accountId)));
  return {
    version: SIDEBAR_STATE_VERSION,
    checkedAt: next.checkedAt,
    accounts: next.accounts,
    quotaBackoffUntil: next.quotaBackoffUntil,
    lastError: next.lastError,
    routingAuthoritative: existing.routingAuthoritative === !0 || next.routingAuthoritative === !0,
    activeRouting
  };
}
export async function upsertSidebarActiveRouting(sessionId, entry, options = {}) {
  const stateFile = options.stateFile ?? getSidebarStateFile();
  await performSidebarWrite(stateFile, (existing) => {
    if (options.onlyForProjectedAccounts && !existing.accounts.some((account) => account.id === entry.accountId))
      return existing;
    const activeRouting = { ...existing.activeRouting, [sessionId]: entry };
    return {
      ...existing,
      routingAuthoritative: options.authoritative === !0 ? !0 : existing.routingAuthoritative,
      activeRouting: pruneActiveRouting(activeRouting, Date.now())
    };
  });
}
export async function removeSidebarActiveRouting(sessionId, options = {}) {
  const stateFile = options.stateFile ?? getSidebarStateFile();
  await performSidebarWrite(stateFile, (existing) => {
    if (!(sessionId in existing.activeRouting))
      return existing;
    const activeRouting = { ...existing.activeRouting };
    delete activeRouting[sessionId];
    return {
      ...existing,
      activeRouting
    };
  });
}
export async function setSidebarMachineState(next, options = {}) {
  const stateFile = options.stateFile ?? getSidebarStateFile();
  await performSidebarWrite(stateFile, (existing) => mergeMachineState(existing, next, options.retainRoutingForAccountIds));
}
