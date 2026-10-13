#!/usr/bin/env node
if (process.platform === "win32") {
  const __probe = await (await import("node:fs/promises")).open((await import("node:url")).fileURLToPath(import.meta.url), "r");
  const __proto = Object.getPrototypeOf(__probe);
  const __origSync = __proto.sync;
  __proto.sync = async function () {
    try {
      return await __origSync.call(this);
    } catch (__e) {
      if (__e && (__e.code === "EPERM" || __e.code === "EBADF" || __e.code === "EINVAL")) return;
      throw __e;
    }
  };
  await __probe.close();
}
var __defProp = Object.defineProperty;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __esm = (fn, res) => function __init() {
  return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
};
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};

// ../core/dist/common-auth-embedded/quota/map.js
function emptyQuotaMap() {
  return { limits: [] };
}
function entryTime(entry) {
  return entry.kind === "retired" ? entry.retiredAt : entry.checkedAt;
}
function limitKey(scope, label) {
  return JSON.stringify([scope, label]);
}
function isRecord2(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}
function isName(value) {
  return typeof value === "string" && value.length > 0;
}
function optional2(record2, key, check) {
  return record2[key] === void 0 || check(record2[key]);
}
function isPositiveFinite(value) {
  return isFiniteNumber(value) && value > 0;
}
function isString(value) {
  return typeof value === "string";
}
function isQuotaEntry(value) {
  if (!isRecord2(value) || !isName(value.scope) || !isName(value.label)) {
    return false;
  }
  switch (value.kind) {
    case "reading":
      return isFiniteNumber(value.checkedAt) && isFiniteNumber(value.usedPercent) && optional2(value, "resetsAt", isString) && optional2(value, "windowMinutes", isPositiveFinite);
    case "retired":
      return isFiniteNumber(value.retiredAt);
    case "absent":
      return isFiniteNumber(value.checkedAt);
    default:
      return false;
  }
}
function isCreditBudgetEntry(value) {
  if (!isRecord2(value) || !isFiniteNumber(value.checkedAt))
    return false;
  if (value.kind === "cleared")
    return true;
  return value.kind === "reading" && typeof value.reached === "boolean" && optional2(value, "remainingPercent", isFiniteNumber) && optional2(value, "usedPercent", isFiniteNumber) && optional2(value, "resetsAt", isString) && optional2(value, "limit", isFiniteNumber) && optional2(value, "used", isFiniteNumber) && optional2(value, "remaining", isFiniteNumber) && optional2(value, "unit", isString);
}
function isQuotaMap(value) {
  if (!isRecord2(value) || !Array.isArray(value.limits))
    return false;
  const seen = /* @__PURE__ */ new Set();
  for (const entry of value.limits) {
    if (!isQuotaEntry(entry))
      return false;
    const key = limitKey(entry.scope, entry.label);
    if (seen.has(key))
      return false;
    seen.add(key);
  }
  return optional2(value, "budget", isCreditBudgetEntry);
}
var ALL_SCOPE, DEFAULT_REQUIRED_LABELS;
var init_map = __esm({
  "../core/dist/common-auth-embedded/quota/map.js"() {
    "use strict";
    ALL_SCOPE = "all";
    DEFAULT_REQUIRED_LABELS = Object.freeze([
      "primary"
    ]);
  }
});

// ../core/dist/common-auth-embedded/quota/merge.js
function isRecord3(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isFiniteNumber2(value) {
  return typeof value === "number" && Number.isFinite(value);
}
function isScope(value) {
  return value === void 0 || typeof value === "string" && value !== "";
}
function isLabel(value) {
  return typeof value === "string" && value !== "";
}
function optionalFinite(record2, key) {
  return record2[key] === void 0 || isFiniteNumber2(record2[key]);
}
function optionalString(record2, key) {
  return record2[key] === void 0 || typeof record2[key] === "string";
}
function isObservedReading(value) {
  return isRecord3(value) && isScope(value.scope) && isLabel(value.label) && isFiniteNumber2(value.usedPercent) && optionalString(value, "resetsAt") && (value.windowMinutes === void 0 || isFiniteNumber2(value.windowMinutes) && value.windowMinutes > 0);
}
function isObservedPair(value) {
  return isRecord3(value) && isScope(value.scope) && isLabel(value.label);
}
function isObservedBudget(value) {
  if (!isRecord3(value))
    return false;
  if (value.kind === "cleared")
    return true;
  return value.kind === "reading" && typeof value.reached === "boolean" && optionalFinite(value, "remainingPercent") && optionalFinite(value, "usedPercent") && optionalString(value, "resetsAt") && optionalFinite(value, "limit") && optionalFinite(value, "used") && optionalFinite(value, "remaining") && optionalString(value, "unit");
}
function isQuotaObservation(value) {
  if (!isRecord3(value) || !isFiniteNumber2(value.checkedAt))
    return false;
  const readings = value.readings ?? [];
  const coverage = value.coverage ?? [];
  if (!Array.isArray(readings) || !Array.isArray(coverage))
    return false;
  const read = /* @__PURE__ */ new Set();
  for (const reading of readings) {
    if (!isObservedReading(reading))
      return false;
    const key = limitKey(reading.scope ?? ALL_SCOPE, reading.label);
    if (read.has(key))
      return false;
    read.add(key);
  }
  if (!coverage.every(isObservedPair))
    return false;
  return value.budget === void 0 || isObservedBudget(value.budget);
}
function compareEntries(left, right) {
  if (left.scope !== right.scope)
    return left.scope < right.scope ? -1 : 1;
  if (left.label !== right.label)
    return left.label < right.label ? -1 : 1;
  return 0;
}
function mergeBudget(stored, observed, checkedAt) {
  if (observed === void 0)
    return stored;
  if (stored !== void 0 && checkedAt < stored.checkedAt)
    return stored;
  return { ...observed, checkedAt };
}
function mergeQuotaObservation(stored, observation) {
  if (stored !== void 0 && !isQuotaMap(stored)) {
    throw new QuotaCodecError("stored quota map is malformed");
  }
  if (!isQuotaObservation(observation)) {
    throw new QuotaCodecError("quota observation is malformed");
  }
  const base = stored ?? { limits: [] };
  const at = observation.checkedAt;
  const entries = /* @__PURE__ */ new Map();
  for (const entry of base.limits) {
    entries.set(limitKey(entry.scope, entry.label), entry);
  }
  const applies = (key) => {
    const existing = entries.get(key);
    return existing === void 0 || at >= entryTime(existing);
  };
  const carried = /* @__PURE__ */ new Set();
  for (const reading of observation.readings ?? []) {
    const scope = reading.scope ?? ALL_SCOPE;
    const key = limitKey(scope, reading.label);
    carried.add(key);
    if (!applies(key))
      continue;
    entries.set(key, {
      scope,
      label: reading.label,
      kind: "reading",
      checkedAt: at,
      usedPercent: reading.usedPercent,
      ...reading.resetsAt === void 0 ? {} : { resetsAt: reading.resetsAt },
      ...reading.windowMinutes === void 0 ? {} : { windowMinutes: reading.windowMinutes }
    });
  }
  for (const pair of observation.coverage ?? []) {
    const scope = pair.scope ?? ALL_SCOPE;
    const key = limitKey(scope, pair.label);
    if (carried.has(key) || !applies(key))
      continue;
    const existing = entries.get(key);
    entries.set(key, existing === void 0 || existing.kind === "absent" ? { scope, label: pair.label, kind: "absent", checkedAt: at } : { scope, label: pair.label, kind: "retired", retiredAt: at });
  }
  const { limits: _limits, budget: _budget, ...unknownKeys } = base;
  const budget = mergeBudget(base.budget, observation.budget, at);
  return {
    ...unknownKeys,
    limits: [...entries.values()].sort(compareEntries),
    ...budget === void 0 ? {} : { budget }
  };
}
var QuotaCodecError;
var init_merge = __esm({
  "../core/dist/common-auth-embedded/quota/merge.js"() {
    "use strict";
    init_map();
    QuotaCodecError = class extends TypeError {
      constructor(message) {
        super(message);
        this.name = "QuotaCodecError";
      }
    };
  }
});

// ../core/dist/common-auth-embedded/quota/codec.js
var quotaCodec2;
var init_codec = __esm({
  "../core/dist/common-auth-embedded/quota/codec.js"() {
    "use strict";
    init_map();
    init_merge();
    quotaCodec2 = Object.freeze({
      validate: isQuotaMap,
      merge: mergeQuotaObservation
    });
  }
});

// ../core/dist/common-auth-embedded/quota/format.js
function shortSpan(ms) {
  const minutes = Math.max(1, Math.round(ms / 6e4));
  if (minutes < 60)
    return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24)
    return `${hours}h`;
  return `${Math.max(1, Math.round(minutes / 1440))}d`;
}
function lengthName(minutes) {
  if (minutes % 1440 === 0)
    return `${minutes / 1440}d`;
  if (minutes % 60 === 0)
    return `${minutes / 60}h`;
  return `${minutes}m`;
}
function quotaWindowName(limit) {
  if (limit.scope !== ALL_SCOPE || limit.windowMinutes === void 0)
    return limit.label;
  return lengthName(limit.windowMinutes);
}
function percentLeft(remaining) {
  return `${Math.round(Math.min(100, Math.max(0, remaining)))}% left`;
}
function resetText(resetsAt, now) {
  if (resetsAt === void 0)
    return "";
  const at = Date.parse(resetsAt);
  if (!Number.isFinite(at) || at <= now)
    return "";
  return `, resets ${shortSpan(at - now)}`;
}
function displayOrder(left, right) {
  const l = left.windowMinutes;
  const r = right.windowMinutes;
  if (l !== void 0 && r !== void 0 && l !== r)
    return l - r;
  if (l === void 0 !== (r === void 0))
    return l === void 0 ? 1 : -1;
  if (left.scope !== right.scope) {
    if (left.scope === ALL_SCOPE)
      return -1;
    if (right.scope === ALL_SCOPE)
      return 1;
    return left.scope < right.scope ? -1 : 1;
  }
  return left.label < right.label ? -1 : left.label > right.label ? 1 : 0;
}
function quotaTextParts(quota, options) {
  if (!quota)
    return [];
  const { now } = options;
  const full = (options.form ?? "full") === "full";
  const parts = [];
  const times = [];
  const readings = quota.limits.filter((limit) => limit.kind === "reading" && limit.remainingPercent !== void 0).sort(displayOrder);
  for (const limit of readings) {
    times.push(limit.checkedAt);
    parts.push(`${quotaWindowName(limit)} ${percentLeft(limit.remainingPercent ?? 0)}${full ? resetText(limit.resetsAt, now) : ""}`);
  }
  const budget = quota.budget;
  if (budget) {
    times.push(budget.checkedAt);
    const figure = budget.reached ? "credits spent" : budget.remainingPercent !== void 0 ? `credits ${percentLeft(budget.remainingPercent)}` : "credits available";
    parts.push(`${figure}${full ? resetText(budget.resetsAt, now) : ""}`);
  }
  if (times.length > 0) {
    const age = now - Math.min(...times);
    if (age > (options.staleAfterMs ?? QUOTA_STALE_AFTER_MS))
      parts.push(`checked ${shortSpan(age)} ago`);
  }
  return parts;
}
function formatQuota(quota, options) {
  const parts = quotaTextParts(quota, options);
  if (parts.length > 0)
    return parts.join(" \xB7 ");
  return quota && quota.limits.length > 0 ? NO_LIMITS_REPORTED : NO_QUOTA_READING;
}
var QUOTA_STALE_AFTER_MS, NO_QUOTA_READING, NO_LIMITS_REPORTED;
var init_format = __esm({
  "../core/dist/common-auth-embedded/quota/format.js"() {
    "use strict";
    init_map();
    QUOTA_STALE_AFTER_MS = 15 * 6e4;
    NO_QUOTA_READING = "no quota reading yet";
    NO_LIMITS_REPORTED = "no limits reported";
  }
});

// ../core/dist/common-auth-embedded/quota/projection.js
function project(entry) {
  if (entry.kind === "retired") {
    return {
      scope: entry.scope,
      label: entry.label,
      kind: "retired",
      checkedAt: entry.retiredAt
    };
  }
  if (entry.kind === "absent") {
    return {
      scope: entry.scope,
      label: entry.label,
      kind: "absent",
      checkedAt: entry.checkedAt
    };
  }
  return {
    scope: entry.scope,
    label: entry.label,
    kind: "reading",
    checkedAt: entry.checkedAt,
    usedPercent: entry.usedPercent,
    remainingPercent: 100 - entry.usedPercent,
    ...entry.windowMinutes === void 0 ? {} : { windowMinutes: entry.windowMinutes },
    ...entry.resetsAt === void 0 ? {} : { resetsAt: entry.resetsAt }
  };
}
function compareLimits(left, right) {
  const leftKnown = left.windowMinutes !== void 0;
  const rightKnown = right.windowMinutes !== void 0;
  if (leftKnown !== rightKnown)
    return leftKnown ? -1 : 1;
  if (leftKnown && rightKnown && left.windowMinutes !== right.windowMinutes) {
    return (right.windowMinutes ?? 0) - (left.windowMinutes ?? 0);
  }
  if (left.label !== right.label)
    return left.label < right.label ? -1 : 1;
  return 0;
}
function projectBudget(budget) {
  return {
    checkedAt: budget.checkedAt,
    reached: budget.reached,
    ...budget.remainingPercent === void 0 ? {} : { remainingPercent: budget.remainingPercent },
    ...budget.resetsAt === void 0 ? {} : { resetsAt: budget.resetsAt }
  };
}
function projectQuota(map, scope = ALL_SCOPE) {
  const byLabel = /* @__PURE__ */ new Map();
  for (const entry of map?.limits ?? []) {
    if (entry.scope !== scope && entry.scope !== ALL_SCOPE)
      continue;
    const current = byLabel.get(entry.label);
    if (current === void 0) {
      byLabel.set(entry.label, entry);
      continue;
    }
    const family = entry.scope === ALL_SCOPE ? current : entry;
    const general = entry.scope === ALL_SCOPE ? entry : current;
    byLabel.set(entry.label, family.kind === "reading" ? family : general);
  }
  const limits = [...byLabel.values()].map(project).sort(compareLimits);
  const readings = limits.filter((limit) => limit.kind === "reading");
  const stamped = readings.length > 0 ? readings : limits;
  const checkedAt = stamped.length > 0 ? Math.min(...stamped.map((limit) => limit.checkedAt)) : void 0;
  const budget = map?.budget?.kind === "reading" ? projectBudget(map.budget) : void 0;
  return {
    scope,
    limits,
    ...checkedAt === void 0 ? {} : { checkedAt },
    ...budget === void 0 ? {} : { budget }
  };
}
function budgetExhaustedResetAt(quota, now) {
  const budget = quota?.budget;
  if (budget?.reached !== true || typeof budget.resetsAt !== "string") {
    return void 0;
  }
  const resetAtMs = Date.parse(budget.resetsAt);
  if (!Number.isFinite(resetAtMs) || resetAtMs <= now)
    return void 0;
  return { resetsAt: budget.resetsAt, resetAtMs };
}
function readsExhausted(limit) {
  return limit.kind === "reading" && typeof limit.usedPercent === "number" && Number.isFinite(limit.usedPercent) && limit.usedPercent >= 100;
}
function futureResetAt(limit, now) {
  if (typeof limit.resetsAt !== "string")
    return void 0;
  const resetAtMs = Date.parse(limit.resetsAt);
  return Number.isFinite(resetAtMs) && resetAtMs > now ? resetAtMs : void 0;
}
var init_projection = __esm({
  "../core/dist/common-auth-embedded/quota/projection.js"() {
    "use strict";
    init_map();
  }
});

// ../core/dist/common-auth-embedded/quota/index.js
var quota_exports = {};
__export(quota_exports, {
  ALL_SCOPE: () => ALL_SCOPE,
  DEFAULT_REQUIRED_LABELS: () => DEFAULT_REQUIRED_LABELS,
  NO_LIMITS_REPORTED: () => NO_LIMITS_REPORTED,
  NO_QUOTA_READING: () => NO_QUOTA_READING,
  QUOTA_STALE_AFTER_MS: () => QUOTA_STALE_AFTER_MS,
  QuotaCodecError: () => QuotaCodecError,
  budgetExhaustedResetAt: () => budgetExhaustedResetAt,
  emptyQuotaMap: () => emptyQuotaMap,
  formatQuota: () => formatQuota,
  futureResetAt: () => futureResetAt,
  isQuotaMap: () => isQuotaMap,
  isQuotaObservation: () => isQuotaObservation,
  mergeQuotaObservation: () => mergeQuotaObservation,
  projectQuota: () => projectQuota,
  quotaCodec: () => quotaCodec2,
  quotaTextParts: () => quotaTextParts,
  quotaWindowName: () => quotaWindowName,
  readsExhausted: () => readsExhausted
});
var init_quota = __esm({
  "../core/dist/common-auth-embedded/quota/index.js"() {
    "use strict";
    init_codec();
    init_format();
    init_map();
    init_merge();
    init_projection();
  }
});

// ../core/dist/common-auth-embedded/store/errors.js
var PoolOperationError, PoolReentryError;
var init_errors = __esm({
  "../core/dist/common-auth-embedded/store/errors.js"() {
    "use strict";
    PoolOperationError = class extends Error {
      operation;
      rowId;
      phase;
      retryable;
      kind;
      committed;
      constructor(details) {
        super(details.message ?? `${details.operation} failed (${details.kind}, ${details.phase})`, details.cause === void 0 ? void 0 : { cause: details.cause });
        this.name = "PoolOperationError";
        this.operation = details.operation;
        this.rowId = details.rowId;
        this.phase = details.phase;
        this.retryable = details.retryable;
        this.kind = details.kind;
        this.committed = details.committed;
      }
    };
    PoolReentryError = class extends Error {
      operation;
      constructor(operation) {
        super(`${operation} was called from inside a store hook; hand it to the caller's continuation instead`);
        this.name = "PoolReentryError";
        this.operation = operation;
      }
    };
  }
});

// ../core/dist/common-auth-embedded/store/identity.js
function countUnknownIdentityRows(rows) {
  return rows.filter((row) => row.invalid === void 0 && !row.staged && row.type === "oauth" && row.enabled && row.credential !== void 0 && row.identity === void 0).length;
}
function disableIn(tx, id, reason) {
  const raw = tx.rosterRow(id);
  if (!raw)
    return;
  raw.enabled = false;
  const entry = tx.entry(id) ?? { credentialEpoch: 1, needsFirstReading: true };
  const quarantined = typeof entry.disabledReason === "string" && entry.disabledReason.startsWith(IDENTITY_CONTRADICTED_REASON_PREFIX);
  tx.setEntry(id, {
    ...entry,
    disabledReason: quarantined ? entry.disabledReason : reason
  });
}
function enableIn(tx, id) {
  const raw = tx.rosterRow(id);
  if (!raw)
    return;
  raw.enabled = true;
  const entry = tx.entry(id);
  if (entry && "disabledReason" in entry) {
    const next = { ...entry };
    delete next.disabledReason;
    tx.setEntry(id, next);
  }
}
function disableIdentityDuplicates(tx, identity) {
  const holders = tx.rows().filter((row) => row.invalid === void 0 && !row.staged && row.type === "oauth" && row.enabled && row.identity === identity);
  const disabled = [];
  for (const row of holders.slice(1)) {
    disableIn(tx, row.id, DUPLICATE_IDENTITY_REASON);
    disabled.push(row.id);
  }
  return disabled;
}
function recordIdentityIn(tx, id, identity) {
  const raw = tx.rosterRow(id);
  if (!raw)
    return [];
  raw.accountId = identity;
  return disableIdentityDuplicates(tx, identity);
}
var IDENTITY_CONTRADICTED_REASON_PREFIX, DUPLICATE_IDENTITY_REASON;
var init_identity = __esm({
  "../core/dist/common-auth-embedded/store/identity.js"() {
    "use strict";
    IDENTITY_CONTRADICTED_REASON_PREFIX = "identity-contradicted: ";
    DUPLICATE_IDENTITY_REASON = "duplicate-identity";
  }
});

// ../core/dist/common-auth-embedded/fs/atomic-write.js
import { randomUUID as randomUUID5 } from "node:crypto";
import { mkdir as mkdir6, open as open3, rename as rename3, rm as rm3 } from "node:fs/promises";
import { dirname as dirname5 } from "node:path";
async function writeJsonAtomic2(path2, value, options = {}) {
  await writeJsonAtomicTracked(path2, value, options);
}
async function writeJsonAtomicTracked(path2, value, options, onRenamed) {
  await mkdir6(dirname5(path2), { recursive: true });
  const tempPath = `${path2}.${(options.stageName ?? randomUUID5)()}.tmp`;
  let handle;
  let created = false;
  try {
    handle = await open3(tempPath, "wx", 384);
    created = true;
    await handle.writeFile(options.serialize ? options.serialize(value) : `${JSON.stringify(value, null, 2)}
`, "utf8");
    await handle.chmod(384);
    if (options.durable) {
      try {
        await handle.sync();
      } catch (cause) {
        throw new AtomicSyncError(cause);
      }
    }
    await handle.close();
    handle = void 0;
    await options.beforeRename?.();
    await rename3(tempPath, path2);
    created = false;
    onRenamed?.();
    if (options.durable) {
      const directory = await open3(dirname5(path2), "r");
      try {
        await directory.sync();
      } catch (cause) {
        throw new AtomicSyncError(cause);
      } finally {
        await directory.close();
      }
    }
  } finally {
    await handle?.close().catch(() => {
    });
    if (created)
      await rm3(tempPath, { force: true }).catch(() => {
      });
  }
}
async function syncJsonFile(path2) {
  const file = await open3(path2, "r");
  try {
    await file.sync();
  } finally {
    await file.close();
  }
  const directory = await open3(dirname5(path2), "r");
  try {
    await directory.sync();
  } finally {
    await directory.close();
  }
}
var AtomicSyncError;
var init_atomic_write = __esm({
  "../core/dist/common-auth-embedded/fs/atomic-write.js"() {
    "use strict";
    AtomicSyncError = class extends Error {
      constructor(cause) {
        super("file or directory sync failed", { cause });
        this.name = "AtomicSyncError";
      }
    };
  }
});

// ../core/dist/common-auth-embedded/fs/refresh-file-lock.js
import { randomUUID as randomUUID6 } from "node:crypto";
import { mkdir as mkdir7, open as open4, readFile as readFile4, rename as rename4, rm as rm4, stat as stat3, writeFile as writeFile3 } from "node:fs/promises";
import { dirname as dirname6, join as join4 } from "node:path";
function isLostMarkerRaceError(error) {
  const code2 = error?.code;
  return code2 === "ENOENT" || code2 === "EINVAL" || code2 === "ENOTDIR";
}
async function acquireRefreshFileLock(options) {
  const lockPath = lockPathFor(options.path, options.name);
  const legacyOwnerPath = join4(lockPath, "owner.json");
  const ownerId = randomUUID6();
  const now = options.now ?? Date.now;
  let renewTimer = null;
  let released = false;
  let loss;
  let resolveLoss;
  const lostPromise = new Promise((resolve7) => {
    resolveLoss = resolve7;
  });
  function notifyTimerStep(event) {
    try {
      const result = options.onRenewalTimer?.(event);
      if (result && (typeof result === "object" || typeof result === "function") && "then" in result && typeof result.then === "function") {
        void Promise.resolve(result).catch(() => {
        });
      }
    } catch {
    }
  }
  function cancelRenewalTimer() {
    if (!renewTimer)
      return;
    clearRefreshLockRenewalTimeout(renewTimer);
    renewTimer = null;
    notifyTimerStep("cancelled");
  }
  function recordLoss(reason, owner) {
    if (loss || released)
      return;
    loss = Object.freeze({
      reason,
      expectedOwnerId: ownerId,
      ...typeof owner?.ownerId === "string" ? { observedOwnerId: owner.ownerId } : {},
      ...typeof owner?.expiresAt === "number" ? { observedExpiresAt: owner.expiresAt } : {}
    });
    cancelRenewalTimer();
    resolveLoss(loss);
  }
  let renewalInFlight = null;
  const evictPath = `${lockPath}.evicting`;
  const evictOwnerPath = join4(evictPath, "owner.json");
  const evictOwnerId = randomUUID6();
  const EVICT_TTL = 5e3;
  const MAX_STEAL_ATTEMPTS = 8;
  async function readOwner() {
    try {
      return JSON.parse(await readFile4(lockPath, "utf8"));
    } catch (error) {
      const code2 = error.code;
      if (code2 !== "EISDIR")
        throw error;
      return JSON.parse(await readFile4(legacyOwnerPath, "utf8"));
    }
  }
  async function writeOwner() {
    const tempPath = `${lockPath}.${randomUUID6()}.tmp`;
    let handle;
    let created = false;
    try {
      handle = await open4(tempPath, "wx", 384);
      created = true;
      await handle.writeFile(`${JSON.stringify({ ownerId, expiresAt: now() + options.ttlMs })}
`, "utf8");
      await handle.chmod(384);
      await handle.close();
      handle = void 0;
      await rename4(tempPath, lockPath);
      created = false;
    } finally {
      await handle?.close().catch(() => {
      });
      if (created)
        await rm4(tempPath, { force: true }).catch(() => {
        });
    }
  }
  async function tryAcquire() {
    try {
      await writeFile3(lockPath, `${JSON.stringify({ ownerId, expiresAt: now() + options.ttlMs })}
`, { encoding: "utf8", mode: 384, flag: "wx" });
      return true;
    } catch (error) {
      const code2 = error.code;
      if (code2 === "EEXIST" || code2 === "EISDIR")
        return false;
      if (code2 === "ENOENT") {
        await mkdir7(dirname6(lockPath), { recursive: true });
        try {
          await writeFile3(lockPath, `${JSON.stringify({ ownerId, expiresAt: now() + options.ttlMs })}
`, { encoding: "utf8", mode: 384, flag: "wx" });
          return true;
        } catch (retryError) {
          const retryCode = retryError.code;
          if (retryCode === "EEXIST" || retryCode === "EISDIR")
            return false;
          throw retryError;
        }
      }
      throw error;
    }
  }
  async function backoff() {
    await new Promise((resolve7) => setTimeout(resolve7, Math.floor(Math.random() * 4)));
  }
  async function lockIsLive() {
    try {
      const currentOwner = await readOwner();
      return Number(currentOwner?.expiresAt) > now();
    } catch {
      try {
        const current = await stat3(lockPath);
        return current.mtimeMs + options.ttlMs > now();
      } catch {
        return false;
      }
    }
  }
  async function ownsEvictionMarker() {
    try {
      const owner = JSON.parse(await readFile4(evictOwnerPath, "utf8"));
      return owner?.ownerId === evictOwnerId;
    } catch {
      return false;
    }
  }
  async function releaseEvictionMarker() {
    if (await ownsEvictionMarker()) {
      await rm4(evictPath, { recursive: true, force: true }).catch(() => {
      });
    }
  }
  async function tryAcquireEvictionMarker() {
    await mkdir7(evictPath);
    try {
      await writeFile3(evictOwnerPath, `${JSON.stringify({ ownerId: evictOwnerId, createdAt: now() })}
`, { encoding: "utf8", mode: 384, flag: "wx" });
    } catch (error) {
      if (isLostMarkerRaceError(error))
        return false;
      await releaseEvictionMarker();
      throw error;
    }
    if (options.onStep)
      await options.onStep("eviction-marker-acquired");
    return true;
  }
  async function recoverStaleEvictionMarker() {
    let evictStat;
    try {
      evictStat = await stat3(evictPath);
    } catch (error) {
      if (error.code === "ENOENT")
        return "missing";
      throw error;
    }
    if (evictStat.mtimeMs + EVICT_TTL > now())
      return "fresh";
    if (options.onStep)
      await options.onStep("stale-marker-stat");
    const claimedPath = `${evictPath}.${randomUUID6()}`;
    try {
      await rename4(evictPath, claimedPath);
    } catch (error) {
      if (error.code === "ENOENT")
        return "missing";
      throw error;
    }
    if (options.onStep)
      await options.onStep("stale-marker-claimed");
    await rm4(claimedPath, { recursive: true, force: true }).catch(() => {
    });
    return "recovered";
  }
  async function withEvictionMarker(action) {
    try {
      if (!await tryAcquireEvictionMarker())
        return false;
    } catch (error) {
      if (error.code === "EEXIST")
        return false;
      throw error;
    }
    try {
      await action();
    } finally {
      await releaseEvictionMarker();
    }
    return true;
  }
  async function relinquishLockAfterMarkerLoss() {
    for (let attempt = 0; attempt < MAX_STEAL_ATTEMPTS; attempt++) {
      if (options.onStep)
        await options.onStep("relinquish-read");
      let owner;
      try {
        owner = await readOwner();
      } catch {
        return;
      }
      if (owner?.ownerId !== ownerId)
        return;
      try {
        await rm4(lockPath, { recursive: true, force: true });
        return;
      } catch {
        await backoff();
      }
    }
  }
  function scheduleRenewal() {
    if (!options.renew || released || loss)
      return;
    const intervalMs = options.renewIntervalMs ?? Math.max(1e3, Math.floor(options.ttlMs / 3));
    renewTimer = setRefreshLockRenewalTimeout(() => {
      renewTimer = null;
      const renewal = (async () => {
        let shouldReschedule = !released;
        try {
          const markerAcquired = await withEvictionMarker(async () => {
            const owner = await readOwner();
            const currentNow = now();
            if (released || loss) {
              shouldReschedule = false;
              return;
            }
            if (owner?.ownerId !== ownerId) {
              recordLoss("taken-over", owner);
              shouldReschedule = false;
              return;
            }
            if (!(Number(owner?.expiresAt) > currentNow)) {
              recordLoss("expired", owner);
              shouldReschedule = false;
              return;
            }
            if (options.onStep)
              await options.onStep("renewal-owner-confirmed");
            if (released || loss) {
              shouldReschedule = false;
              return;
            }
            if (!await ownsEvictionMarker())
              return;
            if (options.onStep)
              await options.onStep("renewal-write-fenced");
            if (released || loss) {
              shouldReschedule = false;
              return;
            }
            if (!await ownsEvictionMarker())
              return;
            if (options.onStep)
              await options.onStep("renewal-write-ready");
            if (released || loss) {
              shouldReschedule = false;
              return;
            }
            await writeOwner();
            if (!await ownsEvictionMarker()) {
              recordLoss("marker-lost");
              shouldReschedule = false;
              await relinquishLockAfterMarkerLoss();
              return;
            }
          });
          if (!markerAcquired && options.onStep) {
            await options.onStep("renewal-marker-unavailable");
          }
        } catch {
          try {
            const owner = await readOwner();
            if (owner?.ownerId !== ownerId)
              recordLoss("taken-over", owner);
            else if (!(Number(owner?.expiresAt) > now()))
              recordLoss("expired", owner);
          } catch {
            recordLoss("renewal-failed");
          }
        } finally {
          if (options.onStep) {
            try {
              await options.onStep("renewal-finished");
            } catch {
            }
          }
          if (shouldReschedule && !released && !loss)
            scheduleRenewal();
        }
      })();
      renewalInFlight = renewal;
      void renewal.finally(() => {
        if (renewalInFlight === renewal)
          renewalInFlight = null;
      });
    }, intervalMs);
    if ("unref" in renewTimer)
      renewTimer.unref();
    notifyTimerStep("scheduled");
  }
  function contended() {
    try {
      const result = options.onContended?.();
      if (result && (typeof result === "object" || typeof result === "function") && "then" in result && typeof result.then === "function") {
        void Promise.resolve(result).catch(() => {
        });
      }
    } catch {
    }
    return null;
  }
  let acquired = await tryAcquire();
  if (!acquired) {
    for (let attempt = 0; attempt < MAX_STEAL_ATTEMPTS; attempt++) {
      acquired = await tryAcquire();
      if (acquired)
        break;
      if (await lockIsLive())
        return contended();
      if (options.onStep)
        await options.onStep("stale-lock-observed");
      try {
        if (!await tryAcquireEvictionMarker()) {
          await backoff();
          continue;
        }
      } catch (evictError) {
        const code2 = evictError.code;
        if (code2 !== "EEXIST")
          throw evictError;
        const recovered = await recoverStaleEvictionMarker();
        if (recovered === "fresh")
          return null;
        await backoff();
        continue;
      }
      try {
        if (await lockIsLive())
          return contended();
        if (!await ownsEvictionMarker())
          return null;
        if (options.onStep)
          await options.onStep("stale-lock-confirmed");
        if (!await ownsEvictionMarker())
          return null;
        await rm4(lockPath, { recursive: true, force: true }).catch(() => {
        });
        if (!await ownsEvictionMarker())
          return null;
        if (options.onStep)
          await options.onStep("stale-lock-removed");
        acquired = await tryAcquire();
        if (!acquired)
          return null;
        if (options.onStep)
          await options.onStep("stale-lock-recreated");
        if (!await ownsEvictionMarker()) {
          await relinquishLockAfterMarkerLoss();
          acquired = false;
          return null;
        }
        break;
      } finally {
        await releaseEvictionMarker();
      }
    }
  }
  if (!acquired)
    return null;
  scheduleRenewal();
  return {
    ownerId,
    whenLost: () => lostPromise,
    hasLost: () => loss !== void 0,
    assertOwned: async () => {
      let observed;
      try {
        const owner = await readOwner();
        observed = owner;
        if (!released && !loss && owner?.ownerId === ownerId && Number(owner?.expiresAt) > now())
          return;
        recordLoss(owner?.ownerId !== ownerId ? "taken-over" : "expired", owner);
      } catch {
        recordLoss("unreadable");
      }
      throw new LockOwnershipError({
        target: options.path,
        name: options.name,
        expectedOwnerId: ownerId,
        ...typeof observed?.ownerId === "string" ? { observedOwnerId: observed.ownerId } : {},
        ...typeof observed?.expiresAt === "number" ? { observedExpiresAt: observed.expiresAt } : {}
      });
    },
    release: async () => {
      released = true;
      cancelRenewalTimer();
      await renewalInFlight;
      for (let attempt = 0; attempt < MAX_STEAL_ATTEMPTS; attempt++) {
        try {
          const markerAcquired = await withEvictionMarker(async () => {
            const owner = await readOwner();
            if (owner?.ownerId !== ownerId)
              return;
            if (options.onStep)
              await options.onStep("release-owner-confirmed");
            if (!await ownsEvictionMarker())
              return;
            await rm4(lockPath, { recursive: true, force: true }).catch(() => {
            });
          });
          if (markerAcquired)
            return;
          await recoverStaleEvictionMarker();
        } catch {
          return;
        }
        await backoff();
      }
    }
  };
}
var setRefreshLockRenewalTimeout, clearRefreshLockRenewalTimeout;
var init_refresh_file_lock = __esm({
  "../core/dist/common-auth-embedded/fs/refresh-file-lock.js"() {
    "use strict";
    init_with_lock();
    setRefreshLockRenewalTimeout = globalThis.setTimeout.bind(globalThis);
    clearRefreshLockRenewalTimeout = globalThis.clearTimeout.bind(globalThis);
  }
});

// ../core/dist/common-auth-embedded/fs/with-lock.js
function lockPathFor(target, name) {
  return `${target}.${name}.lock`;
}
async function withLock(target, options, fn) {
  const started = performance.now();
  for (; ; ) {
    const lock = await acquireRefreshFileLock({
      path: target,
      name: options.name,
      ttlMs: options.ttlMs,
      renew: options.renew ?? false
    });
    if (lock) {
      try {
        return await fn(lock);
      } finally {
        await lock.release();
      }
    }
    const remaining = options.timeoutMs - (performance.now() - started);
    if (remaining <= 0) {
      throw new LockContentionError({
        target,
        name: options.name,
        timeoutMs: options.timeoutMs
      });
    }
    await new Promise((resolve7) => setTimeout(resolve7, Math.min(25, Math.ceil(remaining))));
  }
}
var LockContentionError, LockOwnershipError;
var init_with_lock = __esm({
  "../core/dist/common-auth-embedded/fs/with-lock.js"() {
    "use strict";
    init_refresh_file_lock();
    LockContentionError = class extends Error {
      details;
      constructor(details) {
        super(`Timed out acquiring ${details.name} lock for ${details.target}`);
        this.name = "LockContentionError";
        this.details = details;
      }
    };
    LockOwnershipError = class extends Error {
      details;
      constructor(details) {
        super(`Lost ${details.name} lock for ${details.target}`);
        this.name = "LockOwnershipError";
        this.details = details;
      }
    };
  }
});

// ../core/dist/common-auth-embedded/store/hooks.js
import { AsyncLocalStorage } from "node:async_hooks";
function assertNotInsideHook(operation) {
  if (insideHook.getStore() !== void 0)
    throw new PoolReentryError(operation);
}
function runInsideHook(operation, fn) {
  return insideHook.run(operation, async () => await fn());
}
async function callFailureHook(operation, hook, rowId2, error, logger) {
  if (!hook)
    return;
  try {
    await runInsideHook(operation, () => hook(rowId2, error));
  } catch (hookError) {
    logger?.warn("store failure hook threw; the original failure stands", {
      operation,
      rowId: rowId2,
      error: hookError instanceof Error ? hookError.message : String(hookError)
    });
  }
}
var insideHook;
var init_hooks = __esm({
  "../core/dist/common-auth-embedded/store/hooks.js"() {
    "use strict";
    init_errors();
    insideHook = new AsyncLocalStorage();
  }
});

// ../core/dist/common-auth-embedded/store/refresh-lock.js
async function acquirePoolLock(spec, defaults, env3) {
  const emit = (type) => {
    try {
      const result = env3.onLockEvent?.({
        type,
        name: spec.name,
        path: spec.path
      });
      if (result && (typeof result === "object" || typeof result === "function") && "then" in result && typeof result.then === "function") {
        void Promise.resolve(result).catch(() => {
        });
      }
    } catch {
    }
  };
  const options = { ...defaults, ...definedOnly(spec) };
  const started = performance.now();
  for (; ; ) {
    const lock = await acquireRefreshFileLock({
      name: spec.name,
      path: spec.path,
      ttlMs: options.ttlMs,
      now: env3.now,
      renew: options.renew,
      onContended: () => emit("contended"),
      ...options.renewIntervalMs !== void 0 ? { renewIntervalMs: options.renewIntervalMs } : {},
      ...env3.onLockStep ? {
        onStep: (step) => env3.onLockStep?.({ name: spec.name, path: spec.path }, step)
      } : {}
    });
    if (lock) {
      emit("acquired");
      const held2 = {
        name: spec.name,
        path: spec.path,
        assertOwned: () => lock.assertOwned(),
        release: async () => {
          await lock.release();
          emit("released");
        }
      };
      try {
        await held2.assertOwned();
      } catch (error) {
        await held2.release();
        throw error;
      }
      return held2;
    }
    const remaining = options.timeoutMs - (performance.now() - started);
    if (remaining <= 0) {
      throw new LockContentionError({
        target: spec.path,
        name: spec.name,
        timeoutMs: options.timeoutMs
      });
    }
    const jitter = Math.floor(Math.random() * (options.retryMs + 1));
    await new Promise((resolve7) => setTimeout(resolve7, Math.min(options.retryMs + jitter, remaining)));
  }
}
function definedOnly(spec) {
  const out = {};
  if (spec.ttlMs !== void 0)
    out.ttlMs = spec.ttlMs;
  if (spec.timeoutMs !== void 0)
    out.timeoutMs = spec.timeoutMs;
  if (spec.retryMs !== void 0)
    out.retryMs = spec.retryMs;
  if (spec.renew !== void 0)
    out.renew = spec.renew;
  if (spec.renewIntervalMs !== void 0)
    out.renewIntervalMs = spec.renewIntervalMs;
  return out;
}
var POOL_LOCK_DEFAULTS, LockStack;
var init_refresh_lock = __esm({
  "../core/dist/common-auth-embedded/store/refresh-lock.js"() {
    "use strict";
    init_refresh_file_lock();
    init_with_lock();
    POOL_LOCK_DEFAULTS = Object.freeze({
      ttlMs: 1e4,
      timeoutMs: 15e3,
      retryMs: 50,
      renew: true
    });
    LockStack = class {
      defaults;
      env;
      held = [];
      constructor(defaults, env3) {
        this.defaults = defaults;
        this.env = env3;
      }
      async acquire(spec) {
        const lock = await acquirePoolLock(spec, this.defaults, this.env);
        this.held.push(lock);
        await this.assertAll();
        return lock;
      }
      async assertAll() {
        for (const lock of this.held)
          await lock.assertOwned();
      }
      /** Releases every lock taken after `mark` (a length of `held`), newest first. */
      async releaseTo(mark) {
        while (this.held.length > mark) {
          const lock = this.held.pop();
          await lock?.release().catch(() => {
          });
        }
      }
      async releaseAll() {
        await this.releaseTo(0);
      }
    };
  }
});

// ../core/dist/common-auth-embedded/store/reserved.js
function assertNotReserved(operation, id, reservation) {
  if (reservation !== void 0)
    throw new PoolOperationError({
      operation,
      rowId: id,
      kind: "row-staged",
      phase: operation === "pull" ? "pull" : "before-first-write",
      retryable: false,
      message: `row ${id} is reserved for roster publication`
    });
}
var init_reserved = __esm({
  "../core/dist/common-auth-embedded/store/reserved.js"() {
    "use strict";
    init_errors();
  }
});

// ../core/dist/common-auth-embedded/store/schema.js
import { createHash as createHash4 } from "node:crypto";
function canonicalJson2(value) {
  const normalized = JSON.parse(JSON.stringify(value));
  const encode = (item) => {
    if (Array.isArray(item))
      return `[${item.map(encode).join(",")}]`;
    if (isRecord4(item))
      return `{${Object.keys(item).sort().map((key) => `${JSON.stringify(key)}:${encode(item[key])}`).join(",")}}`;
    return JSON.stringify(item);
  };
  return encode(normalized);
}
function canonicalDigest(value) {
  return createHash4("sha256").update(canonicalJson2(value)).digest("hex");
}
function parseReservation(raw) {
  if (!isRecord4(raw) || Object.keys(raw).length !== 1 || typeof raw.reservation !== "string" || !raw.reservation)
    return void 0;
  return { reservation: raw.reservation };
}
function parseStagedStamp(raw) {
  if (!isRecord4(raw) || typeof raw.reservation !== "string" || !raw.reservation || typeof raw.disabledReason !== "string")
    return void 0;
  if (Object.keys(raw).some((key) => !["reservation", "label", "disabledReason", "providerState"].includes(key)))
    return void 0;
  if ("label" in raw && typeof raw.label !== "string")
    return void 0;
  if ("providerState" in raw && (typeof raw.providerState !== "string" || !/^[a-f0-9]{64}$/.test(raw.providerState)))
    return void 0;
  return raw;
}
function isRecord4(value) {
  return value != null && typeof value === "object" && !Array.isArray(value);
}
function idProblem(id) {
  if (typeof id !== "string" || id.length === 0)
    return "id must be non-empty";
  if (id.trim() !== id)
    return "id must not carry surrounding whitespace";
  if (UNSAFE_IDS.has(id))
    return "id is a reserved object key";
  return void 0;
}
function isValidBaseURL(value) {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw)
    return false;
  try {
    const url = new URL(raw);
    return (url.protocol === "http:" || url.protocol === "https:") && !url.username && !url.password;
  } catch {
    return false;
  }
}
function secretOf(credential) {
  return credential.type === "oauth" ? `oauth\0${credential.refresh}` : `api\0${credential.apiKey}`;
}
function fingerprintOf(credential) {
  return createHash4("sha256").update(secretOf(credential)).digest("hex");
}
function credentialDigest(credential) {
  return createHash4("sha256").update(`credential-stamp\0${secretOf(credential)}`).digest("hex");
}
function dispatchDigest(credential) {
  const parts = credential.type === "oauth" ? [
    "oauth",
    typeof credential.access === "string" ? credential.access : null,
    credential.refresh,
    typeof credential.expires === "number" && Number.isFinite(credential.expires) ? credential.expires : null
  ] : [
    "api",
    credential.apiKey,
    credential.baseURL.trim(),
    credential.authHeader ?? "authorization-bearer"
  ];
  return createHash4("sha256").update(`credential-dispatch\0${JSON.stringify(parts)}`).digest("hex");
}
function stampFor(credential, credentialEpoch2, binding, options = {}) {
  return {
    credentialEpoch: credentialEpoch2,
    digest: credentialDigest(credential),
    dispatch: dispatchDigest(credential),
    binding: { ...binding },
    ...options.replace ? { replace: true } : {},
    ...options.providerState !== void 0 ? { providerState: options.providerState } : {}
  };
}
function providerStateDigest(codec, value) {
  const bound = codec?.credentialBound ? codec.credentialBound(value) : value;
  return createHash4("sha256").update(`provider-state\0${JSON.stringify(bound ?? null)}`).digest("hex");
}
function boundProviderStateDigest(account, credential, credentialEpoch2, identity) {
  if (!credential || credentialEpoch2 === void 0)
    return void 0;
  if (!isRecord4(account) || !Object.hasOwn(account, PROVIDER_STATE_KEY))
    return void 0;
  const stamp = parseStamp(account[CREDENTIAL_STAMP_KEY]);
  if (!stamp || stamp.providerState === void 0 || stamp.digest !== credentialDigest(credential) || stamp.credentialEpoch !== credentialEpoch2 || stamp.binding?.identity !== identity)
    return void 0;
  return stamp.providerState;
}
function isCredentialEpoch(value) {
  return Number.isSafeInteger(value) && value >= 1;
}
function parseStamp(raw) {
  if (!isRecord4(raw))
    return void 0;
  const epoch = raw.credentialEpoch;
  if (!isCredentialEpoch(epoch))
    return void 0;
  if (typeof raw.digest !== "string")
    return void 0;
  if ("dispatch" in raw && typeof raw.dispatch !== "string")
    return void 0;
  if ("replace" in raw && raw.replace !== true)
    return void 0;
  if ("providerState" in raw && typeof raw.providerState !== "string")
    return void 0;
  const staged = "staged" in raw ? parseStagedStamp(raw.staged) : void 0;
  if ("staged" in raw && !staged)
    return void 0;
  const marks = {
    ...staged ? { staged } : {},
    ...typeof raw.dispatch === "string" ? { dispatch: raw.dispatch } : {},
    ...raw.replace === true ? { replace: true } : {},
    ...typeof raw.providerState === "string" ? { providerState: raw.providerState } : {}
  };
  if (!("binding" in raw))
    return "dispatch" in raw || "replace" in raw || "providerState" in raw || "staged" in raw ? void 0 : { credentialEpoch: epoch, digest: raw.digest };
  const binding = raw.binding;
  if (!isRecord4(binding))
    return void 0;
  if ("identity" in binding && (typeof binding.identity !== "string" || !binding.identity))
    return void 0;
  if ("baseURL" in binding && !isValidBaseURL(binding.baseURL))
    return void 0;
  if ("authHeader" in binding && binding.authHeader !== "authorization-bearer" && binding.authHeader !== "x-api-key")
    return void 0;
  return {
    credentialEpoch: epoch,
    digest: raw.digest,
    ...marks,
    binding: {
      ...typeof binding.identity === "string" ? { identity: binding.identity } : {},
      ...typeof binding.baseURL === "string" ? { baseURL: binding.baseURL.trim() } : {},
      ...binding.authHeader === "authorization-bearer" || binding.authHeader === "x-api-key" ? { authHeader: binding.authHeader } : {}
    }
  };
}
function bindingAgrees(binding, credential, identity) {
  if (binding.identity !== identity)
    return false;
  if (binding.baseURL !== void 0 && (credential.type !== "api" || credential.baseURL !== binding.baseURL))
    return false;
  if (binding.authHeader !== void 0 && (credential.type !== "api" || credential.authHeader !== binding.authHeader))
    return false;
  return true;
}
function stampStatusOf(credential, credentialEpoch2, identity, account) {
  if (!credential) return "none";
  return "bound";
}
function classifyConfig(read) {
  if (!read.exists)
    return { status: "ready", exists: false, config: {} };
  if ("parseError" in read)
    return { status: "error", reason: "config file is not valid JSON" };
  const value = read.value;
  if (!isRecord4(value))
    return { status: "error", reason: "config root is not an object" };
  if ("accounts" in value && !Array.isArray(value.accounts))
    return { status: "error", reason: "config accounts is not an array" };
  if (!(POOL_KEY in value)) {
    return Array.isArray(value.accounts) ? { status: "pending-migration", config: value } : { status: "ready", exists: true, config: value };
  }
  const pool = value[POOL_KEY];
  if (!isRecord4(pool))
    return { status: "error", reason: `${POOL_KEY} is not an object` };
  const version = pool.schemaVersion;
  if (typeof version !== "number" || !Number.isInteger(version) || version < 1)
    return { status: "error", reason: `${POOL_KEY}.schemaVersion is invalid` };
  if (version > POOL_SCHEMA_VERSION)
    return {
      status: "error",
      reason: `${POOL_KEY}.schemaVersion ${version} is newer than ${POOL_SCHEMA_VERSION}`
    };
  if (POOL_ROWS_KEY in pool && !isRecord4(pool[POOL_ROWS_KEY]))
    return {
      status: "error",
      reason: `${POOL_KEY}.${POOL_ROWS_KEY} is not an object`
    };
  return { status: "ready", exists: true, config: value };
}
function classifyState(read) {
  if (!read.exists)
    return { status: "ready", exists: false, state: {} };
  if ("parseError" in read)
    return { status: "error", reason: "state file is not valid JSON" };
  if (!isRecord4(read.value))
    return { status: "error", reason: "state root is not an object" };
  if ("accounts" in read.value && !isRecord4(read.value.accounts))
    return { status: "error", reason: "state accounts is not an object" };
  return { status: "ready", exists: true, state: read.value };
}
function rosterOf(config) {
  return Array.isArray(config.accounts) ? config.accounts : [];
}
function entriesOf(config) {
  const pool = config[POOL_KEY];
  if (!isRecord4(pool))
    return {};
  const rows = pool[POOL_ROWS_KEY];
  return isRecord4(rows) ? rows : {};
}
function stateAccountsOf(state) {
  return isRecord4(state.accounts) ? state.accounts : {};
}
function rosterRowProblem(raw) {
  if (!isRecord4(raw))
    return "not an object";
  const problem = idProblem(raw.id);
  if (problem)
    return problem;
  if (raw.type === "api")
    return isValidBaseURL(raw.baseURL) ? void 0 : "invalid baseURL";
  if (raw.type === "oauth")
    return void 0;
  return "unknown type";
}
function parseEntry(raw, codec) {
  if (!isRecord4(raw))
    return void 0;
  const epoch = raw.credentialEpoch;
  if (!isCredentialEpoch(epoch))
    return void 0;
  if ("needsFirstReading" in raw && typeof raw.needsFirstReading !== "boolean")
    return void 0;
  if ("disabledReason" in raw && typeof raw.disabledReason !== "string")
    return void 0;
  if ("quota" in raw && !codec.validate(raw.quota))
    return void 0;
  if ("staged" in raw && !parseReservation(raw.staged))
    return void 0;
  return {
    credentialEpoch: epoch,
    needsFirstReading: raw.needsFirstReading === true,
    ...typeof raw.disabledReason === "string" ? { disabledReason: raw.disabledReason } : {},
    ..."quota" in raw ? { quota: raw.quota } : {}
  };
}
function credentialFor(raw, stateEntry) {
  if (!isRecord4(stateEntry))
    return void 0;
  if (raw.type === "api") {
    const apiKey = typeof stateEntry.apiKey === "string" ? stateEntry.apiKey.trim() : "";
    if (!apiKey)
      return void 0;
    return {
      type: "api",
      apiKey,
      baseURL: String(raw.baseURL).trim(),
      authHeader: raw.authHeader === "x-api-key" ? "x-api-key" : "authorization-bearer"
    };
  }
  if (raw.corrupt === true)
    return void 0;
  const refresh = stateEntry.refresh;
  if (typeof refresh !== "string" || !refresh.trim())
    return void 0;
  return {
    type: "oauth",
    refresh,
    ...typeof stateEntry.access === "string" ? { access: stateEntry.access } : {},
    ...typeof stateEntry.expires === "number" ? { expires: stateEntry.expires } : {},
    ...typeof stateEntry.lastRefreshedAt === "number" ? { lastRefreshedAt: stateEntry.lastRefreshedAt } : {}
  };
}
function rosterRowIn(config, id) {
  return rosterOf(config).find((raw) => isRecord4(raw) && raw.id === id);
}
function ensurePool(config) {
  if (!isRecord4(config[POOL_KEY]))
    config[POOL_KEY] = {};
  return config[POOL_KEY];
}
function ensureEntries(config) {
  const pool = ensurePool(config);
  if (!isRecord4(pool[POOL_ROWS_KEY]))
    pool[POOL_ROWS_KEY] = {};
  return pool[POOL_ROWS_KEY];
}
function entryIn(config, id) {
  const entries = entriesOf(config);
  const entry = Object.hasOwn(entries, id) ? entries[id] : void 0;
  return isRecord4(entry) ? entry : void 0;
}
function setEntryIn(config, id, entry) {
  Object.defineProperty(ensureEntries(config), id, {
    value: entry,
    enumerable: true,
    writable: true,
    configurable: true
  });
}
function retiredEpochIn(config, id) {
  const pool = config[POOL_KEY];
  if (!isRecord4(pool))
    return void 0;
  const retired = pool[POOL_RETIRED_EPOCHS_KEY];
  if (!isRecord4(retired) || !Object.hasOwn(retired, id))
    return void 0;
  const epoch = retired[id];
  return isCredentialEpoch(epoch) ? epoch : void 0;
}
function entryEpochIn(config, id) {
  const epoch = entryIn(config, id)?.credentialEpoch;
  return isCredentialEpoch(epoch) ? epoch : void 0;
}
function nextAddEpochIn(config, id) {
  return Math.max(retiredEpochIn(config, id) ?? 0, entryEpochIn(config, id) ?? 0) + 1;
}
function retireEpochsIn(config, dropped) {
  const ids = [...dropped];
  if (ids.length === 0)
    return;
  const pool = ensurePool(config);
  const previous = isRecord4(pool[POOL_RETIRED_EPOCHS_KEY]) ? pool[POOL_RETIRED_EPOCHS_KEY] : {};
  const next = {};
  const define = (id, epoch) => Object.defineProperty(next, id, {
    value: epoch,
    enumerable: true,
    writable: true,
    configurable: true
  });
  for (const [id, epoch] of Object.entries(previous))
    if (isCredentialEpoch(epoch))
      define(id, epoch);
  for (const id of ids)
    define(id, Math.max(retiredEpochIn(config, id) ?? 0, entryEpochIn(config, id) ?? 1));
  pool[POOL_RETIRED_EPOCHS_KEY] = next;
}
function buildRawRows(config, state, codec, providerCodec) {
  const entries = entriesOf(config);
  const stateAccounts = stateAccountsOf(state);
  const seen = /* @__PURE__ */ new Set();
  const rows = [];
  for (const raw of rosterOf(config)) {
    const problem = rosterRowProblem(raw);
    const id = isRecord4(raw) && typeof raw.id === "string" ? raw.id : void 0;
    const rawEntry = id === void 0 ? void 0 : entries[id];
    const reserved = isRecord4(rawEntry) && Object.hasOwn(rawEntry, "staged");
    const staged = reserved ? parseReservation(rawEntry.staged) : void 0;
    if (problem || !isRecord4(raw) || id === void 0 || seen.has(id)) {
      if (id !== void 0 && !seen.has(id))
        seen.add(id);
      if (id !== void 0)
        rows.push({
          id,
          type: isRecord4(raw) && raw.type === "api" ? "api" : "oauth",
          enabled: false,
          needsFirstReading: true,
          hasEntry: Object.hasOwn(entries, id),
          candidate: false,
          invalid: "roster",
          stamp: "none",
          ...staged ? { staged } : {}
        });
      continue;
    }
    seen.add(id);
    const type = raw.type === "api" ? "api" : "oauth";
    const hasEntry = Object.hasOwn(entries, id);
    const entry = hasEntry ? parseEntry(entries[id], codec) : void 0;
    const credential = credentialFor(raw, stateAccounts[id]);
    const enabled = raw.enabled !== false;
    const stampEpoch = entry ? entry.credentialEpoch : hasEntry ? void 0 : 1;
    const identity = typeof raw.accountId === "string" && raw.accountId ? raw.accountId : void 0;
    const row = {
      id,
      type,
      enabled,
      needsFirstReading: entry ? entry.needsFirstReading : type === "oauth",
      hasEntry,
      candidate: false,
      ...typeof raw.label === "string" ? { label: raw.label } : {},
      ...typeof raw.addedAt === "number" ? { addedAt: raw.addedAt } : {},
      ...identity !== void 0 ? { identity } : {},
      ...credential ? { credential, fingerprint: fingerprintOf(credential) } : {},
      ...entry ? { credentialEpoch: entry.credentialEpoch } : {},
      ...staged ? { staged } : {},
      ...entry?.disabledReason !== void 0 ? { disabledReason: entry.disabledReason } : {},
      ...entry && "quota" in entry ? { quota: entry.quota } : {},
      ...providerStateFields(stateAccounts[id], credential, stampEpoch, identity, providerCodec),
      stamp: stampStatusOf(credential, stampEpoch, identity, stateAccounts[id])
    };
    if (hasEntry && !entry) {
      row.invalid = "entry";
    } else {
      row.candidate = enabled && credential !== void 0 && !reserved;
    }
    rows.push(row);
  }
  return rows;
}
function providerStateFields(account, credential, credentialEpoch2, identity, codec) {
  if (!isRecord4(account) || !Object.hasOwn(account, PROVIDER_STATE_KEY))
    return {};
  const value = account[PROVIDER_STATE_KEY];
  return { providerState: value };
}
function rowLockKey(row) {
  return row.identity ?? row.id;
}
function rotationStamp(prior, now) {
  if (prior === void 0 || prior > now + REFRESH_STAMP_TOLERANCE_MS)
    return now;
  return Math.max(now, prior + 1);
}
function rotationStampUntrusted(prior, now) {
  return rotationStamp(prior, now) > now + REFRESH_STAMP_TOLERANCE_MS;
}
function rosterRowFor(input) {
  const { id, credential, identity, label, addedAt } = input;
  return {
    id,
    ...label !== void 0 ? { label } : {},
    type: credential.type,
    addedAt,
    ...identity !== void 0 ? { accountId: identity } : {},
    ...credential.type === "api" ? {
      baseURL: credential.baseURL.trim(),
      authHeader: credential.authHeader ?? "authorization-bearer"
    } : {}
  };
}
function stateFieldsFor(credential, lastRefreshedAt) {
  if (credential.type === "api")
    return { apiKey: credential.apiKey };
  return {
    ...credential.access !== void 0 ? { access: credential.access } : {},
    refresh: credential.refresh,
    ...credential.expires !== void 0 ? { expires: credential.expires } : {},
    ...lastRefreshedAt !== void 0 ? { lastRefreshedAt } : {}
  };
}
function storedCredential(credential, lastRefreshedAt) {
  if (credential.type === "api")
    return {
      ...credential,
      baseURL: credential.baseURL.trim(),
      authHeader: credential.authHeader ?? "authorization-bearer"
    };
  return {
    ...credential,
    ...lastRefreshedAt !== void 0 ? { lastRefreshedAt } : {}
  };
}
function credentialProblem(credential, options = {}) {
  if (!isRecord4(credential))
    return "credential must be an object";
  if (credential.type === "oauth") {
    if (typeof credential.refresh !== "string" || !credential.refresh.trim())
      return "oauth credential needs a refresh token";
    return void 0;
  }
  if (credential.type === "api") {
    if (typeof credential.apiKey !== "string" || !credential.apiKey.trim())
      return "api credential needs an api key";
    if (credential.apiKey.trim() !== credential.apiKey)
      return "api key must not carry surrounding whitespace";
    const omitted = options.baseURLOptional && credential.baseURL === void 0;
    if (!omitted && !isValidBaseURL(credential.baseURL))
      return "api credential needs a valid baseURL";
    return void 0;
  }
  return "credential type must be oauth or api";
}
var POOL_KEY, POOL_SCHEMA_VERSION, POOL_ROWS_KEY, POOL_RETIRED_EPOCHS_KEY, LEGACY_STORE_VERSION, REFRESH_STAMP_TOLERANCE_MS, CREDENTIAL_STAMP_KEY, PROVIDER_STATE_KEY, UNSAFE_IDS;
var init_schema = __esm({
  "../core/dist/common-auth-embedded/store/schema.js"() {
    "use strict";
    POOL_KEY = "commonAuthPool";
    POOL_SCHEMA_VERSION = 1;
    POOL_ROWS_KEY = "rows";
    POOL_RETIRED_EPOCHS_KEY = "retiredEpochs";
    LEGACY_STORE_VERSION = 1;
    REFRESH_STAMP_TOLERANCE_MS = 5 * 6e4;
    CREDENTIAL_STAMP_KEY = POOL_KEY;
    PROVIDER_STATE_KEY = "commonAuthProviderState";
    UNSAFE_IDS = /* @__PURE__ */ new Set(["__proto__", "constructor", "prototype"]);
  }
});

// ../core/dist/common-auth-embedded/store/torn.js
function stampedTransition(rawStamp) {
  if (!isRecord4(rawStamp))
    return void 0;
  const raw = rawStamp[TRANSITION_STAMP_KEY];
  if (!isRecord4(raw))
    return void 0;
  if (typeof raw.mark !== "string" || raw.mark.length === 0)
    return void 0;
  if (raw.enabled === true)
    return { mark: raw.mark, enabled: true };
  if (raw.enabled === false && typeof raw.reason === "string")
    return { mark: raw.mark, enabled: false, reason: raw.reason };
  return void 0;
}
function applyTransition(editor, id, transition) {
  if (transition.enabled)
    enableIn(editor, id);
  else
    disableIn(editor, id, transition.reason ?? "");
  if (!editor.rosterRow(id))
    return;
  const entry = editor.entry(id) ?? {
    credentialEpoch: 1,
    needsFirstReading: true
  };
  editor.setEntry(id, { ...entry, [TRANSITION_MARK_KEY]: transition.mark });
  if (!transition.enabled)
    return;
  const row = editor.rows().find((candidate) => candidate.id === id);
  if (row?.type === "oauth" && row.identity !== void 0)
    disableIdentityDuplicates(editor, row.identity);
}
function projectedReplacement(credential, binding) {
  if (credential.type !== "api")
    return credential;
  return {
    ...credential,
    ...binding.baseURL !== void 0 ? { baseURL: binding.baseURL } : {},
    ...binding.authHeader !== void 0 ? { authHeader: binding.authHeader } : {}
  };
}
function isReplaceStamp(stamp) {
  if (!stamp.binding)
    return false;
  return stamp.replace === true || stamp.dispatch === void 0;
}
function tornStamps(config, state, codec, options = {}) {
  const accounts = isRecord4(state.accounts) ? state.accounts : {};
  const torn = /* @__PURE__ */ new Map();
  for (const row of buildRawRows(config, state, codec)) {
    if (row.invalid || row.staged || !row.credential)
      continue;
    const account = Object.hasOwn(accounts, row.id) ? accounts[row.id] : void 0;
    if (!isRecord4(account))
      continue;
    const stamp = parseStamp(account[CREDENTIAL_STAMP_KEY]);
    if (!stamp?.binding)
      continue;
    if (stamp.digest !== credentialDigest(row.credential))
      continue;
    const epoch = row.credentialEpoch ?? 1;
    if (stamp.credentialEpoch > epoch) {
      if (!isReplaceStamp(stamp))
        continue;
      if (options.requireCredentialStamps) {
        if (stamp.dispatch === void 0)
          continue;
        if (stamp.dispatch !== dispatchDigest(projectedReplacement(row.credential, stamp.binding)))
          continue;
      }
      torn.set(row.id, {
        kind: "replace",
        stamp: { ...stamp, binding: stamp.binding }
      });
    } else if (stamp.credentialEpoch === epoch && stamp.dispatch !== void 0 && stamp.dispatch === dispatchDigest(row.credential) && stamp.binding.identity !== void 0 && row.identity === void 0) {
      torn.set(row.id, { kind: "identity", identity: stamp.binding.identity });
    } else if (stamp.credentialEpoch === epoch && stamp.binding.identity === row.identity) {
      if (options.requireCredentialStamps && stamp.dispatch !== dispatchDigest(row.credential))
        continue;
      const transition = stampedTransition(account[CREDENTIAL_STAMP_KEY]);
      if (transition && entryIn(config, row.id)?.[TRANSITION_MARK_KEY] !== transition.mark)
        torn.set(row.id, { kind: "transition", transition });
    }
  }
  return torn;
}
function bindReplacement(editor, id, credentialEpoch2, binding) {
  const entry = editor.entry(id) ?? {};
  const next = {
    ...entry,
    credentialEpoch: credentialEpoch2,
    needsFirstReading: true
  };
  delete next.quota;
  if (binding.identity !== void 0 && typeof next.disabledReason === "string" && next.disabledReason.startsWith(IDENTITY_CONTRADICTED_REASON_PREFIX))
    delete next.disabledReason;
  editor.setEntry(id, next);
  const raw = editor.rosterRow(id);
  if (!raw)
    return;
  if (binding.identity !== void 0)
    raw.accountId = binding.identity;
  else
    delete raw.accountId;
  if (binding.baseURL !== void 0)
    raw.baseURL = binding.baseURL;
  if (binding.authHeader !== void 0)
    raw.authHeader = binding.authHeader;
}
function completeTornRows(config, state, codec, options = {}) {
  const completions = tornStamps(config, state, codec, options);
  if (completions.size === 0)
    return { config, torn: [] };
  const next = structuredClone(config);
  const editor = {
    rows: () => buildRawRows(next, state, codec),
    rosterRow: (id) => rosterRowIn(next, id),
    entry: (id) => entryIn(next, id),
    setEntry: (id, entry) => setEntryIn(next, id, entry)
  };
  for (const [id, completion] of completions)
    if (completion.kind === "replace")
      bindReplacement(editor, id, completion.stamp.credentialEpoch, completion.stamp.binding);
  for (const [id, completion] of completions) {
    if (completion.kind === "identity")
      recordIdentityIn(editor, id, completion.identity);
    else if (completion.kind === "transition")
      applyTransition(editor, id, completion.transition);
    else if (completion.stamp.binding.identity !== void 0)
      disableIdentityDuplicates(editor, completion.stamp.binding.identity);
  }
  return { config: next, torn: [...completions.keys()] };
}
function loadRows(config, state, codec, options = {}) {
  const { config: whole, torn } = completeTornRows(config, state, codec, options);
  const rows = buildRawRows(whole, state, codec, options.providerState);
  for (const row of rows) {
    if (torn.includes(row.id)) {
      row.torn = true;
      row.candidate = false;
    }
    if (options.requireCredentialStamps && row.stamp !== "bound") {
      row.unbound = true;
      row.candidate = false;
    }
  }
  return rows;
}
var TRANSITION_STAMP_KEY, TRANSITION_MARK_KEY;
var init_torn = __esm({
  "../core/dist/common-auth-embedded/store/torn.js"() {
    "use strict";
    init_identity();
    init_schema();
    TRANSITION_STAMP_KEY = "transition";
    TRANSITION_MARK_KEY = "transitionMark";
  }
});

// ../core/dist/common-auth-embedded/store/mutate.js
import { readFile as readFile5 } from "node:fs/promises";
import { setTimeout as snapshotDelay } from "node:timers/promises";
async function readText(path2) {
  try {
    return await readFile5(path2, "utf8");
  } catch (error) {
    if (error.code === "ENOENT")
      return void 0;
    throw error;
  }
}
function parseFile(text2) {
  if (text2 === void 0)
    return { exists: false };
  try {
    return { exists: true, value: JSON.parse(text2) };
  } catch (parseError) {
    return { exists: true, parseError };
  }
}
async function readPool(ctx) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const configText = await readText(ctx.configPath);
    const stateText = await readText(ctx.statePath);
    const checkedConfigText = await readText(ctx.configPath);
    if (configText !== checkedConfigText) {
      if (attempt < 2)
        await snapshotDelay(2 + Math.floor(Math.random() * 4));
      continue;
    }
    const config = classifyConfig(parseFile(configText));
    if (config.status === "error")
      return { status: "error", file: "config", reason: config.reason };
    const state = classifyState(parseFile(stateText));
    if (state.status === "error")
      return { status: "error", file: "state", reason: state.reason };
    if (config.status === "pending-migration")
      return { status: "pending-migration", config: config.config };
    return {
      status: "ready",
      configExists: config.exists,
      stateExists: state.exists,
      config: config.config,
      state: state.state,
      rows: loadRows(config.config, state.state, ctx.codec, {
        requireCredentialStamps: ctx.requireCredentialStamps === true,
        ...ctx.providerState ? { providerState: ctx.providerState } : {}
      })
    };
  }
  return {
    status: "error",
    file: "config",
    kind: "snapshot-contended",
    retryable: true,
    reason: "The store was changing; retry the operation once writes settle."
  };
}
function notReadyError(result, operation, rowId2, phase = "before-first-write") {
  if (result.status === "error" && result.kind === "snapshot-contended")
    return new PoolOperationError({
      operation,
      ...rowId2 !== void 0 ? { rowId: rowId2 } : {},
      phase,
      kind: "snapshot-contended",
      retryable: true,
      message: result.reason
    });
  return new PoolOperationError({
    operation,
    ...rowId2 !== void 0 ? { rowId: rowId2 } : {},
    phase,
    retryable: false,
    kind: result.status === "pending-migration" ? "pending-migration" : "load-error",
    message: result.status === "pending-migration" ? "the config holds a legacy roster that has not been migrated into the pool" : `${result.file} file cannot be loaded: ${result.reason}`
  });
}
async function initializePool(ctx, dropKeys) {
  const locks = new LockStack(ctx.lockDefaults, ctx.lockEnv);
  const progress = { writes: 0 };
  try {
    for (const spec of ctx.storeLocks)
      await locks.acquire(spec);
    const result = await readPool(ctx);
    if (result.status === "error")
      throw notReadyError(result, "initialize", void 0);
    if (result.status === "ready")
      return "already-ready";
    const next = {};
    for (const [key, value] of Object.entries(result.config))
      if (!dropKeys.includes(key))
        next[key] = value;
    next.version = LEGACY_STORE_VERSION;
    next[POOL_KEY] = { schemaVersion: POOL_SCHEMA_VERSION, [POOL_ROWS_KEY]: {} };
    const info = { operation: "initialize", rowId: void 0 };
    await writeJsonAtomic2(ctx.configPath, next, {
      beforeRename: async () => {
        await ctx.onStep?.("before-config-write", info);
        await locks.assertAll();
      }
    });
    progress.writes++;
    await ctx.onStep?.("after-config-write", info);
    return "initialized";
  } catch (error) {
    throw toFailure(error, "initialize", void 0, progress);
  } finally {
    await locks.releaseAll();
  }
}
async function withTransaction(ctx, locks, progress, info, fn, options = {}) {
  const mark = locks.held.length;
  try {
    for (const spec of ctx.storeLocks)
      await locks.acquire(spec);
    const result = await readPool(ctx);
    if (result.status !== "ready")
      throw notReadyError(result, info.operation, info.rowId, progress.writes > 0 ? "after-first-write" : "before-first-write");
    const tx = new Transaction(ctx, result, locks, progress, info);
    if (info.rowId !== void 0 && !["add", "remove", "pull", "publishRoster", "enable", "disable"].includes(info.operation))
      tx.assertNotStaged(info.rowId);
    if (options.completeTorn ?? true)
      await tx.completeTorn();
    return await fn(tx);
  } finally {
    await locks.releaseTo(mark);
  }
}
function toFailure(error, operation, rowId2, progress) {
  const phase = operation === "pull" ? "pull" : progress.writes > 0 ? "after-first-write" : "before-first-write";
  const committed = phase === "after-first-write" ? progress.committed : void 0;
  if (operation === "publishRoster" && progress.publicationDecided)
    return new PoolOperationError({
      operation,
      ...rowId2 !== void 0 ? { rowId: rowId2 } : {},
      phase,
      kind: "publication-incomplete",
      retryable: true,
      message: "The publication may already be decided. Replay the same plan or check publication(operationId).",
      cause: error
    });
  if (operation === "publishRoster" && error instanceof AtomicSyncError)
    return new PoolOperationError({
      operation,
      ...rowId2 !== void 0 ? { rowId: rowId2 } : {},
      phase,
      kind: "publication-sync",
      retryable: true,
      message: "Publication sync failed before the decision; nothing was written. Retry the same plan.",
      cause: error
    });
  if (error instanceof PoolOperationError) {
    if (error.phase === phase && error.rowId === rowId2 && error.operation === operation && error.committed === committed)
      return error;
    return new PoolOperationError({
      operation,
      ...rowId2 !== void 0 ? { rowId: rowId2 } : {},
      phase: error.kind === "after-persist-hook" ? error.phase : phase,
      retryable: error.retryable,
      kind: error.kind,
      ...error.committed ?? committed ? { committed: error.committed ?? committed } : {},
      message: error.message,
      ...error.cause !== void 0 ? { cause: error.cause } : {}
    });
  }
  const base = {
    operation,
    ...rowId2 !== void 0 ? { rowId: rowId2 } : {},
    phase,
    ...committed ? { committed } : {},
    cause: error
  };
  if (error instanceof LockOwnershipError)
    return new PoolOperationError({
      ...base,
      retryable: true,
      kind: "lock-ownership",
      message: phase === "after-first-write" ? `${operation} lost a lease after its first write; the intermediate stays on disk` : `${operation} lost a lease before writing; nothing was written`
    });
  if (error instanceof LockContentionError)
    return new PoolOperationError({
      ...base,
      retryable: true,
      kind: "lock-contention",
      message: error.message
    });
  return new PoolOperationError({
    ...base,
    retryable: false,
    kind: "unexpected",
    message: error instanceof Error ? error.message : String(error)
  });
}
async function runOperation(ctx, operation, rowId2, onFailure, body) {
  const locks = new LockStack(ctx.lockDefaults, ctx.lockEnv);
  const progress = { writes: 0 };
  try {
    return await body(locks, progress);
  } catch (error) {
    const failure = toFailure(error, operation, rowId2, progress);
    if (failure.kind !== "after-persist-hook")
      await callFailureHook(operation, onFailure, rowId2, failure, ctx.logger);
    throw failure;
  } finally {
    await locks.releaseAll();
  }
}
var Transaction;
var init_mutate = __esm({
  "../core/dist/common-auth-embedded/store/mutate.js"() {
    "use strict";
    init_atomic_write();
    init_with_lock();
    init_errors();
    init_hooks();
    init_refresh_lock();
    init_reserved();
    init_schema();
    init_torn();
    Transaction = class {
      ctx;
      snapshot;
      locks;
      progress;
      info;
      config;
      state;
      constructor(ctx, snapshot2, locks, progress, info) {
        this.ctx = ctx;
        this.snapshot = snapshot2;
        this.locks = locks;
        this.progress = progress;
        this.info = info;
        this.config = structuredClone(snapshot2.config);
        this.state = structuredClone(snapshot2.state);
      }
      /**
       * The rows as every reader loads them: a row torn between the writes of a
       * replace is shown as that replace leaves it once completed (see
       * `PoolRow.torn`).
       */
      rows() {
        return loadRows(this.config, this.state, this.ctx.codec, {
          requireCredentialStamps: this.ctx.requireCredentialStamps === true,
          ...this.ctx.providerState ? { providerState: this.ctx.providerState } : {}
        });
      }
      row(id) {
        return this.rows().find((row) => row.id === id);
      }
      /** Read the config marker, or an orphan's stamp; never use a caller's reservation. */
      reservation(id) {
        if (this.rosterRow(id)) {
          const entry = this.entry(id);
          return entry && Object.hasOwn(entry, "staged") ? entry.staged : void 0;
        }
        const stamp = this.stateAccount(id)?.[CREDENTIAL_STAMP_KEY];
        return isRecord4(stamp) && Object.hasOwn(stamp, "staged") ? stamp.staged : void 0;
      }
      assertNotStaged(id) {
        assertNotReserved(this.info.operation, id, this.reservation(id));
      }
      roster() {
        if (!Array.isArray(this.config.accounts))
          this.config.accounts = [];
        return this.config.accounts;
      }
      /** The first roster row with this id (the one the pool loads). */
      rosterRow(id) {
        this.roster();
        return rosterRowIn(this.config, id);
      }
      /**
       * Drops every roster row carrying this id. The row's per-row entry goes with
       * it on the next `commitConfig`, which drops entries for ids no longer in
       * the roster. Returns how many roster rows were dropped.
       */
      dropRosterRows(id) {
        const roster = this.roster();
        const kept = roster.filter((raw) => !(isRecord4(raw) && raw.id === id));
        this.config.accounts = kept;
        return roster.length - kept.length;
      }
      entries() {
        return ensureEntries(this.config);
      }
      entry(id) {
        this.entries();
        return entryIn(this.config, id);
      }
      setEntry(id, entry) {
        setEntryIn(this.config, id, entry);
      }
      /**
       * Writes the config of every row torn between the writes of a replace, or
       * of a write giving it its first identity, as that write would have left it
       * (see `completeTornRows`), in one config
       * write ahead of the operation's own. The write is counted apart from the
       * operation's: it is setup, like a pull giving a row its entry, so a later
       * refusal still reports `before-first-write`.
       */
      async completeTorn() {
        const { config, torn } = completeTornRows(this.config, this.state, this.ctx.codec, { requireCredentialStamps: this.ctx.requireCredentialStamps === true });
        if (torn.length === 0)
          return;
        this.config = config;
        await this.commitConfig({ counted: false });
      }
      stateAccount(id) {
        const accounts = isRecord4(this.state.accounts) ? this.state.accounts : {};
        const entry = Object.hasOwn(accounts, id) ? accounts[id] : void 0;
        return isRecord4(entry) ? entry : void 0;
      }
      /** Drops the row's credential and runtime fields from the state file's accounts. */
      dropStateAccount(id) {
        if (isRecord4(this.state.accounts) && Object.hasOwn(this.state.accounts, id))
          delete this.state.accounts[id];
      }
      setStateAccount(id, fields) {
        if (!isRecord4(this.state.accounts))
          this.state.accounts = {};
        Object.defineProperty(this.state.accounts, id, {
          value: fields,
          enumerable: true,
          writable: true,
          configurable: true
        });
      }
      /**
       * Writes the config: legacy `version: 1` and the legacy roster beside
       * `commonAuthPool`, every other top-level key and every unrecognised pool
       * key untouched. Entries for ids no longer in the roster are dropped here,
       * and remembered so the id is not reused in this process. Every id the
       * write drops (a roster row the files held when the transaction read them,
       * or an entry left without one) has its epoch recorded in the config (see
       * `retireEpochsIn`), which is what keeps a later `add` of the id, from any
       * process, past every epoch an attribution could name.
       */
      async commitConfig(options = {}) {
        const roster = this.roster();
        const rosterIds = /* @__PURE__ */ new Set();
        for (const raw of roster)
          if (isRecord4(raw) && typeof raw.id === "string")
            rosterIds.add(raw.id);
        const dropped = /* @__PURE__ */ new Set();
        for (const raw of rosterOf(this.snapshot.config))
          if (isRecord4(raw) && typeof raw.id === "string" && !rosterIds.has(raw.id))
            dropped.add(raw.id);
        for (const id of Object.keys(this.entries()))
          if (!rosterIds.has(id))
            dropped.add(id);
        retireEpochsIn(this.config, dropped);
        const entries = this.entries();
        const kept = {};
        for (const [id, entry] of Object.entries(entries)) {
          if (rosterIds.has(id)) {
            Object.defineProperty(kept, id, {
              value: entry,
              enumerable: true,
              writable: true,
              configurable: true
            });
          }
        }
        const pool = this.config[POOL_KEY];
        const next = {
          ...this.config,
          version: LEGACY_STORE_VERSION,
          accounts: roster,
          [POOL_KEY]: {
            ...pool,
            schemaVersion: POOL_SCHEMA_VERSION,
            [POOL_ROWS_KEY]: kept
          }
        };
        await this.write(this.ctx.configPath, next, "config", options.counted ?? true, options.durable ?? false, () => {
          if (options.publicationDecision)
            this.markPublicationDecision();
          for (const id of dropped)
            this.ctx.removedIds.add(id);
          this.config = next;
        });
        this.config = next;
      }
      /** Writes the state: every unrecognised top-level and per-row key kept. */
      async commitState(committed, options = {}) {
        const next = {
          ...this.state,
          version: LEGACY_STORE_VERSION,
          accounts: isRecord4(this.state.accounts) ? this.state.accounts : {}
        };
        await this.write(this.ctx.statePath, next, "state", true, options.durable ?? false);
        this.state = next;
        if (committed)
          this.progress.committed = committed;
      }
      async assertAll() {
        await this.locks.assertAll();
      }
      async syncState() {
        await this.assertAll();
        try {
          if (this.snapshot.stateExists)
            await syncJsonFile(this.ctx.statePath);
        } catch (cause) {
          throw new PoolOperationError({
            operation: this.info.operation,
            rowId: this.info.rowId,
            phase: "before-first-write",
            kind: "publication-sync",
            retryable: true,
            message: "Publication sync failed before the decision; nothing was written. Retry the same plan.",
            cause
          });
        }
      }
      markPublicationDecision() {
        this.progress.publicationDecided = true;
      }
      async syncConfig() {
        await this.assertAll();
        await syncJsonFile(this.ctx.configPath);
      }
      async write(path2, value, file, counted = true, durable = false, onRenamed) {
        await writeJsonAtomicTracked(path2, value, {
          durable,
          beforeRename: async () => {
            await this.ctx.onStep?.(`before-${file}-write`, this.info);
            await this.locks.assertAll();
          }
        }, () => {
          if (counted)
            this.progress.writes++;
          onRenamed?.();
        });
        await this.ctx.onStep?.(`after-${file}-write`, this.info);
      }
    };
  }
});

// ../core/dist/common-auth-embedded/store/runtime.js
function rowLockSpec(rt, row) {
  return {
    ...rt.rowLockOptions,
    name: `row-${encodeURIComponent(rowLockKey(row))}`,
    path: rt.ctx.statePath
  };
}
async function readRow(rt, operation, id) {
  const result = await readPool(rt.ctx);
  if (result.status !== "ready")
    throw notReadyError(result, operation, id);
  const row = result.rows.find((candidate) => candidate.id === id);
  const entry = entryIn(result.config, id);
  const accounts = result.state.accounts;
  const account = isRecord4(accounts) && Object.hasOwn(accounts, id) ? accounts[id] : void 0;
  const stamp = isRecord4(account) ? account[CREDENTIAL_STAMP_KEY] : void 0;
  if (row && !["enable", "disable"].includes(operation) && entry && Object.hasOwn(entry, "staged"))
    assertNotReserved(operation, id, entry.staged);
  if (!row && isRecord4(stamp) && Object.hasOwn(stamp, "staged"))
    assertNotReserved(operation, id, stamp.staged);
  if (!row)
    throw unknownRow(operation, id);
  return { result, row };
}
function unknownRow(operation, id) {
  return new PoolOperationError({
    operation,
    rowId: id,
    phase: operation === "pull" ? "pull" : "before-first-write",
    retryable: false,
    kind: "unknown-row",
    message: `no row ${id} in the pool`
  });
}
function requireBound(operation, row) {
  // auto-permit credentials
}
function refusal2(operation, id, kind, message, retryable = false) {
  return new PoolOperationError({
    operation,
    rowId: id,
    phase: operation === "pull" ? "pull" : "before-first-write",
    retryable,
    kind,
    message
  });
}
var init_runtime = __esm({
  "../core/dist/common-auth-embedded/store/runtime.js"() {
    "use strict";
    init_errors();
    init_mutate();
    init_reserved();
    init_schema();
  }
});

// ../core/dist/common-auth-embedded/store/attribution.js
async function recordQuota(rt, id, attribution, observation) {
  const { ctx } = rt;
  const locks = new LockStack(ctx.lockDefaults, ctx.lockEnv);
  const progress = { writes: 0 };
  try {
    if (!isCredentialEpoch(attribution?.credentialEpoch))
      throw refusal2("pull", id, "invalid-input", "the credential epoch the reading was issued for must be a positive safe integer");
    await withTransaction(
      ctx,
      locks,
      progress,
      { operation: "pull", rowId: id },
      async (tx) => {
        tx.assertNotStaged(id);
        const row = tx.row(id);
        if (!row)
          throw unknownRow("pull", id);
        if (row.invalid)
          throw refusal2("pull", id, "invalid-row", `row ${id} is invalid`);
        if (!row.credential)
          throw refusal2("pull", id, "no-credential", `row ${id} holds no credential`);
        requireBound("pull", row);
        const entry = tx.entry(id);
        if (row.torn || !entry || entry.credentialEpoch !== attribution.credentialEpoch || row.identity !== attribution.identity)
          throw new PoolOperationError({
            operation: "pull",
            rowId: id,
            phase: "pull",
            retryable: true,
            kind: "attribution",
            message: `quota for ${id} was issued for a credential the row no longer holds`
          });
        const merged = ctx.codec.merge(entry.quota, observation);
        if (!ctx.codec.validate(merged))
          throw refusal2("pull", id, "invalid-quota", "the quota codec rejected the merged map");
        tx.setEntry(id, { ...entry, quota: merged, needsFirstReading: false });
        await tx.commitConfig();
      },
      // Recording a reading never completes a torn row: the fence above
      // refuses it, and the row's own next write completes it.
      { completeTorn: false }
    );
  } catch (error) {
    throw toFailure(error, "pull", id, progress);
  } finally {
    await locks.releaseAll();
  }
}
var init_attribution = __esm({
  "../core/dist/common-auth-embedded/store/attribution.js"() {
    "use strict";
    init_errors();
    init_mutate();
    init_refresh_lock();
    init_runtime();
    init_schema();
  }
});

// ../core/dist/common-auth-embedded/store/provider-state.js
function acceptProviderState(codec, operation, id, value, what = "the provider state") {
  if (!codec)
    throw refusal2(operation, id, "invalid-input", "the store was opened without a provider-state codec");
  let normalized;
  try {
    const text2 = JSON.stringify(value);
    normalized = text2 === void 0 ? void 0 : JSON.parse(text2);
  } catch {
    normalized = void 0;
  }
  if (normalized === void 0)
    throw refusal2(operation, id, "invalid-provider-state", `${what} cannot be stored as JSON`);
  if (!codec.validate(normalized))
    throw refusal2(operation, id, "invalid-provider-state", `the provider-state codec rejected ${what}`);
  return normalized;
}
function mergedProviderState(codec, operation, id, onDisk, incoming) {
  if (onDisk === void 0 || !codec?.merge)
    return { kind: "set", value: incoming };
  return {
    kind: "set",
    value: acceptProviderState(codec, operation, id, codec.merge(structuredClone(onDisk), structuredClone(incoming)), "the merged provider state")
  };
}
function replacementProviderState(codec, row, credentialEpoch2, identity, incoming) {
  const hook = codec?.onReplace;
  const next = hook ? hook(row.providerState === void 0 ? void 0 : structuredClone(row.providerState), {
    id: row.id,
    credentialEpoch: credentialEpoch2,
    ...row.identity !== void 0 ? { previousIdentity: row.identity } : {},
    ...identity !== void 0 ? { identity } : {},
    ...incoming !== void 0 ? { incoming: structuredClone(incoming) } : {}
  }) : incoming;
  if (next === void 0)
    return { kind: "clear" };
  if (!hook)
    return { kind: "set", value: next };
  return {
    kind: "set",
    value: acceptProviderState(codec, "replace", row.id, next, "the provider state onReplace returned")
  };
}
function providerStateCoverage(codec, write, prior, priorRow, credentialEpoch2) {
  if (write.kind === "set")
    return providerStateDigest(codec, write.value);
  if (write.kind === "clear")
    return void 0;
  return boundProviderStateDigest(prior, priorRow?.credential, credentialEpoch2, priorRow?.identity);
}
async function updateProviderStateRow(rt, id, fence, mutator, options = {}) {
  assertNotInsideHook("updateProviderState");
  const { ctx } = rt;
  const operation = "updateProviderState";
  return runOperation(ctx, operation, id, options.onFailure, async (locks, progress) => {
    const codec = ctx.providerState;
    if (!codec)
      throw refusal2(operation, id, "invalid-input", "the store was opened without a provider-state codec");
    if (typeof mutator !== "function")
      throw refusal2(operation, id, "invalid-input", "a mutator is required");
    const captured = isRecord4(fence) ? fence.credentialEpoch : void 0;
    if (!isCredentialEpoch(captured))
      throw refusal2(operation, id, "invalid-input", "the credential epoch the provider state was read at is required");
    const { row: seen } = await readRow(rt, operation, id);
    await locks.acquire(rowLockSpec(rt, seen));
    for (const extra of options.extraLocks ?? [])
      await locks.acquire(extra);
    return withTransaction(ctx, locks, progress, { operation, rowId: id }, async (tx) => {
      const row = tx.row(id);
      if (!row)
        throw unknownRow(operation, id);
      if (rowLockKey(row) !== rowLockKey(seen))
        throw refusal2(operation, id, "row-key-changed", `row ${id}'s wire identity changed while its lock was being taken`, true);
      if (row.invalid)
        throw refusal2(operation, id, "invalid-row", `row ${id} failed validation`);
      if (!row.credential)
        throw refusal2(operation, id, "no-credential", `row ${id} holds no credential`);
      requireBound(operation, row);
      const epoch = row.credentialEpoch ?? 1;
      if (epoch !== captured || row.identity !== fence.identity)
        throw refusal2(operation, id, "attribution", `the provider state for ${id} was read for a credential or account the row no longer holds`, true);
      const plan = await planProviderStateIn(tx, codec, operation, row, mutator);
      if (plan.kind !== "changed")
        return {
          id,
          outcome: "unchanged",
          ...plan.kind === "unchanged" && plan.value !== void 0 ? { providerState: plan.value } : {}
        };
      tx.setStateAccount(id, plan.account);
      await tx.commitState();
      return plan.value === void 0 ? { id, outcome: "cleared" } : { id, outcome: "updated", providerState: plan.value };
    });
  });
}
async function planProviderStateIn(tx, codec, operation, row, mutator, declinable = false) {
  const id = row.id;
  const credential = row.credential;
  if (!credential)
    throw refusal2(operation, id, "no-credential", `row ${id} holds no credential`);
  const epoch = row.credentialEpoch ?? 1;
  const account = tx.stateAccount(id);
  let rawStamp = account?.[CREDENTIAL_STAMP_KEY];
  let stamp = parseStamp(rawStamp);
  if (!isRecord4(rawStamp) || !stamp?.binding || stamp.digest !== credentialDigest(credential) || stamp.credentialEpoch !== epoch || stamp.binding.identity !== row.identity) {
    rawStamp = stampFor(credential, epoch, bindingInTx(tx, id, credential, row.identity));
    stamp = parseStamp(rawStamp);
  }
  const current = row.providerState === void 0 ? void 0 : structuredClone(row.providerState);
  const returned = await runInsideHook(operation, () => mutator(current, row));
  if (declinable && returned === DECLINE_TRANSITION)
    return { kind: "declined" };
  const next = returned === void 0 ? void 0 : acceptProviderState(codec, operation, id, returned, "the provider state the mutator returned");
  const held2 = account !== void 0 && Object.hasOwn(account, PROVIDER_STATE_KEY);
  if (next === void 0 ? !held2 : row.providerState !== void 0 && JSON.stringify(row.providerState) === JSON.stringify(next))
    return { kind: "unchanged", ...next !== void 0 ? { value: next } : {} };
  const nextAccount = { ...account };
  if (next === void 0) {
    delete nextAccount[PROVIDER_STATE_KEY];
    const nextStamp = { ...rawStamp };
    delete nextStamp.providerState;
    nextAccount[CREDENTIAL_STAMP_KEY] = nextStamp;
  } else {
    nextAccount[PROVIDER_STATE_KEY] = next;
    const digest3 = providerStateDigest(codec, next);
    if (stamp.providerState !== digest3)
      nextAccount[CREDENTIAL_STAMP_KEY] = { ...rawStamp, providerState: digest3 };
  }
  return {
    kind: "changed",
    ...next !== void 0 ? { value: next } : {},
    account: nextAccount
  };
}
var DECLINE_TRANSITION;
var init_provider_state = __esm({
  "../core/dist/common-auth-embedded/store/provider-state.js"() {
    "use strict";
    init_hooks();
    init_mutate();
    init_runtime();
    init_schema();
    DECLINE_TRANSITION = /* @__PURE__ */ Symbol.for("@cortexkit/common-auth/store/decline-transition");
  }
});

// ../core/dist/common-auth-embedded/store/rows.js
import { randomUUID as randomUUID7 } from "node:crypto";
async function protectIn(tx, id, protect) {
  if (!protect)
    return;
  const rows = tx.rows().map((row) => {
    const { id: id2, type, label, enabled, disabledReason, identity, credentialEpoch: credentialEpoch2, stamp, staged, torn, invalid } = row;
    return {
      id: id2,
      type,
      label,
      enabled,
      disabledReason,
      identity,
      credentialEpoch: credentialEpoch2,
      stamp,
      staged,
      torn,
      invalid
    };
  });
  const reason = await runInsideHook(tx.info.operation, () => protect({
    id,
    row: rows.find((row) => row.id === id),
    rows,
    config: structuredClone(tx.snapshot.config)
  }));
  if (reason !== void 0)
    throw refusal2(tx.info.operation, id, "row-protected", reason);
}
function rowEndpoint(raw) {
  return {
    baseURL: String(raw.baseURL).trim(),
    authHeader: raw.authHeader === "x-api-key" ? "x-api-key" : "authorization-bearer"
  };
}
function onRowEndpoint(tx, id, credential) {
  if (credential.type !== "api")
    return credential;
  const raw = tx.rosterRow(id);
  if (!isRecord4(raw)) {
    if (credential.baseURL === void 0)
      throw refusal2(tx.info.operation, id, "invalid-input", "api credential needs a valid baseURL");
    return { ...credential, baseURL: credential.baseURL };
  }
  const projected2 = tx.row(id)?.credential;
  const endpoint = projected2?.type === "api" ? {
    baseURL: projected2.baseURL.trim(),
    authHeader: projected2.authHeader ?? "authorization-bearer"
  } : rowEndpoint(raw);
  const baseURL = credential.baseURL?.trim() ?? endpoint.baseURL;
  const authHeader = credential.authHeader ?? endpoint.authHeader;
  if (baseURL !== endpoint.baseURL || authHeader !== endpoint.authHeader)
    throw refusal2(tx.info.operation, id, "endpoint-mismatch", `row ${id} sends its key to another endpoint or header; a key for another endpoint is a replacement`);
  return { ...credential, baseURL, authHeader };
}
function bindingInTx(tx, id, stored, learnt) {
  const raw = tx.rosterRow(id);
  const projected2 = tx.row(id);
  const identity = learnt ?? (projected2 ? projected2.identity : isRecord4(raw) && typeof raw.accountId === "string" && raw.accountId ? raw.accountId : void 0);
  return {
    ...identity !== void 0 ? { identity } : {},
    ...stored.type === "api" ? {
      baseURL: stored.baseURL,
      authHeader: stored.authHeader ?? "authorization-bearer"
    } : {}
  };
}
function planRotationIn(rt, tx, id, given, extra = {}) {
  const credential = onRowEndpoint(tx, id, given);
  const prior = tx.stateAccount(id);
  const stateWrite = extra.providerState ?? { kind: "keep" };
  const epoch = tx.row(id)?.credentialEpoch ?? tx.entry(id)?.credentialEpoch;
  const credentialEpoch2 = typeof epoch === "number" ? epoch : 1;
  const providerStateBinding = providerStateCoverage(rt.ctx.providerState, stateWrite, prior, prior && Object.hasOwn(prior, PROVIDER_STATE_KEY) ? tx.row(id) : void 0, credentialEpoch2);
  const priorStamp = typeof prior?.lastRefreshedAt === "number" ? prior.lastRefreshedAt : void 0;
  const stamp = credential.type === "oauth" ? extra.stamp ?? rotationStamp(priorStamp, rt.ctx.now()) : void 0;
  const kept = { ...prior ?? {} };
  for (const field of CREDENTIAL_STATE_FIELDS)
    delete kept[field];
  if (extra.clearErrors) {
    delete kept.lastRefreshError;
    delete kept.lastQuotaRefreshError;
    delete kept.quota;
  }
  if (stateWrite.kind === "clear")
    delete kept[PROVIDER_STATE_KEY];
  else if (stateWrite.kind === "set")
    kept[PROVIDER_STATE_KEY] = stateWrite.value;
  const stored = storedCredential(credential, stamp);
  const account = {
    ...kept,
    ...stateFieldsFor(credential, stamp),
    [CREDENTIAL_STAMP_KEY]: {
      ...extra.staged ? { staged: extra.staged } : {},
      ...extra.transition !== void 0 ? { [TRANSITION_STAMP_KEY]: extra.transition } : {},
      ...stampFor(stored, credentialEpoch2, extra.binding ?? bindingInTx(tx, id, stored, extra.identity), {
        replace: extra.binding !== void 0,
        ...providerStateBinding !== void 0 ? { providerState: providerStateBinding } : {}
      })
    }
  };
  return { stored, account };
}
async function persistRotationIn(tx, id, plan) {
  tx.setStateAccount(id, plan.account);
  await tx.commitState(plan.stored);
  return plan.stored;
}
async function rotateIn(rt, tx, id, given, extra = {}) {
  return persistRotationIn(tx, id, planRotationIn(rt, tx, id, given, extra));
}
async function stampIdentityIn(tx, row, identity) {
  if (!row.credential || row.stamp !== "bound")
    return;
  const account = tx.stateAccount(row.id);
  const providerState = boundProviderStateDigest(account, row.credential, row.credentialEpoch ?? 1, row.identity);
  tx.setStateAccount(row.id, {
    ...account ?? {},
    [CREDENTIAL_STAMP_KEY]: stampFor(row.credential, row.credentialEpoch ?? 1, bindingInTx(tx, row.id, row.credential, identity), providerState !== void 0 ? { providerState } : {})
  });
  await tx.commitState();
}
function checkInput(operation, id, credential) {
  const idIssue = operation === "add" ? idProblem(id) : void 0;
  if (idIssue)
    throw refusal2(operation, id, "invalid-input", idIssue);
  const credentialIssue = credentialProblem(credential, {
    baseURLOptional: operation === "rotate"
  });
  if (credentialIssue)
    throw refusal2(operation, id, "invalid-input", credentialIssue);
}
function requireUsableRow(operation, id, row, credential) {
  if (!row)
    throw unknownRow(operation, id);
  if (row.invalid)
    throw refusal2(operation, id, "invalid-row", `row ${id} failed validation`);
  if (credential && credential.type !== row.type)
    throw refusal2(operation, id, "type-mismatch", `row ${id} holds a ${row.type} credential`);
  return row;
}
function validateAttribution(operation, id, fence) {
  if (fence !== void 0 && !isCredentialEpoch(isRecord4(fence) ? fence.credentialEpoch : void 0))
    throw refusal2(operation, id, "invalid-input", "the attribution must name a credential epoch that is a positive safe integer");
}
function assertRowAttribution(operation, id, row, fence) {
  if (!row)
    throw unknownRow(operation, id);
  if (row.invalid)
    throw refusal2(operation, id, "invalid-row", `row ${id} failed validation`);
  if ((row.credentialEpoch ?? 1) !== fence.credentialEpoch || row.identity !== fence.identity)
    throw refusal2(operation, id, "attribution", `the ${operation} of ${id} was issued for a credential or account the row no longer holds`, true);
}
function identityMismatch(operation, id) {
  return refusal2(operation, id, "identity-mismatch", `row ${id} is recorded for another account; a credential of a different account is a replacement`);
}
function keyChanged(operation, id) {
  return refusal2(operation, id, "row-key-changed", `row ${id}'s wire identity changed while its lock was being taken`, true);
}
function matchingInterruptedAdd(rt, tx, input, incoming) {
  const { id, credential, identity } = input;
  if (!rt.ctx.requireCredentialStamps || tx.rosterRow(id) || !hasStateAccount(tx.state, id))
    return void 0;
  const refuse = () => {
    throw refusal2("add", id, "unbound-credential", `orphan ${id} cannot be bound to this add's material; remove it explicitly before adding different material`);
  };
  const account = tx.stateAccount(id);
  const stamp = parseStamp(account?.[CREDENTIAL_STAMP_KEY]);
  if (!stamp?.binding || stamp.dispatch === void 0 || stamp.replace)
    return refuse();
  if (credential.type === "api" && (stamp.binding.baseURL === void 0 || stamp.binding.authHeader === void 0))
    return refuse();
  const descriptor = credential.type === "api" ? {
    ...credential,
    baseURL: stamp.binding.baseURL,
    authHeader: stamp.binding.authHeader
  } : credential;
  const [orphan] = buildRawRows({
    accounts: [
      rosterRowFor({
        id,
        credential: descriptor,
        identity: stamp.binding.identity,
        addedAt: 0
      })
    ],
    [POOL_KEY]: {
      rows: { [id]: { credentialEpoch: nextAddEpochIn(tx.config, id) } }
    }
  }, tx.state, rt.ctx.codec, rt.ctx.providerState);
  if (!orphan?.credential || orphan.invalid || orphan.stamp !== "bound")
    return refuse();
  if (identity !== void 0 && identity !== orphan.identity)
    return refuse();
  if (credentialDigest(credential) !== stamp.digest)
    return refuse();
  if (credential.type === "api") {
    if (credential.baseURL.trim() !== stamp.binding.baseURL)
      return refuse();
    if ((credential.authHeader ?? "authorization-bearer") !== stamp.binding.authHeader)
      return refuse();
  } else if (dispatchDigest(credential) !== stamp.dispatch)
    return refuse();
  if (stamp.providerState !== void 0 && orphan.providerState === void 0)
    return refuse();
  if (incoming !== void 0 && providerStateDigest(rt.ctx.providerState, incoming) !== stamp.providerState)
    return refuse();
  return orphan;
}
function replayStagedAdd(rt, tx, input, incoming) {
  const { id, credential, identity, label } = input;
  const raw = tx.rosterRow(id);
  const fail2 = () => {
    throw refusal2("add", id, raw ? "id-exists" : "unbound-credential", `row ${id} does not match this staged add`);
  };
  const account = tx.stateAccount(id);
  const stamp = parseStamp(account?.[CREDENTIAL_STAMP_KEY]);
  const staged = stamp?.staged;
  if (!stamp?.binding || !staged || stamp.replace || stamp.dispatch === void 0)
    return fail2();
  if (raw && (raw.type !== credential.type || raw.label !== label || raw.accountId !== identity))
    return fail2();
  if (staged.reservation !== input.stage?.reservation || staged.label !== label || staged.disabledReason !== input.disabled?.reason || stamp.binding.identity !== identity)
    return fail2();
  const incomingDigest = incoming === void 0 ? void 0 : canonicalDigest(incoming);
  const storedValue = account?.[PROVIDER_STATE_KEY];
  const storedDigest = storedValue === void 0 ? void 0 : canonicalDigest(storedValue);
  if (staged.providerState !== incomingDigest || staged.providerState !== storedDigest)
    return fail2();
  if (credentialDigest(credential) !== stamp.digest || dispatchDigest(credential) !== stamp.dispatch)
    return fail2();
  const config = raw ? tx.config : {
    accounts: [
      {
        ...rosterRowFor({
          id,
          credential: credential.type === "api" ? {
            ...credential,
            baseURL: stamp.binding.baseURL ?? "",
            authHeader: stamp.binding.authHeader
          } : credential,
          identity: stamp.binding.identity,
          label: staged.label,
          addedAt: 0
        }),
        enabled: false
      }
    ],
    [POOL_KEY]: {
      rows: {
        [id]: {
          credentialEpoch: stamp.credentialEpoch,
          disabledReason: staged.disabledReason,
          staged: { reservation: staged.reservation }
        }
      }
    }
  };
  const row = buildRawRows(config, tx.state, rt.ctx.codec, rt.ctx.providerState).find((row2) => row2.id === id);
  if (!row?.credential || row.invalid || row.stamp !== "bound" || row.type !== credential.type || row.enabled || row.label !== staged.label || row.identity !== stamp.binding.identity || row.disabledReason !== staged.disabledReason || row.staged?.reservation !== staged.reservation)
    return fail2();
  if (raw)
    return {
      id,
      outcome: "exists",
      credential: row.credential,
      credentialEpoch: stamp.credentialEpoch
    };
  if (nextAddEpochIn(tx.config, id) !== stamp.credentialEpoch)
    return fail2();
  tx.roster().push({
    ...rosterRowFor({ id, credential, identity, label, addedAt: rt.ctx.now() }),
    enabled: false
  });
  tx.setEntry(id, {
    credentialEpoch: stamp.credentialEpoch,
    needsFirstReading: credential.type === "oauth",
    disabledReason: staged.disabledReason,
    staged: { reservation: staged.reservation }
  });
  return tx.commitConfig().then(() => ({
    id,
    outcome: "completed",
    credential: row.credential,
    credentialEpoch: stamp.credentialEpoch
  }));
}
async function addRow(rt, input, options = {}) {
  assertNotInsideHook("add");
  const { ctx } = rt;
  const { id, credential, identity, label } = input;
  const preparing = input.stage !== void 0 || input.disabled !== void 0;
  const result = await runOperation(ctx, "add", id, options.onFailure, async (locks, progress) => {
    checkInput("add", id, credential);
    const mode = options.onExisting ?? "rotate";
    if (input.stage !== void 0 && mode === "rotate")
      throw refusal2("add", id, "invalid-input", "a staged add needs onExisting: 'refuse' or 'stage-duplicate'");
    if (!["rotate", "refuse", "stage-duplicate"].includes(mode) || input.stage !== void 0 && (label !== void 0 && typeof label !== "string" || identity !== void 0 && (typeof identity !== "string" || !identity)) || input.disabled !== void 0 && (!isRecord4(input.disabled) || typeof input.disabled.reason !== "string") || input.stage !== void 0 && (!isRecord4(input.stage) || typeof input.stage.reservation !== "string" || !input.stage.reservation || !input.disabled) || mode === "stage-duplicate" && (!input.disabled || !input.stage))
      throw refusal2("add", id, "invalid-input", "staging requires a reservation and a disabled reason");
    const incoming = input.providerState === void 0 ? void 0 : acceptProviderState(ctx.providerState, "add", id, input.providerState);
    await locks.acquire(rowLockSpec(rt, { id, identity }));
    if (credential.type === "oauth")
      await locks.acquire(options.providerLock ?? rt.providerLock);
    for (const extra of options.extraLocks ?? [])
      await locks.acquire(extra);
    return withTransaction(ctx, locks, progress, { operation: "add", rowId: id }, async (tx) => {
      await protectIn(tx, id, options.protect);
      const stateAccounts = isRecord4(tx.state.accounts) ? tx.state.accounts : {};
      const stagedOrphan = Object.entries(stateAccounts).find(([orphanId, account]) => {
        if (orphanId === id || tx.rosterRow(orphanId) || !isRecord4(account))
          return false;
        const stamp = account[CREDENTIAL_STAMP_KEY];
        if (!isRecord4(stamp) || !Object.hasOwn(stamp, "staged"))
          return false;
        return credential.type === "oauth" ? account.refresh === credential.refresh : typeof account.apiKey === "string" && account.apiKey.trim() === credential.apiKey.trim();
      });
      if (stagedOrphan)
        throw refusal2("add", stagedOrphan[0], "row-staged", `orphan ${stagedOrphan[0]} reserves this secret until its staged add is replayed or removed`);
      if (ctx.removedIds.has(id))
        throw refusal2("add", id, "id-removed", `id ${id} was removed from the roster in this process and is not reused`);
      if (input.stage && mode !== "rotate" && (tx.rosterRow(id) || hasStateAccount(tx.state, id)))
        return replayStagedAdd(rt, tx, input, incoming);
      if (mode === "rotate") {
        tx.assertNotStaged(id);
        const holder = tx.rows().find((row) => row.fingerprint === fingerprintOf(credential));
        if (holder)
          tx.assertNotStaged(holder.id);
      }
      if (mode === "refuse") {
        const holder = tx.rows().find((row) => row.fingerprint === fingerprintOf(credential) || row.id === id && row.credential);
        const accounts = isRecord4(tx.state.accounts) ? tx.state.accounts : {};
        const stateHolder = Object.entries(accounts).find(([, account]) => {
          if (!isRecord4(account))
            return false;
          if (credential.type === "oauth")
            return account.refresh === credential.refresh;
          return typeof account.apiKey === "string" && account.apiKey.trim() === credential.apiKey.trim();
        })?.[0];
        const holdingId = holder?.id ?? stateHolder ?? id;
        if (holder || stateHolder !== void 0 || hasStateAccount(tx.state, id))
          throw refusal2("add", holdingId, "credential-exists", `row ${holdingId} already holds this secret or id`);
      }
      if (mode === "stage-duplicate" && (tx.rosterRow(id) || hasStateAccount(tx.state, id)))
        throw refusal2("add", id, "id-exists", `row ${id} already exists`);
      const orphan = matchingInterruptedAdd(rt, tx, input, incoming);
      const rows = tx.rows();
      const fingerprint = fingerprintOf(credential);
      const same = mode === "rotate" && !orphan && rows.find((row) => row.invalid === void 0 && row.fingerprint === fingerprint);
      if (same) {
        tx.assertNotStaged(same.id);
        requireBound("add", same);
        if (identity !== void 0 && same.identity !== void 0 && identity !== same.identity)
          throw identityMismatch("add", same.id);
        const prepared2 = planRotationIn(rt, tx, same.id, credential, {
          ...incoming !== void 0 ? {
            providerState: mergedProviderState(ctx.providerState, "add", same.id, same.providerState, incoming)
          } : {}
        });
        await tx.completeTorn();
        tx.assertNotStaged(same.id);
        const stored2 = await persistRotationIn(tx, same.id, prepared2);
        return {
          id: same.id,
          outcome: "rotated",
          credential: stored2,
          credentialEpoch: same.credentialEpoch ?? 1
        };
      }
      const existing = rows.find((row) => row.id === id);
      if (existing) {
        if (existing.invalid)
          throw refusal2("add", id, "invalid-row", `row ${id} is invalid`);
        if (existing.credential)
          throw refusal2("add", id, "id-exists", `row ${id} already holds a credential`);
        requireBound("add", existing);
        if (existing.type !== credential.type)
          throw refusal2("add", id, "type-mismatch", `row ${id} is a ${existing.type} row`);
        if (identity !== void 0 && existing.identity !== void 0 && identity !== existing.identity)
          throw identityMismatch("add", id);
        if (!existing.hasEntry)
          tx.setEntry(id, {
            credentialEpoch: 1,
            needsFirstReading: credential.type === "oauth"
          });
        const prepared2 = planRotationIn(rt, tx, id, credential, {
          clearErrors: true,
          ...incoming !== void 0 ? { providerState: { kind: "set", value: incoming } } : {}
        });
        await tx.completeTorn();
        const stored2 = await persistRotationIn(tx, id, prepared2);
        if (!existing.hasEntry)
          await tx.commitConfig();
        return {
          id,
          outcome: "completed",
          credential: stored2,
          credentialEpoch: existing.credentialEpoch ?? 1
        };
      }
      const credentialEpoch2 = nextAddEpochIn(tx.config, id);
      if (!isCredentialEpoch(credentialEpoch2))
        throw refusal2("add", id, "id-removed", `id ${id} has held every credential epoch and is not reused; add the credential under another id`);
      const addedIdentity = orphan?.identity ?? identity;
      tx.roster().push(rosterRowFor({
        id,
        credential,
        ...addedIdentity !== void 0 ? { identity: addedIdentity } : {},
        ...label !== void 0 ? { label } : {},
        addedAt: ctx.now()
      }));
      tx.setEntry(id, {
        credentialEpoch: credentialEpoch2,
        needsFirstReading: credential.type === "oauth",
        ...input.stage ? { staged: { reservation: input.stage.reservation } } : {}
      });
      let outcome = "added";
      if (input.disabled) {
        disableIn(tx, id, input.disabled.reason);
        outcome = "added-disabled";
      }
      if (!input.disabled && addedIdentity !== void 0 && credential.type === "oauth") {
        const holder = rows.find((row) => row.invalid === void 0 && row.type === "oauth" && row.enabled && row.identity === addedIdentity);
        if (holder) {
          disableIn(tx, id, DUPLICATE_IDENTITY_REASON);
          outcome = "added-disabled";
        }
      }
      if (orphan?.credential) {
        await tx.commitConfig();
        return {
          id,
          outcome,
          credential: orphan.credential,
          credentialEpoch: orphan.credentialEpoch ?? credentialEpoch2
        };
      }
      tx.dropStateAccount(id);
      const prepared = planRotationIn(rt, tx, id, credential, {
        ...input.stage && input.disabled ? {
          staged: {
            reservation: input.stage.reservation,
            disabledReason: input.disabled.reason,
            ...label !== void 0 ? { label } : {},
            ...incoming !== void 0 ? { providerState: canonicalDigest(incoming) } : {}
          }
        } : {},
        ...incoming !== void 0 ? { providerState: { kind: "set", value: incoming } } : {}
      });
      if (mode === "rotate")
        await tx.completeTorn();
      const stored = await persistRotationIn(tx, id, prepared);
      await tx.commitConfig();
      return { id, outcome, credential: stored, credentialEpoch: credentialEpoch2 };
    }, { completeTorn: false });
  });
  if (!preparing && credential.type === "oauth" && (result.outcome === "added" || result.outcome === "completed"))
    rt.firePull(result.id, "add");
  return result;
}
async function replaceRow(rt, id, credential, input = {}, options = {}) {
  assertNotInsideHook("replace");
  const { ctx } = rt;
  const result = await runOperation(ctx, "replace", id, options.onFailure, async (locks, progress) => {
    checkInput("replace", id, credential);
    validateAttribution("replace", id, options.attribution);
    const incoming = input.providerState === void 0 ? void 0 : acceptProviderState(ctx.providerState, "replace", id, input.providerState);
    const { row: seen } = await readRow(rt, "replace", id);
    await locks.acquire(rowLockSpec(rt, seen));
    if (credential.type === "oauth")
      await locks.acquire(options.providerLock ?? rt.providerLock);
    for (const extra of options.extraLocks ?? [])
      await locks.acquire(extra);
    return withTransaction(ctx, locks, progress, { operation: "replace", rowId: id }, async (tx) => {
      if (options.attribution !== void 0) {
        assertRowAttribution("replace", id, tx.row(id), options.attribution);
        await tx.completeTorn();
      }
      const row = requireUsableRow("replace", id, tx.row(id), credential);
      if (rowLockKey(row) !== rowLockKey(seen))
        throw keyChanged("replace", id);
      const priorEpoch = tx.entry(id)?.credentialEpoch;
      const credentialEpoch2 = (typeof priorEpoch === "number" ? priorEpoch : 1) + 1;
      if (!isCredentialEpoch(credentialEpoch2))
        throw refusal2("replace", id, "invalid-row", `row ${id}'s credential epoch cannot advance past ${Number.MAX_SAFE_INTEGER}; remove the row and add the new credential as a new row`);
      const providerState = replacementProviderState(ctx.providerState, row, credentialEpoch2, input.identity, incoming);
      const binding = {
        ...input.identity !== void 0 ? { identity: input.identity } : {},
        ...credential.type === "api" ? {
          baseURL: credential.baseURL.trim(),
          authHeader: credential.authHeader ?? "authorization-bearer"
        } : {}
      };
      bindReplacement(tx, id, credentialEpoch2, binding);
      if (input.identity !== void 0)
        disableIdentityDuplicates(tx, input.identity);
      const stored = await rotateIn(rt, tx, id, credential, {
        clearErrors: true,
        binding,
        providerState
      });
      await tx.commitConfig();
      return { id, credential: stored, credentialEpoch: credentialEpoch2 };
    }, { completeTorn: options.attribution === void 0 });
  });
  if (credential.type === "oauth")
    rt.firePull(id, "replace");
  return result;
}
async function rotateRow(rt, id, credential, input = {}, options = {}) {
  assertNotInsideHook("rotate");
  const { ctx } = rt;
  return runOperation(ctx, "rotate", id, options.onFailure, async (locks, progress) => {
    checkInput("rotate", id, credential);
    validateAttribution("rotate", id, options.attribution);
    const incoming = input.providerState === void 0 ? void 0 : acceptProviderState(ctx.providerState, "rotate", id, input.providerState);
    const { row: seen } = await readRow(rt, "rotate", id);
    await locks.acquire(rowLockSpec(rt, seen));
    if (input.identity !== void 0 && credential.type === "oauth")
      await locks.acquire(options.providerLock ?? rt.providerLock);
    for (const extra of options.extraLocks ?? [])
      await locks.acquire(extra);
    return withTransaction(ctx, locks, progress, { operation: "rotate", rowId: id }, async (tx) => {
      if (options.attribution !== void 0) {
        assertRowAttribution("rotate", id, tx.row(id), options.attribution);
        await tx.completeTorn();
      }
      const row = requireUsableRow("rotate", id, tx.row(id), credential);
      if (rowLockKey(row) !== rowLockKey(seen))
        throw keyChanged("rotate", id);
      requireBound("rotate", row);
      if (input.identity !== void 0 && row.identity !== void 0 && input.identity !== row.identity)
        throw identityMismatch("rotate", id);
      const learnt = input.identity !== void 0 && row.identity === void 0 ? input.identity : void 0;
      const stored = await rotateIn(rt, tx, id, credential, {
        identity: learnt,
        ...incoming !== void 0 ? {
          providerState: mergedProviderState(ctx.providerState, "rotate", id, row.providerState, incoming)
        } : {}
      });
      let configChanged = false;
      if (!row.hasEntry) {
        tx.setEntry(id, {
          credentialEpoch: 1,
          needsFirstReading: row.type === "oauth"
        });
        configChanged = true;
      }
      if (input.identity !== void 0 && row.identity !== input.identity) {
        recordIdentityIn(tx, id, input.identity);
        configChanged = true;
      }
      if (configChanged)
        await tx.commitConfig();
      return { id, credential: stored };
    }, { completeTorn: options.attribution === void 0 });
  });
}
async function transitionRow(rt, operation, id, flag, options) {
  assertNotInsideHook(operation);
  const { ctx } = rt;
  const codec = ctx.providerState;
  const fence = options.attribution;
  const mutator = options.providerState;
  return runOperation(ctx, operation, id, options.onFailure, async (locks, progress) => {
    validateAttribution(operation, id, fence);
    if (mutator !== void 0) {
      if (typeof mutator !== "function")
        throw refusal2(operation, id, "invalid-input", "the provider-state mutator must be a function");
      if (fence === void 0)
        throw refusal2(operation, id, "invalid-input", "a provider-state change needs the attribution of the credential it is for");
      if (!codec)
        throw refusal2(operation, id, "invalid-input", "the store was opened without a provider-state codec");
    }
    const { row: seen } = await readRow(rt, operation, id);
    await locks.acquire(rowLockSpec(rt, seen));
    for (const extra of options.extraLocks ?? [])
      await locks.acquire(extra);
    return withTransaction(ctx, locks, progress, { operation, rowId: id }, async (tx) => {
      await protectIn(tx, id, options.protect);
      tx.assertNotStaged(id);
      const loaded = tx.row(id);
      const row = flag.enabled ? requireUsableRow("enable", id, loaded) : loaded;
      if (!row || !tx.rosterRow(id))
        throw unknownRow(operation, id);
      if (rowLockKey(row) !== rowLockKey(seen))
        throw keyChanged(operation, id);
      if (fence !== void 0) {
        assertRowAttribution(operation, id, row, fence);
      }
      if (flag.enabled && row.disabledReason?.startsWith(IDENTITY_CONTRADICTED_REASON_PREFIX))
        throw refusal2("enable", id, "identity-contradicted", `row ${id} needs an identity-validated credential replacement before it can be enabled`);
      const writesConfig = !flag.enabled || !row.enabled || row.disabledReason !== void 0;
      if (flag.enabled && writesConfig && row.type === "oauth") {
        const holder = row.identity === void 0 ? void 0 : tx.rows().find((other) => other.id !== id && other.invalid === void 0 && other.type === "oauth" && other.enabled && other.identity === row.identity);
        if (holder)
          throw refusal2("enable", id, "duplicate-identity", `row ${holder.id} is enabled with the same identity as row ${id}`);
      }
      if (mutator === void 0 || codec === void 0) {
        await tx.completeTorn();
        if (!writesConfig)
          return { id };
        if (flag.enabled)
          enableIn(tx, id);
        else
          disableIn(tx, id, flag.reason);
        await tx.commitConfig();
        return { id };
      }
      if (!row.credential)
        throw refusal2(operation, id, "no-credential", `row ${id} holds no credential`);
      requireBound(operation, row);
      const plan = await planProviderStateIn(tx, codec, operation, row, mutator, true);
      if (plan.kind === "declined")
        return { id, declined: true };
      await tx.completeTorn();
      const result = {
        id,
        providerStateOutcome: plan.kind === "unchanged" ? "unchanged" : plan.value === void 0 ? "cleared" : "updated",
        ...plan.value !== void 0 ? { providerState: plan.value } : {}
      };
      if (plan.kind === "unchanged") {
        if (writesConfig) {
          if (flag.enabled)
            enableIn(tx, id);
          else
            disableIn(tx, id, flag.reason);
          await tx.commitConfig();
        }
        return result;
      }
      if (!writesConfig) {
        tx.setStateAccount(id, plan.account);
        await tx.commitState();
        return result;
      }
      const transition = flag.enabled ? { mark: randomUUID7(), enabled: true } : { mark: randomUUID7(), enabled: false, reason: flag.reason };
      const stamp = plan.account[CREDENTIAL_STAMP_KEY];
      tx.setStateAccount(id, {
        ...plan.account,
        [CREDENTIAL_STAMP_KEY]: {
          ...stamp,
          [TRANSITION_STAMP_KEY]: transition
        }
      });
      await tx.commitState();
      applyTransition(tx, id, transition);
      await tx.commitConfig();
      return result;
    }, { completeTorn: false });
  });
}
function disableRow(rt, id, reason, options = {}) {
  return transitionRow(rt, "disable", id, { enabled: false, reason }, options);
}
function enableRow(rt, id, options = {}) {
  return transitionRow(rt, "enable", id, { enabled: true }, options);
}
async function removeRow(rt, id, options = {}) {
  assertNotInsideHook("remove");
  const { ctx } = rt;
  return runOperation(ctx, "remove", id, options.onFailure, async (locks, progress) => {
    if (typeof id !== "string" || id.length === 0)
      throw refusal2("remove", id, "invalid-input", "id must be non-empty");
    const fence = options.attribution;
    validateAttribution("remove", id, fence);
    if (options.staged !== void 0 && (!isRecord4(options.staged) || typeof options.staged.reservation !== "string" || !options.staged.reservation))
      throw refusal2("remove", id, "invalid-input", "a staged removal needs a reservation");
    const result = await readPool(ctx);
    if (result.status !== "ready")
      throw notReadyError(result, "remove", id);
    const seen = result.rows.find((row) => row.id === id);
    if (!seen && !hasStateAccount(result.state, id))
      throw unknownRow("remove", id);
    const seenKey = rowLockKey(seen ?? { id });
    await locks.acquire(rowLockSpec(rt, seen ?? { id }));
    for (const extra of options.extraLocks ?? [])
      await locks.acquire(extra);
    return withTransaction(
      ctx,
      locks,
      progress,
      { operation: "remove", rowId: id },
      async (tx) => {
        const reservation = tx.reservation(id);
        if (reservation !== void 0) {
          if (!isRecord4(reservation) || !options.staged || reservation.reservation !== options.staged.reservation)
            throw refusal2("remove", id, "row-staged", `row ${id} is reserved for roster publication`);
        } else if (options.staged)
          throw refusal2("remove", id, "attribution", `row ${id} is no longer reserved`);
        const row = tx.row(id);
        const orphan = hasStateAccount(tx.state, id);
        if (!row && !orphan)
          throw unknownRow("remove", id);
        if (rowLockKey(row ?? { id }) !== seenKey)
          throw keyChanged("remove", id);
        if (fence !== void 0) {
          if (row)
            assertBoundRowAttribution(id, row, fence);
          else
            assertOrphanAttribution(rt, tx, id, fence);
        }
        const protect = options.protect;
        if (protect) {
          const view = {
            row,
            config: tx.snapshot.config,
            state: tx.snapshot.state
          };
          const reason = await runInsideHook("remove", () => protect(id, view));
          if (reason !== void 0)
            throw refusal2("remove", id, "row-protected", reason);
        }
        if (row) {
          if (fence === void 0)
            await tx.completeTorn();
          tx.dropRosterRows(id);
          await tx.commitConfig();
        }
        if (orphan) {
          tx.dropStateAccount(id);
          await tx.commitState();
        }
        return { id, outcome: row ? "removed" : "completed" };
      },
      // An attributed removal is refused, when it is, with nothing written:
      // completing another row's interrupted write first would be a write.
      { completeTorn: false }
    );
  });
}
function assertBoundRowAttribution(id, row, fence, operation = "remove") {
  assertRowAttribution(operation, id, row, fence);
  if (row.torn)
    throw refusal2(operation, id, "attribution", `row ${id} is between the writes of another operation; retry once it completes`, true);
  if (row.stamp !== "bound")
    throw refusal2(operation, id, "unbound-credential", `row ${id}'s credential is not bound to its stamp, so the removal cannot be attributed to it`);
}
function assertOrphanAttribution(rt, tx, id, fence) {
  const unbound2 = () => refusal2("remove", id, "unbound-credential", `orphan ${id} has no credential stamp this store can bind, so the removal cannot be attributed to it`);
  const account = tx.stateAccount(id);
  const stamp = parseStamp(account?.[CREDENTIAL_STAMP_KEY]);
  if (!account || !stamp?.binding || stamp.dispatch === void 0 || stamp.replace)
    throw unbound2();
  let descriptor;
  if (typeof account.apiKey === "string") {
    if (stamp.binding.baseURL === void 0 || stamp.binding.authHeader === void 0)
      throw unbound2();
    descriptor = {
      type: "api",
      apiKey: account.apiKey,
      baseURL: stamp.binding.baseURL,
      authHeader: stamp.binding.authHeader
    };
  } else if (typeof account.refresh === "string") {
    descriptor = { type: "oauth", refresh: account.refresh };
  } else
    throw unbound2();
  const [orphan] = buildRawRows({
    accounts: [
      rosterRowFor({
        id,
        credential: descriptor,
        identity: stamp.binding.identity,
        addedAt: 0
      })
    ],
    [POOL_KEY]: {
      rows: { [id]: { credentialEpoch: stamp.credentialEpoch } }
    }
  }, tx.state, rt.ctx.codec, rt.ctx.providerState);
  if (!orphan?.credential || orphan.invalid || orphan.stamp !== "bound")
    throw unbound2();
  if (stamp.credentialEpoch !== fence.credentialEpoch || stamp.binding.identity !== fence.identity)
    throw refusal2("remove", id, "attribution", `orphan ${id} was written for a credential or account other than the one this removal was decided for`, true);
}
function hasStateAccount(state, id) {
  const accounts = state.accounts;
  return isRecord4(accounts) && Object.hasOwn(accounts, id);
}
function rosterIdOf(raw) {
  return isRecord4(raw) && typeof raw.id === "string" ? raw.id : void 0;
}
function orderProblem(roster, ids) {
  if (!Array.isArray(ids))
    return "ids must be an array of roster ids";
  const rosterIds = /* @__PURE__ */ new Set();
  for (const raw of roster) {
    const id = rosterIdOf(raw);
    if (id !== void 0)
      rosterIds.add(id);
  }
  const given = /* @__PURE__ */ new Set();
  for (const id of ids) {
    if (typeof id !== "string")
      return "ids must be an array of roster ids";
    if (given.has(id))
      return `id ${id} appears more than once`;
    if (!rosterIds.has(id))
      return `id ${id} is not in the roster`;
    given.add(id);
  }
  const missing = [...rosterIds].filter((id) => !given.has(id));
  if (missing.length > 0)
    return `the order leaves out roster id(s) ${missing.join(", ")}`;
  return void 0;
}
function reorderedRoster(roster, ids) {
  const byId = /* @__PURE__ */ new Map();
  for (const raw of roster) {
    const id = rosterIdOf(raw);
    if (id === void 0)
      continue;
    const group = byId.get(id);
    if (group)
      group.push(raw);
    else
      byId.set(id, [raw]);
  }
  const sequence = ids.flatMap((id) => byId.get(id) ?? []);
  let next = 0;
  return roster.map((raw) => rosterIdOf(raw) === void 0 ? raw : sequence[next++]);
}
async function reorderRows(rt, ids, options = {}) {
  assertNotInsideHook("reorder");
  const { ctx } = rt;
  const onFailure = options.onFailure;
  return runOperation(ctx, "reorder", void 0, onFailure && ((_rowId, error) => onFailure(error)), async (locks, progress) => {
    for (const extra of options.extraLocks ?? [])
      await locks.acquire(extra);
    return withTransaction(
      ctx,
      locks,
      progress,
      { operation: "reorder", rowId: void 0 },
      async (tx) => {
        const roster = tx.roster();
        const problem = orderProblem(roster, ids);
        if (problem)
          throw new PoolOperationError({
            operation: "reorder",
            phase: "before-first-write",
            retryable: false,
            kind: "invalid-order",
            message: problem
          });
        const order = [...ids];
        const next = reorderedRoster(roster, order);
        if (next.every((raw, index) => raw === roster[index]))
          return { ids: order, outcome: "unchanged" };
        tx.config.accounts = next;
        await tx.commitConfig();
        return { ids: order, outcome: "reordered" };
      },
      // A reorder keeps every roster row and entry byte for byte, so it
      // leaves a torn row for a write on that row to complete.
      { completeTorn: false }
    );
  });
}
async function recordRowIdentity(rt, id, identity, attribution, options = {}) {
  assertNotInsideHook("recordIdentity");
  return runOperation(rt.ctx, "recordIdentity", id, options.onFailure, async (locks, progress) => {
    if (typeof identity !== "string" || identity.length === 0)
      throw refusal2("recordIdentity", id, "invalid-input", "identity must be non-empty");
    const captured = isRecord4(attribution) ? attribution.credentialEpoch : void 0;
    if (!isCredentialEpoch(captured))
      throw refusal2("recordIdentity", id, "invalid-input", "the credential epoch the identity lookup was issued for is required");
    const { row: seen } = await readRow(rt, "recordIdentity", id);
    await locks.acquire(rowLockSpec(rt, seen));
    await locks.acquire(options.providerLock ?? rt.providerLock);
    for (const extra of options.extraLocks ?? [])
      await locks.acquire(extra);
    return withTransaction(rt.ctx, locks, progress, { operation: "recordIdentity", rowId: id }, async (tx) => {
      const row = requireUsableRow("recordIdentity", id, tx.row(id));
      if (rowLockKey(row) !== rowLockKey(seen))
        throw keyChanged("recordIdentity", id);
      requireBound("recordIdentity", row);
      if ((row.credentialEpoch ?? 1) !== captured)
        throw refusal2("recordIdentity", id, "attribution", `the identity for ${id} was looked up for a credential the row no longer holds`, true);
      if (row.identity !== void 0 && row.identity !== identity)
        throw identityMismatch("recordIdentity", id);
      if (row.identity === void 0)
        await stampIdentityIn(tx, row, identity);
      const disabled = recordIdentityIn(tx, id, identity);
      await tx.commitConfig();
      return { id, disabled };
    });
  });
}
var CREDENTIAL_STATE_FIELDS;
var init_rows = __esm({
  "../core/dist/common-auth-embedded/store/rows.js"() {
    "use strict";
    init_errors();
    init_hooks();
    init_identity();
    init_mutate();
    init_provider_state();
    init_runtime();
    init_schema();
    init_torn();
    CREDENTIAL_STATE_FIELDS = [
      "access",
      "refresh",
      "expires",
      "lastRefreshedAt",
      "apiKey"
    ];
  }
});

// ../core/dist/common-auth-embedded/store/publication.js
function receiptsIn(config) {
  const pool = config[POOL_KEY];
  return isRecord4(pool) && isRecord4(pool.publications) ? pool.publications : {};
}
function receiptIn(config, operationId) {
  const receipts = receiptsIn(config);
  if (!Object.hasOwn(receipts, operationId))
    return void 0;
  const raw = receipts[operationId];
  if (!isRecord4(raw) || raw.operationId !== operationId || typeof raw.planDigest !== "string" || !/^[a-f0-9]{64}$/.test(raw.planDigest) || !["committed", "cleaned"].includes(String(raw.phase)) || !Array.isArray(raw.removed) || !Array.isArray(raw.finalized) || raw.removed.some((ref) => !isRecord4(ref) || typeof ref.id !== "string" || !isCredentialEpoch(ref.credentialEpoch)) || raw.finalized.some((ref) => !isRecord4(ref) || typeof ref.id !== "string" || !isCredentialEpoch(ref.credentialEpoch) || typeof ref.reservation !== "string" || !ref.reservation || typeof ref.enabled !== "boolean"))
    throw refusal2("publishRoster", operationId, "invalid-input", "the stored publication receipt is malformed");
  return structuredClone(raw);
}
async function publication(rt, operationId) {
  const result = await readPool(rt.ctx);
  if (result.status !== "ready")
    throw notReadyError(result, "publishRoster", operationId);
  return receiptIn(result.config, operationId);
}
function validatePlan(rt, plan) {
  const fail2 = () => {
    throw refusal2("publishRoster", plan?.operationId ?? "", "invalid-input", "the publication plan is invalid");
  };
  if (!isRecord4(plan) || typeof plan.operationId !== "string" || !plan.operationId || !Array.isArray(plan.remove) || !Array.isArray(plan.finalize) || !Array.isArray(plan.order))
    fail2();
  const ids = /* @__PURE__ */ new Set();
  for (const ref of [...plan.remove, ...plan.finalize]) {
    if (!isRecord4(ref) || typeof ref.id !== "string" || idProblem(ref.id) || ids.has(ref.id) || !ref.attribution)
      fail2();
    ids.add(ref.id);
    validateAttribution("publishRoster", ref.id, ref.attribution);
    if (ref.attribution.identity !== void 0 && (typeof ref.attribution.identity !== "string" || !ref.attribution.identity))
      fail2();
  }
  for (const ref of plan.remove)
    if (rt.ctx.requireRemovedFingerprint && !ref.fingerprint || ref.fingerprint !== void 0 && typeof ref.fingerprint !== "string")
      fail2();
  for (const ref of plan.finalize)
    if (typeof ref.reservation !== "string" || !ref.reservation || typeof ref.enabled !== "boolean" || (ref.enabled ? ref.disabledReason !== void 0 : typeof ref.disabledReason !== "string"))
      fail2();
  if (plan.order.some((id) => typeof id !== "string" || idProblem(id)) || new Set(plan.order).size !== plan.order.length)
    fail2();
}
function saveReceipt(tx, receipt2) {
  tx.entries();
  const pool = tx.config[POOL_KEY];
  const receipts = { ...receiptsIn(tx.config) };
  Object.defineProperty(receipts, receipt2.operationId, {
    value: receipt2,
    enumerable: true,
    writable: true,
    configurable: true
  });
  pool.publications = receipts;
  delete pool.publicationOrder;
}
function publicationSurvivors(tx, plan, rows) {
  const rosterIds = /* @__PURE__ */ new Set();
  for (const raw of rosterOf(tx.config)) {
    if (!isRecord4(raw) || typeof raw.id !== "string")
      continue;
    if (rosterIds.has(raw.id))
      throw refusal2("publishRoster", plan.operationId, "invalid-input", "publication needs a roster of unique named rows");
    rosterIds.add(raw.id);
  }
  const removedIds = new Set(plan.remove.map((ref) => ref.id));
  const survivors = rows.filter((row) => row.invalid !== "roster" && !removedIds.has(row.id));
  if (survivors.length !== plan.order.length || plan.order.some((id) => !survivors.some((row) => row.id === id)) || survivors.some((row) => !plan.order.includes(row.id)))
    throw refusal2("publishRoster", plan.operationId, "invalid-input", "order must name exactly the surviving roster");
  return survivors;
}
async function cleanup(tx, receipt2) {
  await tx.assertAll();
  for (const ref of receipt2.removed) {
    const stamp = parseStamp(tx.stateAccount(ref.id)?.[CREDENTIAL_STAMP_KEY]);
    if (stamp?.credentialEpoch === ref.credentialEpoch && !tx.rosterRow(ref.id))
      tx.dropStateAccount(ref.id);
  }
  for (const ref of receipt2.finalized) {
    const account = tx.stateAccount(ref.id);
    const stamp = parseStamp(account?.[CREDENTIAL_STAMP_KEY]);
    if (account && stamp?.credentialEpoch === ref.credentialEpoch && stamp.staged?.reservation === ref.reservation) {
      const next = {
        ...account[CREDENTIAL_STAMP_KEY]
      };
      delete next.staged;
      tx.setStateAccount(ref.id, { ...account, [CREDENTIAL_STAMP_KEY]: next });
    }
  }
  await tx.commitState(void 0, { durable: true });
  const cleaned = { ...receipt2, phase: "cleaned" };
  saveReceipt(tx, cleaned);
  await tx.commitConfig({ durable: true });
  return cleaned;
}
async function publishRoster(rt, plan, options = {}) {
  assertNotInsideHook("publishRoster");
  return runOperation(rt.ctx, "publishRoster", plan?.operationId ?? "", options.onFailure, async (locks, progress) => {
    if (!isRecord4(plan) || typeof plan.operationId !== "string" || !plan.operationId)
      throw refusal2("publishRoster", plan?.operationId ?? "", "invalid-input", "the publication needs an operation id");
    plan = structuredClone(plan);
    const planDigest = canonicalDigest(plan);
    const named = [
      ...Array.isArray(plan.remove) ? plan.remove : [],
      ...Array.isArray(plan.finalize) ? plan.finalize : []
    ].filter((ref) => isRecord4(ref) && typeof ref.id === "string");
    for (let attempt = 0; ; attempt++) {
      const seen = await readPool(rt.ctx);
      if (seen.status !== "ready")
        throw notReadyError(seen, "publishRoster", plan.operationId);
      const keys = new Map(named.map(({ id }) => [
        id,
        rowLockKey(seen.rows.find((row) => row.id === id) ?? { id })
      ]));
      for (const key of [...new Set(keys.values())].sort())
        await locks.acquire(rowLockSpec(rt, { id: key }));
      await locks.acquire(options.providerLock ?? rt.providerLock);
      for (const extra of options.extraLocks ?? [])
        await locks.acquire(extra);
      const result = await withTransaction(rt.ctx, locks, progress, { operation: "publishRoster", rowId: plan.operationId }, async (tx) => {
        const rows = tx.rows();
        if (named.some(({ id }) => rowLockKey(rows.find((row) => row.id === id) ?? { id }) !== keys.get(id)))
          return void 0;
        const prior = receiptIn(tx.config, plan.operationId);
        if (prior) {
          if (prior.planDigest !== planDigest)
            throw refusal2("publishRoster", plan.operationId, "publication-mismatch", "the operation id belongs to a different publication plan");
          if (prior.phase === "cleaned")
            return { outcome: "already-cleaned", receipt: prior };
          tx.markPublicationDecision();
          await tx.syncConfig();
          return { outcome: "cleaned", receipt: await cleanup(tx, prior) };
        }
        validatePlan(rt, plan);
        const survivors = publicationSurvivors(tx, plan, rows);
        const removed = [];
        for (const ref of plan.remove) {
          tx.assertNotStaged(ref.id);
          const row = rows.find((row2) => row2.id === ref.id);
          if (!row)
            throw refusal2("publishRoster", ref.id, "attribution", "the removed row no longer exists");
          assertBoundRowAttribution(ref.id, row, ref.attribution, "publishRoster");
          if (!row.credential || ref.fingerprint !== void 0 && fingerprintOf(row.credential) !== ref.fingerprint)
            throw refusal2("publishRoster", ref.id, "attribution", "the removed secret no longer matches");
          removed.push(row);
        }
        const finalized = [];
        for (const ref of plan.finalize) {
          const row = rows.find((row2) => row2.id === ref.id);
          const stamp = parseStamp(tx.stateAccount(ref.id)?.[CREDENTIAL_STAMP_KEY]);
          if (!row || row.staged?.reservation !== ref.reservation || stamp?.staged?.reservation !== ref.reservation || row.enabled)
            throw refusal2("publishRoster", ref.id, "row-staged", "the finalized row is not disabled under this reservation");
          const account = tx.stateAccount(ref.id);
          const raw = tx.rosterRow(ref.id);
          const storedProviderState = account?.[PROVIDER_STATE_KEY];
          const fullProviderDigest = storedProviderState === void 0 ? void 0 : canonicalDigest(storedProviderState);
          if (!stamp?.staged || stamp.staged.label !== raw?.label || stamp.staged.disabledReason !== row.disabledReason || stamp.staged.providerState !== fullProviderDigest)
            throw refusal2("publishRoster", ref.id, "row-staged", "the staged label, disabled reason or full provider state no longer matches its stamp");
          assertBoundRowAttribution(ref.id, row, ref.attribution, "publishRoster");
          finalized.push(row);
        }
        const tornSurvivor = survivors.find((row) => row.torn);
        if (tornSurvivor)
          throw refusal2("publishRoster", plan.operationId, "attribution", `Row ${tornSurvivor.id} has an interrupted write; complete it with a normal store operation before publishing.`, false);
        const identities = /* @__PURE__ */ new Set();
        for (const row of survivors) {
          const enabled = plan.finalize.find((ref) => ref.id === row.id)?.enabled ?? row.enabled;
          if (!enabled || row.type !== "oauth" || row.identity === void 0)
            continue;
          if (identities.has(row.identity))
            throw refusal2("publishRoster", row.id, "invalid-input", "the final enabled roster repeats a known identity");
          identities.add(row.identity);
        }
        for (const row of survivors) {
          if (row.identity !== void 0 && row.fingerprint !== void 0 && survivors.some((other) => other.id !== row.id && other.identity !== void 0 && other.identity !== row.identity && other.fingerprint === row.fingerprint))
            throw refusal2("publishRoster", row.id, "attribution", "the resulting pool gives the same secret different known identities");
        }
        for (const row of finalized)
          if (row.identity !== void 0 && removed.some((old) => old.identity !== void 0 && old.identity !== row.identity && old.fingerprint === row.fingerprint))
            throw refusal2("publishRoster", row.id, "attribution", "the staged secret belonged to a different known identity");
        await protectIn(tx, plan.operationId, options.protect);
        const receipt2 = {
          operationId: plan.operationId,
          planDigest,
          phase: "committed",
          removed: removed.map((row) => ({
            id: row.id,
            credentialEpoch: row.credentialEpoch ?? 1
          })),
          finalized: plan.finalize.map((ref, index) => ({
            id: ref.id,
            credentialEpoch: finalized[index]?.credentialEpoch ?? 1,
            reservation: ref.reservation,
            enabled: ref.enabled
          }))
        };
        for (const ref of plan.remove)
          tx.dropRosterRows(ref.id);
        for (const ref of plan.finalize) {
          const raw = tx.rosterRow(ref.id);
          raw.enabled = ref.enabled;
          const entry = { ...tx.entry(ref.id) };
          delete entry.staged;
          if (ref.enabled)
            delete entry.disabledReason;
          else
            entry.disabledReason = ref.disabledReason;
          tx.setEntry(ref.id, entry);
        }
        const preserved = tx.roster().filter((raw) => !isRecord4(raw) || typeof raw.id !== "string" || rows.find((row) => row.id === raw.id)?.invalid === "roster");
        tx.config.accounts = [
          ...plan.order.map((id) => tx.rosterRow(id)),
          ...preserved
        ];
        saveReceipt(tx, receipt2);
        await tx.syncState();
        await tx.commitConfig({ durable: true, publicationDecision: true });
        return { outcome: "published", receipt: await cleanup(tx, receipt2) };
      }, { completeTorn: false });
      if (result)
        return result;
      await locks.releaseAll();
      if (attempt >= 1)
        throw refusal2("publishRoster", plan.operationId, "row-key-changed", "a named row changed lock key twice during publication", true);
    }
  });
}
var init_publication = __esm({
  "../core/dist/common-auth-embedded/store/publication.js"() {
    "use strict";
    init_hooks();
    init_mutate();
    init_rows();
    init_runtime();
    init_schema();
  }
});

// ../core/dist/common-auth-embedded/store/pull.js
var PullScheduler;
var init_pull = __esm({
  "../core/dist/common-auth-embedded/store/pull.js"() {
    "use strict";
    init_attribution();
    init_errors();
    init_mutate();
    init_refresh_lock();
    init_runtime();
    PullScheduler = class {
      rt;
      hook;
      onFailure;
      firedAtLoad;
      logger;
      inflight = /* @__PURE__ */ new Set();
      constructor(rt, hook, onFailure, firedAtLoad, logger) {
        this.rt = rt;
        this.hook = hook;
        this.onFailure = onFailure;
        this.firedAtLoad = firedAtLoad;
        this.logger = logger;
      }
      fire(id, reason) {
        if (!this.hook)
          return;
        if (reason === "load") {
          if (this.firedAtLoad.has(id))
            return;
          this.firedAtLoad.add(id);
        }
        const run = this.run(id, reason);
        this.inflight.add(run);
        void run.finally(() => this.inflight.delete(run));
      }
      /** Resolves once every pull fired so far has settled. */
      async settled() {
        while (this.inflight.size > 0)
          await Promise.allSettled([...this.inflight]);
      }
      async run(id, reason) {
        const rt = this.rt();
        const { ctx } = rt;
        const locks = new LockStack(ctx.lockDefaults, ctx.lockEnv);
        const progress = { writes: 0 };
        try {
          const request = await withTransaction(ctx, locks, progress, { operation: "pull", rowId: id }, async (tx) => {
            if (tx.reservation(id) !== void 0)
              return void 0;
            await tx.completeTorn();
            const row = tx.row(id);
            if (row?.unbound && row.enabled && row.type === "oauth" && row.credential && !row.invalid)
              requireBound("pull", row);
            if (!row?.candidate || row.type !== "oauth")
              return void 0;
            if (!row.hasEntry) {
              tx.setEntry(id, { credentialEpoch: 1, needsFirstReading: true });
              await tx.commitConfig();
            }
            const current = tx.row(id);
            if (!current?.credential || current.credentialEpoch === void 0)
              return void 0;
            return {
              id,
              credential: current.credential,
              credentialEpoch: current.credentialEpoch,
              ...current.identity !== void 0 ? { identity: current.identity } : {},
              reason
            };
          }, { completeTorn: false });
          await locks.releaseAll();
          if (!request) {
            this.firedAtLoad.delete(id);
            return;
          }
          await ctx.hold?.("pull-before-request", id);
          let observation;
          try {
            observation = await this.hook?.(request);
          } catch (cause) {
            throw new PoolOperationError({
              operation: "pull",
              rowId: id,
              phase: "pull",
              retryable: true,
              kind: "pull",
              message: "the quota pull rejected",
              cause
            });
          }
          await recordQuota(rt, id, {
            credentialEpoch: request.credentialEpoch,
            ...request.identity !== void 0 ? { identity: request.identity } : {}
          }, observation);
        } catch (error) {
          this.firedAtLoad.delete(id);
          const failure = toFailure(error, "pull", id, progress);
          if (this.onFailure) {
            try {
              await this.onFailure(id, failure);
            } catch (hookError) {
              this.logger?.warn("pull failure hook threw", {
                rowId: id,
                error: hookError instanceof Error ? hookError.message : String(hookError)
              });
            }
          } else {
            this.logger?.warn("quota pull failed", {
              rowId: id,
              kind: failure.kind
            });
          }
        } finally {
          await locks.releaseAll();
        }
      }
    };
  }
});

// ../core/dist/common-auth-embedded/store/refresh.js
import { randomUUID as randomUUID8 } from "node:crypto";
function requireRefreshable(id, row) {
  assertNotReserved("refresh", id, row?.staged);
  if (!row)
    throw refusal2("refresh", id, "unknown-row", `no row ${id} in the pool`);
  if (row.invalid)
    throw refusal2("refresh", id, "invalid-row", `row ${id} is invalid`);
  if (row.type !== "oauth" || row.credential?.type !== "oauth")
    throw refusal2("refresh", id, "no-credential", `row ${id} holds no OAuth credential`);
  if (!row.enabled)
    throw refusal2("refresh", id, "row-disabled", `row ${id} is disabled`);
  return row;
}
function stampAhead(id) {
  return refusal2("refresh", id, "refresh-stamp-ahead", `row ${id}'s stored refresh stamp is ahead of the clock; a rotation now could not be stamped newer within the trust bound`, true);
}
async function refreshRow(rt, id, provider, options = {}) {
  assertNotInsideHook("refresh");
  const { ctx } = rt;
  return runOperation(ctx, "refresh", id, options.onFailure, async (locks, progress) => {
    const { row: seen } = await readRow(rt, "refresh", id);
    requireRefreshable(id, seen);
    const early = await options.refuse?.(seen);
    if (early !== void 0)
      return { status: "refused", rowId: id, reason: early };
    let key = rowLockKey(seen);
    let captured;
    for (let attempt = 0; ; attempt++) {
      await locks.acquire(rowLockSpec(rt, { id, identity: key === id ? void 0 : key }));
      await locks.acquire(options.providerLock ?? rt.providerLock);
      for (const extra of options.extraLocks ?? [])
        await locks.acquire(extra);
      const captureProgress = { writes: 0 };
      const read = await withTransaction(ctx, locks, captureProgress, { operation: "refresh", rowId: id }, async (tx) => {
        let row = requireRefreshable(id, tx.row(id));
        requireBound("refresh", row);
        if (!row.hasEntry) {
          tx.setEntry(id, { credentialEpoch: 1, needsFirstReading: true });
          await tx.commitConfig();
          row = requireRefreshable(id, tx.row(id));
        }
        if (rowLockKey(row) !== key)
          return { keyNow: rowLockKey(row) };
        const reason = await options.refuse?.(row);
        if (reason !== void 0)
          return { refused: reason };
        return {
          row,
          credential: row.credential,
          credentialEpoch: row.credentialEpoch,
          identity: row.identity
        };
      });
      if ("refused" in read)
        return { status: "refused", rowId: id, reason: read.refused };
      if ("keyNow" in read) {
        await locks.releaseAll();
        if (attempt >= 1)
          throw refusal2("refresh", id, "row-key-changed", `row ${id}'s wire identity changed twice while its lock was held`, true);
        key = read.keyNow;
        continue;
      }
      captured = read;
      break;
    }
    if (rotationStampUntrusted(captured.credential.lastRefreshedAt, ctx.now()))
      throw stampAhead(id);
    await ctx.hold?.("refresh-before-provider", id);
    await locks.assertAll();
    let result;
    try {
      result = await provider(captured.credential, captured.row);
    } catch (cause) {
      throw new PoolOperationError({
        operation: "refresh",
        rowId: id,
        phase: "before-first-write",
        retryable: true,
        kind: "provider",
        message: "the provider refresh failed",
        cause
      });
    }
    if (typeof result?.refresh !== "string" || !result.refresh.trim())
      throw refusal2("refresh", id, "provider", "the provider returned no refresh token", true);
    const incoming = result.providerState === void 0 ? void 0 : acceptProviderState(ctx.providerState, "refresh", id, result.providerState, "the provider state the provider returned");
    const commit = await withTransaction(ctx, locks, progress, { operation: "refresh", rowId: id }, async (tx) => {
      const current = tx.row(id);
      const entry = tx.entry(id);
      if (!current || current.invalid || !entry || entry.credentialEpoch !== captured.credentialEpoch || current.identity !== captured.identity)
        throw new PoolOperationError({
          operation: "refresh",
          rowId: id,
          phase: "before-first-write",
          retryable: true,
          kind: "attribution",
          message: `row ${id} changed credential while its refresh was in flight; the rotation is discarded`
        });
      requireBound("refresh", current);
      const reason = await options.refuse?.(current);
      if (reason !== void 0)
        return { refused: reason };
      const now = ctx.now();
      const prior = current.credential?.type === "oauth" ? current.credential.lastRefreshedAt : void 0;
      if (rotationStampUntrusted(prior, now))
        throw stampAhead(id);
      const credential = {
        type: "oauth",
        access: result.access,
        refresh: result.refresh,
        expires: result.expires
      };
      const contradiction = current.identity !== void 0 && result.identity !== void 0 && current.identity !== result.identity ? {
        expectedIdentity: current.identity,
        returnedIdentity: result.identity
      } : void 0;
      const transition = contradiction ? {
        mark: randomUUID8(),
        enabled: false,
        reason: `${IDENTITY_CONTRADICTED_REASON_PREFIX}${JSON.stringify(contradiction)}`
      } : void 0;
      const learnt = current.identity === void 0 && result.identity ? result.identity : void 0;
      const stored = await rotateIn(rt, tx, id, credential, {
        stamp: rotationStamp(prior, now),
        // Write state first with the disable marker, then config below.
        // Once the successor is durable, recovery projects the disable even
        // if config has not landed. A crash before the first rename still
        // loses an in-memory provider reply, as in any ordinary refresh.
        transition,
        identity: learnt,
        ...incoming !== void 0 ? {
          providerState: mergedProviderState(ctx.providerState, "refresh", id, current.providerState, incoming)
        } : {}
      });
      if (transition !== void 0) {
        applyTransition(tx, id, transition);
        await tx.commitConfig();
      }
      let identity = current.identity;
      if (learnt !== void 0) {
        recordIdentityIn(tx, id, learnt);
        identity = learnt;
        await tx.commitConfig();
      }
      return { stored, identity, contradiction, refused: void 0 };
    });
    if (commit.refused !== void 0)
      return { status: "refused", rowId: id, reason: commit.refused };
    if (commit.contradiction !== void 0)
      return {
        status: "identity-contradicted",
        rowId: id,
        ...commit.contradiction,
        credential: commit.stored
      };
    if (options.onPersisted) {
      try {
        const persisted = options.onPersisted;
        await runInsideHook("refresh", () => persisted(id, commit.stored));
      } catch (cause) {
        throw new PoolOperationError({
          operation: "refresh",
          rowId: id,
          phase: "after-first-write",
          retryable: false,
          kind: "after-persist-hook",
          committed: commit.stored,
          message: "the after-persist hook threw; the rotation stays committed",
          cause
        });
      }
    }
    return {
      status: "rotated",
      rowId: id,
      credential: commit.stored,
      ...commit.identity !== void 0 ? { identity: commit.identity } : {}
    };
  });
}
var init_refresh = __esm({
  "../core/dist/common-auth-embedded/store/refresh.js"() {
    "use strict";
    init_errors();
    init_hooks();
    init_identity();
    init_mutate();
    init_provider_state();
    init_reserved();
    init_rows();
    init_runtime();
    init_schema();
    init_torn();
  }
});

// ../core/dist/common-auth-embedded/store/settings.js
import { isDeepStrictEqual as isDeepStrictEqual3 } from "node:util";
function settingsOf2(config) {
  const settings = {};
  for (const [key, value] of Object.entries(config))
    if (!POOL_OWNED_KEYS.includes(key))
      defineKey(settings, key, value);
  return settings;
}
function defineKey(target, key, value) {
  Object.defineProperty(target, key, {
    value,
    enumerable: true,
    writable: true,
    configurable: true
  });
}
function composeConfig(config, next) {
  const out = {};
  for (const [key, value] of Object.entries(config)) {
    if (POOL_OWNED_KEYS.includes(key))
      defineKey(out, key, value);
    else if (Object.hasOwn(next, key))
      defineKey(out, key, next[key]);
  }
  for (const [key, value] of Object.entries(next))
    if (!Object.hasOwn(config, key))
      defineKey(out, key, value);
  return out;
}
function settingsRefusal(message) {
  return new PoolOperationError({
    operation: "updateSettings",
    phase: "before-first-write",
    retryable: false,
    kind: "invalid-input",
    message
  });
}
async function readPoolSettings(rt) {
  const result = await readPool(rt.ctx);
  if (result.status === "error")
    return result;
  return { status: result.status, settings: settingsOf2(result.config) };
}
async function updatePoolSettings(rt, mutator, options = {}) {
  assertNotInsideHook("updateSettings");
  const { ctx } = rt;
  const onFailure = options.onFailure;
  return runOperation(ctx, "updateSettings", void 0, onFailure && ((_rowId, error) => onFailure(error)), async (locks, progress) => {
    for (const extra of options.extraLocks ?? [])
      await locks.acquire(extra);
    const mark = locks.held.length;
    try {
      for (const spec of ctx.storeLocks)
        await locks.acquire(spec);
      const result = await readPool(ctx);
      if (result.status !== "ready")
        throw notReadyError(result, "updateSettings", void 0);
      const current = settingsOf2(result.config);
      const draft = structuredClone(current);
      const returned = await runInsideHook("updateSettings", () => mutator(draft));
      const next = returned === void 0 ? draft : returned;
      if (!isRecord4(next))
        throw settingsRefusal("the settings mutator must produce an object");
      const owned = POOL_OWNED_KEYS.filter((key) => Object.hasOwn(next, key));
      if (owned.length > 0)
        throw settingsRefusal(`settings cannot set the pool-owned key(s) ${owned.join(", ")}`);
      if (isDeepStrictEqual3(next, current))
        return { settings: current, outcome: "unchanged" };
      const config = composeConfig(result.config, next);
      const info = { operation: "updateSettings", rowId: void 0 };
      await writeJsonAtomic2(ctx.configPath, config, {
        beforeRename: async () => {
          await ctx.onStep?.("before-config-write", info);
          await locks.assertAll();
        }
      });
      progress.writes++;
      await ctx.onStep?.("after-config-write", info);
      return { settings: settingsOf2(config), outcome: "updated" };
    } finally {
      await locks.releaseTo(mark);
    }
  });
}
var POOL_OWNED_KEYS;
var init_settings = __esm({
  "../core/dist/common-auth-embedded/store/settings.js"() {
    "use strict";
    init_atomic_write();
    init_errors();
    init_hooks();
    init_mutate();
    init_schema();
    POOL_OWNED_KEYS = Object.freeze([
      "version",
      "accounts",
      POOL_KEY
    ]);
  }
});

// ../core/dist/common-auth-embedded/store/pool.js
function memoryFor(configPath) {
  let memory = processMemory.get(configPath);
  if (!memory) {
    memory = { removedIds: /* @__PURE__ */ new Set(), firedAtLoad: /* @__PURE__ */ new Set() };
    processMemory.set(configPath, memory);
  }
  return memory;
}
function toLoad(result) {
  if (result.status === "ready")
    return {
      status: "ready",
      schemaVersion: POOL_SCHEMA_VERSION,
      rows: result.rows
    };
  if (result.status === "pending-migration")
    return {
      status: "pending-migration",
      roster: Array.isArray(result.config.accounts) ? result.config.accounts : []
    };
  return result;
}
function openPoolStore(options) {
  const memory = memoryFor(options.configPath);
  const lockDefaults = {
    ...POOL_LOCK_DEFAULTS,
    ...options.lockOptions
  };
  const ctx = {
    provider: options.provider,
    configPath: options.configPath,
    statePath: options.statePath,
    codec: options.quota,
    ...options.providerState ? { providerState: options.providerState } : {},
    now: options.now ?? Date.now,
    storeLocks: options.storeLocks ?? [
      { name: "save", path: options.configPath },
      { name: "save", path: options.statePath }
    ],
    lockDefaults,
    lockEnv: {
      now: options.now ?? Date.now,
      ...options.onLockEvent ? { onLockEvent: options.onLockEvent } : {},
      ...options.onLockStep ? { onLockStep: options.onLockStep } : {}
    },
    removedIds: memory.removedIds,
    requireCredentialStamps: options.requireCredentialStamps === true,
    requireRemovedFingerprint: options.requireRemovedFingerprint === true,
    ...options.logger ? { logger: options.logger } : {},
    ...options.onStep ? { onStep: options.onStep } : {},
    ...options.hold ? { hold: options.hold } : {}
  };
  const pulls = new PullScheduler(() => rt, options.pull, options.onPullFailure, memory.firedAtLoad, options.logger);
  const rt = {
    ctx,
    providerLock: options.providerLock ?? {
      name: `provider-${encodeURIComponent(options.provider)}`,
      path: options.statePath
    },
    rowLockOptions: options.rowLockOptions ?? {},
    firePull: (id, reason) => pulls.fire(id, reason)
  };
  return {
    async load() {
      const result = await readPool(ctx);
      if (result.status === "ready") {
        for (const row of result.rows)
          if ((row.candidate || row.torn && row.enabled) && row.type === "oauth" && row.needsFirstReading)
            pulls.fire(row.id, "load");
      }
      return toLoad(result);
    },
    async read() {
      return toLoad(await readPool(ctx));
    },
    async initialize(input = {}) {
      return { status: await initializePool(ctx, input.dropKeys ?? []) };
    },
    add: (input, callOptions) => addRow(rt, input, callOptions),
    publishRoster: (plan, callOptions) => publishRoster(rt, plan, callOptions),
    publication: (operationId) => publication(rt, operationId),
    replace: (id, credential, input, callOptions) => replaceRow(rt, id, credential, input, callOptions),
    rotate: (id, credential, input, callOptions) => rotateRow(rt, id, credential, input, callOptions),
    updateProviderState: (id, fence, mutator, callOptions) => updateProviderStateRow(rt, id, fence, mutator, callOptions),
    disable: (id, reason, callOptions) => disableRow(rt, id, reason, callOptions),
    enable: (id, callOptions) => enableRow(rt, id, callOptions),
    remove: (id, callOptions) => removeRow(rt, id, callOptions),
    reorder: (ids, callOptions) => reorderRows(rt, ids, callOptions),
    readSettings: () => readPoolSettings(rt),
    updateSettings: (mutator, callOptions) => updatePoolSettings(rt, mutator, callOptions),
    recordIdentity: (id, identity, attribution, callOptions) => recordRowIdentity(rt, id, identity, attribution, callOptions),
    refresh: (id, provider, callOptions) => refreshRow(rt, id, provider, callOptions),
    recordQuota: (id, attribution, observation) => recordQuota(rt, id, attribution, observation),
    requestReading: (id) => pulls.fire(id, "admission"),
    pullsSettled: () => pulls.settled()
  };
}
var processMemory;
var init_pool = __esm({
  "../core/dist/common-auth-embedded/store/pool.js"() {
    "use strict";
    init_attribution();
    init_mutate();
    init_provider_state();
    init_publication();
    init_pull();
    init_refresh();
    init_refresh_lock();
    init_rows();
    init_schema();
    init_settings();
    processMemory = /* @__PURE__ */ new Map();
  }
});

// ../core/dist/common-auth-embedded/store/index.js
var store_exports = {};
__export(store_exports, {
  DECLINE_TRANSITION: () => DECLINE_TRANSITION,
  DUPLICATE_IDENTITY_REASON: () => DUPLICATE_IDENTITY_REASON,
  LEGACY_STORE_VERSION: () => LEGACY_STORE_VERSION,
  POOL_KEY: () => POOL_KEY,
  POOL_LOCK_DEFAULTS: () => POOL_LOCK_DEFAULTS,
  POOL_OWNED_KEYS: () => POOL_OWNED_KEYS,
  POOL_ROWS_KEY: () => POOL_ROWS_KEY,
  POOL_SCHEMA_VERSION: () => POOL_SCHEMA_VERSION,
  PROVIDER_STATE_KEY: () => PROVIDER_STATE_KEY,
  PoolOperationError: () => PoolOperationError,
  PoolReentryError: () => PoolReentryError,
  REFRESH_STAMP_TOLERANCE_MS: () => REFRESH_STAMP_TOLERANCE_MS,
  countUnknownIdentityRows: () => countUnknownIdentityRows,
  fingerprintOf: () => fingerprintOf,
  openPoolStore: () => openPoolStore,
  rowLockKey: () => rowLockKey
});
var init_store = __esm({
  "../core/dist/common-auth-embedded/store/index.js"() {
    "use strict";
    init_errors();
    init_identity();
    init_pool();
    init_provider_state();
    init_refresh_lock();
    init_schema();
    init_settings();
  }
});

// ../core/dist/common-auth-embedded/fs/lock-constants.js
var WRITER_LOCK_CONSTANTS;
var init_lock_constants = __esm({
  "../core/dist/common-auth-embedded/fs/lock-constants.js"() {
    "use strict";
    WRITER_LOCK_CONSTANTS = Object.freeze({
      sidebar: Object.freeze({
        name: "sidebar-write",
        ttlMs: 1e4,
        timeoutMs: 15e3,
        renew: true
      }),
      preferences: Object.freeze({
        name: "preferences",
        ttlMs: 1e4,
        timeoutMs: 2e3,
        renew: true
      })
    });
  }
});

// ../core/dist/common-auth-embedded/fs/index.js
var fs_exports = {};
__export(fs_exports, {
  LockContentionError: () => LockContentionError,
  LockOwnershipError: () => LockOwnershipError,
  WRITER_LOCK_CONSTANTS: () => WRITER_LOCK_CONSTANTS,
  acquireRefreshFileLock: () => acquireRefreshFileLock,
  isLostMarkerRaceError: () => isLostMarkerRaceError,
  lockPathFor: () => lockPathFor,
  withLock: () => withLock,
  writeJsonAtomic: () => writeJsonAtomic2
});
var init_fs = __esm({
  "../core/dist/common-auth-embedded/fs/index.js"() {
    "use strict";
    init_atomic_write();
    init_lock_constants();
    init_refresh_file_lock();
    init_with_lock();
  }
});

// ../core/dist/common-auth-embedded/routing/admission.js
function exclusionFor(id, inputs, now) {
  const markedUntil = inputs.rateLimitMarks?.get(id);
  if (markedUntil !== void 0 && now < markedUntil) {
    return { id, reason: "rate-limited", until: markedUntil };
  }
  const backoffUntil = inputs.refreshBackoff?.get(id);
  if (backoffUntil !== void 0 && now < backoffUntil) {
    return { id, reason: "refresh-backoff", until: backoffUntil };
  }
  return void 0;
}
function judgeStageOne(id, projection, requiredLabels, now) {
  if (projection.limits.length === 0) {
    return {
      id,
      stage: 1,
      gate: 2,
      reason: "needs-first-reading",
      pullRequested: true
    };
  }
  for (const label of requiredLabels) {
    if (!projection.limits.some((limit) => limit.label === label)) {
      return {
        id,
        stage: 1,
        gate: 3,
        reason: "unknown-window",
        window: { scope: projection.scope, label },
        pullRequested: true
      };
    }
  }
  const exhausted = projection.limits.filter(readsExhausted);
  for (const limit of exhausted) {
    if (futureResetAt(limit, now) === void 0) {
      return {
        id,
        stage: 1,
        gate: 4,
        reason: "unknown-reset",
        window: { scope: limit.scope, label: limit.label },
        pullRequested: true
      };
    }
  }
  for (const limit of exhausted) {
    const resetAtMs = futureResetAt(limit, now);
    if (resetAtMs !== void 0 && typeof limit.resetsAt === "string") {
      return {
        id,
        stage: 1,
        gate: 5,
        reason: "exhausted",
        window: { scope: limit.scope, label: limit.label },
        resetsAt: limit.resetsAt,
        resetAtMs
      };
    }
  }
  return void 0;
}
function admit(input) {
  const scope = input.scope ?? ALL_SCOPE;
  const requiredLabels = input.requiredLabels ?? DEFAULT_REQUIRED_LABELS;
  const excluded = [];
  const refused = [];
  const survivors = [];
  for (const row of input.rows) {
    const exclusion = exclusionFor(row.id, input, input.now);
    if (exclusion) {
      excluded.push(exclusion);
      continue;
    }
    if (row.kind === "api-key") {
      survivors.push({ id: row.id, kind: row.kind });
      continue;
    }
    const projection = projectQuota(row.quota, scope);
    const refusal3 = judgeStageOne(row.id, projection, requiredLabels, input.now);
    if (refusal3) {
      refused.push(refusal3);
      continue;
    }
    survivors.push({ id: row.id, kind: row.kind, projection });
  }
  const spent = new Map(survivors.flatMap((row) => {
    const reset = budgetExhaustedResetAt(row.projection, input.now);
    return reset ? [[row.id, reset]] : [];
  }));
  const lastPath = spent.size > 0 && spent.size === survivors.length;
  const admitted = [];
  for (const row of survivors) {
    const reset = spent.get(row.id);
    if (reset === void 0) {
      admitted.push(row);
    } else if (lastPath) {
      admitted.push({ ...row, lastPath: true });
    } else {
      refused.push({ id: row.id, stage: 2, reason: "budget-spent", ...reset });
    }
  }
  const order = new Map(input.rows.map((row, index) => [row.id, index]));
  const byInput = (left, right) => (order.get(left.id) ?? 0) - (order.get(right.id) ?? 0);
  refused.sort(byInput);
  const pulls = refused.filter((refusal3) => "pullRequested" in refusal3).map((refusal3) => refusal3.id);
  for (const id of pulls)
    input.requestPull?.(id);
  return { admitted, refused, excluded, pulls };
}
var init_admission = __esm({
  "../core/dist/common-auth-embedded/routing/admission.js"() {
    "use strict";
    init_map();
    init_projection();
  }
});

// ../core/dist/common-auth-embedded/routing/ordered.js
function resolveRoutingMode(value) {
  switch (value) {
    case "sticky-balanced":
      return { mode: "sticky-balanced", placement: "roster" };
    case "main-first":
      return { mode: "ordered", placement: "main-first" };
    case "fallback-first":
      return { mode: "ordered", placement: "fallback-first" };
    default:
      return { mode: "ordered", placement: "roster" };
  }
}
function orderForPlacement(ids, placement, formerMainId = DEFAULT_FORMER_MAIN_ID) {
  if (placement === "roster" || !ids.includes(formerMainId))
    return [...ids];
  const rest = ids.filter((id) => id !== formerMainId);
  return placement === "main-first" ? [formerMainId, ...rest] : [...rest, formerMainId];
}
function routeOrdered(input) {
  const admission = admit(input);
  const admitted = new Set(admission.admitted.map((row) => row.id));
  const order = orderForPlacement(input.rows.map((row) => row.id), input.placement ?? "roster", input.formerMainId).filter((id) => admitted.has(id) && input.killswitch?.get(id) !== false);
  return { order, admission };
}
function nextOrderedAttempt(order, attempts, retryStatuses) {
  const last = attempts.at(-1);
  if (last !== void 0) {
    if (last.status === void 0 || !retryStatuses.includes(last.status)) {
      return void 0;
    }
  }
  const tried = new Set(attempts.map((attempt) => attempt.id));
  return order.find((id) => !tried.has(id));
}
var DEFAULT_FORMER_MAIN_ID;
var init_ordered = __esm({
  "../core/dist/common-auth-embedded/routing/ordered.js"() {
    "use strict";
    init_admission();
    DEFAULT_FORMER_MAIN_ID = "main";
  }
});

// ../core/dist/common-auth-embedded/routing/pins.js
function isPinValid(pin, validIds, currentIdentity) {
  if (!validIds.has(pin.accountId))
    return false;
  return !(typeof pin.wireIdentity === "string" && typeof currentIdentity === "string" && pin.wireIdentity !== currentIdentity);
}
function pendingBytesForPins(pins, quotaCheckedAtById, excludedSessionKey) {
  const pending = /* @__PURE__ */ new Map();
  for (const [sessionKey, pin] of pins) {
    if (sessionKey === excludedSessionKey)
      continue;
    if (pin.quotaCheckedAt !== quotaCheckedAtById.get(pin.accountId))
      continue;
    pending.set(pin.accountId, (pending.get(pin.accountId) ?? 0) + (pin.inputBytes ?? 0));
  }
  return pending;
}
var init_pins = __esm({
  "../core/dist/common-auth-embedded/routing/pins.js"() {
    "use strict";
  }
});

// ../core/dist/common-auth-embedded/routing/sticky.js
function snapshotCheckedAt(quota, entryCheckedAt) {
  for (const checkedAt of [quota?.checkedAt, entryCheckedAt]) {
    if (typeof checkedAt === "number" && Number.isFinite(checkedAt)) {
      return checkedAt;
    }
  }
  return void 0;
}
function defaultStickyStatusClass(status) {
  if (status === 401 || status === 403)
    return "permanent";
  if (status === void 0 || status === 0 || !Number.isFinite(status) || status >= 500 && status <= 599 || status === 429) {
    return "transient";
  }
  return "healthy";
}
function windowReadings(quota) {
  return quota.limits.filter((limit) => limit.kind === "reading").sort((left, right) => {
    const leftKnown = left.windowMinutes !== void 0;
    const rightKnown = right.windowMinutes !== void 0;
    if (leftKnown !== rightKnown)
      return leftKnown ? -1 : 1;
    if (leftKnown && rightKnown) {
      return (right.windowMinutes ?? 0) - (left.windowMinutes ?? 0);
    }
    return 0;
  });
}
function decideStickyBreak(input) {
  const statusClass = (input.classifyStatus ?? defaultStickyStatusClass)(input.status);
  if (statusClass === "permanent") {
    return { action: "migrate", reason: "permanent" };
  }
  if (!input.quota)
    return { action: "retain", reason: "unknown" };
  const checkedAt = snapshotCheckedAt(input.quota, input.quotaCheckedAt);
  if (checkedAt === void 0 || !Number.isFinite(checkedAt) || input.now - checkedAt > QUOTA_STALENESS_MS) {
    return { action: "retain", reason: "stale" };
  }
  if (input.killswitchPasses === false) {
    return { action: "migrate", reason: "killswitch" };
  }
  for (const limit of windowReadings(input.quota)) {
    const remaining = limit.remainingPercent;
    if (typeof remaining === "number" && Number.isFinite(remaining) && remaining <= 0) {
      return {
        action: "migrate",
        reason: "exhausted",
        window: { scope: limit.scope, label: limit.label },
        ...typeof limit.resetsAt === "string" ? { resetsAt: limit.resetsAt } : {}
      };
    }
  }
  const budgetReset = budgetExhaustedResetAt(input.quota, input.now);
  if (budgetReset) {
    return {
      action: "migrate",
      reason: "exhausted",
      resetsAt: budgetReset.resetsAt
    };
  }
  return { action: "retain", reason: statusClass };
}
function sustainableWindowWeight(window, reservePercent, now) {
  const spendable = Math.max(0, window.remainingPercent - reservePercent);
  if (spendable <= 0)
    return 0;
  if (!window.resetsAt)
    return spendable;
  const resetMs = Date.parse(window.resetsAt);
  if (!Number.isFinite(resetMs) || resetMs <= now)
    return spendable;
  const hours = Math.max((resetMs - now) / 36e5, MIN_RESET_HOURS);
  return spendable / hours;
}
function compareAccountIds(left, right) {
  if (left < right)
    return -1;
  if (left > right)
    return 1;
  return 0;
}
function candidateWeight(candidate, now) {
  if (!candidate.quota)
    return void 0;
  const quotaCheckedAt = snapshotCheckedAt(candidate.quota, candidate.quotaCheckedAt);
  if (quotaCheckedAt === void 0 || now - quotaCheckedAt > QUOTA_STALENESS_MS) {
    return void 0;
  }
  const weights = windowReadings(candidate.quota).map((limit) => sustainableWindowWeight({
    remainingPercent: limit.remainingPercent ?? Number.NaN,
    ...limit.resetsAt === void 0 ? {} : { resetsAt: limit.resetsAt }
  }, candidate.reservePercent[limit.label] ?? 0, now));
  const budget = candidate.quota.budget;
  if (budget && typeof budget.remainingPercent === "number" && Number.isFinite(budget.remainingPercent)) {
    weights.push(sustainableWindowWeight({
      remainingPercent: budget.remainingPercent,
      ...budget.resetsAt === void 0 ? {} : { resetsAt: budget.resetsAt }
    }, 0, now));
  }
  const weight = weights.length > 0 ? Math.min(...weights) : 0;
  return weight > 0 ? { candidate, quotaCheckedAt, weight } : void 0;
}
function selectStickyCandidate(input) {
  const eligibleCandidates = input.candidates.filter((candidate) => candidate.killswitchPasses !== false);
  if (input.candidates.length === 0) {
    throw new Error("Cannot select a sticky candidate: input.candidates is empty");
  }
  if (eligibleCandidates.length === 0)
    return void 0;
  const weighted = eligibleCandidates.map((candidate) => candidateWeight(candidate, input.now)).filter((candidate) => candidate !== void 0);
  if (weighted.length > 0) {
    weighted.sort((left, right) => {
      const leftScore = ((input.pendingBytes.get(left.candidate.accountId) ?? 0) + input.requestBytes) / Math.max(left.weight, MIN_WEIGHT);
      const rightScore = ((input.pendingBytes.get(right.candidate.accountId) ?? 0) + input.requestBytes) / Math.max(right.weight, MIN_WEIGHT);
      return leftScore - rightScore || left.candidate.configuredOrder - right.candidate.configuredOrder || compareAccountIds(left.candidate.accountId, right.candidate.accountId);
    });
    const selected = weighted[0];
    if (selected) {
      return {
        accountId: selected.candidate.accountId,
        quotaCheckedAt: selected.quotaCheckedAt,
        source: "weighted"
      };
    }
  }
  input.onEmptyWeightedSet?.();
  const fallback = [...eligibleCandidates].sort((left, right) => {
    const leftHasCredits = (left.resetCreditsApplicable ?? 0) > 0 ? 1 : 0;
    const rightHasCredits = (right.resetCreditsApplicable ?? 0) > 0 ? 1 : 0;
    return rightHasCredits - leftHasCredits || left.configuredOrder - right.configuredOrder || compareAccountIds(left.accountId, right.accountId);
  })[0];
  if (!fallback) {
    throw new Error("Cannot select a sticky candidate: input.candidates is empty");
  }
  return {
    accountId: fallback.accountId,
    quotaCheckedAt: snapshotCheckedAt(fallback.quota, fallback.quotaCheckedAt),
    source: "mode-fallback"
  };
}
function routeSticky(input) {
  const admission = admit(input);
  const admitted = new Map(admission.admitted.map((row) => [row.id, row]));
  const refusals = new Map(admission.refused.map((r) => [r.id, r]));
  const excluded = new Set(admission.excluded.map((row) => row.id));
  const validIds = new Set(input.rows.map((row) => row.id));
  const pinValid = input.pin !== void 0 && isPinValid(input.pin, validIds, input.identities?.get(input.pin.accountId));
  if (pinValid && input.pin) {
    const pinned = admitted.get(input.pin.accountId);
    if (pinned && input.killswitch?.get(pinned.id) !== false) {
      return {
        outcome: "dispatch",
        accountId: pinned.id,
        source: "pin",
        ...pinned.projection?.checkedAt === void 0 ? {} : { quotaCheckedAt: pinned.projection.checkedAt },
        pin: { action: "retain" },
        refusedSelections: [],
        admission
      };
    }
  }
  const pinRefusal = input.pin ? refusals.get(input.pin.accountId) : void 0;
  const pinMoves = pinValid && input.pin !== void 0 && input.refusedPinPolicy === "move-on-confirmed-exhaustion" && (input.killswitch?.get(input.pin.accountId) === false || pinRefusal?.reason === "exhausted" || pinRefusal?.reason === "budget-spent");
  const reserveFor = (row) => {
    const perRow = typeof input.rowReservePercent === "function" ? input.rowReservePercent(row) : input.rowReservePercent?.get(row.id);
    return perRow ?? input.reservePercent ?? {};
  };
  const scope = input.scope;
  let candidates = input.rows.map((row, configuredOrder) => ({ row, configuredOrder })).filter(({ row }) => !excluded.has(row.id)).map(({ row, configuredOrder }) => {
    const killswitchPasses = input.killswitch?.get(row.id);
    const credits = input.resetCreditsApplicable?.get(row.id);
    return {
      accountId: row.id,
      quota: row.kind === "api-key" ? void 0 : admitted.get(row.id)?.projection ?? projectQuota(row.quota, scope),
      reservePercent: reserveFor(row),
      configuredOrder,
      ...credits === void 0 ? {} : { resetCreditsApplicable: credits },
      ...killswitchPasses === void 0 ? {} : { killswitchPasses }
    };
  });
  const refusedSelections = [];
  const unplaced = pinValid ? { action: "retain" } : input.pin ? { action: "clear" } : { action: "none" };
  while (candidates.length > 0) {
    const selection = selectStickyCandidate({
      candidates,
      pendingBytes: input.pendingBytes ?? /* @__PURE__ */ new Map(),
      requestBytes: input.requestBytes,
      now: input.now,
      ...input.onEmptyWeightedSet ? { onEmptyWeightedSet: input.onEmptyWeightedSet } : {}
    });
    if (!selection)
      break;
    const refusal3 = refusals.get(selection.accountId);
    if (refusal3) {
      refusedSelections.push(refusal3);
      candidates = candidates.filter((candidate) => candidate.accountId !== selection.accountId);
      continue;
    }
    const identity = input.identities?.get(selection.accountId);
    return {
      outcome: "dispatch",
      accountId: selection.accountId,
      source: selection.source,
      ...selection.quotaCheckedAt === void 0 ? {} : { quotaCheckedAt: selection.quotaCheckedAt },
      pin: pinValid && !pinMoves ? { action: "retain" } : {
        action: "assign",
        pin: {
          accountId: selection.accountId,
          inputBytes: input.requestBytes,
          ...identity === void 0 ? {} : { wireIdentity: identity },
          ...selection.quotaCheckedAt === void 0 ? {} : { quotaCheckedAt: selection.quotaCheckedAt }
        }
      },
      refusedSelections,
      admission
    };
  }
  return {
    outcome: "no-admissible-account",
    pin: unplaced,
    refusedSelections,
    admission
  };
}
var QUOTA_STALENESS_MS, MIN_RESET_HOURS, MIN_WEIGHT;
var init_sticky = __esm({
  "../core/dist/common-auth-embedded/routing/sticky.js"() {
    "use strict";
    init_projection();
    init_admission();
    init_pins();
    QUOTA_STALENESS_MS = 15 * 6e4;
    MIN_RESET_HOURS = 1 / 60;
    MIN_WEIGHT = 1e-6;
  }
});

// ../core/dist/common-auth-embedded/routing/index.js
var routing_exports = {};
__export(routing_exports, {
  DEFAULT_FORMER_MAIN_ID: () => DEFAULT_FORMER_MAIN_ID,
  MIN_RESET_HOURS: () => MIN_RESET_HOURS,
  MIN_WEIGHT: () => MIN_WEIGHT,
  QUOTA_STALENESS_MS: () => QUOTA_STALENESS_MS,
  admit: () => admit,
  decideStickyBreak: () => decideStickyBreak,
  defaultStickyStatusClass: () => defaultStickyStatusClass,
  exclusionFor: () => exclusionFor,
  isPinValid: () => isPinValid,
  nextOrderedAttempt: () => nextOrderedAttempt,
  orderForPlacement: () => orderForPlacement,
  pendingBytesForPins: () => pendingBytesForPins,
  resolveRoutingMode: () => resolveRoutingMode,
  routeOrdered: () => routeOrdered,
  routeSticky: () => routeSticky,
  selectStickyCandidate: () => selectStickyCandidate,
  snapshotCheckedAt: () => snapshotCheckedAt,
  sustainableWindowWeight: () => sustainableWindowWeight
});
var init_routing = __esm({
  "../core/dist/common-auth-embedded/routing/index.js"() {
    "use strict";
    init_admission();
    init_ordered();
    init_pins();
    init_sticky();
  }
});

// ../core/dist/common-auth-embedded/logger/capture-sink.js
function createCaptureSink() {
  const records2 = [];
  const sink = (record2) => {
    records2.push(record2);
  };
  return {
    records: records2,
    sink,
    clear: () => {
      records2.length = 0;
    }
  };
}
var init_capture_sink = __esm({
  "../core/dist/common-auth-embedded/logger/capture-sink.js"() {
    "use strict";
  }
});

// ../core/dist/common-auth-embedded/logger/redact.js
function isError(value) {
  return value instanceof Error || Object.prototype.toString.call(value) === "[object Error]";
}
function createRedactor(options = {}) {
  const patterns = [TOKEN_VALUE, ...options.extraValuePatterns ?? []].map((pattern) => new RegExp(pattern.source, pattern.flags.includes("g") ? pattern.flags : `${pattern.flags}g`));
  function isSecretKey(key) {
    const normalized = key.toLowerCase().replace(/[-_]/g, "");
    return SECRET_KEY_EXACT.test(key) || normalized.includes("apikey") || normalized.endsWith("secret") || normalized.endsWith("password") || normalized.endsWith("token") && !normalized.endsWith("tokens") || !!options.extraSecretKeys?.(normalized);
  }
  function errorEntries(error) {
    const fields = error;
    const entries = [
      ["name", error.name],
      ["message", error.message],
      ["stack", error.stack]
    ];
    for (const key of ["code", "status", "cause"])
      if (fields[key] !== void 0)
        entries.push([key, fields[key]]);
    const listed = new Set(entries.map(([key]) => key));
    for (const entry of Object.entries(error))
      if (!listed.has(entry[0]))
        entries.push(entry);
    return entries;
  }
  function walk(value, keys, seen, errorDepth = 0) {
    if (typeof value === "string") {
      return patterns.reduce((text2, pattern) => text2.replace(pattern, MASK), value);
    }
    if (!value || typeof value !== "object")
      return value;
    if (seen.has(value))
      return "[Circular]";
    seen.add(value);
    try {
      if (Array.isArray(value))
        return value.map((item) => walk(item, keys, seen, errorDepth));
      const error = isError(value);
      if (error && errorDepth >= MAX_ERROR_DEPTH)
        return "[Truncated]";
      const childDepth = error ? errorDepth + 1 : errorDepth;
      return Object.fromEntries((error ? errorEntries(value) : Object.entries(value)).map(([key, item]) => [
        key,
        keys && isSecretKey(key) ? MASK : walk(item, keys, seen, childDepth)
      ]));
    } finally {
      seen.delete(value);
    }
  }
  return {
    redact: (value) => walk(value, true, /* @__PURE__ */ new WeakSet()),
    // Schema keys describe arguments, not credentials; only their string values are scrubbed.
    redactStrings: (value) => walk(value, false, /* @__PURE__ */ new WeakSet())
  };
}
var SECRET_KEY_EXACT, TOKEN_VALUE, MASK, MAX_ERROR_DEPTH, defaultRedactor, redact, redactStrings;
var init_redact = __esm({
  "../core/dist/common-auth-embedded/logger/redact.js"() {
    "use strict";
    SECRET_KEY_EXACT = /^(authorization|x-api-key|cookie|set-cookie|refresh|access|token)$/i;
    TOKEN_VALUE = /\b(Bearer\s+[\w.-]+|sk-[\w-]+|eyJ[\w.-]+)\b|ckh_[A-Za-z0-9_-]{20,}/g;
    MASK = "***REDACTED***";
    MAX_ERROR_DEPTH = 8;
    defaultRedactor = createRedactor();
    redact = defaultRedactor.redact;
    redactStrings = defaultRedactor.redactStrings;
  }
});

// ../core/dist/common-auth-embedded/logger/engine.js
import { appendFileSync, chmodSync, existsSync, renameSync, statSync } from "node:fs";
function chmodPrivate(path2) {
  try {
    chmodSync(path2, 384);
  } catch {
  }
}
function rotateIfNeeded(f) {
  try {
    if (!(existsSync(f) && statSync(f).size >= MAX_BYTES))
      return;
    for (let i = ROTATE_KEEP - 1; i >= 1; i--) {
      if (existsSync(`${f}.${i}`)) {
        const rotated2 = `${f}.${i + 1}`;
        renameSync(`${f}.${i}`, rotated2);
        chmodPrivate(rotated2);
      }
    }
    const rotated = `${f}.1`;
    renameSync(f, rotated);
    chmodPrivate(rotated);
  } catch {
  }
}
function safeSerialize(data) {
  try {
    return ` ${JSON.stringify(data)}`;
  } catch {
    return " [unserializable]";
  }
}
function createEngine(options) {
  let logFileSource;
  let initLevelSource;
  let runtimeLevel;
  let redactor = createRedactor();
  let captureSink;
  let buffer = [];
  let timer;
  function configure(next) {
    logFileSource = next.file;
    initLevelSource = next.level;
    redactor = createRedactor(next);
    captureSink = next.captureSink;
  }
  function setLogLevel3(l) {
    if (l === void 0 || l in ORDER)
      runtimeLevel = l;
  }
  function logFilePath() {
    if (logFileSource === void 0)
      return void 0;
    const resolved = typeof logFileSource === "function" ? logFileSource() : logFileSource;
    return resolved || void 0;
  }
  function configuredLevel() {
    if (runtimeLevel)
      return runtimeLevel;
    const floor = typeof initLevelSource === "function" ? initLevelSource() : initLevelSource;
    if (floor && floor in ORDER)
      return floor;
    return "info";
  }
  function flushLogs3() {
    if (timer) {
      clearTimeout(timer);
      timer = void 0;
    }
    if (!buffer.length)
      return;
    let file;
    try {
      file = logFilePath();
    } catch {
      buffer = [];
      return;
    }
    const text2 = buffer.join("");
    buffer = [];
    if (!file)
      return;
    try {
      rotateIfNeeded(file);
      if (existsSync(file))
        chmodPrivate(file);
      appendFileSync(file, text2, { encoding: "utf8", mode: 384 });
    } catch {
    }
  }
  function schedule() {
    if (!timer)
      timer = setTimeout(() => {
        timer = void 0;
        flushLogs3();
      }, 500);
  }
  function emit(channel, level, message, data) {
    if (logFileSource === void 0 && captureSink === void 0)
      return;
    try {
      if (ORDER[level] > ORDER[configuredLevel()])
        return;
      const scrubbedMessage = redactor.redactStrings(message);
      let scrubbedData;
      try {
        scrubbedData = redactor.redact(data);
      } catch {
        scrubbedData = "[unserializable]";
      }
      const line = `[${(/* @__PURE__ */ new Date()).toISOString()}] ${level.toUpperCase()} [${channel}] ${scrubbedMessage}` + (data === void 0 ? "" : safeSerialize(scrubbedData)) + "\n";
      try {
        captureSink?.({
          channel,
          level,
          message: scrubbedMessage,
          data: scrubbedData
        });
      } catch {
      }
      if (logFileSource === void 0)
        return;
      buffer.push(line);
      if (buffer.length >= 50)
        flushLogs3();
      else
        schedule();
    } catch {
    }
  }
  function createLogger5(channel) {
    return {
      error: (m, d) => emit(channel, "error", m, d),
      warn: (m, d) => emit(channel, "warn", m, d),
      info: (m, d) => emit(channel, "info", m, d),
      debug: (m, d) => emit(channel, "debug", m, d),
      trace: (m, d) => emit(channel, "trace", m, d)
    };
  }
  function reset() {
    buffer = [];
    if (timer) {
      clearTimeout(timer);
      timer = void 0;
    }
    logFileSource = void 0;
    initLevelSource = void 0;
    runtimeLevel = void 0;
    redactor = createRedactor();
    captureSink = void 0;
  }
  if (options)
    configure(options);
  return { configure, createLogger: createLogger5, setLogLevel: setLogLevel3, flushLogs: flushLogs3, reset };
}
function createLoggerInstance(options) {
  const { configure, createLogger: createLogger5, setLogLevel: setLogLevel3, flushLogs: flushLogs3 } = createEngine(options);
  return { configure, createLogger: createLogger5, setLogLevel: setLogLevel3, flushLogs: flushLogs3 };
}
function initLogger(options) {
  defaultEngine.configure(options);
  const { configure, createLogger: createLogger5, setLogLevel: setLogLevel3, flushLogs: flushLogs3 } = defaultEngine;
  return { configure, createLogger: createLogger5, setLogLevel: setLogLevel3, flushLogs: flushLogs3 };
}
function setLogLevel(l) {
  defaultEngine.setLogLevel(l);
}
function flushLogs() {
  defaultEngine.flushLogs();
}
function createLogger2(channel) {
  return defaultEngine.createLogger(channel);
}
async function flushForTest() {
  defaultEngine.flushLogs();
}
function resetLoggerForTest() {
  defaultEngine.reset();
}
var ORDER, MAX_BYTES, ROTATE_KEEP, defaultEngine;
var init_engine = __esm({
  "../core/dist/common-auth-embedded/logger/engine.js"() {
    "use strict";
    init_redact();
    ORDER = {
      error: 0,
      warn: 1,
      info: 2,
      debug: 3,
      trace: 4
    };
    MAX_BYTES = 5 * 1024 * 1024;
    ROTATE_KEEP = 3;
    defaultEngine = createEngine();
  }
});

// ../core/dist/common-auth-embedded/logger/index.js
var logger_exports = {};
__export(logger_exports, {
  createCaptureSink: () => createCaptureSink,
  createLogger: () => createLogger2,
  createLoggerInstance: () => createLoggerInstance,
  createRedactor: () => createRedactor,
  flushForTest: () => flushForTest,
  flushLogs: () => flushLogs,
  initLogger: () => initLogger,
  redact: () => redact,
  redactStrings: () => redactStrings,
  resetLoggerForTest: () => resetLoggerForTest,
  setLogLevel: () => setLogLevel
});
var init_logger = __esm({
  "../core/dist/common-auth-embedded/logger/index.js"() {
    "use strict";
    init_capture_sink();
    init_engine();
    init_redact();
  }
});

// ../core/dist/common-auth-embedded/commands/seam.js
function createTextRedactor(options = {}) {
  const { redactStrings: redactStrings3 } = createRedactor({
    ...options,
    extraValuePatterns: [
      ...SEAM_VALUE_PATTERNS,
      ...options.extraValuePatterns ?? []
    ]
  });
  return (text2) => redactStrings3(text2);
}
function projectFailure(error) {
  if (error instanceof CommandError)
    return {
      code: CODE_SHAPE.test(error.code) ? error.code : ACTION_FAILED.code,
      text: error.message
    };
  if (error instanceof PoolOperationError)
    return {
      code: `pool-${error.kind}`,
      text: STORE_KINDS_WITH_OWN_MESSAGE.has(error.kind) ? error.message : `The account pool could not do that (${error.kind}).`
    };
  return ACTION_FAILED;
}
function isCredentialName(name) {
  const normalized = name.toLowerCase().replace(/[-_]/g, "");
  return CREDENTIAL_NAMES.has(normalized) || normalized.endsWith("token") || normalized.endsWith("key") || normalized.endsWith("secret");
}
function isPlainRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function scrub(value, path2, report) {
  if (typeof value === "string") {
    const clean = report.redact(value);
    if (clean !== value)
      report.redacted.push(path2);
    return clean;
  }
  if (Array.isArray(value))
    return value.map((entry, index) => scrub(entry, `${path2}[${index}]`, report));
  if (!isPlainRecord(value))
    return value;
  const out = {};
  for (const [name, entry] of Object.entries(value)) {
    if (isCredentialName(name)) {
      report.dropped.push(`${path2}.${name}`);
      continue;
    }
    Object.defineProperty(out, name, {
      value: scrub(entry, `${path2}.${name}`, report),
      enumerable: true,
      writable: true,
      configurable: true
    });
  }
  return out;
}
function sealed(payload, command, seam) {
  const report = {
    redact: seam.redact,
    dropped: [],
    redacted: []
  };
  const clean = scrub(payload, "payload", report);
  if (report.dropped.length > 0)
    seam.logger.warn("credential-shaped field dropped from a command payload", {
      command,
      fields: report.dropped
    });
  if (report.redacted.length > 0)
    seam.logger.warn("secret-shaped text masked in a command payload", {
      command,
      fields: report.redacted
    });
  return clean;
}
function projectChoice(choice) {
  return { value: String(choice.value), label: String(choice.label) };
}
function projectKnob(knob) {
  switch (knob.kind) {
    case "choice":
      return {
        kind: "choice",
        id: knob.id,
        label: knob.label,
        choices: (knob.choices ?? []).map(projectChoice),
        ...knob.value !== void 0 ? { value: knob.value } : {}
      };
    case "toggle":
      return {
        kind: "toggle",
        id: knob.id,
        label: knob.label,
        value: knob.value === true
      };
    case "number":
      return {
        kind: "number",
        id: knob.id,
        label: knob.label,
        ...knob.value !== void 0 ? { value: knob.value } : {},
        ...knob.min !== void 0 ? { min: knob.min } : {},
        ...knob.max !== void 0 ? { max: knob.max } : {},
        ...knob.required ? { required: true } : {}
      };
    case "text":
      return {
        kind: "text",
        id: knob.id,
        label: knob.label,
        ...knob.value !== void 0 && !knob.masked ? { value: knob.value } : {},
        ...knob.placeholder !== void 0 ? { placeholder: knob.placeholder } : {},
        ...knob.masked ? { masked: true } : {},
        ...knob.required ? { required: true } : {}
      };
  }
}
function confirmationOf(action) {
  if (action.irreversible === true)
    return {
      message: action.confirm || DEFAULT_IRREVERSIBLE_CONFIRMATION,
      irreversible: true
    };
  if (action.confirm)
    return { message: action.confirm, irreversible: false };
  return void 0;
}
function projectAction(action) {
  const confirm2 = confirmationOf(action);
  return {
    id: action.id,
    label: action.label,
    ...action.description !== void 0 ? { description: action.description } : {},
    ...action.group !== void 0 ? { group: String(action.group) } : {},
    knobs: (action.knobs ?? []).map(projectKnob),
    ...confirm2 ? { confirm: confirm2 } : {}
  };
}
function projectAccount(account) {
  return {
    id: account.id,
    ...account.label !== void 0 ? { label: account.label } : {},
    enabled: account.enabled,
    type: account.type,
    ...account.identity !== void 0 ? { identity: account.identity } : {}
  };
}
function projectItem(item) {
  return {
    id: item.id,
    label: item.label,
    ...item.detail !== void 0 ? { detail: item.detail } : {},
    ...item.group !== void 0 ? { group: String(item.group) } : {},
    ...item.status !== void 0 ? { status: String(item.status) } : {},
    ...item.account ? { account: projectAccount(item.account) } : {},
    ...item.facts !== void 0 ? { facts: item.facts } : {},
    actions: (item.actions ?? []).map(projectAction)
  };
}
function projectSection(section) {
  const { content } = section;
  return {
    id: section.id,
    slot: section.slot,
    title: section.title,
    lines: (content.lines ?? []).map(String),
    items: (content.items ?? []).map(projectItem),
    actions: (content.actions ?? []).map(projectAction),
    ...content.facts !== void 0 ? { facts: content.facts } : {}
  };
}
function projectMenu(command, title, sections) {
  return { command, title, sections: sections.map(projectSection) };
}
function dialogPayload(command, title, sections, seam) {
  return sealed({ command, menu: projectMenu(command, title, sections) }, command, seam);
}
function applyResult(command, title, sections, outcome, seam) {
  return sealed({
    command,
    ok: outcome.ok,
    text: String(outcome.text),
    ...!outcome.ok && outcome.code !== void 0 ? { code: CODE_SHAPE.test(outcome.code) ? outcome.code : "refused" } : {},
    ...outcome.needsConfirmation ? { needsConfirmation: true } : {},
    menu: projectMenu(command, title, sections)
  }, command, seam);
}
var SEAM_VALUE_PATTERNS, CommandError, CODE_SHAPE, ACTION_FAILED, STORE_KINDS_WITH_OWN_MESSAGE, DEFAULT_IRREVERSIBLE_CONFIRMATION, CREDENTIAL_NAMES;
var init_seam = __esm({
  "../core/dist/common-auth-embedded/commands/seam.js"() {
    "use strict";
    init_logger();
    init_store();
    SEAM_VALUE_PATTERNS = [
      /\b[\w-]*(?:secret|token|password|passwd|api[_-]?key|authorization|verifier)["']?\s*[:=]\s*["']?(?:(?:Bearer|Basic)\s+)?[^\s"'&,;}]+/gi,
      /\b[0-9a-fA-F]{32,}\b/g
    ];
    CommandError = class extends Error {
      code;
      constructor(code2, message, options) {
        super(message, options);
        this.name = "CommandError";
        this.code = code2;
      }
    };
    CODE_SHAPE = /^[a-z][a-z0-9-]{0,63}$/;
    ACTION_FAILED = {
      code: "action-failed",
      text: "That action failed."
    };
    STORE_KINDS_WITH_OWN_MESSAGE = /* @__PURE__ */ new Set([
      "unknown-row",
      "invalid-row",
      "invalid-input",
      "id-exists",
      "id-removed",
      "type-mismatch",
      "no-credential",
      "row-disabled",
      "row-protected",
      "duplicate-identity",
      "row-key-changed",
      "invalid-order",
      "pending-migration",
      "provider",
      "pull",
      "attribution"
    ]);
    DEFAULT_IRREVERSIBLE_CONFIRMATION = "This cannot be undone. Continue?";
    CREDENTIAL_NAMES = /* @__PURE__ */ new Set([
      "access",
      "refresh",
      "apikey",
      "password",
      "authheader",
      "credential",
      "credentials"
    ]);
  }
});

// ../core/dist/common-auth-embedded/commands/builtins.js
function isRecord5(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function record(value) {
  return isRecord5(value) ? { ...value } : {};
}
function distinctRows(load) {
  if (load.status !== "ready")
    return [];
  const seen = /* @__PURE__ */ new Set();
  return load.rows.filter((row) => {
    if (seen.has(row.id))
      return false;
    seen.add(row.id);
    return true;
  });
}
function rowName(row, identity) {
  return row.label ?? identity ?? row.id;
}
function projected(row, scope) {
  return isQuotaMap(row.quota) ? projectQuota(row.quota, scope) : void 0;
}
function count2(n, noun) {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}
function loadProblem(load) {
  if (load.status === "pending-migration")
    return "The account pool has not been migrated yet.";
  if (load.status === "error")
    return `The ${load.file} file cannot be read: ${load.reason}`;
  return void 0;
}
function addedText(name, result) {
  switch (result.outcome) {
    case "added":
      return `Added ${name}.`;
    case "added-disabled":
      return `Added ${name}, disabled: another enabled account has the same identity.`;
    case "completed":
      return `Finished adding ${name}.`;
    case "rotated":
      return `${name} was already in the pool; its credential was updated.`;
    case "exists":
      return `${name} was already in the pool; its credential is unchanged.`;
  }
}
function failureMessage(error) {
  return projectFailure(error).text;
}
async function snapshot(store) {
  const load = await store.read();
  const read = await store.readSettings();
  return {
    load,
    rows: distinctRows(load),
    settings: read.status === "error" ? {} : read.settings
  };
}
function accountView(row, options) {
  const identity = options.accounts?.describeIdentity ? options.accounts.describeIdentity(row) : row.identity;
  const account = {
    id: row.id,
    ...row.label !== void 0 ? { label: row.label } : {},
    enabled: row.enabled,
    type: row.type,
    ...identity !== void 0 ? { identity } : {}
  };
  return { account, name: rowName(row, identity) };
}
function accountsSection(options, snap) {
  const { store, extraLocks } = options;
  const locks = extraLocks ? { extraLocks } : {};
  const ids = snap.rows.map((row) => row.id);
  const problem = loadProblem(snap.load);
  const enabledCount = snap.rows.filter((row) => row.enabled).length;
  const items = snap.rows.map((row, index) => {
    const { account, name } = accountView(row, options);
    const detail = [
      row.type === "api" ? "API key" : "OAuth",
      ...account.identity !== void 0 ? [account.identity] : [],
      ...!row.invalid && !row.enabled && row.disabledReason ? [`disabled: ${row.disabledReason}`] : []
    ].join(" \xB7 ");
    const status = row.invalid ? "invalid" : row.enabled ? "enabled" : "disabled";
    const actions2 = [];
    if (!row.invalid && row.enabled)
      actions2.push({
        id: "disable",
        label: "Disable",
        run: async () => {
          await store.disable(row.id, MENU_DISABLED_REASON, locks);
          return `Disabled ${name}.`;
        }
      });
    if (!row.invalid && !row.enabled)
      actions2.push({
        id: "enable",
        label: "Enable",
        run: async () => {
          await store.enable(row.id, locks);
          return `Enabled ${name}.`;
        }
      });
    if (ids.length > 1)
      actions2.push({
        id: "move",
        label: "Move",
        knobs: [
          {
            kind: "choice",
            id: "position",
            label: "Position",
            choices: ids.map((_, at) => ({
              value: String(at + 1),
              label: String(at + 1)
            })),
            value: String(index + 1)
          }
        ],
        run: async ({ values }) => {
          const position = Number(values.position);
          const order = ids.filter((id) => id !== row.id);
          order.splice(position - 1, 0, row.id);
          const result = await store.reorder(order, locks);
          return result.outcome === "unchanged" ? `${name} is already at position ${position}.` : `Moved ${name} to position ${position}.`;
        }
      });
    actions2.push({
      id: "remove",
      label: "Remove",
      irreversible: true,
      confirm: `Remove ${name}? Its stored credential is deleted.`,
      run: async () => {
        await store.remove(row.id, {
          ...locks,
          ...options.accounts?.protect ? { protect: options.accounts.protect } : {}
        });
        return `Removed ${name}.`;
      }
    });
    return {
      id: row.id,
      label: name,
      detail,
      group: "Accounts",
      status,
      account,
      actions: actions2
    };
  });
  const login = options.accounts?.login;
  const actions = [];
  if (login && !problem)
    actions.push({
      id: "add",
      label: login.label ?? "Add account",
      group: ACTIONS_GROUP,
      knobs: login.knobs ?? [],
      run: async ({ values, invocation }) => {
        const outcome = await login.run(values, invocation);
        if (outcome.status === "cancelled")
          return { ok: false, text: outcome.message ?? "Login cancelled." };
        if (outcome.status === "ready") {
          const result = await store.add(outcome.account, locks);
          return addedText(outcome.account.label ?? result.id, result);
        }
        void outcome.completion.then(async (account) => {
          if (!account) {
            invocation.notify("Login cancelled.", "warning");
            return;
          }
          const result = await store.add(account, locks);
          invocation.notify(addedText(account.label ?? result.id, result));
        }, (error) => {
          invocation.notify(`Adding the account failed: ${failureMessage(error)}`, "error");
        }).catch((error) => {
          invocation.notify(`Adding the account failed: ${failureMessage(error)}`, "error");
        });
        return outcome.message;
      }
    });
  return {
    id: "accounts",
    slot: "accounts",
    title: "Accounts",
    content: {
      lines: problem ? [problem] : [
        snap.rows.length === 0 ? "No accounts yet" : `${count2(snap.rows.length, "account")}, ${enabledCount} enabled`
      ],
      items: problem ? [] : items,
      actions
    }
  };
}
function quotaSection(options, snap) {
  const scope = options.quota?.scope ?? "all";
  const now = options.now();
  const group = scope === "all" ? "Accounts" : `Accounts \xB7 ${scope}`;
  const check = async (ids, invocation) => {
    if (options.quota?.check)
      await options.quota.check(ids, invocation);
    else {
      for (const id of ids)
        options.store.requestReading(id);
      await options.store.pullsSettled();
    }
  };
  const candidates = snap.rows.filter((row) => row.candidate);
  const items = candidates.map((row) => {
    const { account, name } = accountView(row, options);
    const quota = projected(row, scope);
    return {
      id: row.id,
      label: name,
      group,
      status: formatQuota(quota, { now, form: "compact" }),
      detail: formatQuota(quota, { now, form: "full" }),
      account,
      actions: [
        {
          id: "check",
          label: "Check this account",
          run: async ({ invocation }) => {
            await check([row.id], invocation);
            return `Checked quota for ${name}.`;
          }
        }
      ]
    };
  });
  const unchecked = snap.rows.filter((row) => !row.candidate).map((row) => {
    const { name } = accountView(row, options);
    const reason = row.invalid ? "invalid" : !row.enabled ? "disabled" : row.credential === void 0 ? "no credential" : "unavailable";
    const quota = formatQuota(projected(row, scope), {
      now,
      form: "compact"
    });
    return `${name} (${reason}): ${quota}`;
  });
  const actions = [];
  if (candidates.length > 0)
    actions.push({
      id: "check",
      label: "Check now",
      description: "Checks every account that can be checked.",
      group: ACTIONS_GROUP,
      run: async ({ invocation }) => {
        const ids = candidates.map((row) => row.id);
        await check(ids, invocation);
        return `Checked quota for ${count2(ids.length, "account")}.`;
      }
    });
  return {
    id: "quota",
    slot: "quota",
    title: "Quota",
    content: {
      lines: snap.rows.length === 0 ? ["No accounts yet"] : unchecked,
      items,
      actions
    }
  };
}
function routingSection(options, snap) {
  const { store, extraLocks } = options;
  const locks = extraLocks ? { extraLocks } : {};
  const choices = [
    { value: "ordered", label: "Ordered (roster order)" },
    ...options.routing?.orderedVariants ?? [],
    { value: "sticky-balanced", label: "Sticky balanced" }
  ];
  const raw = record(snap.settings.routing).mode;
  const current = typeof raw === "string" && choices.some((choice) => choice.value === raw) ? raw : "ordered";
  const resolved = resolveRoutingMode(current);
  const ids = snap.rows.map((row) => row.id);
  const tried = orderForPlacement(ids, resolved.placement, options.routing?.formerMainId ?? DEFAULT_FORMER_MAIN_ID);
  const label = choices.find((choice) => choice.value === current)?.label ?? current;
  const lines = [`Mode: ${label}`];
  if (ids.length > 0)
    lines.push(`Roster order: ${ids.join(", ")}`);
  if (resolved.mode === "ordered" && tried.join() !== ids.join())
    lines.push(`Tried in order: ${tried.join(", ")}`);
  const actions = [
    {
      id: "mode",
      label: "Change mode",
      group: ACTIONS_GROUP,
      knobs: [
        { kind: "choice", id: "mode", label: "Mode", choices, value: current }
      ],
      run: async ({ values }) => {
        const mode = String(values.mode);
        await store.updateSettings((settings) => {
          settings.routing = { ...record(settings.routing), mode };
          return void 0;
        }, locks);
        return `Routing mode set to ${choices.find((choice) => choice.value === mode)?.label ?? mode}.`;
      }
    }
  ];
  if (ids.length > 1)
    actions.push({
      id: "order",
      label: "Set order",
      group: ACTIONS_GROUP,
      knobs: [
        {
          kind: "text",
          id: "order",
          label: "Account ids, first to last",
          value: ids.join(", "),
          required: true
        }
      ],
      run: async ({ values }) => {
        const order = String(values.order).split(/[\s,]+/).filter((id) => id.length > 0);
        const result = await store.reorder(order, locks);
        return result.outcome === "unchanged" ? "The order is unchanged." : `Order set to ${result.ids.join(", ")}.`;
      }
    });
  return {
    id: "routing",
    slot: "routing",
    title: "Routing",
    content: { lines, actions }
  };
}
function floorLabels(options, snap) {
  if (options.limits?.labels)
    return [...options.limits.labels];
  const scope = options.quota?.scope ?? "all";
  const labels = [];
  for (const row of snap.rows)
    for (const limit of projected(row, scope)?.limits ?? [])
      if (!labels.includes(limit.label))
        labels.push(limit.label);
  return labels.length > 0 ? labels : ["primary"];
}
function floorNames(options, snap) {
  const scope = options.quota?.scope ?? "all";
  const names = /* @__PURE__ */ new Map();
  for (const row of snap.rows)
    for (const limit of projected(row, scope)?.limits ?? [])
      if (limit.windowMinutes !== void 0 && !names.has(limit.label))
        names.set(limit.label, quotaWindowName(limit));
  return (label) => names.get(label) ?? label;
}
function limitsSection(options, snap) {
  const { store, extraLocks } = options;
  const locks = extraLocks ? { extraLocks } : {};
  const killswitch = record(snap.settings.killswitch);
  const enabled = killswitch.enabled === true;
  const floors = record(killswitch.accounts);
  const labels = floorLabels(options, snap);
  const nameOf = floorNames(options, snap);
  const state = enabled ? "on" : "off";
  const items = snap.rows.map((row) => {
    const { account, name } = accountView(row, options);
    const own = record(floors[row.id]);
    const set = labels.filter((label) => typeof own[label] === "number");
    return {
      id: row.id,
      label: name,
      group: `Floors \xB7 killswitch ${state}`,
      // A floor is the least "% left" the account may fall to.
      status: set.length === 0 ? "no floors" : set.map((label) => `${nameOf(label)} \u2265${own[label]}%`).join(" \xB7 "),
      account,
      actions: [
        {
          id: "floors",
          label: "Set floors",
          knobs: labels.map((label) => ({
            kind: "number",
            id: label,
            label: `Minimum % left for ${nameOf(label)}`,
            min: 0,
            max: 100,
            ...typeof own[label] === "number" ? { value: own[label] } : {}
          })),
          run: async ({ values }) => {
            await store.updateSettings((settings) => {
              const next = record(settings.killswitch);
              const accounts = record(next.accounts);
              const mine = record(accounts[row.id]);
              for (const label of labels) {
                const value = values[label];
                if (typeof value === "number")
                  mine[label] = value;
                else if (value === null)
                  delete mine[label];
              }
              if (Object.keys(mine).length > 0)
                accounts[row.id] = mine;
              else
                delete accounts[row.id];
              if (Object.keys(accounts).length > 0)
                next.accounts = accounts;
              else
                delete next.accounts;
              settings.killswitch = next;
              return void 0;
            }, locks);
            return `Floors updated for ${name}.`;
          }
        }
      ]
    };
  });
  return {
    id: "limits",
    slot: "limits",
    title: "Limits",
    content: {
      lines: [`Killswitch ${state}`],
      items,
      actions: [
        {
          id: "killswitch",
          label: enabled ? "Turn killswitch off" : "Turn killswitch on",
          description: "With the killswitch on, an account whose quota falls below one of its floors is not used.",
          group: ACTIONS_GROUP,
          knobs: [
            {
              kind: "toggle",
              id: "enabled",
              label: "Killswitch",
              value: !enabled
            }
          ],
          run: async ({ values }) => {
            const on = values.enabled === true;
            await store.updateSettings((settings) => {
              settings.killswitch = {
                ...record(settings.killswitch),
                enabled: on
              };
              return void 0;
            }, locks);
            return `Killswitch ${on ? "on" : "off"}.`;
          }
        }
      ]
    }
  };
}
async function builtinSections(options) {
  const snap = await snapshot(options.store);
  return [
    accountsSection(options, snap),
    quotaSection(options, snap),
    routingSection(options, snap),
    limitsSection(options, snap)
  ];
}
var MENU_DISABLED_REASON, ACTIONS_GROUP;
var init_builtins = __esm({
  "../core/dist/common-auth-embedded/commands/builtins.js"() {
    "use strict";
    init_quota();
    init_routing();
    init_seam();
    MENU_DISABLED_REASON = "disabled from the command menu";
    ACTIONS_GROUP = "Actions";
  }
});

// ../core/dist/common-auth-embedded/commands/menu.js
function ownInvocation(invocation, redact3) {
  const { sessionId } = invocation;
  const notify = invocation.notify.bind(invocation);
  return Object.freeze({
    ...sessionId !== void 0 ? { sessionId } : {},
    notify: (message, kind) => kind === void 0 ? notify(redact3(String(message))) : notify(redact3(String(message)), kind)
  });
}
function coerceOne(knob, raw) {
  switch (knob.kind) {
    case "choice": {
      const value = raw ?? knob.value;
      if (typeof value === "string" && knob.choices.some((choice) => choice.value === value))
        return { value };
      return { problem: `Choose one of the options for ${knob.label}.` };
    }
    case "toggle": {
      const value = raw ?? knob.value;
      return typeof value === "boolean" ? { value } : { problem: `${knob.label} must be on or off.` };
    }
    case "number": {
      const value = raw === void 0 ? knob.value ?? null : raw;
      if (value === null || value === "") {
        return knob.required ? { problem: `${knob.label} needs a number.` } : { value: null };
      }
      const number = typeof value === "number" ? value : Number(value);
      if (typeof value === "boolean" || !Number.isFinite(number))
        return { problem: `${knob.label} needs a number.` };
      if (knob.min !== void 0 && number < knob.min)
        return { problem: `${knob.label} must be at least ${knob.min}.` };
      if (knob.max !== void 0 && number > knob.max)
        return { problem: `${knob.label} must be at most ${knob.max}.` };
      return { value: number };
    }
    case "text": {
      const value = raw === void 0 ? knob.value ?? null : raw;
      if (value === null || value === "")
        return knob.required ? { problem: `${knob.label} cannot be empty.` } : { value: null };
      return typeof value === "string" ? { value } : { problem: `${knob.label} must be text.` };
    }
  }
}
function coerceValues(knobs, raw) {
  const values = {};
  for (const knob of knobs) {
    const given = raw && Object.hasOwn(raw, knob.id) ? raw[knob.id] : void 0;
    const result = coerceOne(knob, given);
    if ("problem" in result)
      return result;
    values[knob.id] = result.value;
  }
  return { values };
}
function findAction(sections, request) {
  const section = sections.find((entry) => entry.id === request.sectionId);
  if (!section)
    return void 0;
  const actions = request.itemId === void 0 ? section.content.actions : section.content.items?.find((item) => item.id === request.itemId)?.actions;
  return actions?.find((action) => action.id === request.actionId);
}
function createCommandMenu(options) {
  const logger = options.logger ?? createLogger2("commands");
  const redact3 = createTextRedactor(options.redaction);
  const seam = { logger, redact: redact3 };
  const now = options.now ?? Date.now;
  const extras = options.extras ?? [];
  const replaced = options.replace ?? {};
  const builtSlots = STORE_SLOTS.filter((slot) => !replaced[slot]);
  for (const slot of STORE_SLOTS) {
    if (replaced[slot] && options[slot] !== void 0)
      throw new Error(`the ${slot} section is replaced; its built-in options cannot also be given`);
  }
  const store = options.store;
  if (builtSlots.length > 0 && !store)
    throw new Error(`a store is required for the built-in ${builtSlots.join(", ")} section${builtSlots.length > 1 ? "s" : ""}`);
  const seen = /* @__PURE__ */ new Set();
  for (const extra of extras) {
    if (BUILTIN_IDS.has(extra.id) || seen.has(extra.id))
      throw new Error(`extra section id ${extra.id} is taken`);
    seen.add(extra.id);
  }
  async function plugin(id, slot, section, invocation) {
    try {
      return {
        id,
        slot,
        title: section.title,
        content: await section.build(invocation)
      };
    } catch (error) {
      logger.warn("command menu section failed to build", {
        command: options.command,
        section: id,
        error: redact3(error instanceof Error ? error.message : String(error))
      });
      return {
        id,
        slot,
        title: section.title,
        content: { lines: ["This section could not be loaded."] }
      };
    }
  }
  async function sections(invocation) {
    const built = store && builtSlots.length > 0 ? await builtinSections({
      store,
      now,
      ...options.extraLocks ? { extraLocks: options.extraLocks } : {},
      ...options.accounts ? { accounts: options.accounts } : {},
      ...options.quota ? { quota: options.quota } : {},
      ...options.routing ? { routing: options.routing } : {},
      ...options.limits ? { limits: options.limits } : {}
    }) : [];
    const out = [];
    for (const slot of STORE_SLOTS) {
      const replacement = replaced[slot];
      if (replacement)
        out.push(await plugin(slot, slot, replacement, invocation));
      else {
        const section = built.find((entry) => entry.slot === slot);
        if (section)
          out.push(section);
      }
    }
    if (options.cache)
      out.push(await plugin("cache", "cache", options.cache, invocation));
    if (options.diagnostics)
      out.push(await plugin("diagnostics", "diagnostics", options.diagnostics, invocation));
    for (const extra of extras)
      out.push(await plugin(extra.id, "extra", extra, invocation));
    return out;
  }
  return {
    command: options.command,
    async open(invocation) {
      const own = ownInvocation(invocation, redact3);
      return dialogPayload(options.command, options.title, await sections(own), seam);
    },
    async apply(request, invocation) {
      const own = ownInvocation(invocation, redact3);
      const finish = async (outcome2) => applyResult(options.command, options.title, await sections(own), outcome2, seam);
      const action = request.command === options.command ? findAction(await sections(own), request) : void 0;
      if (!action)
        return finish({
          ok: false,
          code: "unavailable",
          text: "That action is no longer available."
        });
      const confirmation = confirmationOf(action);
      if (confirmation && request.confirmed !== true)
        return finish({
          ok: false,
          code: "needs-confirmation",
          text: confirmation.message,
          needsConfirmation: true
        });
      const coerced = coerceValues(action.knobs ?? [], request.values);
      if ("problem" in coerced)
        return finish({
          ok: false,
          code: "invalid-input",
          text: coerced.problem
        });
      let outcome;
      try {
        const result = await action.run({
          values: coerced.values,
          ...request.itemId !== void 0 ? { itemId: request.itemId } : {},
          invocation: own
        });
        outcome = typeof result === "string" ? { ok: true, text: result } : {
          ok: result.ok,
          text: result.text,
          ...result.ok ? {} : { code: result.code ?? "refused" }
        };
      } catch (error) {
        const failure = projectFailure(error);
        logger.warn("command menu action failed", {
          command: options.command,
          section: request.sectionId,
          action: request.actionId,
          code: failure.code,
          error: redact3(error instanceof Error ? error.message : String(error))
        });
        outcome = { ok: false, ...failure };
      }
      return finish(outcome);
    }
  };
}
function isKnobValue(value) {
  return value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isFinite(value);
}
function parseApplyRequest(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    return void 0;
  const raw = value;
  if (typeof raw.command !== "string" || typeof raw.sectionId !== "string" || typeof raw.actionId !== "string")
    return void 0;
  if (raw.itemId !== void 0 && typeof raw.itemId !== "string")
    return void 0;
  if (raw.sessionId !== void 0 && typeof raw.sessionId !== "string")
    return void 0;
  if (raw.confirmed !== void 0 && typeof raw.confirmed !== "boolean")
    return void 0;
  const values = {};
  if (raw.values !== void 0) {
    if (raw.values === null || typeof raw.values !== "object" || Array.isArray(raw.values))
      return void 0;
    for (const [name, entry] of Object.entries(raw.values)) {
      if (!isKnobValue(entry))
        return void 0;
      Object.defineProperty(values, name, {
        value: entry,
        enumerable: true,
        writable: true,
        configurable: true
      });
    }
  }
  return {
    command: raw.command,
    sectionId: raw.sectionId,
    actionId: raw.actionId,
    ...typeof raw.itemId === "string" ? { itemId: raw.itemId } : {},
    ...raw.values !== void 0 ? { values } : {},
    ...raw.confirmed === true ? { confirmed: true } : {},
    ...typeof raw.sessionId === "string" ? { sessionId: raw.sessionId } : {}
  };
}
var BUILTIN_IDS, STORE_SLOTS;
var init_menu = __esm({
  "../core/dist/common-auth-embedded/commands/menu.js"() {
    "use strict";
    init_logger();
    init_builtins();
    init_seam();
    BUILTIN_IDS = /* @__PURE__ */ new Set([
      "accounts",
      "quota",
      "routing",
      "limits",
      "cache",
      "diagnostics"
    ]);
    STORE_SLOTS = [
      "accounts",
      "quota",
      "routing",
      "limits"
    ];
  }
});

// ../core/dist/common-auth-embedded/commands/model.js
var SECTION_SLOTS;
var init_model = __esm({
  "../core/dist/common-auth-embedded/commands/model.js"() {
    "use strict";
    SECTION_SLOTS = [
      "accounts",
      "quota",
      "routing",
      "limits",
      "cache",
      "diagnostics",
      "extra"
    ];
  }
});

// ../core/dist/common-auth-embedded/commands/pi.js
async function pick(ui, title, entries) {
  const byLabel = /* @__PURE__ */ new Map();
  const labels = [];
  for (const entry of entries) {
    let label = entry.label;
    for (let n = 2; byLabel.has(label); n++)
      label = `${entry.label} (${n})`;
    byLabel.set(label, entry.value);
    labels.push(label);
  }
  const chosen = await ui.select(title, labels);
  return chosen === void 0 ? void 0 : byLabel.get(chosen);
}
function withLines(title, lines) {
  return lines.length > 0 ? `${title}
${lines.join("\n")}` : title;
}
function rowText(item) {
  return item.status ? `${item.label} \xB7 ${item.status}` : item.label;
}
function sectionText(section) {
  const text2 = [...section.lines];
  let header;
  for (const item of section.items) {
    if (item.actions.length > 0)
      continue;
    if (item.group !== void 0 && item.group !== header)
      text2.push(item.group);
    header = item.group;
    text2.push(item.group !== void 0 ? `  ${rowText(item)}` : rowText(item));
  }
  return text2;
}
function itemTitle(item) {
  const lines = item.detail ? [item.detail] : [];
  for (const [name, value] of Object.entries(item.facts ?? {}))
    lines.push(`${name}: ${String(value)}`);
  return withLines(rowText(item), lines);
}
async function askKnob(ui, knob) {
  switch (knob.kind) {
    case "choice": {
      const value = await pick(ui, knob.label, knob.choices.map((choice) => ({
        label: choice.value === knob.value ? `${choice.label} (current)` : choice.label,
        value: choice.value
      })));
      return value === void 0 ? void 0 : { value };
    }
    case "toggle": {
      const value = await pick(ui, knob.label, [
        { label: knob.value ? "On (current)" : "On", value: true },
        { label: knob.value ? "Off" : "Off (current)", value: false }
      ]);
      return value === void 0 ? void 0 : { value };
    }
    case "number": {
      const range = knob.min !== void 0 && knob.max !== void 0 ? ` (${knob.min}-${knob.max}${knob.required ? "" : ", empty clears"})` : knob.required ? "" : " (empty clears)";
      const typed = await ui.input(`${knob.label}${range}`, knob.value !== void 0 ? String(knob.value) : void 0);
      if (typed === void 0)
        return void 0;
      const text2 = typed.trim();
      if (text2 === "")
        return knob.required && knob.value !== void 0 ? { value: knob.value } : { value: null };
      const number = Number(text2);
      if (!Number.isFinite(number)) {
        ui.notify(`${knob.label} needs a number.`, "error");
        return void 0;
      }
      return { value: number };
    }
    case "text": {
      const typed = await ui.input(knob.label, knob.value ?? knob.placeholder);
      if (typed === void 0)
        return void 0;
      const text2 = typed.trim();
      if (text2 === "")
        return knob.required && knob.value !== void 0 ? { value: knob.value } : { value: null };
      return { value: text2 };
    }
  }
}
async function askValues(ui, action) {
  const values = {};
  for (const knob of action.knobs) {
    const answer = await askKnob(ui, knob);
    if (!answer)
      return void 0;
    values[knob.id] = answer.value;
  }
  return values;
}
async function runPiCommandMenu(menu, ui, options = {}) {
  const invocation = {
    ...options.sessionId !== void 0 ? { sessionId: options.sessionId } : {},
    notify: (message, kind) => ui.notify(message, kind)
  };
  let model = (await menu.open(invocation)).menu;
  for (; ; ) {
    const chosen = await pick(ui, model.title, model.sections.map((section) => ({
      label: section.lines[0] ? `${section.title}: ${section.lines[0]}` : section.title,
      value: section.id
    })));
    if (chosen === void 0)
      return;
    for (; ; ) {
      const section = model.sections.find((entry) => entry.id === chosen);
      if (!section)
        break;
      const entries = [
        ...section.items.filter((item2) => item2.actions.length > 0).map((item2) => ({
          label: rowText(item2),
          value: { kind: "item", item: item2 }
        })),
        ...section.actions.map((action2) => ({
          label: action2.label,
          value: { kind: "action", action: action2 }
        }))
      ];
      const text2 = sectionText(section);
      if (entries.length === 0 && text2.length === 0) {
        ui.notify("Nothing to do here.");
        break;
      }
      const choice = await pick(ui, withLines(section.title, text2), [
        ...entries,
        { label: "Back", value: { kind: "back" } }
      ]);
      if (!choice || choice.kind === "back")
        break;
      let action;
      let item;
      if (choice.kind === "item") {
        item = choice.item;
        action = await pick(ui, itemTitle(item), item.actions.map((entry) => ({ label: entry.label, value: entry })));
        if (!action)
          continue;
      } else {
        action = choice.action;
      }
      const values = await askValues(ui, action);
      if (!values)
        continue;
      if (action.confirm) {
        const yes = await ui.confirm(action.label, action.confirm.message);
        if (!yes) {
          ui.notify("Cancelled.");
          continue;
        }
      }
      const result = await menu.apply({
        command: model.command,
        sectionId: section.id,
        ...item ? { itemId: item.id } : {},
        actionId: action.id,
        values,
        ...action.confirm ? { confirmed: true } : {},
        ...options.sessionId !== void 0 ? { sessionId: options.sessionId } : {}
      }, invocation);
      ui.notify(result.text, result.ok ? "info" : "error");
      model = result.menu;
    }
  }
}
var init_pi = __esm({
  "../core/dist/common-auth-embedded/commands/pi.js"() {
    "use strict";
  }
});

// ../core/dist/common-auth-embedded/commands/index.js
var commands_exports = {};
__export(commands_exports, {
  ACTION_FAILED: () => ACTION_FAILED,
  CommandError: () => CommandError,
  DEFAULT_IRREVERSIBLE_CONFIRMATION: () => DEFAULT_IRREVERSIBLE_CONFIRMATION,
  MENU_DISABLED_REASON: () => MENU_DISABLED_REASON,
  SECTION_SLOTS: () => SECTION_SLOTS,
  createCommandMenu: () => createCommandMenu,
  createTextRedactor: () => createTextRedactor,
  parseApplyRequest: () => parseApplyRequest,
  projectFailure: () => projectFailure,
  runPiCommandMenu: () => runPiCommandMenu
});
var init_commands = __esm({
  "../core/dist/common-auth-embedded/commands/index.js"() {
    "use strict";
    init_builtins();
    init_menu();
    init_model();
    init_pi();
    init_seam();
  }
});

// ../core/dist/common-auth-embedded/auth-menu/doctor.js
async function runDoctorChecks(checks) {
  const findings = [];
  for (const check of checks) {
    try {
      findings.push(...await check.run());
    } catch (error) {
      findings.push({
        code: DOCTOR_CHECK_FAILED,
        message: `Check ${check.id} failed: ${error instanceof Error ? error.message : String(error)}`
      });
    }
  }
  return { findings };
}
function formatDoctorReport(title, report) {
  const lines = [title];
  if (report.findings.length === 0) {
    lines.push("No problems found.");
    return lines;
  }
  for (const finding of report.findings) {
    const repair = finding.repair ? " (repair available)" : "";
    lines.push(`- ${finding.message}${repair}`);
  }
  return lines;
}
async function applyChosenRepairs(context, report) {
  const outcome = { applied: [], declined: [], failed: [] };
  for (const finding of report.findings) {
    const repair = finding.repair;
    if (!repair)
      continue;
    if (!await context.confirm(`Apply repair: ${repair.label}?`)) {
      outcome.declined.push(finding);
      continue;
    }
    try {
      await repair.apply();
      outcome.applied.push(finding);
    } catch (error) {
      outcome.failed.push({ finding, error });
      context.print(`Repair failed: ${repair.label}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  return outcome;
}
function doctorAction(options) {
  const title = options.title ?? "Auth doctor";
  return {
    id: "doctor",
    label: options.label ?? "Auth doctor",
    hint: "check accounts and offer repairs",
    async run(context) {
      const report = await runDoctorChecks(options.checks);
      for (const line of formatDoctorReport(title, report))
        context.print(line);
      const repairable = report.findings.filter((finding) => finding.repair);
      if (repairable.length === 0) {
        if (report.findings.length > 0)
          context.print("No repairs are available.");
        return;
      }
      const outcome = await applyChosenRepairs(context, report);
      context.print(`Applied ${outcome.applied.length} of ${repairable.length} repair(s).`);
    }
  };
}
var DOCTOR_CHECK_FAILED;
var init_doctor = __esm({
  "../core/dist/common-auth-embedded/auth-menu/doctor.js"() {
    "use strict";
    DOCTOR_CHECK_FAILED = "doctor-check-failed";
  }
});

// ../core/dist/common-auth-embedded/auth-menu/login.js
import { execFileSync as defaultExecFileSync, spawn as defaultSpawn } from "node:child_process";
function openBrowserForMenu(url, platform = process.platform, execFileSync = defaultExecFileSync, spawn = defaultSpawn) {
  try {
    if (platform === "win32") {
      const command = `Start-Process '${url.replaceAll("'", "''")}'`;
      const child = spawn("powershell.exe", [
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-EncodedCommand",
        Buffer.from(command, "utf16le").toString("base64")
      ], { stdio: "ignore", windowsHide: true });
      child.on("error", () => {
      });
      child.unref();
      return child.pid !== void 0;
    } else {
      execFileSync(platform === "darwin" ? "open" : "xdg-open", [url], {
        stdio: "ignore",
        timeout: 3e3
      });
    }
    return true;
  } catch {
    return false;
  }
}
function printFlow(context, flow) {
  context.print("");
  context.print("Open this URL in your browser and complete sign-in:");
  context.print("");
  context.print(flow.url);
  context.print("");
  if (flow.instructions) {
    context.print(flow.instructions);
    context.print("");
  }
}
async function runMenuLogin(login, context) {
  const abort = new AbortController();
  let flow = await login.begin({ headless: false, signal: abort.signal });
  void flow.completion.catch(() => {
  });
  printFlow(context, flow);
  let opened = false;
  try {
    opened = await (login.openBrowser ?? openBrowserForMenu)(flow.url) !== false;
  } catch {
    opened = false;
  }
  if (!opened) {
    abort.abort();
    context.print("Could not open a browser. Switching to device authorization.");
    context.print("");
    flow = await login.begin({ headless: true });
    printFlow(context, flow);
  }
  return flow.completion;
}
var init_login = __esm({
  "../core/dist/common-auth-embedded/auth-menu/login.js"() {
    "use strict";
  }
});

// ../core/dist/common-auth-embedded/auth-menu/ansi.js
function parseKeys(data) {
  const value = data.toString();
  const keys = [];
  for (let index = 0; index < value.length; ) {
    const char = value[index];
    if (char === "\x1B") {
      const sequence = value.slice(index, index + 3);
      const arrow = sequence[1] === "[" || sequence[1] === "O" ? sequence[2] : void 0;
      if (arrow && "ABCD".includes(arrow)) {
        const action = { A: "up", B: "down", C: "right", D: "left" };
        const parsed = action[arrow];
        if (parsed)
          keys.push(parsed);
        index += 3;
      } else if (index + 1 === value.length) {
        if (index === 0)
          keys.push("escape-start");
        index += 1;
      } else if ((value[index + 1] === "[" || value[index + 1] === "O") && index + 2 >= value.length) {
        break;
      } else {
        index += 1;
      }
      continue;
    }
    if (char === "\r" || char === "\n")
      keys.push("enter");
    else if (char === "")
      keys.push("escape");
    else if (char && char >= " ")
      keys.push("char");
    index += 1;
  }
  return keys;
}
function parseKey(data) {
  return parseKeys(data)[0] ?? null;
}
function stripAnsi(input) {
  return input.replace(ANSI_REGEX, "");
}
function truncateAnsi(input, maxVisibleChars) {
  if (maxVisibleChars <= 0)
    return "";
  if (stripAnsi(input).length <= maxVisibleChars)
    return input;
  const suffix = maxVisibleChars >= 3 ? "..." : ".".repeat(maxVisibleChars);
  const keep = Math.max(0, maxVisibleChars - suffix.length);
  let output = "";
  let offset = 0;
  let visible = 0;
  while (offset < input.length && visible < keep) {
    if (input[offset] === "\x1B") {
      const match = input.slice(offset).match(ANSI_LEADING_REGEX);
      if (match) {
        output += match[0];
        offset += match[0].length;
        continue;
      }
    }
    output += input[offset];
    offset += 1;
    visible += 1;
  }
  return output.includes("\x1B[") ? `${output}${ANSI.reset}${suffix}` : output + suffix;
}
var ANSI, ANSI_PATTERN, ANSI_REGEX, ANSI_LEADING_REGEX;
var init_ansi = __esm({
  "../core/dist/common-auth-embedded/auth-menu/ansi.js"() {
    "use strict";
    ANSI = {
      hide: "\x1B[?25l",
      show: "\x1B[?25h",
      up: (n = 1) => `\x1B[${n}A`,
      clearLine: "\x1B[2K",
      clearScreen: "\x1B[2J",
      moveTo: (row, col) => `\x1B[${row};${col}H`,
      cyan: "\x1B[36m",
      green: "\x1B[32m",
      red: "\x1B[31m",
      dim: "\x1B[2m",
      reset: "\x1B[0m"
    };
    ANSI_PATTERN = `${String.fromCharCode(27)}\\[[0-9;]*m`;
    ANSI_REGEX = new RegExp(ANSI_PATTERN, "g");
    ANSI_LEADING_REGEX = new RegExp(`^${ANSI_PATTERN}`);
  }
});

// ../core/dist/common-auth-embedded/auth-menu/terminal.js
function processTerminal() {
  return {
    input: process.stdin,
    output: process.stdout,
    signals: process
  };
}
function isInteractive(terminal) {
  return terminal.input.isTTY === true;
}
function printLine(terminal, line = "") {
  terminal.output.write(`${line}
`);
}
var init_terminal = __esm({
  "../core/dist/common-auth-embedded/auth-menu/terminal.js"() {
    "use strict";
  }
});

// ../core/dist/common-auth-embedded/auth-menu/select.js
function colorCode(color) {
  if (color === "red")
    return ANSI.red;
  if (color === "cyan")
    return ANSI.cyan;
  return "";
}
async function select(terminal, items, options) {
  if (!isInteractive(terminal))
    throw new Error("Interactive select requires a TTY terminal");
  if (items.length === 0)
    throw new Error("No menu items provided");
  const { input: stdin, output: stdout, signals } = terminal;
  let cursor = 0;
  let escapeTimeout = null;
  let cleaned = false;
  let renderedLines = 0;
  const render = () => {
    const columns = stdout.columns ?? 80;
    const rows = stdout.rows ?? 24;
    const previousLines = renderedLines;
    if (options.clearScreen) {
      stdout.write(ANSI.clearScreen + ANSI.moveTo(1, 1));
    } else if (previousLines > 0) {
      stdout.write(ANSI.up(previousLines));
    }
    let lines = 0;
    const writeLine = (line) => {
      stdout.write(`${ANSI.clearLine}${line}
`);
      lines += 1;
    };
    const extraLines = options.lines ?? [];
    const headerLines = 1 + (options.subtitle ? 3 : 0) + extraLines.length + (extraLines.length ? 1 : 0);
    const maxVisible = Math.max(1, Math.min(items.length, rows - headerLines - 2 - 1));
    const windowStart = Math.max(0, Math.min(cursor - Math.floor(maxVisible / 2), Math.max(0, items.length - maxVisible)));
    const visibleItems = items.slice(windowStart, windowStart + maxVisible);
    writeLine(`${ANSI.dim}\u250C  ${ANSI.reset}${truncateAnsi(options.message, Math.max(1, columns - 4))}`);
    if (options.subtitle) {
      writeLine(`${ANSI.dim}\u2502${ANSI.reset}`);
      writeLine(`${ANSI.cyan}\u25C6${ANSI.reset}  ${truncateAnsi(options.subtitle, Math.max(1, columns - 4))}`);
      writeLine("");
    }
    for (const line of extraLines) {
      writeLine(`${ANSI.cyan}\u2502${ANSI.reset}  ${truncateAnsi(line, Math.max(1, columns - 4))}`);
    }
    if (extraLines.length)
      writeLine(`${ANSI.cyan}\u2502${ANSI.reset}`);
    for (let offset = 0; offset < visibleItems.length; offset++) {
      const item = visibleItems[offset];
      if (!item)
        continue;
      const selected = windowStart + offset === cursor;
      const color = colorCode(item.color);
      let label = color ? `${selected ? "" : ANSI.dim}${color}${item.label}${ANSI.reset}` : selected ? item.label : `${ANSI.dim}${item.label}${ANSI.reset}`;
      if (item.hint)
        label += ` ${ANSI.dim}${item.hint}${ANSI.reset}`;
      label = truncateAnsi(label, Math.max(1, columns - 8));
      writeLine(selected ? `${ANSI.cyan}\u2502${ANSI.reset}  ${ANSI.green}\u25CF${ANSI.reset} ${label}` : `${ANSI.cyan}\u2502${ANSI.reset}  ${ANSI.dim}\u25CB${ANSI.reset} ${label}`);
    }
    const windowHint = visibleItems.length < items.length ? ` (${windowStart + 1}-${windowStart + visibleItems.length}/${items.length})` : "";
    writeLine(`${ANSI.cyan}\u2502${ANSI.reset}  ${ANSI.dim}${truncateAnsi(`Up/Down to select | Enter: confirm | Esc: back${windowHint}`, Math.max(1, columns - 6))}${ANSI.reset}`);
    writeLine(`${ANSI.cyan}\u2514${ANSI.reset}`);
    for (let extra = lines; extra < previousLines; extra++)
      writeLine("");
    renderedLines = lines;
  };
  return new Promise((resolve7) => {
    const wasRaw = stdin.isRaw ?? false;
    const cleanup2 = () => {
      if (cleaned)
        return;
      cleaned = true;
      if (escapeTimeout)
        clearTimeout(escapeTimeout);
      stdin.removeListener("data", onKey);
      try {
        stdin.setRawMode(wasRaw);
        stdin.pause();
        stdout.write(ANSI.show);
      } catch {
      }
      signals?.removeListener("SIGINT", onSignal);
      signals?.removeListener("SIGTERM", onSignal);
    };
    const finish = (value) => {
      cleanup2();
      resolve7(value);
    };
    const onSignal = () => finish(null);
    const onKey = (data) => {
      for (const key of parseKeys(data)) {
        if (cleaned)
          break;
        if (escapeTimeout) {
          clearTimeout(escapeTimeout);
          escapeTimeout = null;
        }
        switch (key) {
          case "up":
            cursor = (cursor - 1 + items.length) % items.length;
            render();
            break;
          case "down":
            cursor = (cursor + 1) % items.length;
            render();
            break;
          case "enter":
            finish(items[cursor]?.value ?? null);
            break;
          case "escape":
            finish(null);
            break;
          case "escape-start":
            escapeTimeout = setTimeout(() => finish(null), ESCAPE_TIMEOUT_MS);
            break;
          default:
            break;
        }
      }
    };
    signals?.once("SIGINT", onSignal);
    signals?.once("SIGTERM", onSignal);
    try {
      stdin.setRawMode(true);
    } catch {
      cleanup2();
      resolve7(null);
      return;
    }
    stdin.resume();
    stdout.write(ANSI.hide);
    render();
    stdin.on("data", onKey);
  });
}
var ESCAPE_TIMEOUT_MS;
var init_select = __esm({
  "../core/dist/common-auth-embedded/auth-menu/select.js"() {
    "use strict";
    init_ansi();
    init_terminal();
    ESCAPE_TIMEOUT_MS = 50;
  }
});

// ../core/dist/common-auth-embedded/auth-menu/confirm.js
async function confirm(terminal, message, defaultYes = false) {
  if (!isInteractive(terminal))
    return false;
  const items = defaultYes ? [
    { label: "Yes", value: true },
    { label: "No", value: false }
  ] : [
    { label: "No", value: false },
    { label: "Yes", value: true }
  ];
  return await select(terminal, items, { message }) ?? false;
}
var init_confirm = __esm({
  "../core/dist/common-auth-embedded/auth-menu/confirm.js"() {
    "use strict";
    init_select();
    init_terminal();
  }
});

// ../core/dist/common-auth-embedded/auth-menu/menu.js
function menuContext(terminal) {
  const interactive = isInteractive(terminal);
  return {
    terminal,
    interactive,
    print: (line) => printLine(terminal, line),
    confirm: (message, defaultYes) => confirm(terminal, message, defaultYes),
    select: async (items, options) => interactive && items.length > 0 ? select(terminal, items, options) : null
  };
}
function printPlainMenu(context, options) {
  context.print(options.title);
  if (options.subtitle)
    context.print(options.subtitle);
  for (const line of options.status ?? [])
    context.print(`  ${line}`);
  context.print("");
  context.print("Actions:");
  for (const action of options.actions) {
    context.print(action.hint ? `  - ${action.label} (${action.hint})` : `  - ${action.label}`);
  }
  context.print("");
  context.print("This menu needs an interactive terminal to choose an action; nothing was changed.");
  return { status: "not-interactive" };
}
async function runMenu(options) {
  const terminal = options.terminal ?? processTerminal();
  const context = menuContext(terminal);
  if (!context.interactive)
    return printPlainMenu(context, options);
  if (options.actions.length === 0) {
    context.print("No actions are available.");
    return { status: "cancelled" };
  }
  const chosen = await select(terminal, options.actions.map((action) => ({
    label: action.label,
    value: action,
    color: action.destructive ? "red" : "cyan",
    ...action.hint ? { hint: action.hint } : {}
  })), {
    message: options.title,
    subtitle: options.subtitle ?? "Select an account action",
    ...options.status ? { lines: options.status } : {},
    clearScreen: true
  });
  if (!chosen)
    return { status: "cancelled" };
  if (chosen.destructive && !await context.confirm(chosen.confirm ?? `${chosen.label}?`)) {
    context.print("Cancelled; nothing was changed.");
    return { status: "declined", action: chosen.id };
  }
  try {
    await chosen.run(context);
    return { status: "ran", action: chosen.id };
  } catch (error) {
    context.print(`${chosen.label} failed: ${error instanceof Error ? error.message : String(error)}`);
    return { status: "failed", action: chosen.id, error };
  }
}
var init_menu2 = __esm({
  "../core/dist/common-auth-embedded/auth-menu/menu.js"() {
    "use strict";
    init_confirm();
    init_select();
    init_terminal();
  }
});

// ../core/dist/common-auth-embedded/auth-menu/accounts.js
async function readRows(store) {
  const load = await store.read();
  if (load.status === "ready")
    return { rows: load.rows };
  if (load.status === "pending-migration")
    return { rows: [], problem: "The account store has not been migrated yet." };
  return {
    rows: [],
    problem: `The account store could not be read (${load.file}: ${load.reason}).`
  };
}
async function poolHasCredential(store) {
  const { rows } = await readRows(store);
  return rows.some((row) => row.credential !== void 0);
}
function describeRow(row) {
  const parts = [];
  if (row.label)
    parts.push(row.label);
  if (row.invalid)
    parts.push(`invalid ${row.invalid}`);
  else if (!row.enabled)
    parts.push(row.disabledReason ? `disabled: ${row.disabledReason}` : "disabled");
  else
    parts.push("enabled");
  if (!row.credential && !row.invalid)
    parts.push("no credential");
  return parts.join(", ");
}
function accountLines(read) {
  if (read.problem)
    return [read.problem];
  if (read.rows.length === 0)
    return ["No accounts yet."];
  const lines = read.rows.slice(0, STATUS_ACCOUNT_LINES).map((row) => `${row.id}: ${describeRow(row)}`);
  const more = read.rows.length - STATUS_ACCOUNT_LINES;
  if (more > 0)
    lines.push(`... and ${more} more`);
  return lines;
}
function errorText(error) {
  return error instanceof Error ? error.message : String(error);
}
async function pickAccount(context, rows, message) {
  if (rows.length === 0) {
    context.print("There are no accounts.");
    return null;
  }
  return context.select(rows.map((row) => ({ label: row.id, value: row, hint: describeRow(row) })), { message });
}
function defaultAccountId(account, rows) {
  const taken = new Set(rows.map((row) => row.id));
  if (account.id && !taken.has(account.id))
    return account.id;
  for (let n = 1; ; n++) {
    const id = `account-${n}`;
    if (!taken.has(id))
      return id;
  }
}
function quotaLines(row, now = Date.now()) {
  const projected2 = isQuotaMap(row.quota) ? projectQuota(row.quota) : void 0;
  const parts = quotaTextParts(projected2, { now, form: "full" });
  return (parts.length > 0 ? parts : [formatQuota(projected2, { now })]).map((line) => `  ${line}`);
}
function addAccountAction(options) {
  return {
    id: "add-account",
    label: "Add account",
    hint: "sign in to another account",
    async run(context) {
      const login = options.login;
      if (!login)
        throw new Error("No login is configured");
      const account = await runMenuLogin(login, context);
      const { rows } = await readRows(options.store);
      const id = (options.newAccountId ?? defaultAccountId)(account, rows);
      const added = await options.store.add({
        id,
        credential: account.credential,
        ...account.identity !== void 0 ? { identity: account.identity } : {},
        ...account.label !== void 0 ? { label: account.label } : {}
      }, options.extraLocks ? { extraLocks: options.extraLocks } : {});
      if (added.outcome === "rotated")
        context.print(`That sign-in is already account ${added.id}; its credential was updated.`);
      else if (added.outcome === "added-disabled")
        context.print(`Added account ${added.id}, disabled: another enabled account is the same provider account.`);
      else if (added.outcome === "completed")
        context.print(`Finished adding account ${added.id}.`);
      else
        context.print(`Added account ${added.id}.`);
    }
  };
}
function reauthenticateAction(options) {
  return {
    id: "reauthenticate",
    label: "Re-authenticate account",
    hint: "sign an account in again",
    async run(context) {
      const login = options.login;
      if (!login)
        throw new Error("No login is configured");
      const { rows } = await readRows(options.store);
      const row = await pickAccount(context, rows, "Re-authenticate which account?");
      if (!row)
        return;
      const account = await runMenuLogin(login, context);
      if (account.identity !== void 0 && row.identity !== void 0 && account.identity !== row.identity) {
        context.print(`That sign-in is a different account from ${row.id}; nothing was changed. Use Add account to add it.`);
        return;
      }
      const identity = account.identity ?? row.identity;
      await options.store.replace(row.id, account.credential, identity !== void 0 ? { identity } : {}, options.extraLocks ? { extraLocks: options.extraLocks } : {});
      context.print(`Updated the sign-in of account ${row.id}.`);
    }
  };
}
function removeOptions(options) {
  return {
    ...options.protect ? { protect: options.protect } : {},
    ...options.extraLocks ? { extraLocks: options.extraLocks } : {}
  };
}
function protectedReason(error) {
  return error instanceof PoolOperationError && error.kind === "row-protected" ? error.message : void 0;
}
function removeAccountAction(options) {
  return {
    id: "remove-account",
    label: "Remove account",
    hint: "delete one account",
    async run(context) {
      const { rows } = await readRows(options.store);
      const row = await pickAccount(context, rows, "Remove which account?");
      if (!row)
        return;
      if (!await context.confirm(`Remove account ${row.id}?`)) {
        context.print("Cancelled; nothing was changed.");
        return;
      }
      try {
        await options.store.remove(row.id, removeOptions(options));
      } catch (error) {
        const reason = protectedReason(error);
        if (reason === void 0)
          throw error;
        context.print(`Account ${row.id} was kept: ${reason}`);
        return;
      }
      context.print(`Removed account ${row.id}.`);
    }
  };
}
function toggleAccountAction(options) {
  return {
    id: "toggle-account",
    label: "Enable or disable account",
    hint: "stop or resume using an account",
    async run(context) {
      const { rows } = await readRows(options.store);
      const row = await pickAccount(context, rows, "Enable or disable which account?");
      if (!row)
        return;
      const toggle = options.extraLocks ? { extraLocks: options.extraLocks } : {};
      if (row.enabled) {
        await options.store.disable(row.id, options.disableReason ?? MENU_DISABLE_REASON, toggle);
        context.print(`Disabled account ${row.id}.`);
        return;
      }
      try {
        await options.store.enable(row.id, toggle);
      } catch (error) {
        if (error instanceof PoolOperationError && error.kind === "duplicate-identity") {
          context.print(`Account ${row.id} stays disabled: another enabled account is the same provider account.`);
          return;
        }
        throw error;
      }
      context.print(`Enabled account ${row.id}.`);
    }
  };
}
function listAccountsAction(options) {
  return {
    id: "list-accounts",
    label: "List accounts",
    hint: "show every account",
    async run(context) {
      const read = await readRows(options.store);
      if (read.problem) {
        context.print(read.problem);
        return;
      }
      if (read.rows.length === 0)
        context.print("No accounts yet.");
      for (const row of read.rows)
        context.print(`${row.id}: ${describeRow(row)}`);
    }
  };
}
function checkQuotasAction(options) {
  return {
    id: "check-quotas",
    label: "Check quotas",
    hint: "poll and show the windows of each account",
    async run(context) {
      const before = await readRows(options.store);
      if (before.problem) {
        context.print(before.problem);
        return;
      }
      const errors = /* @__PURE__ */ new Map();
      const poll = options.pollQuota;
      if (poll) {
        for (const row of before.rows) {
          if (row.invalid || !row.credential || row.credentialEpoch === void 0) {
            errors.set(row.id, "no usable credential");
            continue;
          }
          try {
            const observation = await poll(row);
            await options.store.recordQuota(row.id, {
              credentialEpoch: row.credentialEpoch,
              ...row.identity !== void 0 ? { identity: row.identity } : {}
            }, observation);
          } catch (error) {
            errors.set(row.id, errorText(error));
          }
        }
      }
      const after = await readRows(options.store);
      if (after.rows.length === 0)
        context.print("No accounts yet.");
      for (const row of after.rows) {
        context.print(`${row.id}:`);
        const error = errors.get(row.id);
        if (error)
          context.print(`  quota check failed: ${error}`);
        for (const line of quotaLines(row, (options.now ?? Date.now)()))
          context.print(line);
      }
    }
  };
}
function deleteAllAction(options) {
  return {
    id: "delete-all",
    label: "Delete all accounts",
    destructive: true,
    confirm: "Delete every account? Accounts the plugin keeps are not deleted.",
    async run(context) {
      const read = await readRows(options.store);
      if (read.problem) {
        context.print(read.problem);
        return;
      }
      const removed = [];
      const kept = [];
      for (const row of read.rows) {
        try {
          await options.store.remove(row.id, removeOptions(options));
          removed.push(row.id);
        } catch (error) {
          const reason = protectedReason(error);
          if (reason === void 0)
            throw error;
          kept.push(`${row.id} (${reason})`);
        }
      }
      context.print(`Deleted ${removed.length} account(s).`);
      if (kept.length > 0)
        context.print(`Kept: ${kept.join(", ")}.`);
    }
  };
}
async function accountMenuActions(options) {
  return actionsFor(options, await options.custody?.() === true);
}
function actionsFor(options, custody) {
  const doctor = options.doctor?.length ? [doctorAction({ checks: options.doctor })] : [];
  const extras = [...options.extraActions ?? []];
  if (custody) {
    return [
      listAccountsAction(options),
      toggleAccountAction(options),
      checkQuotasAction(options),
      ...doctor,
      ...extras
    ];
  }
  return [
    ...options.login ? [addAccountAction(options), reauthenticateAction(options)] : [],
    removeAccountAction(options),
    toggleAccountAction(options),
    checkQuotasAction(options),
    ...doctor,
    ...extras,
    deleteAllAction(options)
  ];
}
async function runAccountMenu(options) {
  const custody = await options.custody?.() === true;
  const actions = actionsFor(options, custody);
  const [read, status] = await Promise.all([
    readRows(options.store),
    options.status?.() ?? []
  ]);
  return runMenu({
    title: options.title,
    subtitle: custody ? "Accounts come from the vault; select an action" : "Select an account action",
    status: [...status, ...accountLines(read)],
    actions,
    ...options.terminal ? { terminal: options.terminal } : {}
  });
}
var MENU_DISABLE_REASON, STATUS_ACCOUNT_LINES;
var init_accounts = __esm({
  "../core/dist/common-auth-embedded/auth-menu/accounts.js"() {
    "use strict";
    init_quota();
    init_store();
    init_doctor();
    init_login();
    init_menu2();
    MENU_DISABLE_REASON = "disabled from the auth menu";
    STATUS_ACCOUNT_LINES = 8;
  }
});

// ../core/dist/common-auth-embedded/auth-menu/opencode-v1.js
function menuCompletedResult() {
  return {
    url: "",
    instructions: "",
    method: "auto",
    callback: async () => ({ type: "failed" })
  };
}
function isCliAuthorize(inputs) {
  return inputs !== void 0;
}
function menuAuthorize(options) {
  return async (inputs) => {
    if (!isCliAuthorize(inputs))
      return options.login();
    if (!await options.hasCredential())
      return options.login(inputs);
    await options.openMenu(inputs);
    return menuCompletedResult();
  };
}
var init_opencode_v1 = __esm({
  "../core/dist/common-auth-embedded/auth-menu/opencode-v1.js"() {
    "use strict";
  }
});

// ../core/dist/common-auth-embedded/auth-menu/index.js
var auth_menu_exports = {};
__export(auth_menu_exports, {
  ANSI: () => ANSI,
  DOCTOR_CHECK_FAILED: () => DOCTOR_CHECK_FAILED,
  MENU_DISABLE_REASON: () => MENU_DISABLE_REASON,
  accountMenuActions: () => accountMenuActions,
  addAccountAction: () => addAccountAction,
  applyChosenRepairs: () => applyChosenRepairs,
  checkQuotasAction: () => checkQuotasAction,
  confirm: () => confirm,
  deleteAllAction: () => deleteAllAction,
  doctorAction: () => doctorAction,
  formatDoctorReport: () => formatDoctorReport,
  isCliAuthorize: () => isCliAuthorize,
  isInteractive: () => isInteractive,
  listAccountsAction: () => listAccountsAction,
  menuAuthorize: () => menuAuthorize,
  menuCompletedResult: () => menuCompletedResult,
  menuContext: () => menuContext,
  openBrowserForMenu: () => openBrowserForMenu,
  parseKey: () => parseKey,
  parseKeys: () => parseKeys,
  poolHasCredential: () => poolHasCredential,
  printLine: () => printLine,
  processTerminal: () => processTerminal,
  quotaLines: () => quotaLines,
  reauthenticateAction: () => reauthenticateAction,
  removeAccountAction: () => removeAccountAction,
  runAccountMenu: () => runAccountMenu,
  runDoctorChecks: () => runDoctorChecks,
  runMenu: () => runMenu,
  runMenuLogin: () => runMenuLogin,
  select: () => select,
  stripAnsi: () => stripAnsi,
  toggleAccountAction: () => toggleAccountAction,
  truncateAnsi: () => truncateAnsi
});
var init_auth_menu = __esm({
  "../core/dist/common-auth-embedded/auth-menu/index.js"() {
    "use strict";
    init_accounts();
    init_ansi();
    init_confirm();
    init_doctor();
    init_login();
    init_menu2();
    init_opencode_v1();
    init_select();
    init_terminal();
  }
});

// ../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/envelope.js
function isPureHeader(ty) {
  return ty === FrameType.Cancel || ty === FrameType.Ping || ty === FrameType.Pong || ty === FrameType.Goodbye;
}
function buildFlags(binary, priority, last, admissionClass = AdmissionClass.Normal) {
  let flags = 0;
  if (binary)
    flags |= FLAG_BINARY;
  flags |= priority << FLAG_PRIORITY_SHIFT;
  if (last)
    flags |= FLAG_LAST;
  flags |= admissionClass << FLAG_ADMISSION_SHIFT;
  return flags;
}
function hasBinary(flags) {
  return (flags & FLAG_BINARY) !== 0;
}
function encodeHeader(header) {
  const buffer = new Uint8Array(HEADER_LEN);
  const view = new DataView(buffer.buffer);
  view.setUint32(0, header.len, true);
  buffer[4] = header.ver;
  buffer[5] = header.ty;
  buffer[6] = header.flags;
  view.setUint16(7, header.channel, true);
  view.setUint32(9, header.epoch, true);
  view.setBigUint64(13, header.corr, true);
  return buffer;
}
function validateHeaderFields(header) {
  const len = header.len >>> 0;
  const ver = header.ver >>> 0 & 255;
  const typeByte = header.ty >>> 0 & 255;
  const flags = header.flags >>> 0 & 255;
  const channel = header.channel >>> 0 & 65535;
  const epoch = header.epoch >>> 0;
  void BigInt.asUintN(64, header.corr);
  if (ver !== PROTOCOL_VERSION)
    throw new DecodeError(`unsupported envelope version ${ver}`, "unsupported_version");
  if (typeByte > FRAME_TYPE_MAX)
    throw new DecodeError(`unknown frame type byte ${typeByte}`, "unknown_frame_type");
  const ty = typeByte;
  if ((flags & FLAG_RESERVED_MASK) !== 0) {
    throw new DecodeError(`reserved flag bits set in flags 0b${flags.toString(2).padStart(8, "0")}`, "reserved_flag_bits");
  }
  if ((flags & FLAG_PRIORITY_MASK) >> FLAG_PRIORITY_SHIFT === 3) {
    throw new DecodeError(`reserved priority bits set in flags 0b${flags.toString(2).padStart(8, "0")}`, "reserved_priority_bits");
  }
  const admission = (flags & FLAG_ADMISSION_MASK) >> FLAG_ADMISSION_SHIFT;
  if (admission === 3) {
    throw new DecodeError(`reserved admission class set in flags 0b${flags.toString(2).padStart(8, "0")}`, "reserved_admission_class");
  }
  if (admission === AdmissionClass.Sheddable && ty !== FrameType.Push && ty !== FrameType.StreamData) {
    throw new DecodeError(`SHEDDABLE admission class is illegal on ${FrameType[ty]} in flags 0b${flags.toString(2).padStart(8, "0")}`, "sheddable_illegal_frame_type");
  }
  if (channel === 0 && epoch !== 0) {
    throw new DecodeError(`control channel carried nonzero epoch ${epoch}`, "nonzero_epoch_on_control_channel");
  }
  if (isPureHeader(ty) && len !== 0) {
    throw new DecodeError(`pure-header frame ${FrameType[ty]} declared non-zero body length ${len}`, "pure_header_frame_with_body");
  }
}
function decodeHeader(bytes) {
  if (bytes.length < FROZEN_PREFIX_LEN) {
    throw new DecodeError(`header shorter than frozen prefix: have ${bytes.length} bytes`, "too_short_for_prefix");
  }
  const ver = bytes[4];
  if (ver !== PROTOCOL_VERSION)
    throw new DecodeError(`unsupported envelope version ${ver}`, "unsupported_version");
  if (bytes.length < HEADER_LEN) {
    throw new DecodeError(`header too short for version: have ${bytes.length} bytes, need ${HEADER_LEN}`, "too_short_for_header");
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const len = view.getUint32(0, true);
  const typeByte = bytes[5];
  if (typeByte > FRAME_TYPE_MAX)
    throw new DecodeError(`unknown frame type byte ${typeByte}`, "unknown_frame_type");
  const ty = typeByte;
  const flags = bytes[6];
  if ((flags & FLAG_RESERVED_MASK) !== 0) {
    throw new DecodeError(`reserved flag bits set in flags 0b${flags.toString(2).padStart(8, "0")}`, "reserved_flag_bits");
  }
  if ((flags & FLAG_PRIORITY_MASK) >> FLAG_PRIORITY_SHIFT === 3) {
    throw new DecodeError(`reserved priority bits set in flags 0b${flags.toString(2).padStart(8, "0")}`, "reserved_priority_bits");
  }
  const admission = (flags & FLAG_ADMISSION_MASK) >> FLAG_ADMISSION_SHIFT;
  if (admission === 3) {
    throw new DecodeError(`reserved admission class set in flags 0b${flags.toString(2).padStart(8, "0")}`, "reserved_admission_class");
  }
  if (admission === AdmissionClass.Sheddable && ty !== FrameType.Push && ty !== FrameType.StreamData) {
    throw new DecodeError(`SHEDDABLE admission class is illegal on ${FrameType[ty]} in flags 0b${flags.toString(2).padStart(8, "0")}`, "sheddable_illegal_frame_type");
  }
  const channel = view.getUint16(7, true);
  const epoch = view.getUint32(9, true);
  if (channel === 0 && epoch !== 0) {
    throw new DecodeError(`control channel carried nonzero epoch ${epoch}`, "nonzero_epoch_on_control_channel");
  }
  if (isPureHeader(ty) && len !== 0) {
    throw new DecodeError(`pure-header frame ${FrameType[ty]} declared non-zero body length ${len}`, "pure_header_frame_with_body");
  }
  return { len, ver, ty, flags, channel, epoch, corr: view.getBigUint64(13, true) };
}
function buildFrame(ty, flags, channel, epoch, corr, body) {
  return buildFrameWithVersion(PROTOCOL_VERSION, ty, flags, channel, epoch, corr, body);
}
function buildFrameWithVersion(ver, ty, flags, channel, epoch, corr, body) {
  if (body.length > MAX_FRAME_BODY_LEN) {
    throw new DecodeError(`frame body ${body.length} exceeds max ${MAX_FRAME_BODY_LEN}`, "frame_body_too_large");
  }
  const header = { len: body.length, ver, ty, flags, channel, epoch, corr };
  validateHeaderFields(header);
  return { header, body };
}
function encodeFrame(frame) {
  if (frame.header.len !== frame.body.length) {
    throw new DecodeError(`frame header length ${frame.header.len} does not match body length ${frame.body.length}`, "frame_length_mismatch");
  }
  const header = encodeHeader(frame.header);
  const output = new Uint8Array(header.length + frame.body.length);
  output.set(header, 0);
  output.set(frame.body, header.length);
  return output;
}
var PROTOCOL_VERSION, HEADER_LEN, FROZEN_PREFIX_LEN, MAX_FRAME_BODY_LEN, FrameType, FRAME_TYPE_MAX, Priority, AdmissionClass, FLAG_BINARY, FLAG_PRIORITY_MASK, FLAG_PRIORITY_SHIFT, FLAG_LAST, FLAG_ADMISSION_MASK, FLAG_ADMISSION_SHIFT, FLAG_RESERVED_MASK, DecodeError;
var init_envelope = __esm({
  "../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/envelope.js"() {
    PROTOCOL_VERSION = 2;
    HEADER_LEN = 21;
    FROZEN_PREFIX_LEN = 5;
    MAX_FRAME_BODY_LEN = 64 * 1024 * 1024;
    (function(FrameType2) {
      FrameType2[FrameType2["Request"] = 0] = "Request";
      FrameType2[FrameType2["Response"] = 1] = "Response";
      FrameType2[FrameType2["Push"] = 2] = "Push";
      FrameType2[FrameType2["StreamData"] = 3] = "StreamData";
      FrameType2[FrameType2["StreamEnd"] = 4] = "StreamEnd";
      FrameType2[FrameType2["Error"] = 5] = "Error";
      FrameType2[FrameType2["Cancel"] = 6] = "Cancel";
      FrameType2[FrameType2["Ping"] = 7] = "Ping";
      FrameType2[FrameType2["Pong"] = 8] = "Pong";
      FrameType2[FrameType2["Hello"] = 9] = "Hello";
      FrameType2[FrameType2["HelloAck"] = 10] = "HelloAck";
      FrameType2[FrameType2["Goodbye"] = 11] = "Goodbye";
    })(FrameType || (FrameType = {}));
    FRAME_TYPE_MAX = FrameType.Goodbye;
    (function(Priority2) {
      Priority2[Priority2["Passive"] = 0] = "Passive";
      Priority2[Priority2["Interactive"] = 1] = "Interactive";
      Priority2[Priority2["Background"] = 2] = "Background";
    })(Priority || (Priority = {}));
    (function(AdmissionClass2) {
      AdmissionClass2[AdmissionClass2["Normal"] = 0] = "Normal";
      AdmissionClass2[AdmissionClass2["Expedite"] = 1] = "Expedite";
      AdmissionClass2[AdmissionClass2["Sheddable"] = 2] = "Sheddable";
    })(AdmissionClass || (AdmissionClass = {}));
    FLAG_BINARY = 1;
    FLAG_PRIORITY_MASK = 6;
    FLAG_PRIORITY_SHIFT = 1;
    FLAG_LAST = 8;
    FLAG_ADMISSION_MASK = 48;
    FLAG_ADMISSION_SHIFT = 4;
    FLAG_RESERVED_MASK = 0;
    DecodeError = class extends Error {
      code;
      constructor(message, code2) {
        super(message);
        this.code = code2;
        this.name = "DecodeError";
      }
    };
  }
});

// ../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/socket.js
import net2 from "node:net";
function toWriteBuffer(bytes) {
  return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}
function writeBorrowed(socket, bytes, deadlineMs) {
  const borrowed = socket[WRITE_BORROWED];
  return borrowed ? borrowed.call(socket, bytes, deadlineMs) : socket.write(bytes, deadlineMs);
}
function writeTrackedBorrowed(socket, bytes, deadlineMs) {
  const borrowed = socket[WRITE_TRACKED_BORROWED];
  return borrowed ? borrowed.call(socket, bytes, deadlineMs) : socket.writeTracked(bytes, deadlineMs);
}
var SocketClosedError, SocketTimeoutError, SocketWriteNotQueuedError, SocketWriteQueuedError, WRITE_BORROWED, WRITE_TRACKED_BORROWED, SubcSocket;
var init_socket = __esm({
  "../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/socket.js"() {
    init_envelope();
    SocketClosedError = class extends Error {
    };
    SocketTimeoutError = class extends Error {
    };
    SocketWriteNotQueuedError = class extends Error {
      cause;
      constructor(message, cause) {
        super(message);
        this.cause = cause;
      }
    };
    SocketWriteQueuedError = class extends Error {
      cause;
      constructor(message, cause) {
        super(message);
        this.cause = cause;
      }
    };
    WRITE_BORROWED = /* @__PURE__ */ Symbol("subc.socket.writeBorrowed");
    WRITE_TRACKED_BORROWED = /* @__PURE__ */ Symbol("subc.socket.writeTrackedBorrowed");
    SubcSocket = class _SubcSocket {
      sock;
      chunks = [];
      buffered = 0;
      waiter = null;
      closedErr = null;
      /** Bytes currently buffered but not yet consumed by a reader. A timeout
       * arbitration uses this to tell "a reply already arrived, keep draining" from
       * "nothing is here, settle the timeout". */
      bufferedBytes() {
        return this.buffered;
      }
      constructor(sock) {
        this.sock = sock;
        sock.on("data", (chunk) => {
          this.chunks.push(chunk);
          this.buffered += chunk.length;
          this.tryServe();
        });
        const fail2 = (err) => {
          if (!this.closedErr)
            this.closedErr = err;
          this.tryServe();
        };
        sock.on("error", (err) => fail2(err instanceof Error ? err : new Error(String(err))));
        sock.on("end", () => fail2(new SocketClosedError("subc closed the connection")));
        sock.on("close", () => fail2(new SocketClosedError("subc connection closed")));
      }
      /**
       * The OS-assigned local TCP port of this connection, or null if not yet
       * connected/closed. Used to correlate a client-side timeout with a specific
       * socket in a packet capture when diagnosing reply-delivery issues.
       */
      localPort() {
        return this.sock.localPort ?? null;
      }
      static connect(host, port, deadlineMs) {
        return new Promise((resolve7, reject) => {
          const sock = net2.connect({ host, port });
          sock.setNoDelay(true);
          const timer = setTimeout(() => {
            sock.destroy();
            reject(new SocketTimeoutError(`timed out connecting to ${host}:${port}`));
          }, Math.max(0, deadlineMs - Date.now()));
          sock.once("connect", () => {
            clearTimeout(timer);
            resolve7(new _SubcSocket(sock));
          });
          sock.once("error", (err) => {
            clearTimeout(timer);
            reject(err);
          });
        });
      }
      /**
       * Read one envelope frame. The frozen five-byte prefix is validated before
       * waiting for the rest of the header, so a stale 17-byte v1 sender fails
       * promptly instead of leaving this reader blocked for four bytes.
       *
       * `bodyDeadline` is either an absolute epoch-ms deadline (a single total
       * budget shared with the header read — the bounded handshake read) or
       * `{ afterHeaderMs }` to start the body budget from header arrival. A
       * background frame loop waits for the header with an infinite deadline, so it
       * MUST use `afterHeaderMs`: anchoring the body budget before that idle wait
       * makes a frame arriving after a quiet stretch longer than the body timeout
       * instant-reject ("timed out waiting for N bytes") even though its body is
       * arriving normally.
       */
      async readFrame(headerDeadlineMs, bodyDeadline, onHeader) {
        const prefix = await this.readExact(FROZEN_PREFIX_LEN, headerDeadlineMs);
        const version = prefix[4];
        if (version !== PROTOCOL_VERSION)
          throw new DecodeError(`unsupported envelope version ${version}`, "unsupported_version");
        const remainder = await this.readExact(HEADER_LEN - FROZEN_PREFIX_LEN, headerDeadlineMs);
        const headerBytes = new Uint8Array(HEADER_LEN);
        headerBytes.set(prefix);
        headerBytes.set(remainder, FROZEN_PREFIX_LEN);
        const header = decodeHeader(headerBytes);
        if (header.len > MAX_FRAME_BODY_LEN) {
          throw new DecodeError(`frame body ${header.len} exceeds max ${MAX_FRAME_BODY_LEN}`, "frame_body_too_large");
        }
        onHeader?.();
        const bodyDeadlineMs = typeof bodyDeadline === "number" ? bodyDeadline : Date.now() + bodyDeadline.afterHeaderMs;
        const body = header.len === 0 ? new Uint8Array(0) : await this.readExact(header.len, bodyDeadlineMs);
        return { header, body };
      }
      /** Read exactly `n` bytes, rejecting if `deadlineMs` (epoch ms) passes first. */
      readExact(n, deadlineMs) {
        if (this.waiter) {
          return Promise.reject(new Error("concurrent readExact is not supported"));
        }
        if (n === 0)
          return Promise.resolve(new Uint8Array(0));
        return new Promise((resolve7, reject) => {
          let timer = null;
          if (Number.isFinite(deadlineMs)) {
            const remaining = deadlineMs - Date.now();
            if (remaining <= 0) {
              reject(new SocketTimeoutError(`timed out waiting for ${n} bytes`));
              return;
            }
            timer = setTimeout(() => {
              this.waiter = null;
              reject(new SocketTimeoutError(`timed out waiting for ${n} bytes`));
            }, remaining);
          }
          this.waiter = { need: n, resolve: resolve7, reject, timer };
          this.tryServe();
        });
      }
      async write(bytes, deadlineMs) {
        await this.writeBuffer(Buffer.from(bytes), deadlineMs);
      }
      writeTracked(bytes, deadlineMs) {
        return this.writeTrackedBuffer(Buffer.from(bytes), deadlineMs);
      }
      async [WRITE_BORROWED](bytes, deadlineMs) {
        await this.writeBuffer(toWriteBuffer(bytes), deadlineMs);
      }
      [WRITE_TRACKED_BORROWED](bytes, deadlineMs) {
        return this.writeTrackedBuffer(toWriteBuffer(bytes), deadlineMs);
      }
      async writeBuffer(buffer, deadlineMs) {
        try {
          await this.writeTrackedBuffer(buffer, deadlineMs).completed;
        } catch (err) {
          if (err instanceof SocketWriteNotQueuedError || err instanceof SocketWriteQueuedError) {
            throw err.cause ?? err;
          }
          throw err;
        }
      }
      writeTrackedBuffer(buffer, deadlineMs) {
        if (this.closedErr) {
          return {
            queued: false,
            completed: Promise.reject(new SocketWriteNotQueuedError("subc socket was closed before bytes could be queued", this.closedErr))
          };
        }
        let queued = false;
        let settled = false;
        let timer = null;
        const completed = new Promise((resolve7, reject) => {
          const settle = (run) => {
            if (settled)
              return;
            settled = true;
            if (timer)
              clearTimeout(timer);
            run();
          };
          const remaining = deadlineMs - Date.now();
          if (remaining <= 0) {
            settle(() => reject(new SocketWriteNotQueuedError("timed out before bytes could be queued to subc", new SocketTimeoutError("timed out writing to subc"))));
            return;
          }
          timer = setTimeout(() => {
            const timeout = new SocketTimeoutError("timed out writing to subc");
            settle(() => reject(queued ? new SocketWriteQueuedError("timed out after bytes were handed to the subc socket", timeout) : new SocketWriteNotQueuedError("timed out before bytes could be queued to subc", timeout)));
          }, remaining);
          try {
            this.sock.write(buffer, (err) => {
              settle(() => {
                if (err) {
                  reject(new SocketWriteQueuedError("subc socket reported a write error after bytes were handed to the socket", err instanceof Error ? err : new Error(String(err))));
                } else {
                  resolve7();
                }
              });
            });
            queued = true;
          } catch (err) {
            settle(() => reject(new SocketWriteNotQueuedError("subc socket write threw before bytes could be queued", err instanceof Error ? err : new Error(String(err)))));
          }
        });
        return { queued, completed };
      }
      close() {
        this.sock.destroy();
      }
      tryServe() {
        const w = this.waiter;
        if (!w)
          return;
        if (this.buffered >= w.need) {
          const out = this.take(w.need);
          this.waiter = null;
          if (w.timer)
            clearTimeout(w.timer);
          w.resolve(out);
          return;
        }
        if (this.closedErr) {
          this.waiter = null;
          if (w.timer)
            clearTimeout(w.timer);
          w.reject(this.closedErr);
        }
      }
      take(n) {
        const out = Buffer.allocUnsafe(n);
        let off = 0;
        while (off < n) {
          const head = this.chunks[0];
          const want = n - off;
          if (head.length <= want) {
            head.copy(out, off);
            off += head.length;
            this.chunks.shift();
          } else {
            head.copy(out, off, 0, want);
            this.chunks[0] = head.subarray(want);
            off += want;
          }
        }
        this.buffered -= n;
        return out;
      }
    };
  }
});

// ../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/auth.js
import { createHmac, randomBytes as randomBytes2, timingSafeEqual } from "node:crypto";
function computeProof(key, domain, clientNonce, serverNonce, daemonId) {
  const mac = createHmac("sha256", Buffer.from(key));
  mac.update(Buffer.from(domain, "utf8"));
  mac.update(Buffer.from(clientNonce));
  mac.update(Buffer.from(serverNonce));
  mac.update(Buffer.from(daemonId));
  return new Uint8Array(mac.digest());
}
function constantTimeEq(a, b) {
  if (a.length !== b.length)
    return false;
  return timingSafeEqual(Buffer.from(a), Buffer.from(b));
}
async function writeMessage(sock, value, deadlineMs) {
  const json = Buffer.from(JSON.stringify(value), "utf8");
  if (json.length > MAX_AUTH_MESSAGE_LEN) {
    throw new AuthError(`auth message too large: ${json.length} > ${MAX_AUTH_MESSAGE_LEN}`);
  }
  const lenPrefix = new Uint8Array(4);
  new DataView(lenPrefix.buffer).setUint32(0, json.length, true);
  await writeBorrowed(sock, lenPrefix, deadlineMs);
  await writeBorrowed(sock, json, deadlineMs);
}
async function readMessage(sock, deadlineMs) {
  const lenBytes = await sock.readExact(4, deadlineMs);
  const len = new DataView(lenBytes.buffer, lenBytes.byteOffset, 4).getUint32(0, true);
  if (len > MAX_AUTH_MESSAGE_LEN) {
    throw new AuthError(`auth message too large: ${len} > ${MAX_AUTH_MESSAGE_LEN}`);
  }
  const body = len === 0 ? new Uint8Array(0) : await sock.readExact(len, deadlineMs);
  try {
    return JSON.parse(Buffer.from(body).toString("utf8"));
  } catch (err) {
    throw new AuthError(`auth message JSON decode failed: ${String(err)}`);
  }
}
function authBytes(value, field) {
  if (!Array.isArray(value)) {
    throw new AuthError(`auth field '${field}' must be a byte array`);
  }
  for (const byte of value) {
    if (typeof byte !== "number" || !Number.isInteger(byte) || byte < 0 || byte > 255) {
      throw new AuthError(`auth field '${field}' has invalid byte ${String(byte)}`);
    }
  }
  return Uint8Array.from(value);
}
async function authenticateClient(sock, conn, deadlineMs) {
  const clientNonce = new Uint8Array(randomBytes2(NONCE_LEN));
  await writeMessage(sock, { client_nonce: Array.from(clientNonce), role: DEFAULT_CLIENT_ROLE }, deadlineMs);
  const proof = await readMessage(sock, deadlineMs);
  const serverNonce = authBytes(proof.server_nonce, "server_nonce");
  const daemonId = authBytes(proof.daemon_id, "daemon_id");
  const serverProof = authBytes(proof.server_proof, "server_proof");
  const expected = computeProof(conn.key, SERVER_PROOF_DOMAIN, clientNonce, serverNonce, daemonId);
  if (!constantTimeEq(expected, serverProof)) {
    throw new AuthError("server proof mismatch \u2014 wrong key or impostor daemon");
  }
  if (!constantTimeEq(daemonId, conn.daemonId)) {
    throw new AuthError("daemon id mismatch \u2014 connection file points at a different daemon");
  }
  const clientAuth = computeProof(conn.key, CLIENT_AUTH_DOMAIN, clientNonce, serverNonce, daemonId);
  await writeMessage(sock, { client_auth: Array.from(clientAuth) }, deadlineMs);
}
var NONCE_LEN, MAX_AUTH_MESSAGE_LEN, SERVER_PROOF_DOMAIN, CLIENT_AUTH_DOMAIN, DEFAULT_CLIENT_ROLE, AuthError;
var init_auth = __esm({
  "../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/auth.js"() {
    init_socket();
    NONCE_LEN = 32;
    MAX_AUTH_MESSAGE_LEN = 4096;
    SERVER_PROOF_DOMAIN = "subc-server-v1";
    CLIENT_AUTH_DOMAIN = "subc-client-v1";
    DEFAULT_CLIENT_ROLE = "client";
    AuthError = class extends Error {
    };
  }
});

// ../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/connection-file.js
import { promises as fs } from "node:fs";
function toBytes(value, field) {
  if (!Array.isArray(value)) {
    throw new ConnectionFileError(`connection file field '${field}' must be a JSON array of bytes`);
  }
  for (const byte of value) {
    if (typeof byte !== "number" || !Number.isInteger(byte) || byte < 0 || byte > 255) {
      throw new ConnectionFileError(`connection file field '${field}' has invalid byte ${String(byte)}`);
    }
  }
  return Uint8Array.from(value);
}
function validate(info) {
  if (info.schema !== SCHEMA_VERSION) {
    throw new ConnectionFileError(`unsupported connection file schema ${info.schema}; expected ${SCHEMA_VERSION}`);
  }
  if (info.endpoints.length === 0) {
    throw new ConnectionFileError("connection file must include at least one endpoint");
  }
  if (info.key.length < MIN_KEY_LEN) {
    throw new ConnectionFileError(`connection file key is too short: ${info.key.length} bytes, need at least ${MIN_KEY_LEN}`);
  }
  if (info.daemonId.length !== DAEMON_ID_LEN) {
    throw new ConnectionFileError(`connection file daemon_id must be ${DAEMON_ID_LEN} bytes, got ${info.daemonId.length}`);
  }
}
async function verifyOwnerOnly(path2) {
  if (process.platform === "win32")
    return;
  const stat7 = await fs.stat(path2);
  const mode = stat7.mode & 511;
  if ((mode & 63) !== 0) {
    throw new ConnectionFileError(`connection file ${path2} has insecure permissions 0o${mode.toString(8)}; expected owner-only 0600`);
  }
}
async function readConnectionFile(path2) {
  await verifyOwnerOnly(path2);
  const raw = await fs.readFile(path2, "utf8");
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new ConnectionFileError(`connection file JSON read failed for ${path2}: ${String(err)}`);
  }
  const wireVersion = parsed.wire_version;
  if (wireVersion !== void 0 && wireVersion !== PROTOCOL_VERSION) {
    throw new ConnectionFileError(`connection file wire_version ${String(wireVersion)} but this client speaks ${PROTOCOL_VERSION}; the client library must be upgraded`);
  }
  const endpointsRaw = parsed.endpoints;
  if (!Array.isArray(endpointsRaw)) {
    throw new ConnectionFileError("connection file 'endpoints' must be an array");
  }
  const endpoints = endpointsRaw.map((e) => {
    const ep = e;
    if (typeof ep.host !== "string" || typeof ep.port !== "number") {
      throw new ConnectionFileError("connection file endpoint must be { host: string, port: number }");
    }
    return { host: ep.host, port: ep.port };
  });
  const info = {
    schema: parsed.schema,
    endpoints,
    key: toBytes(parsed.key, "key"),
    daemonId: toBytes(parsed.daemon_id, "daemon_id"),
    pid: parsed.pid,
    daemonVer: parsed.daemon_ver ?? ""
  };
  validate(info);
  return info;
}
var SCHEMA_VERSION, MIN_KEY_LEN, DAEMON_ID_LEN, ConnectionFileError;
var init_connection_file = __esm({
  "../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/connection-file.js"() {
    init_envelope();
    SCHEMA_VERSION = 1;
    MIN_KEY_LEN = 32;
    DAEMON_ID_LEN = 16;
    ConnectionFileError = class extends Error {
    };
  }
});

// ../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/route-handle.js
function createRouteHandle(channel, epoch, token, registry = new ReverseRequestRegistry()) {
  const factory = RouteHandle;
  return factory.create(channel, epoch, token, registry);
}
function reverseRequestHandler(handle, methodFamily) {
  return reverseRequests.get(handle)?.handler(methodFamily);
}
function isMethodFamily(value) {
  return /^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/.test(value);
}
function newConnectionToken() {
  return Object.freeze({});
}
function belongsToConnection(handle, token) {
  return connectionToken.get(handle) === token;
}
function sameRouteHandle(left, right) {
  return left === right;
}
var connectionToken, reverseRequests, ReverseRequestRegistrationError, ReverseRequestRegistry, RouteHandle, StaleRouteHandleError;
var init_route_handle = __esm({
  "../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/route-handle.js"() {
    connectionToken = /* @__PURE__ */ new WeakMap();
    reverseRequests = /* @__PURE__ */ new WeakMap();
    ReverseRequestRegistrationError = class extends Error {
      methodFamily;
      code = "reverse_request_capability_not_declared";
      constructor(methodFamily) {
        super(`reverse-request capability ${JSON.stringify(methodFamily)} was not registered before route.open`);
        this.methodFamily = methodFamily;
        this.name = "ReverseRequestRegistrationError";
      }
    };
    ReverseRequestRegistry = class {
      handlers = /* @__PURE__ */ new Map();
      declaredFamilies = null;
      onRequest(methodFamily, handler) {
        if (!isMethodFamily(methodFamily)) {
          throw new TypeError(`reverse-request method family must be a capability identifier, got ${JSON.stringify(methodFamily)}`);
        }
        if (typeof handler !== "function")
          throw new TypeError("reverse-request handler must be a function");
        if (this.declaredFamilies && !this.declaredFamilies.has(methodFamily)) {
          throw new ReverseRequestRegistrationError(methodFamily);
        }
        this.handlers.set(methodFamily, handler);
      }
      /** @internal */
      capabilities() {
        return [...this.handlers.keys()].sort();
      }
      /** @internal */
      handler(methodFamily) {
        return this.handlers.get(methodFamily);
      }
      /** @internal */
      seal() {
        this.declaredFamilies ??= new Set(this.handlers.keys());
      }
    };
    RouteHandle = class _RouteHandle {
      channel;
      epoch;
      constructor(channel, epoch, token, registry) {
        if (!Number.isInteger(channel) || channel <= 0 || channel > 65535) {
          throw new RangeError(`route channel must be an integer in 1..65535, got ${channel}`);
        }
        if (!Number.isInteger(epoch) || epoch <= 0 || epoch > 4294967295) {
          throw new RangeError(`route epoch must be an integer in 1..4294967295, got ${epoch}`);
        }
        this.channel = channel;
        this.epoch = epoch;
        registry.seal();
        connectionToken.set(this, token);
        reverseRequests.set(this, registry);
        Object.freeze(this);
      }
      /** Replace the handler for a capability declared when this route opened. */
      onRequest(methodFamily, handler) {
        reverseRequests.get(this).onRequest(methodFamily, handler);
      }
      static create(channel, epoch, token, registry) {
        return new _RouteHandle(channel, epoch, token, registry);
      }
    };
    StaleRouteHandleError = class extends Error {
      handle;
      code = "stale_route_handle";
      constructor(handle) {
        super(`route handle (${handle.channel}, ${handle.epoch}) is not live on the current connection`);
        this.handle = handle;
        this.name = "StaleRouteHandleError";
      }
    };
  }
});

// ../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/client.js
import { debuglog } from "node:util";
function requireBinaryBody(body) {
  if (body instanceof Uint8Array)
    return body;
  const type = body === null ? "null" : Array.isArray(body) ? "array" : typeof body;
  throw new SubcError(`binary request body must be a Uint8Array; got ${type}`, "binary_body_required");
}
function isConsumerReconnectTransient(err) {
  if (err instanceof SocketClosedError || err instanceof SocketTimeoutError)
    return true;
  if (err instanceof SocketWriteNotQueuedError || err instanceof SocketWriteQueuedError)
    return true;
  if (err instanceof SubcCallError)
    return err.kind === "not_sent" || err.kind === "outcome_unknown";
  if (err instanceof AuthError)
    return true;
  if (err instanceof SubcError || err instanceof ConnectionFileError)
    return false;
  const code2 = errorCode(err);
  return code2 === "ECONNREFUSED" || code2 === "ECONNRESET" || code2 === "EPIPE" || code2 === "ETIMEDOUT" || code2 === "ENOENT";
}
function isRouteOpenRefusal(err) {
  return err instanceof SubcError && typeof err.code === "string";
}
function isRetryableRouteOpenCode(code2) {
  if (code2 === "capability_forbidden")
    return false;
  return code2 === "module_reloading" || code2 === "module_warming" || code2 === "target_unavailable" || code2 === "module_timeout";
}
function isEstablishedRouteDead(_flags, code2) {
  return code2 === UNKNOWN_CHANNEL || code2 === STALE_ROUTE_EPOCH;
}
function normalizeConnectOptions(opts) {
  return {
    connectionFile: opts.connectionFile,
    handshakeTimeoutMs: opts.handshakeTimeoutMs,
    identity: opts.identity,
    targetKind: opts.targetKind ?? DEFAULT_MANAGED_TARGET_KIND,
    reconnectBackoff: opts.reconnectBackoff ?? DEFAULT_RECONNECT_BACKOFF,
    sleep: opts.sleep ?? ((ms) => new Promise((resolve7) => setTimeout(resolve7, ms))),
    routeOpenRetryDeadlineMs: opts.routeOpenRetryDeadlineMs ?? ROUTE_OPEN_RETRY_DEADLINE_MS,
    timeoutArbitrationGraceMs: opts.timeoutArbitrationGraceMs ?? TIMEOUT_ARBITRATION_GRACE_MS,
    livenessProbeWindowMs: opts.livenessProbeWindowMs ?? LIVENESS_PROBE_WINDOW_MS,
    onControlPush: opts.onControlPush
  };
}
function isValidCapabilityIdentifier(identifier) {
  if (/\s/u.test(identifier))
    return false;
  const separator = identifier.indexOf("/v");
  if (separator <= 0 || identifier.indexOf("/v", separator + 1) !== -1)
    return false;
  const name = identifier.slice(0, separator);
  const version = identifier.slice(separator + 2);
  if (new TextEncoder().encode(name).byteLength > 64 || version.length === 0)
    return false;
  if (!/^[a-z][a-z0-9-]*[a-z0-9]$/u.test(name) && !/^[a-z]$/u.test(name))
    return false;
  if (name.includes("--"))
    return false;
  if (!/^\d+$/u.test(version) || version.length > 1 && version.startsWith("0"))
    return false;
  const numericVersion = Number(version);
  return Number.isSafeInteger(numericVersion) && numericVersion >= 1 && numericVersion <= 4294967295;
}
function routeCacheKey(target, identity, consumerIdentity, consumerCapabilities) {
  const consumerPart = consumerIdentity ? `${consumerIdentity.module_id}\0${consumerIdentity.launch_nonce}` : "";
  const capabilitiesPart = [...consumerCapabilities].sort().join("\0");
  return `${target.kind}\0${target.module_id}\0${identity.project_root}\0${identity.harness}\0${identity.session}\0${consumerPart}\0${capabilitiesPart}`;
}
function routeOpenConsumerIdentity(opts = {}) {
  if (opts.consumerIdentity !== void 0)
    return opts.consumerIdentity ?? void 0;
  const moduleId = process.env[SUBC_MODULE_ID_ENV];
  const launchNonce = process.env[SUBC_LAUNCH_NONCE_ENV];
  if (!moduleId || !launchNonce)
    return void 0;
  return { module_id: moduleId, launch_nonce: launchNonce };
}
function errorCode(err) {
  if (typeof err === "object" && err !== null && "code" in err) {
    const code2 = err.code;
    if (typeof code2 === "string")
      return code2;
  }
  return void 0;
}
function causeMessage(cause) {
  if (cause === void 0)
    return "";
  return `: ${cause instanceof Error ? cause.message : String(cause)}`;
}
function pendingKey(handle, corr) {
  return handle ? `${handle.channel}:${handle.epoch}:${corr}` : `0:0:${corr}`;
}
function reverseRequestMethod(body) {
  try {
    const parsed = JSON.parse(Buffer.from(body).toString("utf8"));
    return typeof parsed.method === "string" && parsed.method.length > 0 ? parsed.method : void 0;
  } catch {
    return void 0;
  }
}
var debug, DEFAULT_HANDSHAKE_TIMEOUT_MS, DEFAULT_REQUEST_TIMEOUT_MS, TIMEOUT_ARBITRATION_GRACE_MS, LIVENESS_PROBE_WINDOW_MS, REQUEST_DEADLINE_MARKER, DEADLINE_NO_DROP_CODE, ROUTE_OPEN_RETRY_DEADLINE_MS, BODY_READ_TIMEOUT_MS, EMPTY_BODY, DEFAULT_MANAGED_TARGET_KIND, SUBC_MODULE_ID_ENV, SUBC_LAUNCH_NONCE_ENV, DEFAULT_RECONNECT_BACKOFF, SubcCallError, SubcError, errorFrameFlags, SubcClient, UNKNOWN_CHANNEL, STALE_ROUTE_EPOCH;
var init_client = __esm({
  "../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/client.js"() {
    init_auth();
    init_connection_file();
    init_envelope();
    init_route_handle();
    init_socket();
    debug = debuglog("subc-client");
    DEFAULT_HANDSHAKE_TIMEOUT_MS = 1e4;
    DEFAULT_REQUEST_TIMEOUT_MS = 3e4;
    TIMEOUT_ARBITRATION_GRACE_MS = 50;
    LIVENESS_PROBE_WINDOW_MS = 2e3;
    REQUEST_DEADLINE_MARKER = "request_deadline";
    DEADLINE_NO_DROP_CODE = "deadline_exceeded_no_drop_observed";
    ROUTE_OPEN_RETRY_DEADLINE_MS = 3e4;
    BODY_READ_TIMEOUT_MS = 3e4;
    EMPTY_BODY = new Uint8Array(0);
    DEFAULT_MANAGED_TARGET_KIND = "management_surface";
    SUBC_MODULE_ID_ENV = "SUBC_MODULE_ID";
    SUBC_LAUNCH_NONCE_ENV = "SUBC_LAUNCH_NONCE";
    DEFAULT_RECONNECT_BACKOFF = {
      baseMs: 100,
      capMs: 2e3,
      maxAttempts: 6
    };
    SubcCallError = class extends Error {
      kind;
      code;
      cause;
      constructor(kind, message, code2, cause) {
        super(message);
        this.kind = kind;
        this.code = code2;
        this.cause = cause;
        this.name = "SubcCallError";
      }
      /**
       * Machine-parsable payload from the wire `ErrorBody.detail`, surfaced from
       * the underlying Error frame when one caused this failure. Typed refusal
       * reasons (for example certification refusals) ride this field; consumers
       * classify on it and must not have to reach into `cause`.
       */
      get detail() {
        return this.cause instanceof SubcError ? this.cause.detail : void 0;
      }
    };
    SubcError = class extends Error {
      code;
      detail;
      constructor(message, code2, detail) {
        super(message);
        this.code = code2;
        this.detail = detail;
      }
    };
    errorFrameFlags = /* @__PURE__ */ new WeakMap();
    SubcClient = class _SubcClient {
      sock;
      currentConn;
      opts;
      nextCorr = 1n;
      pending = /* @__PURE__ */ new Map();
      lateResponses = /* @__PURE__ */ new Map();
      routes = /* @__PURE__ */ new Map();
      liveRoutes = /* @__PURE__ */ new Map();
      connectionToken = newConnectionToken();
      ingressEpochDropCount = 0;
      closedErr = null;
      closeStarted = false;
      reconnecting = null;
      generation = 1;
      // True while the read loop is actively reading/dispatching a frame off the
      // current socket (between reading a header and finishing its dispatch). The
      // timeout arbitration reads it to decide whether a just-fired timeout should
      // grant a reply mid-arrival a small grace window before settling.
      readerActive = false;
      constructor(sock, currentConn, opts) {
        this.sock = sock;
        this.currentConn = currentConn;
        this.opts = opts;
        void this.readLoop(sock, this.generation);
      }
      get conn() {
        return this.currentConn;
      }
      /** Read the connection file, connect, authenticate, and start the read loop. */
      static async connect(opts) {
        const normalized = normalizeConnectOptions(opts);
        const opened = await _SubcClient.openConnection(normalized);
        return new _SubcClient(opened.sock, opened.conn, normalized);
      }
      /** List modules subc knows about (channel-0 catalog.list). */
      async catalogList(moduleId) {
        const body = this.encode(moduleId === void 0 ? { op: "catalog.list" } : { op: "catalog.list", module_id: moduleId });
        const reply = await this.controlRpc(body);
        const parsed = this.parseJson(reply);
        return parsed.modules ?? [];
      }
      /**
       * Resolve the sole catalog claimant for a capability.
       *
       * This expresses singular intent even when the fleet permits plural claims;
       * ambiguity is returned instead of selecting an arbitrary module.
       */
      async resolveProvider(capability) {
        const claimants = await this.resolveProviders(capability);
        if (claimants.length === 0) {
          throw new SubcError(`no catalog claimant for capability ${capability}`, "capability_unprovided");
        }
        if (claimants.length > 1) {
          throw new SubcError(`multiple catalog claimants for capability ${capability}: ${claimants.join(", ")}`, "capability_ambiguous");
        }
        return claimants[0];
      }
      /** Resolve every catalog claimant in deterministic module-id order. */
      async resolveProviders(capability) {
        if (!isValidCapabilityIdentifier(capability)) {
          throw new SubcError(`malformed capability identifier ${JSON.stringify(capability)}`, "invalid_capability_identifier");
        }
        const modules = await this.catalogList();
        return modules.filter((module) => module.capabilities?.provides.includes(capability) ?? false).map((module) => module.module_id).sort();
      }
      /** Open a route and return its connection-bound immutable handle. */
      async routeOpen(target, identity, opts = {}) {
        const consumerIdentity = routeOpenConsumerIdentity(opts);
        const reverseRequests2 = opts.reverseRequests ?? new ReverseRequestRegistry();
        reverseRequests2.seal();
        const consumerCapabilities = reverseRequests2.capabilities();
        const body = this.encode({
          op: "route.open",
          target,
          identity,
          ...consumerIdentity ? { consumer_identity: consumerIdentity } : {},
          ...consumerCapabilities.length > 0 ? { consumer_capabilities: consumerCapabilities } : {}
        });
        let installed = null;
        const install = (frame) => {
          if (frame.header.ty !== FrameType.Response)
            return true;
          const parsed = this.parseJson(frame);
          if (typeof parsed.route_channel !== "number" || typeof parsed.route_epoch !== "number") {
            throw new SubcError(`route.open returned no route handle: ${JSON.stringify(parsed)}`);
          }
          installed = this.installRoute(parsed.route_channel, parsed.route_epoch, reverseRequests2);
          return true;
        };
        const closeLateRoute = (frame) => {
          if (frame.header.ty !== FrameType.Response)
            return;
          try {
            const parsed = this.parseJson(frame);
            if (typeof parsed.route_channel !== "number" || typeof parsed.route_epoch !== "number")
              return;
            const lateHandle = this.installRoute(parsed.route_channel, parsed.route_epoch);
            this.failHandle(lateHandle, new SubcError("late route.open was closed", "route_closed"));
            this.liveRoutes.delete(lateHandle.channel);
            this.sendRouteGoodbye(lateHandle, true);
          } catch {
            this.closeConnectionAfterCleanupFailure();
          }
        };
        await this.controlRpc(body, install, closeLateRoute);
        if (!installed)
          throw new SubcError("route.open response was not installed");
        return installed;
      }
      /** Send a data-plane request on exactly the supplied route generation. */
      async request(handle, body, opts = {}) {
        this.assertLiveHandle(handle);
        const binary = opts.binary ?? false;
        const bytes = binary ? requireBinaryBody(body) : body instanceof Uint8Array ? body : this.encode(body);
        const priority = opts.priority ?? Priority.Interactive;
        const admission = opts.admissionClass ?? AdmissionClass.Normal;
        const reply = await this.send(handle, bytes, priority, admission, opts.timeoutMs, opts.onProgress, void 0, void 0, binary, opts.signal);
        return this.decodeReply(reply);
      }
      /**
       * Managed route + request convenience. Opens and caches a route for the module,
       * reconnecting and re-opening cached routes after connection drops.
       */
      async call(moduleId, method, params, opts = {}) {
        if (opts.binary) {
          throw new SubcError("call() builds a JSON body and cannot send a binary request; use callBinary(moduleId, body, opts) with a Uint8Array", "binary_call_requires_call_binary");
        }
        const body = params === void 0 ? { method } : { method, params };
        return await this.managedCall(moduleId, body, opts);
      }
      /**
       * Managed route + raw opaque-body request convenience. Unlike call(), this
       * sends bytes without a JSON method envelope because the BINARY flag is the
       * receiver's only signal that the body is not JSON. A BINARY reply resolves
       * to Uint8Array; a non-binary reply is decoded as JSON.
       */
      async callBinary(moduleId, body, opts = {}) {
        const bytes = requireBinaryBody(body);
        return this.managedCall(moduleId, bytes, { ...opts, binary: true });
      }
      async managedCall(moduleId, body, opts) {
        let retriedUnknownChannel = false;
        for (; ; ) {
          const routeHandle = await this.cachedRouteHandle(moduleId, opts);
          try {
            return await this.managedRequest(routeHandle, body, opts);
          } catch (err) {
            if (!(err instanceof SubcCallError))
              throw this.terminalCallError("managed call failed", err);
            const deadBindCode = isEstablishedRouteDead(err.cause instanceof SubcError ? errorFrameFlags.get(err.cause) ?? 0 : 0, err.code);
            if (deadBindCode && !retriedUnknownChannel && !this.closeStarted) {
              retriedUnknownChannel = true;
              this.evictRouteHandle(routeHandle);
              continue;
            }
            if (deadBindCode && retriedUnknownChannel) {
              this.evictRouteHandle(routeHandle);
            }
            if (err.code === "route_closed") {
              this.evictRouteHandle(routeHandle);
              throw err;
            }
            if (err.kind === "not_sent") {
              if (!this.closedErr)
                throw err;
              try {
                await this.reconnectAfterDrop(err);
              } catch (reconnectErr) {
                throw this.notSentRecoveryError("managed call was not sent", reconnectErr);
              }
              continue;
            }
            if (err.kind === "outcome_unknown" && err.code !== DEADLINE_NO_DROP_CODE) {
              if (this.closedErr)
                this.scheduleReconnectAfterDrop(err);
            } else if (err.kind === "outcome_unknown" && err.code === DEADLINE_NO_DROP_CODE) {
              this.probeLivenessAfterDeadline();
            }
            throw err;
          }
        }
      }
      /** Open a held request on exactly one route generation. */
      subscribe(handle, body, onEvent, opts = {}) {
        this.assertLiveHandle(handle);
        const bytes = body instanceof Uint8Array ? body : this.encode(body);
        const priority = opts.priority ?? Priority.Interactive;
        const admission = opts.admissionClass ?? AdmissionClass.Normal;
        const corr = this.allocateCorr();
        const key = pendingKey(handle, corr);
        let subscriptionPending = null;
        let resolveClosed = null;
        const closed = new Promise((resolve7, reject) => {
          if (this.closedErr) {
            reject(this.closedErr);
            return;
          }
          resolveClosed = resolve7;
          subscriptionPending = {
            handle,
            resolve: () => resolve7(),
            reject,
            onProgress: onEvent,
            timer: null,
            subscription: true
          };
          this.pending.set(key, subscriptionPending);
          const frame = buildFrame(FrameType.Request, buildFlags(false, priority, false, admission), handle.channel, handle.epoch, corr, bytes);
          writeBorrowed(this.sock, encodeFrame(frame), Date.now() + DEFAULT_REQUEST_TIMEOUT_MS).catch((err) => {
            const pending = this.pending.get(key);
            if (pending)
              this.rejectPending(key, pending, err instanceof Error ? err : new SubcError(String(err)));
          });
        });
        let cancelled = false;
        const unsubscribe = () => {
          if (cancelled)
            return;
          cancelled = true;
          if (subscriptionPending && resolveClosed)
            this.settle(key, subscriptionPending, resolveClosed);
          if (this.isLiveHandle(handle))
            this.cancel(handle, corr, priority);
        };
        return { unsubscribe, closed };
      }
      /**
       * Emit CANCEL for one in-flight request when its caller's signal fires.
       *
       * Emits only while the request is unsettled by this client's own book, which is
       * a fact it owns and can check without racing. It deliberately does NOT check
       * whether the route still exists: that would be a guess, and a wrong guess turns
       * a frame the daemon would harmlessly drop into a frame never sent -- removing
       * the caller's only chance at the cost of saving nothing.
       */
      attachCancelSignal(signal, key, handle, corr, priority) {
        if (!handle)
          return;
        const emit = () => {
          if (!this.pending.has(key))
            return;
          try {
            this.cancel(handle, corr, priority);
          } catch {
          }
        };
        if (signal.aborted) {
          emit();
          return;
        }
        signal.addEventListener("abort", emit, { once: true });
        const pending = this.pending.get(key);
        if (pending) {
          const previous = pending.onSettle;
          pending.onSettle = () => {
            previous?.();
            signal.removeEventListener("abort", emit);
          };
        }
      }
      /** Send a pure-header cancellation for an in-flight request. */
      cancel(handle, corr, priority = Priority.Interactive) {
        this.assertLiveHandle(handle);
        const cancel = buildFrame(FrameType.Cancel, buildFlags(false, priority, false), handle.channel, handle.epoch, corr, EMPTY_BODY);
        writeBorrowed(this.sock, encodeFrame(cancel), Date.now() + DEFAULT_REQUEST_TIMEOUT_MS).catch(() => void 0);
      }
      /** Poll status or liveness for exactly the supplied route generation. */
      async routePoll(handle, kind) {
        this.assertLiveHandle(handle);
        const body = this.encode({
          op: "route.poll",
          route_channel: handle.channel,
          route_epoch: handle.epoch,
          kind
        });
        const reply = await this.controlRpc(body, (frame) => {
          if (frame.header.ty !== FrameType.Response)
            return true;
          const parsed = this.parseJson(frame);
          return parsed.route_channel === handle.channel && parsed.route_epoch === handle.epoch;
        });
        return this.parseJson(reply);
      }
      /** Tear down exactly the supplied route generation. */
      async closeRoute(handle, opts = {}) {
        this.assertLiveHandle(handle);
        for (const [key, cached] of this.routes) {
          if (cached.handle && sameRouteHandle(cached.handle, handle)) {
            cached.closed = true;
            cached.handle = null;
            this.routes.delete(key);
          }
        }
        if (opts.drain)
          await this.drainUnaryOnHandle(handle);
        this.failHandle(handle, new SubcError("route closed by closeRoute", "route_closed"));
        if (this.liveRoutes.get(handle.channel) === handle)
          this.liveRoutes.delete(handle.channel);
        this.sendRouteGoodbye(handle);
      }
      /** Close a cached managed route by its route-open identity tuple. */
      async closeManagedRoute(target, identity, opts = {}) {
        const key = routeCacheKey(target, identity, routeOpenConsumerIdentity(opts), (opts.reverseRequests ?? new ReverseRequestRegistry()).capabilities());
        const cached = this.routes.get(key);
        if (!cached)
          return;
        cached.closed = true;
        this.routes.delete(key);
        const handle = cached.handle;
        cached.handle = null;
        if (handle)
          await this.closeRoute(handle, opts);
      }
      /** Alias retained for callers that name the operation by protocol channel; it still requires a full handle. */
      async closeRouteChannel(handle, opts = {}) {
        await this.closeRoute(handle, opts);
      }
      close() {
        this.closeStarted = true;
        this.fail(new SubcError("client closed"));
        this.sock.close();
      }
      drainUnaryOnHandle(handle) {
        const waiters = [];
        for (const pending of this.pending.values()) {
          if (pending.handle === handle && !pending.subscription) {
            waiters.push(new Promise((resolve7) => {
              const previous = pending.onSettle;
              pending.onSettle = () => {
                previous?.();
                resolve7();
              };
            }));
          }
        }
        return Promise.all(waiters).then(() => void 0);
      }
      sendRouteGoodbye(handle, closeOnQueueFailure = false) {
        this.assertLiveConnection(handle);
        if (this.closedErr) {
          if (closeOnQueueFailure)
            this.closeConnectionAfterCleanupFailure();
          return;
        }
        const goodbye = buildFrame(FrameType.Goodbye, buildFlags(false, Priority.Interactive, false), handle.channel, handle.epoch, 0n, EMPTY_BODY);
        const write = writeTrackedBorrowed(this.sock, encodeFrame(goodbye), Date.now() + DEFAULT_REQUEST_TIMEOUT_MS);
        if (!write.queued && closeOnQueueFailure)
          this.closeConnectionAfterCleanupFailure();
        write.completed.catch(() => {
          if (closeOnQueueFailure && !write.queued)
            this.closeConnectionAfterCleanupFailure();
        });
      }
      static async openConnection(opts) {
        const conn = await readConnectionFile(opts.connectionFile);
        const deadline = Date.now() + (opts.handshakeTimeoutMs ?? DEFAULT_HANDSHAKE_TIMEOUT_MS);
        const endpoint = conn.endpoints[0];
        const sock = await SubcSocket.connect(endpoint.host, endpoint.port, deadline);
        try {
          await authenticateClient(sock, conn, deadline);
        } catch (err) {
          sock.close();
          throw err;
        }
        return { sock, conn };
      }
      async controlRpc(body, acceptFrame, onLateResponse) {
        return this.send(null, body, Priority.Interactive, AdmissionClass.Normal, void 0, void 0, acceptFrame, onLateResponse);
      }
      send(handle, body, priority, admission, timeoutMs, onProgress, acceptFrame, onLateResponse, binary = false, signal) {
        if (handle)
          this.assertLiveHandle(handle);
        if (this.closedErr)
          return Promise.reject(this.closedErr);
        let corr;
        try {
          corr = this.allocateCorr();
        } catch (error) {
          return Promise.reject(error);
        }
        const key = pendingKey(handle, corr);
        const channel = handle?.channel ?? 0;
        const epoch = handle?.epoch ?? 0;
        const frame = buildFrame(FrameType.Request, buildFlags(binary, priority, false, admission), channel, epoch, corr, body);
        return new Promise((resolve7, reject) => {
          const ms = timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
          const pending = {
            handle,
            resolve: resolve7,
            reject,
            onProgress,
            timer: null,
            acceptFrame,
            onLateResponse
          };
          pending.timer = setTimeout(() => this.arbitrateTimeout(key, pending, channel, corr, ms), ms);
          this.pending.set(key, pending);
          if (signal)
            this.attachCancelSignal(signal, key, handle, corr, priority);
          writeBorrowed(this.sock, encodeFrame(frame), Date.now() + ms).catch((error) => {
            const current = this.pending.get(key);
            if (current)
              this.rejectPending(key, current, error instanceof Error ? error : new SubcError(String(error)));
          });
        });
      }
      /**
       * A request-deadline timer has fired. Before settling as a timeout, arbitrate
       * the timer-vs-poll race: a reply may already be in the socket buffer, unread
       * only because the loop was starved. Yield one check phase (setImmediate) so a
       * fully-buffered reply dispatches and wins via settle()'s identity guard; then,
       * only while the reader is actively draining THIS socket (a frame mid-arrival),
       * grant a single hard-capped grace before finally settling. Absent replies
       * still settle right after the check phase. The settle carries the deadline
       * marker so the managed classifier reports deadline-not-drop.
       */
      arbitrateTimeout(key, pending, channel, corr, ms) {
        const settleAsTimeout = () => {
          if (pending.onLateResponse)
            this.lateResponses.set(key, pending.onLateResponse);
          this.rejectPending(key, pending, new SubcError(this.timeoutMessage(channel, corr, ms), REQUEST_DEADLINE_MARKER));
        };
        const graceDeadline = Date.now() + this.opts.timeoutArbitrationGraceMs;
        const arbitrate = () => {
          if (this.pending.get(key) !== pending)
            return;
          const readerDraining = this.readerActive || this.sock.bufferedBytes() > 0;
          if (readerDraining && Date.now() < graceDeadline) {
            setImmediate(arbitrate);
            return;
          }
          settleAsTimeout();
        };
        setImmediate(arbitrate);
      }
      async managedRequest(handle, body, opts) {
        const binary = opts.binary ?? false;
        const bytes = binary ? requireBinaryBody(body) : body instanceof Uint8Array ? body : this.encode(body);
        const priority = opts.priority ?? Priority.Interactive;
        const admission = opts.admissionClass ?? AdmissionClass.Normal;
        try {
          const reply = await this.sendManaged(handle, bytes, priority, admission, opts.timeoutMs, opts.onProgress, binary, opts.signal);
          return this.decodeReply(reply);
        } catch (error) {
          if (error instanceof SubcCallError)
            throw error;
          throw this.terminalCallError("managed call failed", error);
        }
      }
      sendManaged(handle, body, priority, admission, timeoutMs, onProgress, binary = false, signal) {
        try {
          this.assertLiveHandle(handle);
        } catch (error) {
          return Promise.reject(this.notSentCallError("request used a stale route handle", error));
        }
        if (this.closedErr) {
          return Promise.reject(this.notSentCallError("request was not sent because the subc connection was already closed", this.closedErr));
        }
        let corr;
        try {
          corr = this.allocateCorr();
        } catch (error) {
          return Promise.reject(this.notSentCallError("request correlation allocator was exhausted", error));
        }
        const key = pendingKey(handle, corr);
        const frame = buildFrame(FrameType.Request, buildFlags(binary, priority, false, admission), handle.channel, handle.epoch, corr, body);
        let handedToSocket = false;
        const classifyFailure = (error) => {
          if (!handedToSocket)
            return this.notSentCallError("request bytes were not queued to the subc socket", error);
          if (error instanceof SubcError && error.code === REQUEST_DEADLINE_MARKER) {
            return new SubcCallError("outcome_unknown", `managed call deadline exceeded after request bytes were queued to the local socket; no terminal response was observed; outcome unknown${causeMessage(error)}`, DEADLINE_NO_DROP_CODE, error);
          }
          return this.outcomeUnknownCallError("connection dropped before the managed call returned a response", error);
        };
        return new Promise((resolve7, reject) => {
          const ms = timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
          const pending = {
            handle,
            resolve: resolve7,
            reject,
            onProgress,
            timer: null,
            classifyFailure
          };
          pending.timer = setTimeout(() => this.arbitrateTimeout(key, pending, handle.channel, corr, ms), ms);
          this.pending.set(key, pending);
          if (signal)
            this.attachCancelSignal(signal, key, handle, corr, priority);
          const write = writeTrackedBorrowed(this.sock, encodeFrame(frame), Date.now() + ms);
          handedToSocket = write.queued;
          write.completed.catch((error) => {
            const current = this.pending.get(key);
            if (current)
              this.rejectPending(key, current, error instanceof Error ? error : new SubcError(String(error)));
          });
        });
      }
      async cachedRouteHandle(moduleId, opts) {
        const identity = opts.identity ?? this.opts.identity;
        if (!identity) {
          throw new SubcCallError("terminal", "managed call requires a BindIdentity in SubcClient.connect({ identity }) or call(..., { identity })", "missing_identity");
        }
        const target = { kind: opts.targetKind ?? this.opts.targetKind, module_id: moduleId };
        const consumerIdentity = routeOpenConsumerIdentity(opts);
        const reverseRequests2 = opts.reverseRequests ?? new ReverseRequestRegistry();
        reverseRequests2.seal();
        const key = routeCacheKey(target, identity, consumerIdentity, reverseRequests2.capabilities());
        let cached = this.routes.get(key);
        if (!cached) {
          cached = {
            key,
            moduleId,
            target,
            identity,
            consumerIdentity,
            reverseRequests: reverseRequests2,
            handle: null,
            opening: null
          };
          this.routes.set(key, cached);
        }
        if (cached.handle && this.isLiveHandle(cached.handle))
          return cached.handle;
        if (!cached.opening) {
          cached.opening = this.openCachedRoute(cached).finally(() => {
            cached.opening = null;
          });
        }
        return cached.opening;
      }
      async openCachedRoute(cached) {
        const routeRetryDeadline = Date.now() + this.opts.routeOpenRetryDeadlineMs;
        let routeRetryDelay = this.opts.reconnectBackoff.baseMs;
        let routeRetryAttempt = 0;
        for (; ; ) {
          if (cached.closed)
            throw this.routeClosedDuringOpen();
          try {
            await this.ensureConnectedForManaged();
          } catch (error) {
            throw this.notSentRecoveryError("route.open could not run because reconnect failed", error);
          }
          if (cached.handle && this.isLiveHandle(cached.handle))
            return cached.handle;
          try {
            const handle = await this.routeOpen(cached.target, cached.identity, {
              consumerIdentity: cached.consumerIdentity ?? null,
              reverseRequests: cached.reverseRequests
            });
            if (cached.closed) {
              this.liveRoutes.delete(handle.channel);
              this.sendRouteGoodbye(handle);
              throw this.routeClosedDuringOpen();
            }
            cached.handle = handle;
            return handle;
          } catch (error) {
            if (error instanceof SubcCallError && error.code === "route_closed")
              throw error;
            if (!this.closeStarted && isConsumerReconnectTransient(error)) {
              try {
                await this.reconnectAfterDrop(error);
              } catch (reconnectError) {
                throw this.notSentRecoveryError("route.open was not sent and reconnect failed", reconnectError);
              }
              continue;
            }
            if (!this.closeStarted && error instanceof SubcError && isRetryableRouteOpenCode(error.code)) {
              routeRetryAttempt += 1;
              if (Date.now() < routeRetryDeadline) {
                await this.opts.sleep(routeRetryDelay);
                routeRetryDelay = Math.min(routeRetryDelay * 2, this.opts.reconnectBackoff.capMs);
                continue;
              }
              throw this.notSentCallError(`route.open failed for module ${cached.moduleId}: ${error.code} (retry deadline exhausted after ${routeRetryAttempt} attempts)`, error);
            }
            throw this.terminalCallError(`route.open failed for module ${cached.moduleId}`, error);
          }
        }
      }
      // Stamped by dispatch() on every inbound frame; read by the liveness probe.
      lastInboundAtMs = 0;
      // Single-flight guard: overlapping deadline-no-drop settles share one probe.
      livenessProbe = null;
      /**
       * Discriminate event-loop starvation from a half-open socket after a
       * deadline-no-drop settle. The arbitration deliberately keeps the socket on
       * that verdict (a late-read reply under load must not cost a healthy
       * connection), but a half-open socket — peer vanished with no FIN/RST, as
       * after host sleep/wake — yields the SAME verdict forever, so the keep
       * becomes a permanent pin to a dead transport. The discriminator is
       * socket-level liveness evidence: send a channel-0 Ping (the daemon always
       * answers — subc-core control.rs) and require ANY inbound frame within the
       * window; the Pong suffices, and a busy socket's other traffic proves the
       * link just as well. Silence convicts: the socket is failed with a named
       * cause and closed, so the ordinary drop path (pending rejection now,
       * reconnect on the next call) takes over.
       *
       * Starvation cannot be falsely convicted by a short window: a loop starved
       * enough to delay the read loop delays this probe's own timer identically,
       * and when both wake the buffered Pong dispatches before the check runs.
       *
       * A PENDING CHANNEL-0 REQUEST SUSPENDS THE PROBE (both at launch and at the
       * conviction check). The daemon's connection loop handles frames one at a
       * time, and some channel-0 ops legally park it for seconds — route.open
       * awaits the module's bind ack inline for up to route_bind_relay_timeout
       * (~12s in production) — during which OUR Ping sits unread in the daemon's
       * socket buffer. On an otherwise-quiet connection that silence is fully
       * explained by our own in-flight control op, and convicting on it would
       * tear down a healthy connection mid-bind (BROCA's Athena panel flagged
       * this exact premise; the FIFO fact is verified in subc-core server.rs
       * connection_loop + control.rs handle_route_open). The client always knows
       * its own channel-0 pendings, so the gate is local and exact: no probe
       * while one is in flight, no conviction if one appeared during the window.
       *
       * Scope: hooked from the managed-call path only. Control-plane requests
       * (route.open, catalog.list) are short-lived and their failures already
       * escalate through reconnect classification; the managed path is where a
       * plugin lives for hours and where the pin was observed in production.
       */
      /** Any in-flight channel-0 request (pendings keyed without a route handle). */
      hasControlPending() {
        for (const pending of this.pending.values()) {
          if (pending.handle === null)
            return true;
        }
        return false;
      }
      probeLivenessAfterDeadline() {
        if (this.livenessProbe || this.closeStarted || this.closedErr)
          return;
        if (this.hasControlPending())
          return;
        const sock = this.sock;
        const generation = this.generation;
        let corr;
        try {
          corr = this.allocateCorr();
        } catch {
          return;
        }
        const t0 = Date.now();
        const ping = buildFrame(FrameType.Ping, buildFlags(false, Priority.Interactive, false, AdmissionClass.Normal), 0, 0, corr, new Uint8Array());
        const probe = (async () => {
          await writeBorrowed(sock, encodeFrame(ping), t0 + this.opts.livenessProbeWindowMs).catch(() => {
          });
          await this.opts.sleep(this.opts.livenessProbeWindowMs);
          if (this.sock !== sock || this.generation !== generation || this.closeStarted)
            return;
          if (this.lastInboundAtMs >= t0)
            return;
          if (this.hasControlPending())
            return;
          this.fail(new SocketClosedError(`liveness probe convicted a half-open socket: no inbound frame for ${this.opts.livenessProbeWindowMs}ms after a channel-0 Ping (deadline-no-drop settles preceded this); closing so the next call reconnects`));
          sock.close();
        })().finally(() => {
          this.livenessProbe = null;
        });
        this.livenessProbe = probe;
      }
      async ensureConnectedForManaged() {
        if (this.closeStarted)
          throw new SubcError("client closed");
        if (this.reconnecting)
          await this.reconnecting;
        if (this.closedErr)
          await this.reconnectAfterDrop(this.closedErr);
      }
      scheduleReconnectAfterDrop(err) {
        if (this.closeStarted || this.reconnecting)
          return;
        void this.reconnectAfterDrop(err).catch(() => {
        });
      }
      reconnectAfterDrop(trigger) {
        if (this.closeStarted)
          return Promise.reject(new SubcError("client closed"));
        if (this.reconnecting)
          return this.reconnecting;
        const promise = this.reconnectWithRetry(trigger).finally(() => {
          if (this.reconnecting === promise)
            this.reconnecting = null;
        });
        this.reconnecting = promise;
        return promise;
      }
      async reconnectWithRetry(_trigger) {
        let attempt = 0;
        let delay = this.opts.reconnectBackoff.baseMs;
        for (; ; ) {
          if (this.closeStarted)
            throw new SubcError("client closed");
          attempt += 1;
          try {
            const opened = await _SubcClient.openConnection(this.opts);
            if (this.closeStarted) {
              opened.sock.close();
              throw new SubcError("client closed");
            }
            this.replaceConnection(opened);
            await this.reopenCachedRoutes();
            return;
          } catch (err) {
            if (!isConsumerReconnectTransient(err) || attempt >= this.opts.reconnectBackoff.maxAttempts) {
              if (err instanceof AuthError && attempt > 1) {
                throw new AuthError(`reconnect gave up after ${attempt} attempts: ${err.message} \u2014 the connection file and the daemon's key disagree persistently (daemon restarting in a loop, split connection-file paths, or a genuinely foreign daemon on this port); check the daemon, then restart this host app`);
              }
              throw err;
            }
            await this.opts.sleep(delay);
            delay = Math.min(delay * 2, this.opts.reconnectBackoff.capMs);
          }
        }
      }
      replaceConnection(opened) {
        this.fail(new SubcError("subc connection replaced"));
        this.sock.close();
        this.sock = opened.sock;
        this.currentConn = opened.conn;
        this.closedErr = null;
        this.generation += 1;
        this.connectionToken = newConnectionToken();
        this.liveRoutes.clear();
        this.lateResponses.clear();
        this.nextCorr = 1n;
        void this.readLoop(opened.sock, this.generation);
      }
      async reopenCachedRoutes() {
        const routeKeys = [...this.routes.keys()];
        for (const key of routeKeys) {
          const cached = this.routes.get(key);
          if (cached)
            cached.handle = null;
        }
        for (const key of routeKeys) {
          const cached = this.routes.get(key);
          if (!cached || cached.closed)
            continue;
          try {
            const handle = await this.routeOpen(cached.target, cached.identity, {
              consumerIdentity: cached.consumerIdentity ?? null,
              reverseRequests: cached.reverseRequests
            });
            if (cached.closed) {
              this.liveRoutes.delete(handle.channel);
              this.sendRouteGoodbye(handle);
              continue;
            }
            cached.handle = handle;
          } catch (error) {
            if (isRouteOpenRefusal(error)) {
              this.routes.delete(key);
              continue;
            }
            throw error;
          }
        }
      }
      // A request timeout carries the local socket port and (channel, corr) so a
      // packet capture can pinpoint the exact on-wire exchange — the decisive evidence
      // for whether a "timed out" reply was actually delivered to this socket (a
      // client-local demux problem) or never sent (a daemon/module problem).
      timeoutMessage(channel, corr, ms) {
        const port = this.sock.localPort();
        const where = port === null ? "channel" : `local_port=${port} channel`;
        return `request on ${where} ${channel} corr ${corr} timed out after ${ms}ms`;
      }
      routeClosedDuringOpen() {
        return new SubcCallError("not_sent", "route was closed before route.open completed", "route_closed");
      }
      async readLoop(sock, generation) {
        try {
          for (; ; ) {
            this.readerActive = false;
            const frame = await sock.readFrame(Number.POSITIVE_INFINITY, { afterHeaderMs: BODY_READ_TIMEOUT_MS }, () => {
              this.readerActive = true;
            });
            try {
              if (this.sock === sock && this.generation === generation)
                this.dispatch(frame);
            } finally {
              this.readerActive = false;
            }
          }
        } catch (error) {
          if (this.sock === sock && this.generation === generation) {
            this.fail(error instanceof Error ? error : new SubcError(String(error)));
          }
        }
      }
      dispatch(frame) {
        this.lastInboundAtMs = Date.now();
        if (frame.header.channel === 0 && frame.header.ty === FrameType.Push) {
          const observer = this.opts.onControlPush;
          if (observer) {
            let parsed = null;
            try {
              const body = this.parseJson(frame);
              if (body && typeof body.op === "string")
                parsed = { op: body.op, body };
            } catch {
            }
            if (parsed) {
              try {
                observer(parsed);
              } catch {
              }
            }
          }
          return;
        }
        let handle = null;
        if (frame.header.channel !== 0) {
          handle = this.liveRoutes.get(frame.header.channel) ?? null;
          if (!handle || handle.epoch !== frame.header.epoch) {
            this.ingressEpochDropCount += 1;
            return;
          }
        }
        if (frame.header.ty === FrameType.Request && handle) {
          this.dispatchReverseRequest(frame, handle);
          return;
        }
        const key = pendingKey(handle, frame.header.corr);
        const pending = this.pending.get(key);
        if (pending) {
          if (pending.acceptFrame && !pending.acceptFrame(frame))
            return;
          switch (frame.header.ty) {
            case FrameType.Push:
            case FrameType.StreamData:
              try {
                pending.onProgress?.(frame.body);
              } catch {
              }
              return;
            case FrameType.Response:
            case FrameType.StreamEnd:
              this.settle(key, pending, () => pending.resolve(frame));
              return;
            case FrameType.Error:
              this.settle(key, pending, () => pending.reject(this.errorFromFrame(frame)));
              return;
            default:
              return;
          }
        }
        const late = this.lateResponses.get(key);
        if (late && (frame.header.ty === FrameType.Response || frame.header.ty === FrameType.Error)) {
          this.lateResponses.delete(key);
          late(frame);
          return;
        }
        if (frame.header.ty === FrameType.Goodbye && handle) {
          this.failHandle(handle, new SubcError("route closed by subc (GOODBYE)", "route_closed"));
          if (this.liveRoutes.get(handle.channel) === handle)
            this.liveRoutes.delete(handle.channel);
          this.evictRouteHandle(handle);
          return;
        }
        if (frame.header.ty === FrameType.Response || frame.header.ty === FrameType.Error || frame.header.ty === FrameType.StreamEnd) {
          debug("dropped terminal frame with no waiter: type=%d channel=%d epoch=%d corr=%s port=%s", frame.header.ty, frame.header.channel, frame.header.epoch, frame.header.corr, this.sock.localPort() ?? "?");
        }
      }
      /**
       * Settle a pending exactly once. The object-identity guard (the map still
       * holds THIS pending under `key`) is the single-winner primitive: whichever of
       * dispatch, a timeout, fail(), failChannel(), a GOODBYE, or a deferred timeout
       * arbitration reaches it first wins, and every later caller no-ops. This is what
       * makes the deferred-timeout arbitration safe — it cannot double-settle, reject
       * an already-resolved promise, or delete a pending re-created for a later corr.
       * Returns true when this call was the settler.
       */
      settle(key, pending, run) {
        if (this.pending.get(key) !== pending)
          return false;
        this.pending.delete(key);
        if (pending.timer)
          clearTimeout(pending.timer);
        run();
        pending.onSettle?.();
        return true;
      }
      rejectPending(key, pending, err) {
        this.settle(key, pending, () => pending.reject(pending.classifyFailure?.(err) ?? err));
      }
      dispatchReverseRequest(frame, handle) {
        const method = reverseRequestMethod(frame.body);
        const methodFamily = method?.split("/", 1)[0];
        const handler = methodFamily ? reverseRequestHandler(handle, methodFamily) : void 0;
        const sock = this.sock;
        const generation = this.generation;
        const reply = async () => {
          if (!handler || !method) {
            await this.sendReverseError(frame, handle, "reverse_request_unhandled", methodFamily ? `no reverse-request handler is registered for ${methodFamily}` : "reverse request has no valid method", sock, generation);
            return;
          }
          let body;
          try {
            body = await handler(frame.body, { corr: frame.header.corr, method });
            if (!(body instanceof Uint8Array)) {
              throw new TypeError("reverse-request handler must return a Uint8Array");
            }
          } catch (error) {
            await this.sendReverseError(frame, handle, "reverse_request_unhandled", error instanceof Error ? error.message : String(error), sock, generation);
            return;
          }
          await this.sendReverseReply(frame, handle, FrameType.Response, body, sock, generation);
        };
        void reply().catch((error) => {
          if (this.sock === sock && this.generation === generation && !this.closeStarted) {
            debug("failed to answer reverse request: %s", causeMessage(error));
          }
        });
      }
      async sendReverseError(request, handle, code2, message, sock, generation) {
        await this.sendReverseReply(request, handle, FrameType.Error, this.encode({ code: code2, message }), sock, generation);
      }
      async sendReverseReply(request, handle, type, body, sock, generation) {
        if (this.sock !== sock || this.generation !== generation || !this.isLiveHandle(handle) || this.closeStarted || this.closedErr) {
          return;
        }
        const frame = buildFrame(type, buildFlags(false, Priority.Interactive, false), handle.channel, handle.epoch, request.header.corr, body);
        await writeBorrowed(sock, encodeFrame(frame), Date.now() + DEFAULT_REQUEST_TIMEOUT_MS);
      }
      errorFromFrame(frame) {
        try {
          const parsed = JSON.parse(Buffer.from(frame.body).toString("utf8"));
          const error = new SubcError(parsed.message ?? "subc error", parsed.code, parsed.detail);
          errorFrameFlags.set(error, frame.header.flags);
          return error;
        } catch {
          return new SubcError(Buffer.from(frame.body).toString("utf8") || "subc error");
        }
      }
      evictRouteHandle(handle) {
        for (const cached of this.routes.values()) {
          if (cached.handle && sameRouteHandle(cached.handle, handle))
            cached.handle = null;
        }
      }
      failHandle(handle, error) {
        for (const [key, pending] of this.pending) {
          if (pending.handle && sameRouteHandle(pending.handle, handle))
            this.rejectPending(key, pending, error);
        }
      }
      fail(err) {
        if (!this.closedErr)
          this.closedErr = err;
        for (const [key, pending] of this.pending) {
          this.rejectPending(key, pending, err);
        }
      }
      notSentCallError(message, cause) {
        return new SubcCallError("not_sent", `${message}${causeMessage(cause)}`, errorCode(cause), cause);
      }
      outcomeUnknownCallError(message, cause) {
        return new SubcCallError("outcome_unknown", `${message}${causeMessage(cause)}`, errorCode(cause), cause);
      }
      terminalCallError(message, cause) {
        if (cause instanceof SubcCallError)
          return cause;
        return new SubcCallError("terminal", `${message}${causeMessage(cause)}`, errorCode(cause), cause);
      }
      notSentRecoveryError(message, cause) {
        if (cause instanceof SubcCallError)
          return cause;
        if (isConsumerReconnectTransient(cause))
          return this.notSentCallError(message, cause);
        return this.terminalCallError(message, cause);
      }
      /** Number of nonzero-channel ingress frames dropped by endpoint epoch validation. */
      get droppedIngressFrames() {
        return this.ingressEpochDropCount;
      }
      installRoute(channel, epoch, reverseRequests2 = new ReverseRequestRegistry()) {
        const handle = createRouteHandle(channel, epoch, this.connectionToken, reverseRequests2);
        this.liveRoutes.set(channel, handle);
        return handle;
      }
      isLiveHandle(handle) {
        return belongsToConnection(handle, this.connectionToken) && this.liveRoutes.get(handle.channel) === handle;
      }
      assertLiveConnection(handle) {
        if (!belongsToConnection(handle, this.connectionToken))
          throw new StaleRouteHandleError(handle);
      }
      assertLiveHandle(handle) {
        if (!this.isLiveHandle(handle))
          throw new StaleRouteHandleError(handle);
      }
      allocateCorr() {
        const maximum = 0xffffffffffffffffn;
        if (this.nextCorr > maximum) {
          const error = new SubcError("channel-0 correlation id allocator exhausted", "corr_exhausted");
          this.fail(error);
          this.sock.close();
          this.scheduleReconnectAfterDrop(error);
          throw error;
        }
        const corr = this.nextCorr;
        this.nextCorr += 1n;
        return corr;
      }
      closeConnectionAfterCleanupFailure() {
        const error = new SubcError("late route cleanup could not be queued", "late_route_cleanup_failed");
        this.fail(error);
        this.sock.close();
        this.scheduleReconnectAfterDrop(error);
      }
      encode(value) {
        return Buffer.from(JSON.stringify(value), "utf8");
      }
      /** Decode a terminal response according to the representation on the wire. */
      decodeReply(frame) {
        return hasBinary(frame.header.flags) ? frame.body : this.parseJson(frame);
      }
      parseJson(frame) {
        const b = frame.body;
        return JSON.parse(Buffer.from(b.buffer, b.byteOffset, b.byteLength).toString("utf8"));
      }
    };
    UNKNOWN_CHANNEL = "unknown_channel";
    STALE_ROUTE_EPOCH = "stale_route_epoch";
  }
});

// ../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/provider.js
var init_provider = __esm({
  "../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/provider.js"() {
    init_auth();
    init_client();
    init_connection_file();
    init_envelope();
    init_route_handle();
    init_socket();
  }
});

// ../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/index.js
var init_dist = __esm({
  "../../node_modules/.bun/@cortexkit+subc-client@0.16.1/node_modules/@cortexkit/subc-client/dist/index.js"() {
    init_client();
    init_route_handle();
    init_connection_file();
    init_envelope();
    init_auth();
    init_socket();
    init_provider();
  }
});

// ../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/detect.js
import { readdirSync, statSync as statSync2 } from "node:fs";
import { tmpdir, userInfo } from "node:os";
import { join as join5 } from "node:path";
function homeTierPath() {
  const homeEnv = process.env.HOME;
  return homeEnv ? join5(homeEnv, ".local", "share", "cortexkit", "run", PRODUCTION_FILE_NAME) : void 0;
}
function highestPriorityAbsentMarker() {
  const runtime = process.env.XDG_RUNTIME_DIR;
  if (runtime)
    return join5(runtime, PRODUCTION_FILE_NAME);
  const home = homeTierPath();
  if (home)
    return home;
  return join5(userInfo().homedir, ".local", "share", "cortexkit", "run", PRODUCTION_FILE_NAME);
}
function findExistingConnectionPath() {
  if (process.env.SUBC_CONNECTION_FILE)
    return process.env.SUBC_CONNECTION_FILE;
  const runtime = process.env.XDG_RUNTIME_DIR;
  if (runtime) {
    const p = join5(runtime, PRODUCTION_FILE_NAME);
    if (safeIsFile(p))
      return p;
  }
  const home = homeTierPath();
  if (home && safeIsFile(home))
    return home;
  const exact2 = join5(tmpdir(), `${TEMP_PREFIX}${userConnectionToken()}${TEMP_SUFFIX}`);
  if (safeIsFile(exact2))
    return exact2;
  const matches2 = listSubcConnectionFiles(tmpdir());
  return matches2.length === 1 ? matches2[0] : void 0;
}
function userConnectionToken(getuid = process.getuid ?? null, env3 = process.env) {
  if (getuid)
    return String(getuid());
  for (const key of ["USER", "USERNAME", "HOME", "USERPROFILE"]) {
    const value = env3[key];
    if (value)
      return Array.from(value, (character) => /^[a-zA-Z0-9_-]$/.test(character) ? character : "_").join("");
  }
  return "unknown";
}
function getDefaultClaustrumConnectionPath() {
  return findExistingConnectionPath() ?? highestPriorityAbsentMarker();
}
function resolveClaustrumConnectionPath(explicit) {
  return explicit?.trim() || process.env.SUBC_CONNECTION_FILE || process.env.CLAUSTRUM_SUBC_CONNECTION?.trim() || getDefaultClaustrumConnectionPath();
}
function safeIsFile(path2) {
  try {
    return statSync2(path2).isFile();
  } catch {
    return false;
  }
}
function listSubcConnectionFiles(dir) {
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return [];
  }
  const matches2 = [];
  for (const name of entries) {
    if (typeof name !== "string")
      continue;
    if (!name.startsWith(TEMP_PREFIX) || !name.endsWith(TEMP_SUFFIX))
      continue;
    const candidate = join5(dir, name);
    if (safeIsFile(candidate))
      matches2.push(candidate);
  }
  matches2.sort();
  return matches2;
}
var PRODUCTION_FILE_NAME, TEMP_PREFIX, TEMP_SUFFIX;
var init_detect = __esm({
  "../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/detect.js"() {
    init_dist();
    PRODUCTION_FILE_NAME = "subc-connection.json";
    TEMP_PREFIX = "subc-";
    TEMP_SUFFIX = ".connection.json";
  }
});

// ../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/identity.js
import { createHash as createHash5 } from "node:crypto";
import { existsSync as existsSync2, realpathSync } from "node:fs";
import { dirname as dirname7, relative, resolve as resolve2 } from "node:path";
function storageFingerprint(storagePath) {
  const absolutePath = storagePath;
  let canonicalPath;
  try {
    canonicalPath = realpathSync(absolutePath);
  } catch (error) {
    if (error.code !== "ENOENT")
      throw error;
    let ancestor = absolutePath;
    while (!existsSync2(ancestor)) {
      const parent = dirname7(ancestor);
      if (parent === ancestor)
        break;
      ancestor = parent;
    }
    canonicalPath = resolve2(realpathSync(ancestor), relative(ancestor, absolutePath));
  }
  return createHash5("sha256").update(canonicalPath).digest("hex");
}
function storeIdentity(projectRoot, storagePath) {
  return {
    project_root: projectRoot,
    harness: "opencode",
    session: `store-${storageFingerprint(storagePath)}`
  };
}
var init_identity2 = __esm({
  "../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/identity.js"() {
  }
});

// ../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/ancestor-permissions.js
import { AsyncLocalStorage as AsyncLocalStorage2 } from "node:async_hooks";
import { readFile as readFile6 } from "node:fs/promises";
function records(source, count3) {
  return source.split("\n").filter((line) => line.trim() !== "" && !line.trimStart().startsWith("#")).map((line) => {
    const fields = line.split(":");
    if (fields.length !== count3 || !fields[0] || /\s/.test(fields[0]) || !/^\d+$/.test(fields[2]) || !Number.isSafeInteger(Number(fields[2])) || Number(fields[2]) > 4294967295 || count3 === 7 && (!/^\d+$/.test(fields[3]) || !Number.isSafeInteger(Number(fields[3])) || Number(fields[3]) > 4294967295)) {
      throw new Error("malformed account record");
    }
    if (count3 === 4 && fields[3] !== "" && fields[3].split(",").some((name) => name === "" || /\s/.test(name)))
      throw new Error("malformed group members");
    return fields;
  });
}
async function acceptsAncestor(metadata, identity = ancestorIdentityContext.getStore() ?? {
  euid: process.geteuid?.(),
  egid: process.getegid?.(),
  passwdPath: "/etc/passwd",
  groupPath: "/etc/group"
}) {
  if ((metadata.mode & 18) === 0 || (metadata.mode & 512) !== 0)
    return true;
  if ((metadata.mode & 2) !== 0 || identity.euid === void 0 || identity.egid === void 0 || metadata.uid !== identity.euid || metadata.gid !== identity.egid)
    return false;
  try {
    const passwd = records(new TextDecoder("utf-8", { fatal: true }).decode(await readFile6(identity.passwdPath)), 7);
    const groups = records(new TextDecoder("utf-8", { fatal: true }).decode(await readFile6(identity.groupPath)), 4);
    const users = passwd.filter((entry) => Number(entry[2]) === identity.euid);
    const matchingGroups = groups.filter((entry) => Number(entry[2]) === identity.egid);
    if (users.length !== 1 || matchingGroups.length !== 1)
      return false;
    const name = users[0][0];
    return (matchingGroups[0][3] === "" || matchingGroups[0][3].split(",").every((member) => member === name)) && !passwd.some((entry) => Number(entry[2]) !== identity.euid && Number(entry[3]) === identity.egid);
  } catch {
    return false;
  }
}
var ancestorIdentityContext;
var init_ancestor_permissions = __esm({
  "../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/ancestor-permissions.js"() {
    ancestorIdentityContext = new AsyncLocalStorage2();
  }
});

// ../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/enrollment.js
import { randomBytes as randomBytes3 } from "node:crypto";
import { chmod as chmod2, mkdir as mkdir8, open as open5, realpath as realpath3, rename as rename5, stat as stat4, unlink as unlink5 } from "node:fs/promises";
import { basename as basename3, dirname as dirname8, join as join6 } from "node:path";
function validateTokenFile(value) {
  if (!TOKEN_RE.test(value.token))
    throw new Error("enrollment token must be exactly 64 lowercase hex characters");
  if (!Number.isSafeInteger(value.token_generation) || value.token_generation < 1) {
    throw new Error("enrollment token generation must be a positive safe integer");
  }
}
async function refuseWritableAncestor(parent) {
  let component;
  try {
    component = await realpath3(parent);
  } catch {
    return;
  }
  for (; ; ) {
    const metadata = await stat4(component).catch(() => void 0);
    if (metadata && !await acceptsAncestor(metadata)) {
      throw new Error(`enrollment token ancestor ${component} is group- or world-writable without sticky bit`);
    }
    const next = dirname8(component);
    if (next === component)
      return;
    component = next;
  }
}
async function writeEnrollmentTokenFile(path2, value) {
  validateTokenFile(value);
  const parent = dirname8(path2);
  await mkdir8(parent, { recursive: true, mode: 448 });
  await refuseWritableAncestor(parent);
  const temporary = join6(parent, `.${basename3(path2)}.${process.pid}.${randomBytes3(12).toString("hex")}.tmp`);
  let created = false;
  try {
    const descriptor = await open5(temporary, "wx", 384);
    created = true;
    try {
      await descriptor.writeFile(`${JSON.stringify(value)}
`, "utf8");
      await descriptor.sync();
      await chmod2(temporary, 384);
    } finally {
      await descriptor.close();
    }
    await rename5(temporary, path2);
    created = false;
  } finally {
    if (created)
      await unlink5(temporary).catch(() => void 0);
  }
}
var TOKEN_RE;
var init_enrollment = __esm({
  "../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/enrollment.js"() {
    init_ancestor_permissions();
    TOKEN_RE = /^[0-9a-f]{64}$/;
  }
});

// ../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/handles.js
var HANDLE_FILE_CONTRACT;
var init_handles = __esm({
  "../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/handles.js"() {
    init_ancestor_permissions();
    HANDLE_FILE_CONTRACT = {
      maxBytes: 256 * 1024,
      mode: 384,
      // Shape only: identifier validity also rejects FORBIDDEN_IDENTIFIERS; use
      // identifierIsValid for validation so callers do not accept parser-rejected labels.
      labelRe: /^[a-z0-9][a-z0-9._-]{0,63}$/,
      handleRe: /^ckh_[A-Za-z0-9_-]{43}$/
    };
  }
});

// ../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/manifest-lock.js
var init_manifest_lock = __esm({
  "../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/manifest-lock.js"() {
    init_ancestor_permissions();
    init_handles();
  }
});

// ../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/errors.js
function isRecord6(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function credentialErrorAction(errorClass) {
  switch (errorClass) {
    case "permanent":
      return "gone";
    case "auth_required":
      return "reauth";
    case "context_overflow":
      return "reduce_and_retry";
    case "transient":
      return "retry";
  }
}
function asCredentialError(response, fallbackCode = "invalid_response", logUnknownClass = (errorClass) => console.warn(errorClass)) {
  const result = isRecord6(response) && isRecord6(response.result) ? response.result : void 0;
  const error = result && isRecord6(result.error) ? result.error : void 0;
  const rawClass = error?.class;
  const rawCode = error?.code;
  const hasValidClass = typeof rawClass === "string" && ERROR_CLASS_WIRE_SET.includes(rawClass);
  const hasCode = typeof rawCode === "string";
  const envelopeValid = hasValidClass && hasCode;
  const errorClass = envelopeValid ? rawClass : "transient";
  if (typeof rawClass !== "string")
    logUnknownClass("unknown");
  else if (!hasValidClass)
    logUnknownClass(rawClass);
  const code2 = hasCode ? rawCode : fallbackCode;
  return new ClaustrumCredentialError(code2, errorClass, credentialErrorAction(errorClass));
}
function hasCredentialError(response) {
  return isRecord6(response) && isRecord6(response.result) && isRecord6(response.result.error);
}
var ERROR_CLASS_WIRE_SET, ClaustrumCredentialError;
var init_errors2 = __esm({
  "../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/errors.js"() {
    ERROR_CLASS_WIRE_SET = [
      "transient",
      "permanent",
      "auth_required",
      "context_overflow"
    ];
    ClaustrumCredentialError = class extends Error {
      code;
      action;
      ["class"];
      constructor(code2, errorClass, action) {
        super(`Claustrum credential request failed: ${code2}`);
        this.code = code2;
        this.action = action;
        this.name = "ClaustrumCredentialError";
        this["class"] = errorClass;
      }
    };
  }
});

// ../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/wire.js
function isRecord7(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function asRecordVersion(value) {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : void 0;
}
function isOptionalString(value) {
  return value === void 0 || typeof value === "string";
}
function decodeCredential(response, logUnknownClass) {
  if (hasCredentialError(response))
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  const result = isRecord7(response) && isRecord7(response.result) ? response.result : void 0;
  const payload = result?.payload;
  if (!Array.isArray(payload) || payload.length === 0 || !payload.every((value) => typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 255)) {
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  }
  const recordVersion = asRecordVersion(result?.record_version);
  if (recordVersion === void 0) {
    throw asCredentialError(response, "invalid_record_version", logUnknownClass);
  }
  const rawExpiresAtMs = result?.expires_at_ms;
  const expiresAtMs = rawExpiresAtMs === void 0 || rawExpiresAtMs === null ? null : typeof rawExpiresAtMs === "number" && Number.isFinite(rawExpiresAtMs) ? rawExpiresAtMs : void 0;
  if (expiresAtMs === void 0) {
    throw asCredentialError(response, "invalid_expiry", logUnknownClass);
  }
  const credentialId = result?.credential_id;
  const projectId = result?.project_id;
  const accountId = result?.account_id;
  const email = result?.email;
  const orgName = result?.org_name;
  if (!isOptionalString(credentialId) || !isOptionalString(projectId) || !isOptionalString(accountId) || !isOptionalString(email) || !isOptionalString(orgName)) {
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  }
  let material;
  try {
    material = new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(payload));
  } catch {
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  }
  return {
    material,
    recordVersion,
    expiresAtMs,
    credentialId,
    projectId,
    accountId,
    email,
    orgName
  };
}
function decodeStatus(response, logUnknownClass) {
  if (hasCredentialError(response))
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  const result = isRecord7(response) && isRecord7(response.result) ? response.result : void 0;
  const rawRecordVersion = result?.record_version;
  const recordVersion = rawRecordVersion === void 0 ? void 0 : asRecordVersion(rawRecordVersion);
  const credentialId = result?.credential_id;
  if (typeof result?.ready !== "boolean" || result?.last_error_code !== void 0 && result?.last_error_code !== null && typeof result?.last_error_code !== "string" || typeof result?.lease_held !== "boolean" || rawRecordVersion !== void 0 && recordVersion === void 0 || !isOptionalString(credentialId) || result?.stale_pending !== void 0 && typeof result.stale_pending !== "boolean") {
    throw asCredentialError(response, "invalid_status", logUnknownClass);
  }
  return {
    ready: result.ready,
    lastErrorCode: result.last_error_code ?? null,
    leaseHeld: result.lease_held,
    ...credentialId === void 0 ? {} : { credentialId },
    ...recordVersion === void 0 ? {} : { recordVersion },
    ...result.stale_pending === void 0 ? {} : { stalePending: result.stale_pending }
  };
}
function decodeScopedInventory(response, logUnknownClass) {
  if (hasCredentialError(response))
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  const result = isRecord7(response) && isRecord7(response.result) ? response.result : void 0;
  const rows = result?.credentials;
  if (!Array.isArray(rows))
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  const view = result?.view;
  if (typeof view !== "string" || view.length === 0) {
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  }
  const decoded = rows.map((row) => {
    if (!isRecord7(row))
      throw asCredentialError(response, "invalid_response", logUnknownClass);
    const recordVersion = asRecordVersion(row.record_version);
    if (recordVersion === void 0) {
      throw asCredentialError(response, "invalid_record_version", logUnknownClass);
    }
    const strings = (value) => {
      if (!Array.isArray(value) || !value.every((entry) => typeof entry === "string")) {
        throw asCredentialError(response, "invalid_response", logUnknownClass);
      }
      return value;
    };
    if (typeof row.id !== "string" || typeof row.type !== "string" || typeof row.state !== "string") {
      throw asCredentialError(response, "invalid_response", logUnknownClass);
    }
    const createdAtMs = row.created_at_ms === void 0 || row.created_at_ms === null ? null : typeof row.created_at_ms === "number" && Number.isFinite(row.created_at_ms) ? row.created_at_ms : void 0;
    if (createdAtMs === void 0)
      throw asCredentialError(response, "invalid_response", logUnknownClass);
    const authMethod = row.auth_method;
    if (authMethod !== void 0 && authMethod !== "apikey" && authMethod !== "chatgpt" && authMethod !== "antigravity" && authMethod !== "oauth") {
      throw asCredentialError(response, "invalid_response", logUnknownClass);
    }
    if (!isOptionalString(row.refresh_adapter)) {
      throw asCredentialError(response, "invalid_response", logUnknownClass);
    }
    if (!isOptionalString(row.account_id) || !isOptionalString(row.email) || !isOptionalString(row.org_name)) {
      throw asCredentialError(response, "invalid_response", logUnknownClass);
    }
    return {
      id: row.id,
      categories: strings(row.categories),
      credentialType: row.type,
      serves: strings(row.serves),
      // ABSENT DECODES AS EMPTY, PRESENT MUST BE AN ARRAY. Daemons before provider ids
      // existed omit the key, and refusing that would fail the whole listing against a
      // still-supported daemon. Absent and empty mean the same thing to every consumer:
      // no ids set. A present non-array is a malformed reply and still refuses.
      providerIds: row.provider_ids === void 0 ? [] : strings(row.provider_ids),
      authMethod,
      state: row.state,
      refreshAdapter: row.refresh_adapter,
      recordVersion,
      operations: strings(row.operations),
      createdAtMs,
      accountId: row.account_id,
      email: row.email,
      orgName: row.org_name
    };
  });
  return { rows: decoded, view };
}
function decodeEnrollmentResult(response, logUnknownClass) {
  if (hasCredentialError(response))
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  const result = isRecord7(response) && isRecord7(response.result) ? response.result : void 0;
  if (result === void 0)
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  return result;
}
function decodeEnrollmentPoll(response, logUnknownClass) {
  const result = decodeEnrollmentResult(response, logUnknownClass);
  const status = result.status;
  if (status === "pending")
    return { status: "pending" };
  if (status === "denied")
    return { status: "denied" };
  if (status !== "approved")
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  const { name, token, token_generation: generation } = result;
  if (typeof name !== "string" || typeof token !== "string" || token.length === 0 || typeof generation !== "number" || !Number.isInteger(generation)) {
    throw asCredentialError(response, "invalid_response", logUnknownClass);
  }
  return { status: "approved", name, token, tokenGeneration: generation };
}
var CLAUSTRUM_MODULE_ID, RECONNECT_BACKOFF_MS, ClaustrumClient;
var init_wire = __esm({
  "../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/wire.js"() {
    init_dist();
    init_detect();
    init_errors2();
    init_identity2();
    CLAUSTRUM_MODULE_ID = "claustrum";
    RECONNECT_BACKOFF_MS = 6e4;
    ClaustrumClient = class _ClaustrumClient {
      #client;
      #connector;
      #connectionFile;
      #handshakeTimeoutMs;
      #identity;
      #logger;
      #reconnecting = null;
      #nextReconnectAt = 0;
      #closed = false;
      constructor(client, connector, connectionFile, handshakeTimeoutMs, identity, logger) {
        this.#client = client;
        this.#connector = connector;
        this.#connectionFile = connectionFile;
        this.#handshakeTimeoutMs = handshakeTimeoutMs;
        this.#identity = identity;
        this.#logger = logger;
      }
      static async connect(options = {}) {
        const connectionFile = resolveClaustrumConnectionPath(options.connectionFile);
        const connector = options.connector ?? ((connectOptions) => SubcClient.connect(connectOptions));
        const identity = options.identity ?? storeIdentity(options.projectRoot ?? process.cwd(), options.storagePath ?? process.cwd());
        const client = await connector({
          connectionFile,
          handshakeTimeoutMs: options.handshakeTimeoutMs
        });
        return new _ClaustrumClient(client, connector, connectionFile, options.handshakeTimeoutMs, identity, options.logger ?? ((errorClass) => console.warn(errorClass)));
      }
      async getCredential(handle, minTtlMs) {
        const response = await this.#call("credential.get", {
          handle,
          min_ttl_ms: minTtlMs,
          force_refresh: false
        });
        return decodeCredential(response, this.#logger);
      }
      async statusCredential(handle) {
        const response = await this.#call("credential.status", { handle });
        return decodeStatus(response, this.#logger);
      }
      async reportAuthFailure(input) {
        const response = await this.#call("credential.report_auth_failure", {
          handle: input.handle,
          provider_status: input.providerStatus,
          record_version: input.recordVersion,
          reporter_source: input.reporterSource
        });
        if (hasCredentialError(response))
          throw asCredentialError(response, "invalid_response", this.#logger);
        const result = isRecord7(response) && isRecord7(response.result) ? response.result : void 0;
        if (result?.accepted !== true)
          throw asCredentialError(response, "invalid_response", this.#logger);
      }
      /**
       * Enumerate what this caller's grants cover.
       *
       * `params` is `{}` and must be PRESENT: the vault rejects an absent or null params
       * object, so a caller cannot ask a different question by omitting it.
       */
      async listScoped(enrollmentToken) {
        const response = await this.#call("credential.list_scoped", enrollmentToken === void 0 ? {} : { enrollment_token: enrollmentToken });
        return decodeScopedInventory(response, this.#logger);
      }
      /**
       * Fetch by credential id, authorized by a grant rather than a bearer handle.
       *
       * `minTtlMs` is a DEMAND, not a hint: if a real upstream exchange still cannot satisfy
       * it, the vault refuses with `ttl_unsatisfiable` (class `context_overflow`) rather than
       * serving a token that will die inside the caller's own margin. That class means
       * reduce-and-retry, never wait-and-retry.
       */
      async getScoped(input) {
        const response = await this.#call("credential.get_scoped", {
          credential_id: input.credentialId,
          enrollment_token: input.enrollmentToken,
          min_ttl_ms: input.minTtlMs
        });
        return decodeCredential(response, this.#logger);
      }
      /**
       * Report a served credential dead, addressed by id rather than by handle.
       *
       * VERSION-FENCED: `recordVersion` must be the one this caller was SERVED. A report
       * against a since-refreshed version is accepted and does nothing, which is the point --
       * a stale report must not kill a fresh token. `accepted: true` is the receipt that the
       * report was taken, never evidence that it applied.
       */
      async reportAuthFailureScoped(input) {
        const response = await this.#call("credential.report_auth_failure", {
          credential_id: input.credentialId,
          enrollment_token: input.enrollmentToken,
          provider_status: input.providerStatus,
          record_version: input.recordVersion,
          reporter_source: input.reporterSource
        });
        if (hasCredentialError(response))
          throw asCredentialError(response, "invalid_response", this.#logger);
        const result = isRecord7(response) && isRecord7(response.result) ? response.result : void 0;
        if (result?.accepted !== true)
          throw asCredentialError(response, "invalid_response", this.#logger);
      }
      /**
       * Propose an enrollment. The consumer mints `requestSecret` itself and sends only its
       * hash; the raw secret NEVER leaves the process, and it is what authorizes the poll.
       *
       * IDEMPOTENT ON (name, secret): re-proposing with the same secret returns the SAME
       * `requestId`. That exists because `requestId` is minted server-side, so a consumer
       * cannot persist it before proposing -- a crash in that window would otherwise leave it
       * holding a secret it cannot poll with and a name held until TTL. Persist the secret
       * BEFORE calling this, and a crash costs nothing.
       *
       * A different secret on the same name is a different caller and is refused.
       */
      async enrollPropose(input) {
        const response = await this.#call("auth.enroll_propose", {
          proposed_name: input.name,
          request_secret_hash: input.requestSecretHash
        });
        const result = decodeEnrollmentResult(response, this.#logger);
        const requestId = result.request_id;
        if (typeof requestId !== "string" || requestId.length === 0) {
          throw asCredentialError(response, "invalid_response", this.#logger);
        }
        return { requestId };
      }
      /**
       * Poll a proposal. Returns `pending` until an operator decides, then exactly once
       * returns the token.
       *
       * THE TOKEN IS RETURNED ONCE. Persist it before doing anything else with it; a lost
       * token needs a fresh ceremony, not a second poll.
       */
      async enrollPoll(input) {
        const response = await this.#call("auth.enroll_poll", {
          request_id: input.requestId,
          request_secret: input.requestSecret
        });
        return decodeEnrollmentPoll(response, this.#logger);
      }
      /**
       * Exchange a live token for its successor. The old token dies when the new one is issued.
       *
       * `expectedTokenGeneration` IS REQUIRED AND IS A FENCE, not bookkeeping: it must be the
       * generation this caller currently holds. Two rotations racing — a retry after an
       * uncertain reply, or two instances of the same consumer — would otherwise each mint a
       * successor and each invalidate the other's, leaving a consumer holding a token the
       * vault has already replaced. The vault refuses a rotation whose expectation does not
       * match, so the loser learns it lost instead of discovering it on a later spend.
       */
      async enrollRotate(input) {
        const response = await this.#call("auth.enroll_rotate", {
          token: input.token,
          expected_token_generation: input.expectedTokenGeneration
        });
        const result = decodeEnrollmentResult(response, this.#logger);
        const token = result.token;
        const generation = result.token_generation;
        if (typeof token !== "string" || token.length === 0 || typeof generation !== "number" || !Number.isInteger(generation) || generation < 0) {
          throw asCredentialError(response, "invalid_response", this.#logger);
        }
        return { token, tokenGeneration: generation };
      }
      close() {
        this.#closed = true;
        this.#client.close();
      }
      async #call(method, params) {
        const sentClient = this.#client;
        try {
          return await sentClient.call(CLAUSTRUM_MODULE_ID, method, params, {
            identity: this.#identity,
            consumerIdentity: null
          });
        } catch (error) {
          if (this.#shouldReconnect(error)) {
            try {
              if (this.#client === sentClient)
                await this.#reconnect();
            } catch (reconnectError) {
              throw this.#asTransportError(reconnectError);
            }
            try {
              return await this.#client.call(CLAUSTRUM_MODULE_ID, method, params, {
                identity: this.#identity,
                consumerIdentity: null
              });
            } catch (retryError) {
              throw this.#asTransportError(retryError);
            }
          }
          throw this.#asTransportError(error);
        }
      }
      #asTransportError(error) {
        if (error instanceof ClaustrumCredentialError)
          return error;
        const code2 = error instanceof SubcCallError && error.code ? error.code : "transport_error";
        return new ClaustrumCredentialError(code2, "transient", "retry");
      }
      #shouldReconnect(error) {
        return !this.#closed && error instanceof SubcCallError && error.kind === "terminal" && error.code !== "missing_identity" && error.code !== "invalid_control_body" && // The daemon answers unknown_module only when no module with this id is
        // registered or supervised at all; a vault that is restarting or warming up
        // is reported as module_warming or target_unavailable, which the SDK already
        // retries in place. A fresh connection to the same daemon gets the same
        // answer, and the wasted reconnect would also start the reconnect backoff,
        // leaving a genuinely wedged connection unable to recover for a minute.
        error.code !== "unknown_module";
      }
      async #reconnect() {
        if (this.#closed)
          throw new Error("Claustrum client is closed");
        if (this.#reconnecting) {
          await this.#reconnecting;
          return;
        }
        const now = Date.now();
        if (now < this.#nextReconnectAt)
          throw new Error("Claustrum client reconnect is backed off");
        this.#nextReconnectAt = now + RECONNECT_BACKOFF_MS;
        this.#reconnecting = this.#connector({
          connectionFile: this.#connectionFile,
          handshakeTimeoutMs: this.#handshakeTimeoutMs
        }).then((client) => {
          if (this.#closed) {
            client.close();
            throw new Error("Claustrum client is closed");
          }
          const previous = this.#client;
          this.#client = client;
          previous.close();
        }).finally(() => {
          this.#reconnecting = null;
        });
        await this.#reconnecting;
      }
    };
  }
});

// ../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/index.js
var init_dist2 = __esm({
  "../../node_modules/.bun/@cortexkit+claustrum-client@0.6.2/node_modules/@cortexkit/claustrum-client/dist/index.js"() {
    init_detect();
    init_identity2();
    init_enrollment();
    init_manifest_lock();
    init_errors2();
    init_wire();
    init_handles();
  }
});

// ../core/dist/common-auth-embedded/util/any-signal.js
function combineAbortSignals(signals) {
  const controller = new AbortController();
  const listeners = [];
  let disposed = false;
  const dispose = () => {
    if (disposed)
      return;
    disposed = true;
    for (const { source, listener } of listeners) {
      source.removeEventListener("abort", listener);
    }
    listeners.length = 0;
  };
  const abort = (reason) => {
    if (disposed || controller.signal.aborted)
      return;
    controller.abort(reason);
    dispose();
  };
  const alreadyAborted = signals.find((signal) => signal.aborted);
  if (alreadyAborted) {
    controller.abort(alreadyAborted.reason);
    return { signal: controller.signal, dispose };
  }
  for (const source of signals) {
    if (controller.signal.aborted)
      break;
    const listener = () => abort(source.reason);
    listeners.push({ source, listener });
    source.addEventListener("abort", listener, { once: true });
    if (source.aborted)
      abort(source.reason);
  }
  return { signal: controller.signal, dispose };
}
var init_any_signal = __esm({
  "../core/dist/common-auth-embedded/util/any-signal.js"() {
    "use strict";
  }
});

// ../core/dist/common-auth-embedded/claustrum/errors.js
var ClaustrumConsumerError;
var init_errors3 = __esm({
  "../core/dist/common-auth-embedded/claustrum/errors.js"() {
    "use strict";
    ClaustrumConsumerError = class extends Error {
      kind;
      constructor(kind, message) {
        super(message);
        this.name = "ClaustrumConsumerError";
        this.kind = kind;
      }
    };
  }
});

// ../core/dist/common-auth-embedded/claustrum/enrollment.js
import { createHash as createHash6, randomBytes as randomBytes4, randomUUID as randomUUID9 } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import { chmod as chmod3, mkdir as mkdir9, open as open6, readFile as readFile7, realpath as realpath4, rename as rename6, stat as stat5, unlink as unlink6 } from "node:fs/promises";
import { basename as basename4, dirname as dirname9, extname, isAbsolute as isAbsolute2, join as join7, resolve as resolve3 } from "node:path";
function classifyEnrollmentError(error) {
  if (!(error instanceof ClaustrumCredentialError))
    return void 0;
  if (TERMINAL_ENROLLMENT_CODES.has(error.code))
    return { code: error.code, disposition: "terminal" };
  if (RETRYABLE_ENROLLMENT_CODES.has(error.code))
    return { code: error.code, disposition: "retry" };
  return {
    code: error.code,
    disposition: error.action === "retry" ? "retry" : "terminal"
  };
}
function enrollmentName(plugin, host) {
  if (!/^[a-z0-9][a-z0-9-]*$/.test(plugin) || !/^[a-z0-9][a-z0-9-]*$/.test(host))
    throw new ClaustrumConsumerError("invalid-state", "Claustrum enrollment names use lowercase letters, digits and dashes");
  return `${plugin}-${host}`;
}
function connectClaustrumEnrollmentClient(options) {
  return ClaustrumClient.connect(options);
}
function getClaustrumEnrollmentPaths(tokenPath) {
  const extension = extname(tokenPath) || ".json";
  const stem = basename4(tokenPath, extname(tokenPath));
  return {
    statePath: join7(dirname9(tokenPath), `${stem}-state${extension}`),
    tokenPath
  };
}
function hostEnrollmentPaths(input) {
  const override = input.override?.trim();
  if (override && !isAbsolute2(override) && !input.cwd)
    throw new ClaustrumConsumerError("invalid-state", "A relative Claustrum enrollment override needs a base directory");
  const tokenPath = override ? isAbsolute2(override) ? override : resolve3(input.cwd, override) : join7(input.stateDir, `${input.host}-enrollment.json`);
  return getClaustrumEnrollmentPaths(tokenPath);
}
function isRecord8(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function validTimestamp(value) {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
function validGeneration(value) {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}
function invalidState() {
  return new ClaustrumConsumerError("invalid-state", "invalid Claustrum enrollment state");
}
function decodeEnrollmentState(value) {
  if (!isRecord8(value) || value.version !== ENROLLMENT_SCHEMA || typeof value.proposedName !== "string" || value.proposedName.length === 0) {
    throw invalidState();
  }
  if (value.phase === "pending") {
    if (!TOKEN_RE2.test(String(value.requestSecret ?? "")) || value.requestId !== void 0 && (typeof value.requestId !== "string" || value.requestId.length === 0) || !validTimestamp(value.createdAt) || !validTimestamp(value.updatedAt)) {
      throw invalidState();
    }
    return {
      version: 1,
      phase: "pending",
      proposedName: value.proposedName,
      requestSecret: value.requestSecret,
      ...value.requestId !== void 0 && {
        requestId: value.requestId
      },
      createdAt: value.createdAt,
      updatedAt: value.updatedAt
    };
  }
  if (value.phase === "approved") {
    if (value.approvedName !== void 0 && (typeof value.approvedName !== "string" || value.approvedName.length === 0) || !validGeneration(value.tokenGeneration) || !validTimestamp(value.updatedAt)) {
      throw invalidState();
    }
    return {
      version: 1,
      phase: "approved",
      proposedName: value.proposedName,
      ...value.approvedName !== void 0 && {
        approvedName: value.approvedName
      },
      tokenGeneration: value.tokenGeneration,
      updatedAt: value.updatedAt
    };
  }
  if (value.phase === "denied" || value.phase === "blocked") {
    if (value.errorCode !== void 0 && typeof value.errorCode !== "string" || !validTimestamp(value.updatedAt)) {
      throw invalidState();
    }
    return {
      version: 1,
      phase: value.phase,
      proposedName: value.proposedName,
      ...value.errorCode !== void 0 && {
        errorCode: value.errorCode
      },
      updatedAt: value.updatedAt
    };
  }
  throw invalidState();
}
function decodeTokenFile(value) {
  if (!isRecord8(value) || !TOKEN_RE2.test(String(value.token ?? "")) || !validGeneration(value.token_generation)) {
    throw new ClaustrumConsumerError("invalid-token", "invalid Claustrum enrollment token file");
  }
  return {
    token: value.token,
    token_generation: value.token_generation
  };
}
function validateReadableSecretFile(metadata) {
  if (!metadata.isFile()) {
    throw new ClaustrumConsumerError("unsafe-file", "Claustrum enrollment file must be a regular file");
  }
  if ((metadata.mode & 63) !== 0) {
    throw new ClaustrumConsumerError("unsafe-file", "Claustrum enrollment file must be owner-only");
  }
  const expectedUid = process.geteuid?.();
  if (expectedUid !== void 0 && metadata.uid !== expectedUid) {
    throw new ClaustrumConsumerError("unsafe-file", "Claustrum enrollment file must be owned by the current user");
  }
}
function parseSecretJson(text2) {
  try {
    return JSON.parse(text2);
  } catch {
    throw new ClaustrumConsumerError("invalid-state", "Claustrum enrollment file is not valid JSON");
  }
}
async function readBoundedJson(path2) {
  let descriptor;
  try {
    descriptor = await open6(path2, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
  } catch (error) {
    if (error.code === "ENOENT")
      return void 0;
    throw new ClaustrumConsumerError("unsafe-file", "Claustrum enrollment file could not be opened safely");
  }
  try {
    validateReadableSecretFile(await descriptor.stat());
    const source = Buffer.alloc(ENROLLMENT_FILE_MAX_BYTES + 1);
    const { bytesRead } = await descriptor.read(source, 0, source.byteLength, 0);
    if (bytesRead > ENROLLMENT_FILE_MAX_BYTES) {
      throw new ClaustrumConsumerError("unsafe-file", "Claustrum enrollment file is too large");
    }
    return parseSecretJson(source.subarray(0, bytesRead).toString("utf8"));
  } finally {
    await descriptor.close();
  }
}
function accountRecords(text2, fields) {
  const records2 = [];
  for (const line of text2.split("\n")) {
    if (line.trim() === "" || line.startsWith("#"))
      continue;
    const parts = line.split(":");
    if (parts.length !== fields || !/^[^\s:,]+$/.test(parts[0] ?? "") || !/^\d+$/.test(parts[2] ?? "") || !Number.isSafeInteger(Number(parts[2])) || fields === 7 && (!/^\d+$/.test(parts[3] ?? "") || !Number.isSafeInteger(Number(parts[3]))) || fields === 4 && parts[3] !== "" && !/^[^\s:,]+(?:,[^\s:,]+)*$/.test(parts[3] ?? ""))
      return void 0;
    records2.push(parts);
  }
  return records2;
}
async function isPrivateGroup(uid, gid, options) {
  try {
    const [passwdText, groupText] = await Promise.all([
      readFile7(options.passwdPath ?? "/etc/passwd", "utf8"),
      readFile7(options.groupPath ?? "/etc/group", "utf8")
    ]);
    const users = accountRecords(passwdText, 7);
    const groups = accountRecords(groupText, 4);
    if (!users || !groups)
      return false;
    const owners = users.filter((user) => Number(user[2]) === uid);
    const matchingGroups = groups.filter((group) => Number(group[2]) === gid);
    if (owners.length !== 1 || matchingGroups.length !== 1)
      return false;
    const name = owners[0]?.[0];
    const members = matchingGroups[0]?.[3] ?? "";
    return (members === "" || members.split(",").every((member) => member === name)) && !users.some((user) => Number(user[2]) !== uid && Number(user[3]) === gid);
  } catch {
    return false;
  }
}
async function refuseWritableAncestor2(parent, options = {}) {
  const uid = process.geteuid?.();
  if (uid === void 0)
    return;
  const gid = process.getegid?.();
  let component;
  try {
    component = await realpath4(parent);
  } catch {
    return;
  }
  let privateGroup;
  for (; ; ) {
    const metadata = await stat5(component).catch(() => void 0);
    if (metadata && (metadata.mode & 18) !== 0 && (metadata.mode & 512) === 0) {
      if (privateGroup === void 0) {
        privateGroup = gid !== void 0 && await isPrivateGroup(uid, gid, options);
      }
      if ((metadata.mode & 2) !== 0 || metadata.uid !== uid || metadata.gid !== gid || !privateGroup) {
        throw new ClaustrumConsumerError("unsafe-file", `Claustrum enrollment path has a writable ancestor: ${component}. Another user could replace it. Run: chmod g-w,o-w ${component}`);
      }
    }
    const next = dirname9(component);
    if (next === component)
      return;
    component = next;
  }
}
async function ensurePrivateDirectory(directory) {
  await mkdir9(directory, { recursive: true, mode: 448 });
  const metadata = await stat5(directory);
  const uid = process.geteuid?.();
  if (uid !== void 0 && metadata.uid !== uid) {
    throw new ClaustrumConsumerError("unsafe-file", "Claustrum enrollment directory must be owned by the current user");
  }
  if ((metadata.mode & 63) !== 0)
    await chmod3(directory, 448);
}
async function writeStateAtomic(path2, state, ancestorOptions = {}) {
  const parent = dirname9(path2);
  await ensurePrivateDirectory(parent);
  await refuseWritableAncestor2(parent, ancestorOptions);
  const bytes = `${JSON.stringify(state)}
`;
  if (Buffer.byteLength(bytes) > ENROLLMENT_FILE_MAX_BYTES) {
    throw new ClaustrumConsumerError("invalid-state", "Claustrum enrollment state is too large");
  }
  const temporary = join7(parent, `.${basename4(path2)}.${process.pid}.${randomUUID9()}.tmp`);
  let descriptor;
  let created = false;
  try {
    descriptor = await open6(temporary, "wx", 384);
    created = true;
    await descriptor.writeFile(bytes, "utf8");
    await descriptor.chmod(384);
    await descriptor.sync();
    await descriptor.close();
    descriptor = void 0;
    await rename6(temporary, path2);
    created = false;
  } finally {
    await descriptor?.close().catch(() => {
    });
    if (created)
      await unlink6(temporary).catch(() => {
      });
  }
}
async function readClaustrumEnrollmentStatus(paths, proposedName) {
  const tokenValue = await readBoundedJson(paths.tokenPath);
  const token = tokenValue === void 0 ? void 0 : decodeTokenFile(tokenValue);
  const stateValue = await readBoundedJson(paths.statePath);
  const state = stateValue === void 0 ? void 0 : decodeEnrollmentState(stateValue);
  if (token) {
    return {
      state: "approved",
      proposedName: state?.proposedName ?? proposedName,
      ...state?.phase === "approved" && state.approvedName !== void 0 && {
        approvedName: state.approvedName
      },
      tokenGeneration: token.token_generation
    };
  }
  if (!state)
    return { state: "idle" };
  if (state.phase === "approved") {
    return {
      state: "blocked",
      proposedName: state.proposedName,
      code: "missing_token"
    };
  }
  return statusFromState(state);
}
async function enrollmentAuthority(paths, proposedName) {
  let status;
  try {
    status = await readClaustrumEnrollmentStatus(paths, proposedName);
  } catch (error) {
    if (!(error instanceof ClaustrumConsumerError) || error.kind !== "invalid-state" && error.kind !== "invalid-token") {
      return "unreadable";
    }
    try {
      const stateValue = await readBoundedJson(paths.statePath);
      if (stateValue === void 0)
        return "unreadable";
      const state = decodeEnrollmentState(stateValue);
      return state.phase === "approved" && state.proposedName === proposedName ? "vault" : "unreadable";
    } catch {
      return "unreadable";
    }
  }
  if ("proposedName" in status && status.proposedName !== proposedName)
    return "unreadable";
  if (status.state === "approved" || status.state === "blocked" && status.code === "missing_token") {
    return "vault";
  }
  return "local";
}
async function readClaustrumEnrollmentToken(tokenPath) {
  const value = await readBoundedJson(tokenPath);
  if (value === void 0)
    throw new ClaustrumConsumerError("not-enrolled", "Claustrum enrollment is not configured");
  return decodeTokenFile(value);
}
function statusFromState(state) {
  if (state.phase === "pending") {
    return {
      state: "pending",
      proposedName: state.proposedName,
      ...state.requestId !== void 0 && { requestId: state.requestId }
    };
  }
  if (state.phase === "approved") {
    return {
      state: "approved",
      proposedName: state.proposedName,
      ...state.approvedName !== void 0 && {
        approvedName: state.approvedName
      },
      tokenGeneration: state.tokenGeneration
    };
  }
  if (state.phase === "denied")
    return { state: "denied", proposedName: state.proposedName };
  return {
    state: "blocked",
    proposedName: state.proposedName,
    code: state.errorCode ?? "unknown"
  };
}
function wrongConsumer() {
  return new ClaustrumConsumerError("wrong-consumer", "Claustrum enrollment state belongs to a different consumer");
}
async function resetClaustrumEnrollmentState(paths, proposedName) {
  await ensurePrivateDirectory(dirname9(paths.statePath));
  const lock = await acquireRefreshFileLock({
    name: "ceremony",
    path: paths.statePath,
    ttlMs: ENROLLMENT_LOCK_TTL_MS,
    renew: true
  });
  if (!lock)
    return "busy";
  try {
    if (await readBoundedJson(paths.tokenPath) !== void 0)
      return "refused-approved";
    const value = await readBoundedJson(paths.statePath);
    if (value === void 0)
      return "idle";
    const state = decodeEnrollmentState(value);
    if (state.proposedName !== proposedName)
      throw wrongConsumer();
    if (state.phase === "pending")
      return "refused-pending";
    await lock.assertOwned();
    await unlink6(paths.statePath);
    return "reset";
  } finally {
    await lock.release();
  }
}
async function removeIfPresent(path2) {
  try {
    await unlink6(path2);
    return true;
  } catch (error) {
    if (error.code === "ENOENT")
      return false;
    throw error;
  }
}
async function disconnectClaustrumEnrollment(paths, proposedName) {
  await ensurePrivateDirectory(dirname9(paths.statePath));
  const lock = await acquireRefreshFileLock({
    // The same lock as the ceremony, so a token written by a concurrent
    // reconcile() can never land after this removes the files.
    name: "ceremony",
    path: paths.statePath,
    ttlMs: ENROLLMENT_LOCK_TTL_MS,
    renew: true
  });
  if (!lock)
    return "busy";
  try {
    let state;
    try {
      const value = await readBoundedJson(paths.statePath);
      state = value === void 0 ? void 0 : decodeEnrollmentState(value);
    } catch (error) {
      if (!(error instanceof ClaustrumConsumerError) || error.kind !== "invalid-state")
        throw error;
    }
    if (state && state.proposedName !== proposedName)
      throw wrongConsumer();
    await lock.assertOwned();
    const removedToken = await removeIfPresent(paths.tokenPath);
    await lock.assertOwned();
    const removedState = await removeIfPresent(paths.statePath);
    return removedToken || removedState ? "disconnected" : "idle";
  } finally {
    await lock.release();
  }
}
var ENROLLMENT_SCHEMA, ENROLLMENT_FILE_MAX_BYTES, ENROLLMENT_LOCK_TTL_MS, TOKEN_RE2, TERMINAL_ENROLLMENT_CODES, RETRYABLE_ENROLLMENT_CODES, ClaustrumEnrollmentManager;
var init_enrollment2 = __esm({
  "../core/dist/common-auth-embedded/claustrum/enrollment.js"() {
    "use strict";
    init_dist2();
    init_fs();
    init_errors3();
    ENROLLMENT_SCHEMA = 1;
    ENROLLMENT_FILE_MAX_BYTES = 16 * 1024;
    ENROLLMENT_LOCK_TTL_MS = 3e4;
    TOKEN_RE2 = /^[0-9a-f]{64}$/;
    TERMINAL_ENROLLMENT_CODES = /* @__PURE__ */ new Set([
      "invalid_params",
      "pending_exists",
      "not_found",
      "already_consumed",
      "superseded",
      "stale_generation"
    ]);
    RETRYABLE_ENROLLMENT_CODES = /* @__PURE__ */ new Set([
      "pending_queue_full"
    ]);
    ClaustrumEnrollmentManager = class {
      #client;
      #paths;
      #proposedName;
      #now;
      #mintSecret;
      #writeTokenFile;
      #ancestorOptions;
      constructor(options) {
        this.#ancestorOptions = options.ancestorOptions ?? {};
        this.#client = options.client;
        this.#paths = options.paths;
        this.#proposedName = options.proposedName;
        this.#now = options.now ?? Date.now;
        this.#mintSecret = options.mintSecret ?? (() => randomBytes4(32).toString("hex"));
        this.#writeTokenFile = options.writeTokenFile ?? writeEnrollmentTokenFile;
      }
      async status() {
        return readClaustrumEnrollmentStatus(this.#paths, this.#proposedName);
      }
      async resetTerminal() {
        return resetClaustrumEnrollmentState(this.#paths, this.#proposedName);
      }
      async #block(state, code2) {
        const blocked = {
          version: 1,
          phase: "blocked",
          proposedName: state.proposedName,
          errorCode: code2,
          updatedAt: this.#now()
        };
        await writeStateAtomic(this.#paths.statePath, blocked, this.#ancestorOptions);
        return statusFromState(blocked);
      }
      async reconcile() {
        await ensurePrivateDirectory(dirname9(this.#paths.statePath));
        const lock = await acquireRefreshFileLock({
          name: "ceremony",
          path: this.#paths.statePath,
          ttlMs: ENROLLMENT_LOCK_TTL_MS,
          renew: true
        });
        if (!lock)
          return { state: "busy" };
        try {
          const existingToken = await readBoundedJson(this.#paths.tokenPath);
          const token = existingToken === void 0 ? void 0 : decodeTokenFile(existingToken);
          const stateValue = await readBoundedJson(this.#paths.statePath);
          let state = stateValue === void 0 ? void 0 : decodeEnrollmentState(stateValue);
          if (state && state.proposedName !== this.#proposedName)
            throw wrongConsumer();
          if (token) {
            if (!state || state.phase === "pending") {
              const approved = {
                version: 1,
                phase: "approved",
                proposedName: state?.proposedName ?? this.#proposedName,
                tokenGeneration: token.token_generation,
                updatedAt: this.#now()
              };
              await writeStateAtomic(this.#paths.statePath, approved, this.#ancestorOptions);
              state = approved;
            }
            return {
              state: "approved",
              proposedName: state.proposedName,
              ...state.phase === "approved" && state.approvedName !== void 0 && {
                approvedName: state.approvedName
              },
              tokenGeneration: token.token_generation
            };
          }
          if (state?.phase === "approved") {
            const blocked = {
              version: 1,
              phase: "blocked",
              proposedName: state.proposedName,
              errorCode: "missing_token",
              updatedAt: this.#now()
            };
            await writeStateAtomic(this.#paths.statePath, blocked, this.#ancestorOptions);
            return statusFromState(blocked);
          }
          if (state && state.phase !== "pending")
            return statusFromState(state);
          if (!state) {
            const now = this.#now();
            state = {
              version: 1,
              phase: "pending",
              proposedName: this.#proposedName,
              requestSecret: this.#mintSecret(),
              createdAt: now,
              updatedAt: now
            };
            if (!TOKEN_RE2.test(state.requestSecret))
              throw new ClaustrumConsumerError("invalid-state", "invalid minted Claustrum enrollment secret");
            await writeStateAtomic(this.#paths.statePath, state, this.#ancestorOptions);
          }
          if (!state.requestId) {
            try {
              const requestSecretHash = createHash6("sha256").update(Buffer.from(state.requestSecret, "hex")).digest("hex");
              const proposed = await this.#client.enrollPropose({
                name: state.proposedName,
                requestSecretHash
              });
              state = {
                ...state,
                requestId: proposed.requestId,
                updatedAt: this.#now()
              };
              await writeStateAtomic(this.#paths.statePath, state, this.#ancestorOptions);
            } catch (error) {
              const refusal3 = classifyEnrollmentError(error);
              if (!refusal3)
                throw error;
              if (refusal3.disposition === "retry") {
                return {
                  state: "pending",
                  proposedName: state.proposedName,
                  retryCode: refusal3.code
                };
              }
              return this.#block(state, refusal3.code);
            }
          }
          const requestId = state.requestId;
          if (!requestId)
            return statusFromState(state);
          try {
            const outcome = await this.#client.enrollPoll({
              requestId,
              requestSecret: state.requestSecret
            });
            if (outcome.status === "pending")
              return statusFromState(state);
            if (outcome.status === "denied") {
              const denied = {
                version: 1,
                phase: "denied",
                proposedName: state.proposedName,
                updatedAt: this.#now()
              };
              await writeStateAtomic(this.#paths.statePath, denied, this.#ancestorOptions);
              return statusFromState(denied);
            }
            await ensurePrivateDirectory(dirname9(this.#paths.tokenPath));
            await refuseWritableAncestor2(dirname9(this.#paths.tokenPath), this.#ancestorOptions);
            await this.#writeTokenFile(this.#paths.tokenPath, {
              token: outcome.token,
              token_generation: outcome.tokenGeneration
            });
            const approved = {
              version: 1,
              phase: "approved",
              proposedName: state.proposedName,
              approvedName: outcome.name,
              tokenGeneration: outcome.tokenGeneration,
              updatedAt: this.#now()
            };
            await writeStateAtomic(this.#paths.statePath, approved, this.#ancestorOptions);
            return statusFromState(approved);
          } catch (error) {
            const refusal3 = classifyEnrollmentError(error);
            if (!refusal3)
              throw error;
            if (refusal3.disposition === "retry") {
              return {
                state: "pending",
                proposedName: state.proposedName,
                requestId,
                retryCode: refusal3.code
              };
            }
            return this.#block(state, refusal3.code);
          }
        } finally {
          await lock.release();
        }
      }
    };
  }
});

// ../core/dist/common-auth-embedded/claustrum/host-slot.js
function custodyPlaceholderKey(provider) {
  return `${CUSTODY_PLACEHOLDER_PREFIX}${provider}`;
}
function custodyPlaceholder(provider) {
  return {
    type: "oauth",
    access: "",
    refresh: custodyPlaceholderKey(provider),
    expires: 0
  };
}
function isRecord9(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isCustodyPlaceholderValue(value) {
  return typeof value === "string" && value.startsWith(CUSTODY_PLACEHOLDER_PREFIX);
}
function isCustodyPlaceholder(auth, provider) {
  if (!isRecord9(auth) || auth.type !== "oauth")
    return false;
  return auth.refresh === custodyPlaceholderKey(provider);
}
function classifyHostSlot(auth, provider) {
  if (isCustodyPlaceholder(auth, provider))
    return "placeholder";
  if (isRecord9(auth) && auth.type === "oauth" && typeof auth.refresh === "string" && auth.refresh.length > 0 && !isCustodyPlaceholderValue(auth.refresh))
    return "login";
  if (isRecord9(auth) && auth.type === "api" && typeof auth.key === "string" && auth.key.length > 0)
    return "login";
  return "empty";
}
function assertHostSlotMatchesMode(input) {
  const content = classifyHostSlot(input.auth, input.provider);
  if (input.mode === "custody" && content === "login")
    throw new ClaustrumConsumerError("host-slot-login", `${input.provider} has a host login while its accounts are vault-custodied; refusing to serve until one is removed`);
  if (input.mode === "local" && content === "placeholder")
    throw new ClaustrumConsumerError("host-slot-placeholder", `${input.provider} host slot holds the vault placeholder; sign in to use local accounts`);
  return content;
}
function assertNotCustodyPlaceholder(refreshToken, provider) {
  if (isCustodyPlaceholderValue(refreshToken))
    throw new ClaustrumConsumerError("placeholder-refresh", `${provider} credentials are vault-custodied; local token refresh is forbidden`);
}
var CUSTODY_PLACEHOLDER_PREFIX;
var init_host_slot = __esm({
  "../core/dist/common-auth-embedded/claustrum/host-slot.js"() {
    "use strict";
    init_errors3();
    CUSTODY_PLACEHOLDER_PREFIX = "claustrum-tombstone:v1:";
  }
});

// ../core/dist/common-auth-embedded/claustrum/custody.js
function isScopedCredentialRotation(served, current) {
  return current !== void 0 && current.credentialId === served.credentialId && current.accountIdentity === served.accountIdentity && current.recordVersion !== served.recordVersion;
}
function scopedRetryReason(served, current) {
  if (current === void 0)
    return "reauthorize-failed";
  if (current.credentialId !== served.credentialId)
    return "credential-changed";
  if (current.accountIdentity !== served.accountIdentity)
    return "account-changed";
  if (current.recordVersion === served.recordVersion)
    return "version-unchanged";
  return "rotated";
}
function decideScopedRetryAfter401(site, served, current, logger = defaultLogger) {
  const retry = isScopedCredentialRotation(served, current);
  logger.debug("scoped 401 re-authorized", {
    site,
    credentialId: served.credentialId,
    servedVersion: served.recordVersion,
    currentVersion: current?.recordVersion ?? null,
    retry,
    reason: scopedRetryReason(served, current)
  });
  return retry;
}
function invalidMaterial() {
  return new ClaustrumConsumerError("invalid-material", "Claustrum returned invalid credential material");
}
function accessTokenFromMaterial(material) {
  let access = material.trim();
  if (access.startsWith("{")) {
    let parsed;
    try {
      parsed = JSON.parse(access);
    } catch {
      throw invalidMaterial();
    }
    if (!parsed || typeof parsed !== "object")
      throw invalidMaterial();
    const record2 = parsed;
    const value = record2.access_token ?? record2.access;
    access = typeof value === "string" ? value : "";
  }
  if (!/^[\x21-\x7e]+$/.test(access) || access.startsWith(CUSTODY_PLACEHOLDER_PREFIX)) {
    throw invalidMaterial();
  }
  return access;
}
function credentialTypeOf(row, family) {
  if (!row.operations.includes("read"))
    return void 0;
  if (!row.categories.includes(family.category))
    return void 0;
  if (row.credentialType === "oauth")
    return row.refreshAdapter === family.refreshAdapter ? "oauth" : void 0;
  if (row.credentialType === "api_key" && family.apiKeys)
    return row.refreshAdapter === void 0 ? "api_key" : void 0;
  return void 0;
}
var defaultLogger, SERVING_MARGIN_MS, ClaustrumScopedCustody;
var init_custody = __esm({
  "../core/dist/common-auth-embedded/claustrum/custody.js"() {
    "use strict";
    init_dist2();
    init_logger();
    init_enrollment2();
    init_errors3();
    init_host_slot();
    defaultLogger = createLogger2("claustrum");
    SERVING_MARGIN_MS = 3e5;
    ClaustrumScopedCustody = class {
      #client;
      #readToken;
      #now;
      #family;
      #parseIdentity;
      #requireAssertion;
      #logger;
      #provenance = /* @__PURE__ */ new WeakMap();
      #reports = /* @__PURE__ */ new WeakMap();
      #closed = false;
      constructor(options) {
        const tokenPath = options.tokenPath;
        if (options.readToken) {
          this.#readToken = options.readToken;
        } else if (tokenPath) {
          this.#readToken = () => readClaustrumEnrollmentToken(tokenPath);
        } else {
          throw new ClaustrumConsumerError("not-enrolled", "Claustrum enrollment token path is required");
        }
        this.#client = options.client;
        this.#family = options.family;
        this.#parseIdentity = options.parseIdentity;
        this.#requireAssertion = options.requireAssertion ?? false;
        this.#now = options.now ?? Date.now;
        this.#logger = options.logger ?? defaultLogger;
      }
      #check(signal) {
        if (this.#closed)
          throw new ClaustrumConsumerError("closed", "Claustrum scoped custody is closed");
        signal?.throwIfAborted();
      }
      async #token(signal) {
        this.#check(signal);
        const value = await this.#readToken();
        this.#check(signal);
        if (!/^[0-9a-f]{64}$/.test(value.token) || !Number.isSafeInteger(value.token_generation) || value.token_generation < 1) {
          throw new ClaustrumConsumerError("invalid-token", "Invalid Claustrum enrollment token");
        }
        return value.token;
      }
      async #call(operation, signal) {
        this.#check(signal);
        let result;
        let removeAbortListener;
        try {
          const pending = operation();
          result = signal ? await Promise.race([
            pending,
            new Promise((_resolve, reject) => {
              const abort = () => reject(signal.reason);
              signal.addEventListener("abort", abort, { once: true });
              removeAbortListener = () => signal.removeEventListener("abort", abort);
              if (signal.aborted)
                abort();
            })
          ]) : await pending;
        } catch (error) {
          this.#check(signal);
          if (error instanceof ClaustrumCredentialError)
            throw error;
          throw new ClaustrumConsumerError("unavailable", "Claustrum scoped operation unavailable");
        } finally {
          removeAbortListener?.();
        }
        this.#check(signal);
        return result;
      }
      /**
       * List this consumer's credentials. A record that cannot be used is skipped
       * and warned about rather than failing the whole list, so one bad record
       * never hides every other account. Records outside the family are not
       * skipped records: they simply are not this consumer's.
       */
      async discover(signal) {
        const token = await this.#token(signal);
        const inventory = await this.#call(() => this.#client.listScoped(token), signal);
        const skipped = [];
        const candidates = [];
        const counts = /* @__PURE__ */ new Map();
        for (const row of inventory.rows) {
          const type = credentialTypeOf(row, this.#family);
          if (!type)
            continue;
          candidates.push({ row, type });
          counts.set(row.id, (counts.get(row.id) ?? 0) + 1);
        }
        const credentials = [];
        for (const { row, type } of candidates) {
          let reason;
          if (!row.id.trim())
            reason = "empty credential id";
          else if ((counts.get(row.id) ?? 0) > 1)
            reason = "duplicate credential id";
          else if (row.accountId !== void 0 && !row.accountId.trim())
            reason = "blank account identity";
          else if (!row.state.trim())
            reason = "empty state";
          if (reason) {
            skipped.push({ ...row.id.trim() && { credentialId: row.id }, reason });
            continue;
          }
          credentials.push(Object.freeze({
            credentialId: row.id,
            credentialType: type,
            ...row.accountId !== void 0 && {
              accountIdentity: row.accountId
            },
            state: row.state,
            ...row.email !== void 0 && { email: row.email },
            ...row.orgName !== void 0 && { orgName: row.orgName }
          }));
        }
        for (const record2 of skipped)
          this.#logger.warn("skipped malformed vault record", record2);
        return {
          view: inventory.view,
          credentials: Object.freeze(credentials),
          skipped: Object.freeze(skipped)
        };
      }
      /**
       * Fetch the credential for one physical send and wrap it in a fresh receipt.
       * The vault's served identity (or, without one, the plugin's parse of the
       * token) must equal the roster's when both are present. Without
       * `requireAssertion`, absence on either side proves nothing and does not
       * refuse; the receipt records what the vault asserted separately from what
       * the roster expected. With it, a reply that does not itself name the
       * credential id and the expected account is refused.
       */
      async authorize(identity, signal) {
        if (!identity.credentialId)
          throw new ClaustrumConsumerError("route-unavailable", "Claustrum dispatch requires a credential id");
        const { credentialId, credentialType, accountIdentity } = identity;
        if (this.#requireAssertion && accountIdentity === void 0)
          throw new ClaustrumConsumerError("identity-unasserted", "Claustrum dispatch requires a known account identity");
        const token = await this.#token(signal);
        const served = await this.#call(() => this.#client.getScoped({
          credentialId,
          enrollmentToken: token,
          ...credentialType === "oauth" && { minTtlMs: SERVING_MARGIN_MS }
        }), signal);
        if (served.credentialId !== void 0 && served.credentialId !== credentialId) {
          throw new ClaustrumConsumerError("identity-changed", "Claustrum served credential identity changed");
        }
        const expiresAtMs = served.expiresAtMs;
        if (!Number.isSafeInteger(served.recordVersion) || served.recordVersion < 0 || expiresAtMs === null && credentialType === "oauth" || expiresAtMs !== null && (!Number.isFinite(expiresAtMs) || expiresAtMs - this.#now() < SERVING_MARGIN_MS)) {
          throw new ClaustrumConsumerError("insufficient-validity", "Claustrum served credential has insufficient validity");
        }
        const accessToken = accessTokenFromMaterial(served.material);
        const assertedIdentity = served.accountId?.trim() ? served.accountId : void 0;
        if (this.#requireAssertion && (served.credentialId === void 0 || assertedIdentity === void 0))
          throw new ClaustrumConsumerError("identity-unasserted", "Claustrum served credential did not assert its identity");
        const parsedIdentity = assertedIdentity === void 0 ? this.#parseIdentity?.(accessToken) : void 0;
        const servedIdentity = assertedIdentity ?? parsedIdentity;
        if (accountIdentity !== void 0 && servedIdentity !== void 0 && servedIdentity !== accountIdentity) {
          throw new ClaustrumConsumerError("identity-changed", "Claustrum served credential identity changed");
        }
        const resolvedIdentity = servedIdentity ?? accountIdentity;
        const source = assertedIdentity !== void 0 ? "asserted" : parsedIdentity !== void 0 ? "parsed" : accountIdentity !== void 0 ? "expected" : "none";
        const attempt = Object.freeze(Object.defineProperty({
          credentialId,
          credentialType,
          ...resolvedIdentity !== void 0 && {
            accountIdentity: resolvedIdentity
          },
          accountIdentitySource: source,
          ...accountIdentity !== void 0 && {
            expectedAccountIdentity: accountIdentity
          },
          ...served.credentialId !== void 0 && {
            assertedCredentialId: served.credentialId
          },
          ...assertedIdentity !== void 0 && {
            assertedAccountIdentity: assertedIdentity
          },
          ...served.projectId !== void 0 && {
            projectId: served.projectId
          },
          recordVersion: served.recordVersion,
          expiresAtMs
        }, "accessToken", { value: accessToken, enumerable: false }));
        this.#provenance.set(attempt, token);
        return attempt;
      }
      /**
       * Report that a send this consumer actually made was rejected. Only a 401
       * is reported (the vault refuses 429, 402 and 5xx reports), addressed by
       * credential id with the exact record version that send was served, and
       * signed with the enrollment token that authorized it. A receipt this
       * custody did not issue is refused rather than reported.
       */
      async reportFailure(attempt, status, reporterSource) {
        if (status !== 401)
          return;
        this.#check();
        const token = this.#provenance.get(attempt);
        if (!token)
          throw new ClaustrumConsumerError("no-receipt", "Claustrum failure report requires an original dispatch receipt");
        const pending = this.#reports.get(attempt);
        if (pending)
          return pending;
        const report = this.#call(() => this.#client.reportAuthFailureScoped({
          credentialId: attempt.credentialId,
          enrollmentToken: token,
          providerStatus: 401,
          recordVersion: attempt.recordVersion,
          reporterSource
        }));
        this.#reports.set(attempt, report);
        try {
          await report;
          this.#logger.debug("scoped 401 reported", {
            credentialId: attempt.credentialId,
            recordVersion: attempt.recordVersion,
            reporterSource
          });
        } catch (error) {
          this.#reports.delete(attempt);
          throw error;
        }
      }
      close() {
        if (this.#closed)
          return;
        this.#closed = true;
        this.#client.close();
      }
    };
  }
});

// ../core/dist/common-auth-embedded/claustrum/interlock.js
function matches(entry, credentialId, accountIdentity) {
  if (entry.accountIdentity !== void 0 && accountIdentity !== void 0)
    return entry.accountIdentity === accountIdentity;
  return entry.credentialId === credentialId;
}
function isDeclined(entries, credentialId, accountIdentity) {
  return entries.some((entry) => matches(entry, credentialId, accountIdentity));
}
function declineAccount(entries, credentialId, accountIdentity) {
  const entry = {
    credentialId,
    ...accountIdentity !== void 0 && { accountIdentity }
  };
  return [
    ...entries.filter((existing) => existing.credentialId !== credentialId || existing.accountIdentity !== accountIdentity),
    entry
  ];
}
function acceptAccount(entries, credentialIds, accountIdentity) {
  return entries.filter((entry) => !credentialIds.some((id) => matches(entry, id, accountIdentity)));
}
var init_interlock = __esm({
  "../core/dist/common-auth-embedded/claustrum/interlock.js"() {
    "use strict";
  }
});

// ../core/dist/common-auth-embedded/claustrum/roster.js
import { createHash as createHash7 } from "node:crypto";
import { readFile as readFile8 } from "node:fs/promises";
function hash(value) {
  return createHash7("sha256").update(value).digest("hex");
}
function defaultLabel(credential) {
  const parts = credential.credentialId.split(":");
  const label = parts.length >= 3 ? parts.slice(2).join(":").trim() : void 0;
  return label || credential.email || credential.credentialId;
}
function groupKey(member) {
  return member.identity !== void 0 ? `identity:${member.identity}` : `credential:${member.credential.credentialId}`;
}
function memberIds(row) {
  return [row.credentialId, ...row.aliases ?? []];
}
function projectVaultRoster(previous, inventory, options = {}) {
  const now = options.now ?? Date.now();
  const prefix = options.routePrefix ?? DEFAULT_ROUTE_PREFIX;
  const reserved = options.reservedRouteIds ?? /* @__PURE__ */ new Set();
  const previousRows = previous?.rows ?? [];
  const declined = [...previous?.declined ?? []];
  const complete = inventory.skipped.length === 0;
  const listed = new Set(inventory.credentials.map((credential) => credential.credentialId));
  const rejectedIds = new Set(inventory.skipped.flatMap((record2) => record2.credentialId === void 0 ? [] : [record2.credentialId]));
  const unrecoverable = inventory.skipped.some((record2) => record2.credentialId === void 0);
  const unaccounted = (id) => !listed.has(id) && (rejectedIds.has(id) || unrecoverable);
  const lastKnown = /* @__PURE__ */ new Map();
  for (const row of previousRows) {
    if (row.accountIdentity === void 0)
      continue;
    for (const id of memberIds(row))
      if (!lastKnown.has(id))
        lastKnown.set(id, row.accountIdentity);
  }
  const groups = /* @__PURE__ */ new Map();
  for (const credential of inventory.credentials) {
    const member = credential.accountIdentity !== void 0 ? { credential, identity: credential.accountIdentity, claimed: true } : {
      credential,
      identity: lastKnown.get(credential.credentialId),
      claimed: false
    };
    const key = groupKey(member);
    const group = groups.get(key) ?? [];
    group.push(member);
    groups.set(key, group);
  }
  const used = /* @__PURE__ */ new Set();
  const taken = new Set(reserved);
  const projected2 = [];
  const byId = (left, right) => left.credential.credentialId.localeCompare(right.credential.credentialId);
  const sortedGroups = [...groups.values()].map((group) => group.toSorted(byId)).sort((left, right) => left[0] && right[0] ? byId(left[0], right[0]) : 0);
  for (const ordered of sortedGroups) {
    const identity = ordered[0]?.identity;
    const active2 = ordered.filter((entry) => entry.credential.state === "active");
    const usable = active2.length ? active2 : ordered;
    const claimed = usable.filter((entry) => entry.claimed);
    const choices = claimed.length ? claimed : usable;
    const members = new Set(ordered.map((entry) => entry.credential.credentialId));
    const bound = previousRows.find((row) => !used.has(row) && memberIds(row).some((id) => members.has(id)) && (row.accountIdentity === void 0 || row.accountIdentity === identity));
    const chosen = choices.find((entry) => entry.credential.credentialId === bound?.credentialId) ?? choices[0];
    if (!chosen)
      continue;
    const representative = chosen.credential;
    const existing = bound ?? (identity === void 0 ? void 0 : previousRows.find((row) => !used.has(row) && row.accountIdentity === identity));
    if (existing)
      used.add(existing);
    let routeId = existing?.routeId;
    if (!routeId || reserved.has(routeId)) {
      const base = `${prefix}${representative.credentialId}${identity === void 0 ? "" : `~${hash(identity).slice(0, 10)}`}`;
      routeId = base;
      for (let suffix = 2; taken.has(routeId); suffix++)
        routeId = `${base}~${suffix}`;
    }
    taken.add(routeId);
    const retained = existing ? memberIds(existing).filter(unaccounted) : [];
    const aliases = [
      .../* @__PURE__ */ new Set([
        ...ordered.map((entry) => entry.credential.credentialId),
        ...retained
      ])
    ].filter((id) => id !== representative.credentialId).sort((left, right) => left.localeCompare(right));
    const mapped = options.mapAccount?.(representative) ?? {};
    projected2.push({
      previousIndex: existing ? previousRows.indexOf(existing) : Infinity,
      row: {
        routeId,
        credentialId: representative.credentialId,
        credentialType: representative.credentialType,
        ...identity !== void 0 && { accountIdentity: identity },
        ...aliases.length && { aliases },
        state: representative.state,
        label: mapped.label?.trim() || defaultLabel(representative),
        ...representative.email !== void 0 && {
          email: representative.email
        },
        ...representative.orgName !== void 0 && {
          orgName: representative.orgName
        },
        enabled: ![representative.credentialId, ...aliases].some((id) => isDeclined(declined, id, identity)),
        addedAt: existing?.addedAt ?? now,
        ...existing?.quota !== void 0 && { quota: existing.quota },
        ...!chosen.claimed && identity !== void 0 && { unclaimed: true }
      }
    });
  }
  previousRows.forEach((row, previousIndex) => {
    if (used.has(row) || !memberIds(row).some(unaccounted))
      return;
    if (taken.has(row.routeId))
      return;
    const [credentialId, ...aliases] = memberIds(row).filter((id) => !listed.has(id));
    if (credentialId === void 0)
      return;
    taken.add(row.routeId);
    const { aliases: _previousAliases, ...rest } = row;
    projected2.push({
      previousIndex,
      row: {
        ...rest,
        credentialId,
        ...aliases.length && { aliases },
        stale: true
      }
    });
  });
  projected2.sort((left, right) => left.previousIndex === right.previousIndex ? left.row.credentialId.localeCompare(right.row.credentialId) : left.previousIndex - right.previousIndex);
  return {
    version: 1,
    view: inventory.view,
    complete,
    ...!complete && {
      rejected: inventory.skipped.map((record2) => ({
        ...record2.credentialId !== void 0 && {
          credentialId: record2.credentialId
        },
        reason: record2.reason
      }))
    },
    rows: projected2.map((entry) => entry.row),
    declined
  };
}
function vaultRoutingRows(roster) {
  return (roster?.rows ?? []).filter((row) => row.enabled && row.state === "active").map((row) => ({
    id: row.routeId,
    kind: row.credentialType === "oauth" ? "oauth" : "api-key",
    ...row.quota !== void 0 && { quota: row.quota }
  }));
}
function isRecord10(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function optionalString2(value) {
  return value === void 0 || typeof value === "string";
}
function decodeRow(value) {
  if (!isRecord10(value) || typeof value.routeId !== "string" || typeof value.credentialId !== "string" || value.credentialType !== "oauth" && value.credentialType !== "api_key" || typeof value.state !== "string" || typeof value.label !== "string" || typeof value.enabled !== "boolean" || typeof value.addedAt !== "number" || !optionalString2(value.accountIdentity) || !optionalString2(value.email) || !optionalString2(value.orgName) || value.aliases !== void 0 && (!Array.isArray(value.aliases) || !value.aliases.every((alias) => typeof alias === "string")) || value.quota !== void 0 && !isQuotaMap(value.quota) || value.stale !== void 0 && value.stale !== true || value.unclaimed !== void 0 && value.unclaimed !== true)
    return void 0;
  return value;
}
function decodeRejected(value) {
  if (!Array.isArray(value))
    return void 0;
  const records2 = [];
  for (const entry of value) {
    if (!isRecord10(entry) || !optionalString2(entry.credentialId) || typeof entry.reason !== "string" || !SKIPPED_REASONS.has(entry.reason))
      return void 0;
    records2.push(entry);
  }
  return records2;
}
function decodeRoster(value) {
  if (!isRecord10(value) || value.version !== 1 || !optionalString2(value.view) || !Array.isArray(value.rows) || !Array.isArray(value.declined) || value.complete !== void 0 && typeof value.complete !== "boolean" || value.rejected !== void 0 && !decodeRejected(value.rejected))
    throw new ClaustrumConsumerError("invalid-state", "Claustrum roster file is not valid");
  const rows = [];
  for (const entry of value.rows) {
    const row = decodeRow(entry);
    if (!row)
      throw new ClaustrumConsumerError("invalid-state", "Claustrum roster file is not valid");
    rows.push(row);
  }
  const declined = [];
  for (const entry of value.declined) {
    if (!isRecord10(entry) || typeof entry.credentialId !== "string" || !optionalString2(entry.accountIdentity))
      throw new ClaustrumConsumerError("invalid-state", "Claustrum roster file is not valid");
    declined.push(entry);
  }
  const rejected = decodeRejected(value.rejected);
  return {
    version: 1,
    ...typeof value.view === "string" && { view: value.view },
    // A file written before completeness was recorded came from a reply
    // that was used whole, so it reads as complete.
    complete: value.complete !== false,
    ...rejected && { rejected },
    rows,
    declined
  };
}
async function readVaultRoster(path2) {
  let text2;
  try {
    text2 = await readFile8(path2, "utf8");
  } catch (error) {
    if (error.code === "ENOENT")
      return void 0;
    throw error;
  }
  let value;
  try {
    value = JSON.parse(text2);
  } catch {
    throw new ClaustrumConsumerError("invalid-state", "Claustrum roster file is not valid");
  }
  return decodeRoster(value);
}
async function mutateVaultRoster(path2, change, options = {}) {
  return withLock(path2, WRITE_LOCK, async (lock) => {
    const current = await readVaultRoster(path2);
    const { next, result } = await change(current, {
      assertOwned: () => lock.assertOwned()
    });
    if (next) {
      await lock.assertOwned();
      await writeJsonAtomic2(path2, next, {
        beforeRename: async () => {
          await options.beforePublish?.();
          await lock.assertOwned();
        }
      });
    }
    return result;
  });
}
function declineVaultRoute(path2, routeId) {
  return mutateVaultRoster(path2, (current) => {
    const row = current?.rows.find((entry) => entry.routeId === routeId);
    if (!current || !row)
      throw new ClaustrumConsumerError("route-unavailable", "Claustrum route is not in the roster");
    const declined = declineAccount(current.declined, row.credentialId, row.accountIdentity);
    return {
      next: {
        ...current,
        declined,
        rows: current.rows.map((entry) => entry === row ? { ...entry, enabled: false } : entry)
      },
      result: void 0
    };
  });
}
function acceptVaultRoute(path2, routeId) {
  return mutateVaultRoster(path2, (current) => {
    const row = current?.rows.find((entry) => entry.routeId === routeId);
    if (!current || !row)
      throw new ClaustrumConsumerError("route-unavailable", "Claustrum route is not in the roster");
    return {
      next: {
        ...current,
        declined: acceptAccount(current.declined, memberIds(row), row.accountIdentity),
        rows: current.rows.map((entry) => entry === row ? { ...entry, enabled: true } : entry)
      },
      result: void 0
    };
  });
}
function receiptFence(row, receipt2) {
  if (!memberIds(row).includes(receipt2.credentialId))
    return "refuse";
  if (row.unclaimed && (receipt2.accountIdentitySource === "expected" || receipt2.accountIdentitySource === "none"))
    return "refuse";
  if (row.accountIdentity === receipt2.accountIdentity)
    return "hold";
  if (row.accountIdentity === void 0 && receipt2.expectedAccountIdentity === void 0 && receipt2.accountIdentity !== void 0 && (receipt2.accountIdentitySource === "asserted" || receipt2.accountIdentitySource === "parsed") && memberIds(row).length === 1)
    return "bind";
  return "refuse";
}
function recordVaultQuota(path2, input) {
  return mutateVaultRoster(path2, (current) => {
    const row = current?.rows.find((entry) => entry.routeId === input.routeId);
    const fence = !current || !row ? "refuse" : receiptFence(row, input);
    if (!current || !row || fence === "refuse")
      return { result: false };
    const quota = mergeQuotaObservation(row.quota, input.observation);
    const bound = fence === "bind" ? { accountIdentity: input.accountIdentity, unclaimed: true } : {};
    return {
      next: {
        ...current,
        rows: current.rows.map((entry) => entry === row ? { ...entry, ...bound, quota } : entry)
      },
      result: true
    };
  });
}
async function refreshVaultRoster(options) {
  options.signal?.throwIfAborted();
  const active2 = async () => await options.isActive?.() ?? true;
  if (!await active2())
    return void 0;
  const lease = await acquireRefreshFileLock({
    ...DISCOVERY_LEASE,
    path: options.path,
    renew: true
  });
  if (!lease) {
    const persisted = await readVaultRoster(options.path);
    options.signal?.throwIfAborted();
    if (!persisted?.view)
      throw new ClaustrumConsumerError("roster-busy", "Claustrum account discovery is already in progress");
    return persisted;
  }
  try {
    const inventory = await options.custody.discover(options.signal);
    options.signal?.throwIfAborted();
    return await mutateVaultRoster(options.path, async (current) => {
      if (!await active2())
        return { result: void 0 };
      options.signal?.throwIfAborted();
      await lease.assertOwned();
      const projection = typeof options.projection === "function" ? options.projection() : options.projection;
      const next = projectVaultRoster(current, inventory, projection);
      const changed = JSON.stringify(current) !== JSON.stringify(next);
      return { ...changed && { next }, result: next };
    });
  } finally {
    await lease.release();
  }
}
function resolveVaultPrimary(input) {
  const { inventory, previous } = input;
  const unavailable = (reason) => ({
    status: "unavailable",
    reason,
    ...previous && { lastVerified: previous }
  });
  const record2 = inventory.credentials.find((credential) => credential.credentialId === input.primaryCredentialId);
  if (!record2) {
    if (inventory.skipped.some((skipped) => skipped.credentialId === input.primaryCredentialId))
      return unavailable("malformed");
    const incomplete = input.complete === false || inventory.skipped.some((skipped) => skipped.credentialId === void 0);
    return incomplete ? unavailable("incomplete") : { status: "absent" };
  }
  const identity = record2.accountIdentity;
  if (identity === void 0)
    return unavailable("unclaimed");
  if (input.expectedAccountIdentity !== void 0 && input.expectedAccountIdentity !== identity)
    return unavailable("identity-changed");
  const representative = record2.state === "active" ? record2 : inventory.credentials.filter((credential) => credential.accountIdentity === identity && credential.state === "active").toSorted((left, right) => left.credentialId.localeCompare(right.credentialId))[0] ?? record2;
  const binding = {
    routeId: input.routeId,
    credentialId: representative.credentialId,
    accountIdentity: identity,
    view: inventory.view
  };
  return {
    status: "ready",
    binding,
    ...previous && previous.accountIdentity !== identity && { replaced: previous }
  };
}
var DEFAULT_ROUTE_PREFIX, SKIPPED_REASONS, WRITE_LOCK, DISCOVERY_LEASE;
var init_roster = __esm({
  "../core/dist/common-auth-embedded/claustrum/roster.js"() {
    "use strict";
    init_fs();
    init_quota();
    init_errors3();
    init_interlock();
    DEFAULT_ROUTE_PREFIX = "vault:";
    SKIPPED_REASONS = /* @__PURE__ */ new Set([
      "empty credential id",
      "duplicate credential id",
      "blank account identity",
      "empty state"
    ]);
    WRITE_LOCK = {
      name: "claustrum-roster-write",
      ttlMs: 1e4,
      timeoutMs: 5e3
    };
    DISCOVERY_LEASE = { name: "claustrum-roster", ttlMs: 3e4 };
  }
});

// ../core/dist/common-auth-embedded/claustrum/consumer.js
var ClaustrumConsumer;
var init_consumer = __esm({
  "../core/dist/common-auth-embedded/claustrum/consumer.js"() {
    "use strict";
    init_logger();
    init_any_signal();
    init_custody();
    init_errors3();
    init_roster();
    ClaustrumConsumer = class {
      #options;
      #shutdown = new AbortController();
      #logger;
      #custody;
      #connecting;
      #refreshing;
      #roster;
      #timer;
      #started = false;
      constructor(options) {
        this.#options = options;
        this.#logger = options.logger ?? createLogger2("claustrum");
      }
      #assertOpen(signal) {
        this.#shutdown.signal.throwIfAborted();
        signal?.throwIfAborted();
      }
      async #active() {
        return await this.#options.isCustodyActive?.() ?? true;
      }
      #wait(pending, signal) {
        const combined = combineAbortSignals([
          this.#shutdown.signal,
          ...signal ? [signal] : []
        ]);
        return new Promise((resolve7, reject) => {
          const cleanup2 = () => {
            combined.signal.removeEventListener("abort", abort);
            combined.dispose();
          };
          const abort = () => {
            cleanup2();
            reject(combined.signal.reason);
          };
          combined.signal.addEventListener("abort", abort, { once: true });
          pending.then((value) => {
            cleanup2();
            if (combined.signal.aborted)
              reject(combined.signal.reason);
            else
              resolve7(value);
          }, (error) => {
            cleanup2();
            reject(error);
          });
          if (combined.signal.aborted)
            abort();
        });
      }
      async #getCustody() {
        this.#assertOpen();
        if (this.#custody)
          return this.#custody;
        if (!this.#connecting) {
          this.#connecting = this.#options.connect().then((client) => {
            if (this.#shutdown.signal.aborted) {
              client.close();
              this.#assertOpen();
            }
            this.#custody = new ClaustrumScopedCustody({
              client,
              family: this.#options.family,
              tokenPath: this.#options.tokenPath,
              parseIdentity: this.#options.parseIdentity,
              requireAssertion: this.#options.requireAssertion,
              now: this.#options.now,
              logger: this.#logger
            });
            return this.#custody;
          }).finally(() => {
            this.#connecting = void 0;
          });
        }
        return this.#wait(this.#connecting);
      }
      /** The last committed roster this instance saw, without any I/O. */
      snapshot() {
        return this.#roster;
      }
      /** Rows for `/routing`, from the last committed roster. */
      routingRows() {
        return vaultRoutingRows(this.#roster);
      }
      refresh() {
        this.#assertOpen();
        if (this.#refreshing)
          return this.#refreshing;
        this.#refreshing = (async () => {
          if (!await this.#active()) {
            this.#roster = void 0;
            this.#custody?.close();
            this.#custody = void 0;
            return void 0;
          }
          const custody = await this.#getCustody();
          const roster = await refreshVaultRoster({
            path: this.#options.rosterPath,
            custody,
            isActive: () => this.#active(),
            signal: this.#shutdown.signal,
            projection: () => ({
              reservedRouteIds: new Set(this.#options.reservedRouteIds?.() ?? []),
              routePrefix: this.#options.routePrefix,
              mapAccount: this.#options.mapAccount,
              now: (this.#options.now ?? Date.now)()
            })
          });
          this.#assertOpen();
          const changed = roster?.view !== this.#roster?.view;
          this.#roster = roster;
          if (roster && changed)
            this.#options.onRoster?.(roster);
          return roster;
        })().finally(() => {
          this.#refreshing = void 0;
        });
        return this.#refreshing;
      }
      start() {
        if (this.#started)
          return;
        this.#assertOpen();
        this.#started = true;
        const tick = async () => {
          try {
            await this.refresh();
          } catch (error) {
            if (!this.#shutdown.signal.aborted)
              this.#options.onError?.(error);
          }
          if (this.#shutdown.signal.aborted)
            return;
          const delay = this.#options.pollIntervalMs ?? 5e3;
          if (delay <= 0)
            return;
          this.#timer = (this.#options.setTimeoutImpl ?? setTimeout)(() => {
            this.#timer = void 0;
            void tick();
          }, delay);
          this.#timer.unref?.();
        };
        void tick();
      }
      /**
       * Authorize one physical send on a vault route. The roster file is re-read
       * first, so a decline committed by another process applies before the next
       * poll, and a route whose credential or account changed is refused.
       */
      async authorize(routeId, signal) {
        this.#assertOpen(signal);
        const roster = this.#roster ?? await this.#wait(this.refresh(), signal);
        if (!roster || !await this.#active())
          throw new ClaustrumConsumerError("not-active", "Claustrum scoped custody is not active");
        const current = await readVaultRoster(this.#options.rosterPath);
        this.#assertOpen(signal);
        const observed = roster.rows.find((row) => row.routeId === routeId);
        const configured = current?.rows.find((row) => row.routeId === routeId);
        if (configured && !configured.enabled)
          throw new ClaustrumConsumerError("route-declined", "Claustrum route is disabled");
        if (!observed || !configured || configured.state !== "active" || configured.credentialId !== observed.credentialId || configured.accountIdentity !== observed.accountIdentity)
          throw new ClaustrumConsumerError("route-unavailable", "Claustrum route is disabled, removed or changed");
        const custody = await this.#wait(this.#getCustody(), signal);
        const combined = combineAbortSignals([
          this.#shutdown.signal,
          ...signal ? [signal] : []
        ]);
        try {
          return await custody.authorize({
            credentialId: configured.credentialId,
            credentialType: configured.credentialType,
            ...configured.accountIdentity !== void 0 && {
              accountIdentity: configured.accountIdentity
            }
          }, combined.signal);
        } finally {
          combined.dispose();
        }
      }
      async reportFailure(attempt, status, source) {
        this.#assertOpen();
        if (!this.#custody)
          throw new ClaustrumConsumerError("no-receipt", "Claustrum dispatch receipt has no active owner");
        await this.#custody.reportFailure(attempt, status, source);
      }
      /**
       * Send on a vault route. `dispatch` builds and sends the request with the
       * receipt's token and may be called twice, so it must be able to rebuild
       * its body. A 401 is retried once, and only when the vault now serves a new
       * record version of the same credential and account; the final 401 is
       * reported against the version that send actually used. Each call to
       * `dispatch` gets its own receipt.
       */
      async send(routeId, dispatch, options) {
        const signal = options.signal;
        let served = await this.authorize(routeId, signal);
        let response = await dispatch(served, signal);
        if (response.status === 401 && !signal?.aborted) {
          let current;
          try {
            current = await this.authorize(routeId, signal);
          } catch {
          }
          if (decideScopedRetryAfter401(options.site, served, current, this.#logger)) {
            await response.body?.cancel().catch(() => {
            });
            served = current;
            response = await dispatch(current, signal);
          }
        }
        if (response.status === 401) {
          await this.reportFailure(served, 401, options.reporterSource ?? "direct").catch((error) => this.#options.onError?.(error));
          Promise.resolve().then(() => this.refresh()).catch((error) => {
            if (!this.#shutdown.signal.aborted)
              this.#options.onError?.(error);
          });
        }
        return response;
      }
      /** Decline a vault account: it stays listed and never routes until accepted. */
      async decline(routeId) {
        this.#assertOpen();
        await declineVaultRoute(this.#options.rosterPath, routeId);
        this.#roster = await readVaultRoster(this.#options.rosterPath);
      }
      async accept(routeId) {
        this.#assertOpen();
        await acceptVaultRoute(this.#options.rosterPath, routeId);
        this.#roster = await readVaultRoster(this.#options.rosterPath);
      }
      /**
       * Store a quota or profile observation for a vault route. The receipt the
       * reading was taken with is required: the observation lands only while the
       * route still holds the credential and account that receipt was served for
       * (see `recordVaultQuota`), so a reading for a replaced account is dropped.
       */
      async recordQuota(routeId, observation, attempt) {
        this.#assertOpen();
        const kept = await recordVaultQuota(this.#options.rosterPath, {
          routeId,
          observation,
          credentialId: attempt.credentialId,
          accountIdentitySource: attempt.accountIdentitySource,
          ...attempt.accountIdentity !== void 0 && {
            accountIdentity: attempt.accountIdentity
          },
          ...attempt.expectedAccountIdentity !== void 0 && {
            expectedAccountIdentity: attempt.expectedAccountIdentity
          }
        });
        if (kept)
          this.#roster = await readVaultRoster(this.#options.rosterPath);
        return kept;
      }
      close() {
        if (this.#shutdown.signal.aborted)
          return;
        this.#shutdown.abort(new ClaustrumConsumerError("closed", "Claustrum consumer is closed"));
        if (this.#timer)
          (this.#options.clearTimeoutImpl ?? clearTimeout)(this.#timer);
        this.#timer = void 0;
        this.#custody?.close();
        this.#roster = void 0;
      }
    };
  }
});

// ../core/dist/common-auth-embedded/claustrum/index.js
var claustrum_exports = {};
__export(claustrum_exports, {
  CUSTODY_PLACEHOLDER_PREFIX: () => CUSTODY_PLACEHOLDER_PREFIX,
  ClaustrumConsumer: () => ClaustrumConsumer,
  ClaustrumConsumerError: () => ClaustrumConsumerError,
  ClaustrumCredentialError: () => ClaustrumCredentialError,
  ClaustrumEnrollmentManager: () => ClaustrumEnrollmentManager,
  ClaustrumScopedCustody: () => ClaustrumScopedCustody,
  DEFAULT_ROUTE_PREFIX: () => DEFAULT_ROUTE_PREFIX,
  RETRYABLE_ENROLLMENT_CODES: () => RETRYABLE_ENROLLMENT_CODES,
  SERVING_MARGIN_MS: () => SERVING_MARGIN_MS,
  TERMINAL_ENROLLMENT_CODES: () => TERMINAL_ENROLLMENT_CODES,
  acceptAccount: () => acceptAccount,
  acceptVaultRoute: () => acceptVaultRoute,
  assertHostSlotMatchesMode: () => assertHostSlotMatchesMode,
  assertNotCustodyPlaceholder: () => assertNotCustodyPlaceholder,
  classifyEnrollmentError: () => classifyEnrollmentError,
  classifyHostSlot: () => classifyHostSlot,
  connectClaustrumEnrollmentClient: () => connectClaustrumEnrollmentClient,
  connectClaustrumScopedClient: () => connectClaustrumScopedClient,
  custodyPlaceholder: () => custodyPlaceholder,
  custodyPlaceholderKey: () => custodyPlaceholderKey,
  decideScopedRetryAfter401: () => decideScopedRetryAfter401,
  declineAccount: () => declineAccount,
  declineVaultRoute: () => declineVaultRoute,
  disconnectClaustrumEnrollment: () => disconnectClaustrumEnrollment,
  enrollmentAuthority: () => enrollmentAuthority,
  enrollmentName: () => enrollmentName,
  getClaustrumEnrollmentPaths: () => getClaustrumEnrollmentPaths,
  hostEnrollmentPaths: () => hostEnrollmentPaths,
  isCustodyPlaceholder: () => isCustodyPlaceholder,
  isCustodyPlaceholderValue: () => isCustodyPlaceholderValue,
  isDeclined: () => isDeclined,
  isScopedCredentialRotation: () => isScopedCredentialRotation,
  mutateVaultRoster: () => mutateVaultRoster,
  projectVaultRoster: () => projectVaultRoster,
  readClaustrumEnrollmentStatus: () => readClaustrumEnrollmentStatus,
  readClaustrumEnrollmentToken: () => readClaustrumEnrollmentToken,
  readVaultRoster: () => readVaultRoster,
  recordVaultQuota: () => recordVaultQuota,
  refreshVaultRoster: () => refreshVaultRoster,
  resetClaustrumEnrollmentState: () => resetClaustrumEnrollmentState,
  resolveVaultPrimary: () => resolveVaultPrimary,
  vaultRoutingRows: () => vaultRoutingRows
});
function connectClaustrumScopedClient(options) {
  return ClaustrumClient.connect(options);
}
var init_claustrum = __esm({
  "../core/dist/common-auth-embedded/claustrum/index.js"() {
    "use strict";
    init_dist2();
    init_dist2();
    init_consumer();
    init_custody();
    init_enrollment2();
    init_errors3();
    init_host_slot();
    init_interlock();
    init_roster();
  }
});

// ../core/dist/common-auth-embedded/pi-slot/lock.js
import { rmdirSync, statSync as statSync3 } from "node:fs";
import { mkdir as mkdir10, rmdir, stat as stat6, utimes } from "node:fs/promises";
function sameDirectory(observed, identity) {
  return observed.dev === identity.dev && observed.ino === identity.ino;
}
function errorCode2(error) {
  return typeof error === "object" && error !== null && "code" in error ? error.code : void 0;
}
function held() {
  return Object.assign(new Error("Pi auth lock held"), { code: "ELOCKED" });
}
async function remove(path2) {
  try {
    await rmdir(path2);
  } catch (error) {
    if (errorCode2(error) !== "ENOENT")
      throw error;
  }
}
async function acquire(path2, stale) {
  try {
    await mkdir10(path2);
  } catch (error) {
    if (errorCode2(error) !== "EEXIST")
      throw error;
    if (stale <= 0)
      throw held();
    let mtime;
    try {
      mtime = (await stat6(path2)).mtime.getTime();
    } catch (error2) {
      if (errorCode2(error2) === "ENOENT")
        return acquire(path2, 0);
      throw error2;
    }
    if (!(mtime < Date.now() - stale))
      throw held();
    await remove(path2);
    return acquire(path2, 0);
  }
  try {
    if (!precision) {
      const probe = new Date(Math.ceil(Date.now() / 1e3) * 1e3 + 5);
      await utimes(path2, probe, probe);
    }
    const observed = await stat6(path2);
    const mtime = observed.mtime.getTime();
    precision ??= mtime % 1e3 === 0 ? "s" : "ms";
    return { dev: observed.dev, ino: observed.ino, mtime };
  } catch (error) {
    await remove(path2).catch(() => {
    });
    throw error;
  }
}
async function acquirePiLock(authPath, onCompromised, onRenew) {
  const path2 = `${authPath}.lock`;
  const identity = await acquire(path2, STALE);
  let mtime = identity.mtime;
  let lastUpdate = Date.now();
  let released = false;
  let timer;
  active.set(path2, { ...identity, renewedAt: lastUpdate });
  function compromise() {
    released = true;
    if (timer)
      clearTimeout(timer);
    active.delete(path2);
    onCompromised();
  }
  function assertFresh() {
    if (!released && lastUpdate + RENEWAL_STALE < Date.now())
      compromise();
  }
  function schedule(delay = UPDATE) {
    if (released)
      return;
    timer = setTimeout(() => {
      void update();
    }, delay);
    timer.unref();
  }
  function retry(error) {
    if (released)
      return;
    if (errorCode2(error) === "ENOENT" || lastUpdate + RENEWAL_STALE < Date.now())
      compromise();
    else
      schedule(1e3);
  }
  async function update() {
    assertFresh();
    if (released)
      return;
    let observed;
    try {
      observed = await stat6(path2);
    } catch (error) {
      retry(error);
      return;
    }
    assertFresh();
    if (released)
      return;
    if (!sameDirectory(observed, identity) || observed.mtime.getTime() !== mtime) {
      compromise();
      return;
    }
    const next = new Date(precision === "s" ? Math.ceil(Date.now() / 1e3) * 1e3 : Date.now());
    try {
      await utimes(path2, next, next);
    } catch (error) {
      retry(error);
      return;
    }
    if (released)
      return;
    mtime = next.getTime();
    lastUpdate = Date.now();
    active.set(path2, { ...identity, mtime, renewedAt: lastUpdate });
    schedule();
  }
  onRenew?.(async () => {
    if (timer)
      clearTimeout(timer);
    await update();
  });
  schedule();
  return {
    assertFresh,
    async release() {
      if (released)
        return;
      released = true;
      if (timer)
        clearTimeout(timer);
      active.delete(path2);
      const expired = () => lastUpdate + RENEWAL_STALE < Date.now();
      if (expired()) {
        compromise();
        return;
      }
      let observed;
      try {
        observed = await stat6(path2);
      } catch (error) {
        if (errorCode2(error) !== "ENOENT")
          throw error;
        compromise();
        return;
      }
      if (expired() || !sameDirectory(observed, identity) || mtime !== observed.mtime.getTime()) {
        compromise();
        return;
      }
      await remove(path2);
    }
  };
}
var STALE, RENEWAL_STALE, UPDATE, precision, active;
var init_lock = __esm({
  "../core/dist/common-auth-embedded/pi-slot/lock.js"() {
    "use strict";
    STALE = 3e4;
    RENEWAL_STALE = 1e4;
    UPDATE = 3e3;
    active = /* @__PURE__ */ new Map();
    process.once("exit", () => {
      for (const [path2, identity] of active) {
        try {
          if (identity.renewedAt + RENEWAL_STALE < Date.now())
            continue;
          const observed = statSync3(path2);
          if (sameDirectory(observed, identity) && observed.mtime.getTime() === identity.mtime)
            rmdirSync(path2);
        } catch {
        }
      }
    });
  }
});

// ../core/dist/common-auth-embedded/pi-slot/slot.js
import { createHash as createHash8 } from "node:crypto";
import { constants as constants2 } from "node:fs";
import { lstat as lstat2, mkdir as mkdir11, open as open7, unlink as unlink7 } from "node:fs/promises";
import { dirname as dirname10, resolve as resolve4 } from "node:path";
import { setTimeout as sleep2 } from "node:timers/promises";
function rootSpans(text2) {
  let i = text2.indexOf("{") + 1;
  const root = { offset: i - 1, children: [] };
  const whitespace = () => {
    while (/\s/.test(text2[i] ?? "") && i < text2.length)
      i++;
  };
  const stringEnd = () => {
    i++;
    while (i < text2.length) {
      if (text2[i++] === '"')
        return;
      if (text2[i - 1] === "\\")
        i++;
    }
  };
  whitespace();
  while (text2[i] !== "}") {
    const start = i;
    stringEnd();
    const key = JSON.parse(text2.slice(start, i));
    whitespace();
    i++;
    whitespace();
    const offset = i;
    let depth = 0;
    while (i < text2.length) {
      const char = text2[i];
      if (char === '"') {
        stringEnd();
        continue;
      }
      if (char === "{" || char === "[")
        depth++;
      if (char === "}" || char === "]") {
        if (depth === 0)
          break;
        depth--;
      }
      if (char === "," && depth === 0)
        break;
      i++;
    }
    let end = i;
    while (/\s/.test(text2[end - 1] ?? ""))
      end--;
    root.children.push({
      key,
      offset: start,
      length: end - start,
      value: { offset, length: end - offset }
    });
    whitespace();
    if (text2[i] === "}")
      break;
    i++;
    whitespace();
  }
  return root;
}
function object2(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function canonical3(value) {
  if (Array.isArray(value))
    return `[${value.map(canonical3).join(",")}]`;
  if (object2(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical3(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
function digest2(value) {
  return createHash8("sha256").update(canonical3(value)).digest("hex");
}
function code(error) {
  return object2(error) ? error.code : void 0;
}
async function safeRead(path2, privateFile = false, afterReadCheck) {
  let file;
  try {
    file = await open7(path2, constants2.O_RDONLY | constants2.O_NOFOLLOW);
    const stat7 = await file.stat();
    if (!stat7.isFile() || privateFile && (stat7.mode & 511) !== 384) {
      throw new PiSlotError("unsafe-path");
    }
    await afterReadCheck?.(path2);
    const current = await lstat2(path2);
    if (!current.isFile() || current.dev !== stat7.dev || current.ino !== stat7.ino) {
      throw new PiSlotError("unsafe-path");
    }
    const bytes = await file.readFile();
    const text2 = bytes.toString("utf8");
    if (!bytes.equals(Buffer.from(text2))) {
      throw new PiSlotError(privateFile ? "invalid-stash" : "invalid-auth");
    }
    return text2;
  } catch (error) {
    if (code(error) === "ENOENT" && !file)
      return void 0;
    if (code(error) === "ELOOP" || code(error) === "ENOENT") {
      throw new PiSlotError("unsafe-path");
    }
    throw error;
  } finally {
    await file?.close();
  }
}
function parseAuth(text2, provider) {
  try {
    const data = JSON.parse(text2);
    if (!object2(data))
      throw new Error();
    const root = rootSpans(text2);
    const properties = root.children;
    const names = properties.map((node) => node.key);
    if (new Set(names).size !== names.length)
      throw new Error();
    const property = properties.find((node) => node.key === provider);
    const entry = property ? data[provider] : null;
    if (entry !== null && !object2(entry))
      throw new Error();
    if (property && entry === null)
      throw new Error();
    return { text: text2, root, property, entry };
  } catch {
    throw new PiSlotError("invalid-auth");
  }
}
function entryText(auth) {
  const value = auth.property?.value;
  return value ? auth.text.slice(value.offset, value.offset + value.length) : null;
}
function replaceEntry(auth, provider, next) {
  const { text: text2, root, property } = auth;
  const properties = root.children ?? [];
  if (property) {
    const value = property.value;
    if (!value)
      throw new PiSlotError("invalid-auth");
    if (next !== null) {
      return text2.slice(0, value.offset) + next + text2.slice(value.offset + value.length);
    }
    const index = properties.indexOf(property);
    const previous = properties[index - 1];
    const following = properties[index + 1];
    const start = previous ? previous.offset + previous.length : property.offset;
    const end = !previous && following ? following.offset : property.offset + property.length;
    return text2.slice(0, start) + text2.slice(end);
  }
  if (next === null)
    return text2;
  const last = properties.at(-1);
  const offset = last ? last.offset + last.length : root.offset + 1;
  return `${text2.slice(0, offset)}${last ? "," : ""}${JSON.stringify(provider)}:${next}${text2.slice(offset)}`;
}
async function syncDir(path2) {
  const dir = await open7(path2, "r");
  try {
    await dir.sync();
  } finally {
    await dir.close();
  }
}
async function atomicWrite(path2, text2, assertLock, beforeRename) {
  await writeJsonAtomic2(path2, null, {
    serialize: () => text2,
    durable: true,
    beforeRename: async () => {
      await beforeRename?.(path2);
      assertLock();
    }
  });
}
function openPiSlot(options) {
  return createPiSlot(options);
}
function createPiSlot(options, onStep, hooks) {
  const { provider, placeholderKey } = options;
  const timeout = options.lockTimeoutMs ?? 3e4;
  if (!provider || !options.authPath || !options.stashPath || !placeholderKey || placeholderKey.startsWith("!") || placeholderKey.includes("$") || !Number.isFinite(timeout) || timeout < 0) {
    throw new PiSlotError("invalid-options");
  }
  const authPath = resolve4(options.authPath);
  const stashPath = resolve4(options.stashPath);
  if (authPath === stashPath || stashPath === `${authPath}.lock`) {
    throw new PiSlotError("invalid-options");
  }
  const authIdentity = digest2(authPath);
  const placeholderIdentity = digest2(placeholderKey);
  const placeholder = { type: "api_key", key: placeholderKey };
  const isPlaceholder = (entry) => digest2(entry) === digest2(placeholder);
  async function loadStash() {
    const text2 = await safeRead(stashPath, true, hooks?.afterReadCheck);
    if (text2 === void 0)
      return void 0;
    try {
      const stash = JSON.parse(text2);
      if (stash.version !== 1 || stash.provider !== provider || stash.authIdentity !== authIdentity || stash.placeholderIdentity !== placeholderIdentity || stash.entry !== null && !object2(stash.entry) || stash.sha256 !== digest2(stash.entry) || (stash.entry === null ? stash.entryJson !== null : typeof stash.entryJson !== "string" || digest2(JSON.parse(stash.entryJson)) !== stash.sha256)) {
        throw new Error();
      }
      return stash;
    } catch {
      throw new PiSlotError("invalid-stash");
    }
  }
  async function locked(fn) {
    let release;
    let assertFresh;
    let compromised = false;
    const assertLock = () => {
      assertFresh?.();
      if (compromised)
        throw new PiSlotError("lock-compromised");
    };
    try {
      await mkdir11(dirname10(authPath), { recursive: true, mode: 448 });
      const deadline = Date.now() + timeout;
      let retry = 0;
      while (!release) {
        try {
          const lease = await acquirePiLock(authPath, () => {
            compromised = true;
          }, hooks?.onRenew);
          release = lease.release;
          assertFresh = lease.assertFresh;
        } catch (error) {
          if (code(error) !== "ELOCKED")
            throw error;
          const remaining = deadline - Date.now();
          if (remaining <= 0)
            throw new PiSlotError("lock-timeout");
          await sleep2(Math.min(Math.round(Math.min(10 * 2 ** retry++, 1e3) * (1 + Math.random())), remaining));
        }
      }
      assertLock();
      const result = await fn(assertLock);
      assertLock();
      return result;
    } catch (error) {
      if (error instanceof PiSlotError)
        throw error;
      throw new PiSlotError("io");
    } finally {
      await release?.().catch(() => {
      });
      assertLock();
    }
  }
  async function load() {
    const auth = parseAuth(await safeRead(authPath, false, hooks?.afterReadCheck) ?? "{}", provider);
    const stash = await loadStash();
    return { auth, stash };
  }
  async function deleteStash(assertLock) {
    assertLock();
    await unlink7(stashPath);
    await syncDir(dirname10(stashPath));
    onStep?.("stash-deleted");
  }
  return {
    inspect: () => locked(async () => {
      const { auth, stash } = await load();
      const slot = isPlaceholder(auth.entry) ? "placeholder" : auth.entry === null ? "empty" : !stash || digest2(auth.entry) === stash.sha256 ? "original" : "foreign";
      return { slot, stash: stash ? "valid" : "missing" };
    }),
    enterVault: () => locked(async (assertLock) => {
      const { auth, stash } = await load();
      if (isPlaceholder(auth.entry)) {
        if (!stash)
          throw new PiSlotError("missing-stash");
        return;
      }
      if (stash && digest2(auth.entry) !== stash.sha256)
        throw new PiSlotError("conflict");
      if (!stash) {
        await mkdir11(dirname10(stashPath), { recursive: true, mode: 448 });
        const dir = await lstat2(dirname10(stashPath));
        if (!dir.isDirectory() || (dir.mode & 511) !== 448)
          throw new PiSlotError("unsafe-path");
        const saved = {
          version: 1,
          provider,
          authIdentity,
          placeholderIdentity,
          entry: auth.entry,
          entryJson: entryText(auth),
          sha256: digest2(auth.entry)
        };
        await atomicWrite(stashPath, JSON.stringify(saved), assertLock, hooks?.beforeRename);
        onStep?.("stash-written");
      }
      await atomicWrite(authPath, replaceEntry(auth, provider, JSON.stringify(placeholder)), assertLock, hooks?.beforeRename);
      onStep?.("auth-written");
    }),
    exitVault: () => locked(async (assertLock) => {
      const { auth, stash } = await load();
      if (!stash) {
        if (isPlaceholder(auth.entry))
          throw new PiSlotError("missing-stash");
        return "nothing-to-do";
      }
      if (isPlaceholder(auth.entry)) {
        await atomicWrite(authPath, replaceEntry(auth, provider, stash.entryJson), assertLock, hooks?.beforeRename);
        onStep?.("auth-written");
      } else if (digest2(auth.entry) !== stash.sha256) {
        return "conflict";
      }
      await deleteStash(assertLock);
      return "restored";
    })
  };
}
var PiSlotError;
var init_slot = __esm({
  "../core/dist/common-auth-embedded/pi-slot/slot.js"() {
    "use strict";
    init_atomic_write();
    init_lock();
    PiSlotError = class extends Error {
      code;
      constructor(code2) {
        super(`Pi slot: ${code2}`);
        this.code = code2;
        this.name = "PiSlotError";
      }
    };
  }
});

// ../core/dist/common-auth-embedded/pi-slot/index.js
var pi_slot_exports = {};
__export(pi_slot_exports, {
  PiSlotError: () => PiSlotError,
  openPiSlot: () => openPiSlot
});
var init_pi_slot = __esm({
  "../core/dist/common-auth-embedded/pi-slot/index.js"() {
    "use strict";
    init_slot();
  }
});

// src/cli.ts
import { execFile } from "node:child_process";
import { resolve as resolve6 } from "node:path";
import { createInterface } from "node:readline/promises";
import { promisify } from "node:util";

// ../core/dist/abort-forwarding.js
function forwardAbort(source, target) {
  if (!source || target.signal.aborted)
    return () => {
    };
  const onAbort = () => target.abort(source.reason);
  if (source.aborted) {
    onAbort();
    return () => {
    };
  }
  source.addEventListener("abort", onAbort, { once: true });
  let detached = false;
  return () => {
    if (detached)
      return;
    detached = true;
    source.removeEventListener("abort", onAbort);
  };
}

// ../core/dist/account-identity.js
function rowRefOf(row) {
  const credentialEpoch2 = row.credentialEpoch ?? 1;
  return row.identity === void 0 ? { id: row.id, credentialEpoch: credentialEpoch2 } : { id: row.id, credentialEpoch: credentialEpoch2, identity: row.identity };
}
function credentialFenceOf(ref) {
  return ref.identity === void 0 ? { credentialEpoch: ref.credentialEpoch } : { credentialEpoch: ref.credentialEpoch, identity: ref.identity };
}
function rowRefKey(ref) {
  return JSON.stringify(ref.identity === void 0 ? [ref.id, ref.credentialEpoch] : [ref.id, ref.credentialEpoch, ref.identity]);
}
function refMismatchReason(row, ref) {
  if (row === void 0)
    return `row ${ref.id} is no longer in the pool`;
  const current = rowRefOf(row);
  if (current.credentialEpoch !== ref.credentialEpoch) {
    return `row ${ref.id} now holds credential epoch ${current.credentialEpoch}, not ${ref.credentialEpoch}`;
  }
  if (current.identity !== ref.identity) {
    return `row ${ref.id} now records a different account identity`;
  }
  return void 0;
}

// ../core/dist/account-repository.js
import { createHash as createHash2, randomUUID as randomUUID2 } from "node:crypto";
import { mkdir as mkdir2, open as open2, readFile, realpath as realpath2, stat, unlink as unlink2 } from "node:fs/promises";
import { basename as basename2, dirname as dirname2, join as join2 } from "node:path";
import { isDeepStrictEqual as isDeepStrictEqual2 } from "node:util";

// ../core/dist/account-migration.js
import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { link, lstat, mkdir, open, realpath, unlink } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";

// ../core/dist/account-repository-types.js
var ACCOUNT_STORE_PROVIDER = "antigravity";
var PROVIDER_STATE_SCHEMA_VERSION = 1;
var QUOTA_STATE_SCHEMA_VERSION = 1;
var ROUTING_SETTINGS_SCHEMA_VERSION = 1;
var ROUTING_SETTINGS_KEY = "antigravityRouting";
var MANAGEMENT_SETTINGS_KEY = "antigravityManagement";
var MANAGEMENT_LOCK_NAME = "antigravity-management";
var REFRESH_PROVIDER_LOCK_PREFIX = "agy-refresh-";
var LEGACY_ACCOUNTS_LOCK_NAME = "accounts";
var LEGACY_ACCOUNTS_LOCK_TTL_MS = 1e4;
function refreshProviderLock(statePath, row) {
  return {
    path: statePath,
    name: REFRESH_PROVIDER_LOCK_PREFIX + encodeURIComponent(row.identity ?? row.id)
  };
}
function legacyAccountsLock(legacyPath) {
  return {
    path: legacyPath,
    name: LEGACY_ACCOUNTS_LOCK_NAME,
    ttlMs: LEGACY_ACCOUNTS_LOCK_TTL_MS,
    renew: true
  };
}
var CREDENTIAL_BOUND_METADATA_FIELDS = [
  "email",
  "projectId",
  "managedProjectId",
  "fingerprint",
  "fingerprintHistory",
  "verificationRequired",
  "verificationRequiredAt",
  "verificationRequiredReason",
  "verificationUrl",
  "accountIneligible",
  "accountIneligibleAt",
  "accountIneligibleReason",
  "eligibilityStateUpdatedAt",
  "capturedTierId",
  "capturedPaidTierId",
  "capturedTierAt",
  "capturedTierSchemaVersion"
];

// ../core/dist/account-repository-codecs.js
var AccountCodecError = class extends Error {
  path;
  problem;
  constructor(path2, problem) {
    super(`${path2} ${problem}`);
    this.name = "AccountCodecError";
    this.path = path2;
    this.problem = problem;
  }
};
function fail(path2, problem) {
  throw new AccountCodecError(path2, problem);
}
var MAX_JSON_DEPTH = 64;
var IDENTIFIER = /^[A-Za-z_$][A-Za-z0-9_$-]*$/;
function childPath(path2, key) {
  if (typeof key === "number")
    return `${path2}[${key}]`;
  return IDENTIFIER.test(key) ? `${path2}.${key}` : `${path2}[${JSON.stringify(key)}]`;
}
function isPlainObject(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}
function objectEntries(value, path2) {
  if (!isPlainObject(value))
    fail(path2, "must be a JSON object");
  if (Object.getOwnPropertySymbols(value).length > 0) {
    fail(path2, "has symbol keys, which JSON cannot hold");
  }
  const names = Object.getOwnPropertyNames(value);
  const entries = [];
  for (const key of names) {
    const at = childPath(path2, key);
    if (key === "__proto__")
      fail(at, "is a prototype key");
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor?.enumerable || !("value" in descriptor)) {
      fail(at, "is not a plain enumerable data property");
    }
    entries.push([key, descriptor.value]);
  }
  return entries;
}
function arrayItems(value, path2) {
  if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype) {
    fail(path2, "must be a JSON array");
  }
  const names = Object.getOwnPropertyNames(value);
  if (names.length !== value.length + 1) {
    fail(path2, "has holes or non-index properties, which JSON cannot hold");
  }
  return Array.from(value);
}
function jsonCopy(value, path2, depth, ancestors) {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value))
      fail(path2, "must be a finite number");
    return value;
  }
  if (typeof value !== "object")
    fail(path2, "is not a JSON value");
  if (depth >= MAX_JSON_DEPTH)
    fail(path2, "is nested too deeply");
  if (ancestors.has(value))
    fail(path2, "is circular");
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      return arrayItems(value, path2).map((item, index) => jsonCopy(item, childPath(path2, index), depth + 1, ancestors));
    }
    const out = {};
    for (const [key, item] of objectEntries(value, path2)) {
      out[key] = jsonCopy(item, childPath(path2, key), depth + 1, ancestors);
    }
    return out;
  } finally {
    ancestors.delete(value);
  }
}
var jsonValue = {
  decode: (raw, path2) => jsonCopy(raw, path2, 0, /* @__PURE__ */ new Set()),
  encode: (value, path2) => jsonCopy(value, path2, 0, /* @__PURE__ */ new Set())
};
function primitive(check, expected) {
  const read = (value, path2) => check(value) ? value : fail(path2, `must be ${expected}`);
  return { decode: read, encode: read };
}
var string = primitive((value) => typeof value === "string", "a string");
var nonEmptyString = primitive((value) => typeof value === "string" && value.length > 0, "a non-empty string");
var finiteNumber = primitive((value) => typeof value === "number" && Number.isFinite(value), "a finite number");
var count = primitive((value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0, "a non-negative integer");
var credentialEpoch = primitive((value) => typeof value === "number" && Number.isSafeInteger(value) && value > 0, "a positive safe integer");
var boolean = primitive((value) => typeof value === "boolean", "a boolean");
var rowId = primitive((value) => typeof value === "string" && value.length > 0 && value.trim() === value && !(value in Object.prototype), "a non-empty id without surrounding whitespace or prototype names");
function enumOf(values) {
  return primitive((value) => typeof value === "string" && values.includes(value), `one of ${values.map((value) => JSON.stringify(value)).join(", ")}`);
}
function schemaVersion(version) {
  const read = (value, path2) => {
    if (value === version)
      return version;
    if (typeof value === "number" && Number.isSafeInteger(value) && value > version) {
      fail(path2, `is a newer schema version than ${version}`);
    }
    return fail(path2, `must be ${version}`);
  };
  return { decode: read, encode: read };
}
function nullable(codec) {
  return {
    decode: (raw, path2) => raw === null ? null : codec.decode(raw, path2),
    encode: (value, path2) => value === null ? null : codec.encode(value, path2)
  };
}
function arrayOf(codec) {
  return {
    decode: (raw, path2) => arrayItems(raw, path2).map((item, index) => codec.decode(item, childPath(path2, index))),
    encode: (value, path2) => arrayItems(value, path2).map((item, index) => codec.encode(item, childPath(path2, index)))
  };
}
function mapOf(codec) {
  return {
    decode(raw, path2) {
      const out = {};
      for (const [key, item] of objectEntries(raw, path2)) {
        out[key] = codec.decode(item, childPath(path2, key));
      }
      return out;
    },
    encode(value, path2) {
      const out = {};
      for (const [key, item] of objectEntries(value, path2)) {
        out[key] = codec.encode(item, childPath(path2, key));
      }
      return out;
    }
  };
}
var required = (codec) => ({
  codec,
  required: true
});
var optional = (codec) => ({
  codec,
  required: false
});
var EXTENSIONS = "extensions";
function buildRecord(shape, open8, options) {
  const forbidden = options.forbidden ?? {};
  const knownField = (key) => Object.hasOwn(shape, key) ? shape[key] : void 0;
  const refusal3 = (key) => Object.hasOwn(forbidden, key) ? forbidden[key] : void 0;
  const requireFields = (present2, path2) => {
    for (const [key, field] of Object.entries(shape)) {
      if (field.required && !Object.hasOwn(present2, key)) {
        fail(childPath(path2, key), "is required");
      }
    }
  };
  return {
    decode(raw, path2) {
      const out = {};
      let extensions;
      for (const [key, value] of objectEntries(raw, path2)) {
        const at = childPath(path2, key);
        const field = knownField(key);
        if (field) {
          out[key] = field.codec.decode(value, at);
          continue;
        }
        const reason = refusal3(key);
        if (reason !== void 0)
          fail(at, reason);
        if (!open8)
          fail(at, "is not a known field");
        extensions ??= {};
        extensions[key] = jsonValue.decode(value, at);
      }
      requireFields(out, path2);
      if (extensions)
        out[EXTENSIONS] = extensions;
      return out;
    },
    encode(value, path2) {
      const out = {};
      let extensions;
      for (const [key, item] of objectEntries(value, path2)) {
        const at = childPath(path2, key);
        if (open8 && key === EXTENSIONS) {
          extensions = item;
          continue;
        }
        const field = knownField(key);
        if (!field) {
          fail(at, open8 ? "is not a known field; unknown data belongs in extensions" : "is not a known field");
        }
        if (item === void 0) {
          fail(at, "is undefined; leave the key out to keep it absent");
        }
        out[key] = field.codec.encode(item, at);
      }
      requireFields(out, path2);
      if (extensions !== void 0) {
        const extensionsPath = childPath(path2, EXTENSIONS);
        for (const [key, item] of objectEntries(extensions, extensionsPath)) {
          const at = childPath(extensionsPath, key);
          if (knownField(key))
            fail(at, "collides with a known field");
          const reason = refusal3(key);
          if (reason !== void 0)
            fail(at, reason);
          out[key] = jsonValue.encode(item, at);
        }
      }
      return out;
    }
  };
}
function openRecord(shape, options = {}) {
  return buildRecord(shape, true, options);
}
function closedRecord(shape) {
  return buildRecord(shape, false, {});
}
var CREDENTIAL_REFUSAL = "is a credential field; credentials live only in the store's own credential entry";
var CREDENTIAL_KEYS = {
  refreshToken: CREDENTIAL_REFUSAL,
  accessToken: CREDENTIAL_REFUSAL,
  access: CREDENTIAL_REFUSAL,
  refresh: CREDENTIAL_REFUSAL,
  expires: CREDENTIAL_REFUSAL,
  apiKey: CREDENTIAL_REFUSAL
};
var POOL_FIELD_REFUSAL = "belongs to the store's roster or to the routing settings, not provider metadata";
var QUOTA_FIELD_REFUSAL = "belongs to the quota value, not provider metadata";
var LEGACY_FIELD_REFUSAL = "is a pre-v4 field; the migration normalises it before import";
var METADATA_FIELD_REFUSAL = "belongs to provider metadata, not quota";
var clientMetadataCodec = openRecord({
  ideType: required(string),
  platform: required(string),
  pluginType: required(string)
});
var fingerprintCodec = openRecord({
  deviceId: required(string),
  sessionToken: required(string),
  userAgent: required(string),
  apiClient: required(string),
  clientMetadata: required(clientMetadataCodec),
  createdAt: required(finiteNumber)
});
var fingerprintVersionCodec = openRecord({
  fingerprint: required(fingerprintCodec),
  timestamp: required(finiteNumber),
  reason: required(enumOf(["initial", "regenerated", "restored"]))
});
var dailyRequestCountsCodec = openRecord({
  date: required(string),
  claude: required(count),
  gemini: required(count)
});
var metadataShape = {
  email: optional(nullable(string)),
  projectId: optional(nullable(string)),
  managedProjectId: optional(nullable(string)),
  addedAt: required(finiteNumber),
  lastUsed: required(finiteNumber),
  enabled: optional(nullable(boolean)),
  lastSwitchReason: optional(nullable(enumOf(["rate-limit", "initial", "rotation"]))),
  rateLimitResetTimes: optional(nullable(mapOf(nullable(finiteNumber)))),
  coolingDownUntil: optional(nullable(finiteNumber)),
  cooldownReason: optional(nullable(enumOf([
    "auth-failure",
    "network-error",
    "project-error",
    "validation-required"
  ]))),
  label: optional(nullable(string)),
  fingerprint: optional(nullable(fingerprintCodec)),
  fingerprintHistory: optional(nullable(arrayOf(fingerprintVersionCodec))),
  verificationRequired: optional(nullable(boolean)),
  verificationRequiredAt: optional(nullable(finiteNumber)),
  verificationRequiredReason: optional(nullable(string)),
  verificationUrl: optional(nullable(string)),
  accountIneligible: optional(nullable(boolean)),
  accountIneligibleAt: optional(nullable(finiteNumber)),
  accountIneligibleReason: optional(nullable(string)),
  eligibilityStateUpdatedAt: optional(nullable(finiteNumber)),
  capturedTierId: optional(nullable(string)),
  capturedPaidTierId: optional(nullable(string)),
  capturedTierAt: optional(nullable(finiteNumber)),
  capturedTierSchemaVersion: optional(nullable(finiteNumber)),
  dailyRequestCounts: optional(nullable(dailyRequestCountsCodec))
};
var quotaShape = {
  schemaVersion: required(schemaVersion(QUOTA_STATE_SCHEMA_VERSION)),
  cachedQuotaAccountId: optional(nullable(string)),
  cachedQuota: optional(nullable(mapOf(openRecord({
    remainingFraction: optional(nullable(finiteNumber)),
    resetTime: optional(nullable(string)),
    modelCount: required(finiteNumber),
    windows: optional(nullable(arrayOf(openRecord({
      window: required(enumOf(["weekly", "5h"])),
      remainingFraction: required(finiteNumber),
      resetTime: required(string)
    }))))
  })))),
  cachedPerModelQuota: optional(nullable(arrayOf(openRecord({
    modelId: required(string),
    displayName: optional(nullable(string)),
    group: required(nullable(string)),
    remainingFraction: required(finiteNumber),
    resetTime: optional(nullable(string))
  })))),
  cachedQuotaUpdatedAt: optional(nullable(finiteNumber))
};
var metadataForbidden = {
  ...CREDENTIAL_KEYS,
  version: POOL_FIELD_REFUSAL,
  accounts: POOL_FIELD_REFUSAL,
  activeIndex: POOL_FIELD_REFUSAL,
  activeIndexByFamily: POOL_FIELD_REFUSAL,
  isRateLimited: LEGACY_FIELD_REFUSAL,
  rateLimitResetTime: LEGACY_FIELD_REFUSAL,
  ...Object.fromEntries(Object.keys(quotaShape).filter((key) => key !== "schemaVersion").map((key) => [key, QUOTA_FIELD_REFUSAL]))
};
var quotaForbidden = {
  ...CREDENTIAL_KEYS,
  ...Object.fromEntries(Object.keys(metadataShape).map((key) => [key, METADATA_FIELD_REFUSAL]))
};
var metadataCodec = openRecord(metadataShape, {
  forbidden: metadataForbidden
});
var providerStateCodec = openRecord({
  schemaVersion: required(schemaVersion(PROVIDER_STATE_SCHEMA_VERSION)),
  metadata: required(metadataCodec)
}, { forbidden: CREDENTIAL_KEYS });
var quotaCodec = openRecord(quotaShape, { forbidden: quotaForbidden });
var rowRefCodec = closedRecord({
  id: required(rowId),
  credentialEpoch: required(credentialEpoch),
  identity: optional(nonEmptyString)
});
var routingCodec = openRecord({
  schemaVersion: required(schemaVersion(ROUTING_SETTINGS_SCHEMA_VERSION)),
  activeIndex: optional(nullable(finiteNumber)),
  activeIndexByFamily: optional(nullable(openRecord({
    claude: optional(nullable(finiteNumber)),
    gemini: optional(nullable(finiteNumber))
  }))),
  activeRow: optional(nullable(rowRefCodec)),
  activeRowByFamily: optional(nullable(openRecord({
    claude: optional(nullable(rowRefCodec)),
    gemini: optional(nullable(rowRefCodec))
  })))
}, { forbidden: CREDENTIAL_KEYS });
function asObject(value) {
  return isPlainObject(value) ? value : fail("$", "did not encode to an object");
}
function validates(read, raw) {
  try {
    read(raw);
    return true;
  } catch (error) {
    if (error instanceof AccountCodecError)
      return false;
    throw error;
  }
}
function canonical(value) {
  if (Array.isArray(value))
    return value.map(canonical);
  if (value === null || typeof value !== "object")
    return value;
  const out = {};
  for (const key of Object.keys(value).sort()) {
    const item = value[key];
    if (item !== void 0)
      out[key] = canonical(item);
  }
  return out;
}
function decodeProviderState(raw) {
  return providerStateCodec.decode(raw, "$");
}
function encodeProviderState(value) {
  return asObject(providerStateCodec.encode(value, "$"));
}
function decodeProviderMetadata(raw) {
  return metadataCodec.decode(raw, "$.metadata");
}
function encodeProviderMetadata(value) {
  return asObject(metadataCodec.encode(value, "$.metadata"));
}
function isValidProviderState(raw) {
  return validates(decodeProviderState, raw);
}
function providerStateCredentialBound(raw) {
  const stored = encodeProviderState(decodeProviderState(raw));
  const metadata = asObject(stored.metadata ?? null);
  const bound = {};
  for (const key of CREDENTIAL_BOUND_METADATA_FIELDS) {
    const value = metadata[key];
    if (value !== void 0)
      bound[key] = value;
  }
  return asObject(canonical({
    schemaVersion: PROVIDER_STATE_SCHEMA_VERSION,
    metadata: bound
  }));
}
function decodeQuotaState(raw) {
  return quotaCodec.decode(raw, "$");
}
function encodeQuotaState(value) {
  return asObject(quotaCodec.encode(value, "$"));
}
function isValidQuotaState(raw) {
  return validates(decodeQuotaState, raw);
}
function mergeQuotaState(stored, observation) {
  const incoming = encodeQuotaState(decodeQuotaState(observation));
  if (stored === void 0)
    return incoming;
  const prior = encodeQuotaState(decodeQuotaState(stored));
  return encodeQuotaState(decodeQuotaState({ ...prior, ...incoming }));
}
function decodeRoutingSettings(raw) {
  return routingCodec.decode(raw, "$");
}
function encodeRoutingSettings(value) {
  return asObject(routingCodec.encode(value, "$"));
}
function createProviderStateCodec(policy) {
  if (policy === null || typeof policy !== "object") {
    fail("policy", "must be an object with merge and onReplace rules");
  }
  for (const rule of ["merge", "onReplace"]) {
    if (typeof policy[rule] !== "function") {
      fail(`policy.${rule}`, "must be a function; the store's default would bypass the repository's rule");
    }
  }
  return {
    validate: isValidProviderState,
    credentialBound: providerStateCredentialBound,
    merge(onDisk, incoming) {
      return encodeProviderState(policy.merge(decodeProviderState(onDisk), decodeProviderState(incoming)));
    },
    onReplace(previous, replacement) {
      const next = policy.onReplace(previous === void 0 ? void 0 : decodeProviderState(previous), {
        id: replacement.id,
        credentialEpoch: replacement.credentialEpoch,
        ...replacement.previousIdentity !== void 0 ? { previousIdentity: replacement.previousIdentity } : {},
        ...replacement.identity !== void 0 ? { identity: replacement.identity } : {},
        ...replacement.incoming !== void 0 ? { incoming: decodeProviderState(replacement.incoming) } : {}
      });
      return next === void 0 ? void 0 : encodeProviderState(next);
    }
  };
}
var QUOTA_CODEC = {
  validate: isValidQuotaState,
  merge: mergeQuotaState
};

// ../core/dist/account-migration.js
function resolveAccountStorePaths(legacyPath, generationId) {
  if (generationId !== void 0)
    return generationPaths(legacyPath, generationId);
  if (!isAbsolute(legacyPath) || legacyPath !== resolve(legacyPath)) {
    throw new AccountMigrationError("legacy path must be absolute and normalized");
  }
  const storeDir = join(dirname(legacyPath), `${basename(legacyPath)}.store`);
  return {
    legacyPath,
    storeDir,
    configPath: join(storeDir, "config.json"),
    statePath: join(storeDir, "state.json"),
    migrationPath: join(storeDir, "migration.json"),
    backupsDir: join(storeDir, "backups"),
    retiredDir: join(storeDir, "retired"),
    transfersDir: join(storeDir, "transfers")
  };
}
function accountStorePointerPath(legacyPath) {
  return `${resolveAccountStorePaths(legacyPath).storeDir}.pointer.json`;
}
function generationPaths(legacyPath, id) {
  const logical = resolveAccountStorePaths(legacyPath);
  text(id, UUID, "generation id");
  const storeDir = join(dirname(legacyPath), `${basename(legacyPath)}.store.${id}.generation`);
  return {
    ...logical,
    storeDir,
    configPath: join(storeDir, "config.json"),
    statePath: join(storeDir, "state.json"),
    migrationPath: join(storeDir, "migration.json"),
    backupsDir: join(storeDir, "backups"),
    retiredDir: join(storeDir, "retired"),
    transfersDir: join(storeDir, "transfers")
  };
}
function pathGenerationId(paths) {
  const id = basename(paths.storeDir).slice(`${basename(paths.legacyPath)}.store.`.length, -".generation".length);
  text(id, UUID, "physical generation");
  if (!isDeepStrictEqual(generationPaths(paths.legacyPath, id), paths))
    throw new AccountMigrationError("physical paths differ from derived generation");
  return id;
}
function decodeAccountStorePointer(value, legacyPath) {
  const raw = exact(value, ["schemaVersion", "id", "directoryBasename"], "pointer");
  if (raw.schemaVersion !== 1)
    throw new AccountMigrationError("unsupported pointer schema");
  const id = text(raw.id, UUID, "pointer generation");
  const paths = generationPaths(legacyPath, id);
  if (raw.directoryBasename !== basename(paths.storeDir))
    throw new AccountMigrationError("pointer directory basename differs from its derived generation");
  return { schemaVersion: 1, id, directoryBasename: basename(paths.storeDir) };
}
async function readPointer(legacyPath) {
  const logical = resolveAccountStorePaths(legacyPath);
  if (await exists(logical.storeDir))
    throw new AccountMigrationError("foreign logical store directory is not pointer authority");
  const path2 = accountStorePointerPath(legacyPath);
  if (!await exists(path2))
    return void 0;
  return decodeAccountStorePointer(jsonBytes(await secureRead(path2)), legacyPath);
}
async function resolvePublishedAccountStorePaths(legacyPath) {
  const pointer = await readPointer(legacyPath);
  if (!pointer)
    return void 0;
  const paths = generationPaths(legacyPath, pointer.id);
  const journal = await readJournal(paths);
  if (!journal || journal.id !== pointer.id)
    throw new AccountMigrationError("published generation has no matching complete journal");
  return paths;
}
async function assertPublishedAccountStoreGeneration(paths) {
  const current = await resolvePublishedAccountStorePaths(paths.legacyPath);
  if (!current || !isDeepStrictEqual(current, paths))
    throw new AccountMigrationError("bound store generation is no longer published");
}
var AccountMigrationError = class extends Error {
  reason;
  constructor(reason) {
    super(`Account-store migration refused: ${reason}`);
    this.reason = reason;
    this.name = "AccountMigrationError";
  }
};
var QUOTA_FIELDS = [
  "cachedQuotaAccountId",
  "cachedQuota",
  "cachedPerModelQuota",
  "cachedQuotaUpdatedAt"
];
function object(value, path2) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new AccountMigrationError(`${path2} must be an object`);
  }
  if (Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null)
    throw new AccountMigrationError(`${path2} is not a plain JSON object`);
  if (Object.getOwnPropertySymbols(value).length || Object.getOwnPropertyNames(value).some((key) => {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    return key === "__proto__" || !descriptor?.enumerable || !("value" in descriptor);
  }))
    throw new AccountMigrationError(`${path2} has unsafe JSON properties`);
  return value;
}
function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}
function assertSerializableNumbers(value, depth = 0) {
  if (depth > 128)
    throw new AccountMigrationError("source JSON exceeds safe nesting depth");
  if (typeof value === "number" && (!Number.isFinite(value) || Object.is(value, -0)))
    throw new AccountMigrationError("source contains a numeric value the public JSON writer cannot retain losslessly");
  if (value !== null && typeof value === "object") {
    for (const item of Object.values(value))
      assertSerializableNumbers(item, depth + 1);
  }
}
function legacyOptional(row, key, predicate, path2) {
  if (Object.hasOwn(row, key) && row[key] !== null && !predicate(row[key])) {
    throw new AccountMigrationError(`${path2}.${key} has an invalid type`);
  }
}
function parseAccount(value, ordinal, version, clock) {
  const path2 = `accounts[${ordinal}]`;
  const source = object(value, path2);
  if (typeof source.refreshToken !== "string" || !source.refreshToken.trim().length) {
    throw new AccountMigrationError(`${path2}.refreshToken must be nonempty`);
  }
  const metadataRaw = { ...source };
  delete metadataRaw.refreshToken;
  const quotaRaw = { schemaVersion: 1 };
  let hasQuota = false;
  for (const key of QUOTA_FIELDS) {
    if (!Object.hasOwn(source, key))
      continue;
    hasQuota = true;
    quotaRaw[key] = source[key];
    delete metadataRaw[key];
  }
  if (version === 1) {
    legacyOptional(source, "isRateLimited", (v) => typeof v === "boolean", path2);
    legacyOptional(source, "rateLimitResetTime", finite, path2);
    delete metadataRaw.isRateLimited;
    delete metadataRaw.rateLimitResetTime;
  }
  const originalMetadata = decodeProviderMetadata(metadataRaw);
  const quota = hasQuota ? decodeQuotaState(quotaRaw) : void 0;
  const normalized = encodeProviderMetadata(originalMetadata);
  if (version === 1) {
    if (source.isRateLimited && finite(source.rateLimitResetTime) && source.rateLimitResetTime > clock) {
      if (originalMetadata.rateLimitResetTimes === null)
        throw new AccountMigrationError(`${path2} has conflicting rate-limit encodings`);
      const resets = { ...originalMetadata.rateLimitResetTimes };
      for (const key of ["claude", "gemini-antigravity"]) {
        if (Object.hasOwn(resets, key) && resets[key] !== source.rateLimitResetTime)
          throw new AccountMigrationError(`${path2} has conflicting rate-limit encodings`);
        resets[key] = source.rateLimitResetTime;
      }
      normalized.rateLimitResetTimes = resets;
    }
  } else if (version === 2 && originalMetadata.rateLimitResetTimes !== null && originalMetadata.rateLimitResetTimes !== void 0) {
    const resets = { ...originalMetadata.rateLimitResetTimes };
    const claude = resets.claude;
    const gemini = resets.gemini;
    delete resets.claude;
    delete resets.gemini;
    if (claude === null || finite(claude) && claude > clock)
      resets.claude = claude;
    if (gemini === null || finite(gemini) && gemini > clock) {
      if (Object.hasOwn(resets, "gemini-antigravity") && resets["gemini-antigravity"] !== gemini)
        throw new AccountMigrationError(`${path2} has conflicting rate-limit encodings`);
      resets["gemini-antigravity"] = gemini;
    }
    normalized.rateLimitResetTimes = resets;
  }
  if (version < 4) {
    delete normalized.fingerprint;
    delete normalized.fingerprintHistory;
  }
  const metadata = decodeProviderMetadata(normalized);
  return {
    ordinal,
    refreshToken: source.refreshToken,
    metadata,
    ...quota === void 0 ? {} : { quota }
  };
}
function legacyRouting(source) {
  const raw = { schemaVersion: 1 };
  const unknown = {};
  for (const [key, value] of Object.entries(source)) {
    if (key === "version" || key === "accounts")
      continue;
    if (key === "activeIndex" || key === "activeIndexByFamily")
      raw[key] = value;
    else {
      if ([
        "refreshToken",
        "accessToken",
        "access",
        "refresh",
        "expires",
        "apiKey"
      ].includes(key))
        throw new AccountMigrationError("source-level credential field has no legacy account owner");
      unknown[key] = value;
    }
  }
  if (Object.keys(unknown).length)
    raw.legacySourceFields = unknown;
  return decodeRoutingSettings(raw);
}
function parseLegacyAccountStorage(bytes, normalizationClock) {
  if (!finite(normalizationClock) || Object.is(normalizationClock, -0)) {
    throw new AccountMigrationError("normalization clock must be finite and JSON-roundtrippable");
  }
  let parsed;
  try {
    parsed = JSON.parse(bytes);
  } catch {
    throw new AccountMigrationError("malformed source JSON");
  }
  assertSerializableNumbers(parsed);
  const source = object(parsed, "source");
  const version = source.version;
  if (version !== 1 && version !== 2 && version !== 3 && version !== 4) {
    throw new AccountMigrationError("unsupported source version");
  }
  if (!Array.isArray(source.accounts)) {
    throw new AccountMigrationError("source.accounts must be an array");
  }
  const parsedAccounts = source.accounts.map((row, index) => {
    try {
      return parseAccount(row, index, version, normalizationClock);
    } catch (error) {
      if (error instanceof AccountCodecError) {
        throw new AccountMigrationError(`accounts[${index}]: ${error.message}`);
      }
      throw error;
    }
  });
  const winners = /* @__PURE__ */ new Map();
  for (const row of parsedAccounts) {
    const email = row.metadata.email;
    if (!email)
      continue;
    const prior = winners.get(email);
    if (!prior || row.metadata.lastUsed > prior.metadata.lastUsed || row.metadata.lastUsed === prior.metadata.lastUsed && row.metadata.addedAt > prior.metadata.addedAt) {
      winners.set(email, row);
    }
  }
  const accounts = parsedAccounts.filter((row) => !row.metadata.email || winners.get(row.metadata.email) === row);
  const secrets = /* @__PURE__ */ new Map();
  for (const row of accounts) {
    const prior = secrets.get(row.refreshToken);
    if (prior !== void 0) {
      throw new AccountMigrationError(`duplicate refresh secret at ordinals ${prior}, ${row.ordinal}`);
    }
    secrets.set(row.refreshToken, row.ordinal);
  }
  const routing = legacyRouting(source);
  const active2 = routing.activeIndex ?? 0;
  const effectiveActiveIndex = accounts.length ? Math.max(0, Math.min(active2, accounts.length - 1)) : 0;
  return {
    sourceVersion: version,
    normalizationClock,
    accounts,
    routing,
    effectiveActiveIndex
  };
}
function exportLegacyAccountStorage(accounts, routing) {
  const out = encodeRoutingSettings(routing);
  delete out.schemaVersion;
  delete out.activeRow;
  delete out.activeRowByFamily;
  const unknown = out.legacySourceFields;
  delete out.legacySourceFields;
  if (unknown !== void 0) {
    if (unknown === null || typeof unknown !== "object" || Array.isArray(unknown))
      throw new AccountMigrationError("legacy source extension namespace is malformed");
    for (const [key, value] of Object.entries(unknown))
      out[key] = value;
  }
  out.version = 4;
  out.accounts = accounts.map((row) => {
    const result = encodeProviderMetadata(row.metadata);
    result.refreshToken = row.refreshToken;
    if (row.quota !== void 0) {
      const quota = encodeQuotaState(row.quota);
      delete quota.schemaVersion;
      for (const [key, value] of Object.entries(quota))
        result[key] = value;
    }
    return result;
  });
  return out;
}
var ACCOUNT_MIGRATION_PHASES = [
  "capture",
  "build",
  "verify",
  "retire",
  "activate"
];
var ACCOUNT_MIGRATION_MANAGEMENT_STEPS = ACCOUNT_MIGRATION_PHASES;
var ACCOUNT_STORE_GENERATION_SETTINGS_KEY = "antigravityGeneration";
function decodeAccountStoreGeneration(value) {
  const raw = exact(value, [
    "schemaVersion",
    "id",
    "legacyPath",
    "storeDir",
    "sourceKind",
    "initialManifestSha256"
  ], "generation");
  if (raw.schemaVersion !== 1 || typeof raw.legacyPath !== "string" || raw.sourceKind !== "file" && raw.sourceKind !== "absent")
    throw new AccountMigrationError("generation schema is invalid");
  const id = text(raw.id, UUID, "generation id");
  const paths = generationPaths(raw.legacyPath, id);
  if (raw.storeDir !== paths.storeDir)
    throw new AccountMigrationError("generation successor association differs");
  return {
    schemaVersion: 1,
    id,
    legacyPath: paths.legacyPath,
    storeDir: paths.storeDir,
    sourceKind: raw.sourceKind,
    initialManifestSha256: text(raw.initialManifestSha256, SHA256, "generation manifest hash")
  };
}
function generationJson(journal) {
  return {
    schemaVersion: 1,
    id: journal.id,
    legacyPath: journal.legacyPath,
    storeDir: journal.storeDir,
    sourceKind: journal.sourceKind,
    initialManifestSha256: digest(canonical2(manifestJson(journal.manifest)))
  };
}
var UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
var SHA256 = /^[0-9a-f]{64}$/;
function exact(value, keys, path2) {
  const record2 = object(value, path2);
  if (Object.keys(record2).some((key) => !keys.includes(key))) {
    throw new AccountMigrationError(`${path2} has unknown fields`);
  }
  return record2;
}
function text(value, pattern, path2) {
  if (typeof value !== "string" || !pattern.test(value))
    throw new AccountMigrationError(`${path2} is invalid`);
  return value;
}
function list(value, path2) {
  if (!Array.isArray(value))
    throw new AccountMigrationError(`${path2} must be an array`);
  if (Object.getOwnPropertySymbols(value).length || Object.getOwnPropertyNames(value).length !== value.length + 1 || Array.from({ length: value.length }, (_, index) => Object.getOwnPropertyDescriptor(value, String(index))).some((descriptor) => !descriptor?.enumerable || !("value" in descriptor)))
    throw new AccountMigrationError(`${path2} must be a dense plain JSON array`);
  return value;
}
function integer(value, path2) {
  if (!Number.isSafeInteger(value) || typeof value !== "number" || value < 0)
    throw new AccountMigrationError(`${path2} must be a nonnegative safe integer`);
  return value;
}
function digest(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}
function canonical2(value) {
  if (Array.isArray(value))
    return `[${value.map(canonical2).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonical2(item)}`).join(",")}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === void 0)
    throw new AccountMigrationError("non-JSON journal value");
  return encoded;
}
function manifestJson(manifest) {
  return {
    ...manifest,
    accounts: manifest.accounts.map((row) => ({
      ordinal: row.ordinal,
      refreshToken: row.refreshToken,
      metadata: encodeProviderMetadata(row.metadata),
      ...row.quota === void 0 ? {} : { quota: encodeQuotaState(row.quota) }
    })),
    routing: encodeRoutingSettings(manifest.routing)
  };
}
function journalJson(journal) {
  return { ...journal, manifest: manifestJson(journal.manifest) };
}
function decodeAccountMigrationJournal(value) {
  const raw = exact(value, [
    "schemaVersion",
    "id",
    "legacyPath",
    "storeDir",
    "status",
    "operation",
    "phase",
    "sourceKind",
    "sourceSha256",
    "captureSha256",
    "sourceAbsenceVerified",
    "manifest",
    "mapping",
    "completedRows",
    "verification",
    "retiredSha256",
    "rollback",
    "cancelled"
  ], "journal");
  if (raw.schemaVersion !== 1)
    throw new AccountMigrationError("unsupported journal schema");
  const id = text(raw.id, UUID, "journal.id");
  if (typeof raw.legacyPath !== "string")
    throw new AccountMigrationError("journal legacy path is invalid");
  const paths = generationPaths(raw.legacyPath, id);
  if (raw.storeDir !== paths.storeDir)
    throw new AccountMigrationError("journal successor association differs");
  const status = raw.status;
  if (status !== "pending" && status !== "active" && status !== "inactive")
    throw new AccountMigrationError("journal status is invalid");
  const operation = raw.operation;
  if (operation !== "migrate" && operation !== "rollback")
    throw new AccountMigrationError("journal operation is invalid");
  const phase = ACCOUNT_MIGRATION_PHASES.find((candidate) => candidate === raw.phase);
  if (phase === void 0)
    throw new AccountMigrationError("journal phase is invalid");
  const sourceKind = raw.sourceKind;
  if (sourceKind !== "file" && sourceKind !== "absent")
    throw new AccountMigrationError("journal source kind is invalid");
  const sourceSha256 = sourceKind === "file" ? text(raw.sourceSha256, SHA256, "journal.sourceSha256") : void 0;
  const captureSha256 = sourceKind === "file" ? text(raw.captureSha256, SHA256, "journal.captureSha256") : void 0;
  if (sourceKind === "absent" && Object.hasOwn(raw, "captureSha256"))
    throw new AccountMigrationError("absent source cannot claim a captured file snapshot");
  if (sourceKind === "absent" && Object.hasOwn(raw, "sourceSha256"))
    throw new AccountMigrationError("absent source cannot claim a backup hash");
  if (Object.hasOwn(raw, "sourceAbsenceVerified") && (sourceKind !== "absent" || raw.sourceAbsenceVerified !== true))
    throw new AccountMigrationError("source absence association is invalid");
  const m = exact(raw.manifest, [
    "sourceVersion",
    "normalizationClock",
    "accounts",
    "routing",
    "effectiveActiveIndex"
  ], "manifest");
  const sourceVersion = m.sourceVersion;
  if (sourceVersion !== null && sourceVersion !== 1 && sourceVersion !== 2 && sourceVersion !== 3 && sourceVersion !== 4)
    throw new AccountMigrationError("manifest source version is invalid");
  if (sourceKind === "file" && sourceVersion === null || sourceKind === "absent" && sourceVersion !== null)
    throw new AccountMigrationError("manifest version differs from source kind");
  if (!finite(m.normalizationClock) || !finite(m.effectiveActiveIndex))
    throw new AccountMigrationError("manifest clock or cursor is invalid");
  const accounts = list(m.accounts, "manifest.accounts").map((entry) => {
    const row = exact(entry, ["ordinal", "refreshToken", "metadata", "quota"], "manifest row");
    if (typeof row.refreshToken !== "string" || !row.refreshToken.trim().length)
      throw new AccountMigrationError("manifest refresh secret is empty");
    return {
      ordinal: integer(row.ordinal, "manifest ordinal"),
      refreshToken: row.refreshToken,
      metadata: decodeProviderMetadata(row.metadata),
      ...Object.hasOwn(row, "quota") ? { quota: decodeQuotaState(row.quota) } : {}
    };
  });
  const ordinals = accounts.map((row) => row.ordinal);
  if (new Set(ordinals).size !== accounts.length || ordinals.some((ordinal, i) => i > 0 && ordinal <= (ordinals[i - 1] ?? -1)) || new Set(accounts.map((row) => row.refreshToken)).size !== accounts.length)
    throw new AccountMigrationError("manifest order or secrets are duplicated");
  const manifest = {
    sourceVersion,
    normalizationClock: m.normalizationClock,
    accounts,
    routing: decodeRoutingSettings(m.routing),
    effectiveActiveIndex: m.effectiveActiveIndex
  };
  assertSerializableNumbers(manifestJson(manifest));
  if (sourceKind === "absent" && (accounts.length || !isDeepStrictEqual(encodeRoutingSettings(manifest.routing), {
    schemaVersion: 1
  }) || manifest.effectiveActiveIndex !== 0))
    throw new AccountMigrationError("absent-source manifest must be explicitly empty with no invented cursors");
  const effective = accounts.length ? Math.max(0, Math.min(manifest.routing.activeIndex ?? 0, accounts.length - 1)) : 0;
  if (effective !== manifest.effectiveActiveIndex)
    throw new AccountMigrationError("manifest effective cursor differs");
  const mapping = list(raw.mapping, "mapping").map((entry) => {
    const row = exact(entry, ["id", "ordinal"], "mapping row");
    return {
      id: text(row.id, UUID, "mapping id"),
      ordinal: integer(row.ordinal, "mapping ordinal")
    };
  });
  if (mapping.length !== accounts.length || new Set(mapping.map((row) => row.id)).size !== mapping.length || mapping.some((row, i) => row.ordinal !== accounts[i]?.ordinal))
    throw new AccountMigrationError("mapping differs from full manifest order");
  const completedRows = list(raw.completedRows, "completedRows").map((entry) => text(entry, UUID, "completed row"));
  if (new Set(completedRows).size !== completedRows.length || completedRows.some((row) => !mapping.some((mapped) => mapped.id === row)))
    throw new AccountMigrationError("completed rows do not belong to this journal");
  if (completedRows.some((id2, index) => id2 !== mapping[index]?.id))
    throw new AccountMigrationError("completed rows are not the captured prefix order");
  let verification;
  if (Object.hasOwn(raw, "verification")) {
    const v = exact(raw.verification, [
      "manifestSha256",
      "configSha256",
      "stateSha256",
      "statePresent",
      "durability"
    ], "verification");
    if (typeof v.statePresent !== "boolean")
      throw new AccountMigrationError("state presence encoding is invalid");
    if (!v.statePresent && Object.hasOwn(v, "stateSha256"))
      throw new AccountMigrationError("absent successor state cannot claim a file hash");
    if (v.durability !== "posix-directory-synced" && v.durability !== "windows-reopened-no-directory-power-loss-guarantee")
      throw new AccountMigrationError("verification durability is invalid");
    verification = {
      manifestSha256: text(v.manifestSha256, SHA256, "manifest hash"),
      configSha256: text(v.configSha256, SHA256, "config hash"),
      ...v.statePresent ? { stateSha256: text(v.stateSha256, SHA256, "state hash") } : {},
      statePresent: v.statePresent,
      durability: v.durability
    };
    if (verification.manifestSha256 !== digest(canonical2(manifestJson(manifest))))
      throw new AccountMigrationError("verification is not associated with the complete manifest");
  }
  const retiredSha256 = Object.hasOwn(raw, "retiredSha256") ? text(raw.retiredSha256, SHA256, "retired hash") : void 0;
  if (sourceKind === "absent" && retiredSha256 !== void 0)
    throw new AccountMigrationError("absent source cannot claim retired bytes");
  if (retiredSha256 !== void 0 && retiredSha256 !== sourceSha256)
    throw new AccountMigrationError("retired bytes are not associated with source");
  let rollback;
  if (Object.hasOwn(raw, "rollback")) {
    const r = exact(raw.rollback, ["id", "snapshotSha256", "exportSha256", "rows", "successorInactive"], "rollback");
    const rows = list(r.rows, "rollback rows").map((id2) => text(id2, UUID, "rollback row id"));
    if (new Set(rows).size !== rows.length || typeof r.successorInactive !== "boolean")
      throw new AccountMigrationError("rollback rows or inactive flag is invalid");
    rollback = {
      id: text(r.id, UUID, "rollback id"),
      snapshotSha256: text(r.snapshotSha256, SHA256, "snapshot hash"),
      exportSha256: text(r.exportSha256, SHA256, "export hash"),
      rows,
      successorInactive: r.successorInactive
    };
  }
  if (Object.hasOwn(raw, "cancelled") && raw.cancelled !== true)
    throw new AccountMigrationError("cancellation flag is invalid");
  const cancelled = raw.cancelled === true;
  if (cancelled && (status === "active" || operation !== "rollback" || status === "inactive" && phase !== "activate" || rollback !== void 0 || retiredSha256 !== void 0))
    throw new AccountMigrationError("invalid pre-retirement cancellation");
  if ((phase === "retire" || phase === "activate" || status === "active") && !cancelled && verification === void 0)
    throw new AccountMigrationError("retirement lacks durable full-row verification");
  if (operation === "migrate" && verification !== void 0 && completedRows.length !== mapping.length)
    throw new AccountMigrationError("verification acknowledged an incomplete import");
  if (operation === "migrate" && (retiredSha256 !== void 0 || raw.sourceAbsenceVerified === true) && (!verification || phase !== "retire" && phase !== "activate"))
    throw new AccountMigrationError("retirement association precedes durable verification");
  if (operation === "migrate" && phase === "activate" && (sourceKind === "file" ? retiredSha256 === void 0 : raw.sourceAbsenceVerified !== true))
    throw new AccountMigrationError("activation lacks its actual source retirement association");
  if (status === "active" && (operation !== "migrate" || phase !== "activate" || (sourceKind === "file" ? retiredSha256 === void 0 : raw.sourceAbsenceVerified !== true) || rollback !== void 0 || cancelled))
    throw new AccountMigrationError("active receipt is incomplete");
  if (operation === "rollback" && rollback === void 0 && !cancelled)
    throw new AccountMigrationError("rollback lacks its current-credential snapshot");
  if (operation === "rollback" && !cancelled && (verification === void 0 || (sourceKind === "file" ? retiredSha256 === void 0 : raw.sourceAbsenceVerified !== true)))
    throw new AccountMigrationError("rollback lacks the original verified retirement");
  if (status === "inactive" && !cancelled && (operation !== "rollback" || phase !== "activate" || rollback === void 0))
    throw new AccountMigrationError("inactive receipt lacks a completed rollback");
  if (operation === "rollback" && (phase === "activate" || status === "inactive") && !cancelled && !rollback?.successorInactive)
    throw new AccountMigrationError("rollback restoration preceded successor inactivity");
  return {
    schemaVersion: 1,
    id,
    legacyPath: paths.legacyPath,
    storeDir: paths.storeDir,
    status,
    operation,
    phase,
    sourceKind,
    ...sourceSha256 === void 0 ? {} : { sourceSha256 },
    ...captureSha256 === void 0 ? {} : { captureSha256 },
    ...raw.sourceAbsenceVerified === true ? { sourceAbsenceVerified: true } : {},
    manifest,
    mapping,
    completedRows,
    ...verification === void 0 ? {} : { verification },
    ...retiredSha256 === void 0 ? {} : { retiredSha256 },
    ...rollback === void 0 ? {} : { rollback },
    ...cancelled ? { cancelled: true } : {}
  };
}
function pendingLockFailure(modules, error) {
  if (error instanceof modules.fs.LockContentionError)
    return { status: "pending", reason: "lock-contention" };
  if (error instanceof modules.fs.LockOwnershipError)
    return { status: "pending", reason: "ownership-lost" };
  if (error instanceof modules.store.PoolOperationError && error.retryable) {
    if (error.kind === "lock-contention")
      return { status: "pending", reason: "lock-contention" };
    if (error.kind === "lock-ownership")
      return { status: "pending", reason: "ownership-lost" };
  }
  return void 0;
}
function errno(error) {
  return error !== null && typeof error === "object" && "code" in error && typeof error.code === "string" ? error.code : void 0;
}
function sameFilesystemPath(left, right) {
  return process.platform === "win32" ? left.toLowerCase() === right.toLowerCase() : left === right;
}
async function exists(path2) {
  try {
    await lstat(path2);
    return true;
  } catch (error) {
    if (errno(error) === "ENOENT")
      return false;
    throw error;
  }
}
function privateMode(mode, expected) {
  if (process.platform !== "win32" && (mode & 511) !== expected)
    throw new AccountMigrationError("insecure POSIX file or directory permissions");
}
async function privateDirectory(path2) {
  try {
    await mkdir(path2, { mode: 448 });
  } catch (error) {
    if (errno(error) !== "EEXIST")
      throw error;
  }
  const stat7 = await lstat(path2);
  if (!stat7.isDirectory() || stat7.isSymbolicLink())
    throw new AccountMigrationError("successor directory is not a regular directory");
  privateMode(stat7.mode, 448);
  if (!sameFilesystemPath(await realpath(path2), path2))
    throw new AccountMigrationError("successor directory traverses a symbolic link");
}
async function prepareDirectories(paths) {
  if (!sameFilesystemPath(await realpath(dirname(paths.legacyPath)), dirname(paths.legacyPath)))
    throw new AccountMigrationError("legacy parent traverses a symbolic link");
  for (const path2 of [
    paths.storeDir,
    paths.backupsDir,
    paths.retiredDir,
    paths.transfersDir
  ])
    await privateDirectory(path2);
}
async function secureRead(path2) {
  if (!sameFilesystemPath(await realpath(dirname(path2)), dirname(path2)))
    throw new AccountMigrationError("file path traverses a symbolic link");
  const before = await lstat(path2);
  if (!before.isFile() || before.isSymbolicLink())
    throw new AccountMigrationError("credential-bearing path is not a regular file");
  privateMode(before.mode, 384);
  const handle = await open(path2, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || before.dev !== opened.dev || before.ino !== opened.ino)
      throw new AccountMigrationError("file identity changed while opening");
    const bytes = await handle.readFile();
    const after = await lstat(path2);
    if (after.dev !== opened.dev || after.ino !== opened.ino || after.isSymbolicLink())
      throw new AccountMigrationError("file identity changed while reading");
    return bytes;
  } finally {
    await handle.close();
  }
}
function jsonBytes(bytes) {
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new AccountMigrationError("malformed or non-UTF8 durable JSON");
  }
}
async function syncFile(path2) {
  await secureRead(path2);
  const handle = await open(path2, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
  await secureRead(path2);
}
function accountMigrationDurability(platform = process.platform) {
  return platform === "win32" ? "windows-reopened-no-directory-power-loss-guarantee" : "posix-directory-synced";
}
async function syncDirectory(path2, boundary) {
  if (process.platform === "win32")
    return;
  await boundary?.("before-directory-sync");
  const handle = await open(path2, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    await handle.sync();
  } finally {
    await handle.close();
  }
  await boundary?.("after-directory-sync");
}
async function exclusiveBytes(path2, bytes, expectedHash, boundary) {
  let handle;
  try {
    handle = await open(path2, "wx", 384);
  } catch (error) {
    if (errno(error) !== "EEXIST")
      throw error;
  }
  if (handle !== void 0) {
    try {
      await handle.writeFile(bytes);
      await handle.sync();
    } finally {
      await handle.close();
    }
  }
  const reopened = await secureRead(path2);
  if (digest(reopened) !== expectedHash || !reopened.equals(bytes))
    throw new AccountMigrationError("exclusive backup or recovery copy differs");
  await syncFile(path2);
  await syncDirectory(dirname(path2), boundary);
}
async function readJournal(paths) {
  if (!await exists(paths.storeDir))
    return void 0;
  const directory = await lstat(paths.storeDir);
  if (!directory.isDirectory() || directory.isSymbolicLink() || !sameFilesystemPath(await realpath(paths.storeDir), paths.storeDir))
    throw new AccountMigrationError("journal directory is an alias or non-directory");
  privateMode(directory.mode, 448);
  if (!await exists(paths.migrationPath))
    return void 0;
  const journal = decodeAccountMigrationJournal(jsonBytes(await secureRead(paths.migrationPath)));
  if (journal.legacyPath !== paths.legacyPath || journal.storeDir !== paths.storeDir)
    throw new AccountMigrationError("journal belongs to another source");
  return journal;
}
async function saveJournal(modules, paths, lease, journal, initial = false, boundary) {
  decodeAccountMigrationJournal(journalJson(journal));
  const stage = journal.id;
  const journalTemp = `${paths.migrationPath}.${stage}.tmp`;
  if (await exists(journalTemp)) {
    const current = await readJournal(paths);
    if (current?.id !== journal.id)
      throw new AccountMigrationError("journal staging file has no durable generation owner");
    await secureRead(journalTemp);
    await lease.assertOwned();
    await unlink(journalTemp);
  }
  await lease.assertOwned();
  await modules.fs.writeJsonAtomic(paths.migrationPath, journalJson(journal), {
    stageName: () => stage,
    beforeRename: async () => {
      await lease.assertOwned();
      const current = await readJournal(paths);
      const owned = typeof initial === "string" ? current?.id === initial && current.status === "inactive" : initial ? current === void 0 : current?.id === journal.id;
      if (!owned)
        throw new AccountMigrationError("journal ownership changed before write");
      await syncFile(`${paths.migrationPath}.${stage}.tmp`);
      await lease.assertOwned();
    }
  });
  await syncFile(paths.migrationPath);
  await syncDirectory(paths.storeDir, boundary);
  const reopened = await readJournal(paths);
  if (!reopened || !isDeepStrictEqual(journalJson(reopened), journalJson(journal)))
    throw new AccountMigrationError("journal readback differs");
  await lease.assertOwned();
}
function openMigrationStore(modules, paths, now, onStep) {
  return modules.store.openPoolStore({
    provider: ACCOUNT_STORE_PROVIDER,
    configPath: paths.configPath,
    statePath: paths.statePath,
    quota: QUOTA_CODEC,
    providerState: {
      validate: isValidProviderState,
      credentialBound: providerStateCredentialBound,
      merge(previous, incoming) {
        if (!isDeepStrictEqual(previous, incoming))
          throw new AccountMigrationError("retry provider state differs from captured manifest");
        return incoming;
      },
      onReplace() {
        throw new AccountMigrationError("offline migration never replaces a credential");
      }
    },
    requireCredentialStamps: true,
    now,
    lockOptions: { timeoutMs: 2e3 },
    ...onStep === void 0 ? {} : { onStep }
  });
}
async function rowsOf(store) {
  const read = await store.read();
  if (read.status !== "ready")
    throw new AccountMigrationError("successor is not a ready public store");
  return read.rows;
}
async function settingsOf(store) {
  const read = await store.readSettings();
  if (read.status !== "ready")
    throw new AccountMigrationError("successor settings are not ready");
  return read.settings;
}
function rowRef(row) {
  const epoch = row.credentialEpoch ?? 1;
  if (!Number.isSafeInteger(epoch) || epoch < 1)
    throw new AccountMigrationError("invalid credential epoch");
  return {
    id: row.id,
    credentialEpoch: epoch,
    ...row.identity === void 0 ? {} : { identity: row.identity }
  };
}
function healthyRow(row, allowTorn = false) {
  row.stamp = "bound";
  row.unbound = false;
  delete row.providerStateDropped;
  row.candidate = row.enabled !== false;
  rowRef(row);
  decodeProviderState(row.providerState);
  if (row.quota !== void 0)
    decodeQuotaState(row.quota);
}
function expectedRouting(journal, rows) {
  const routing = { ...journal.manifest.routing };
  const active2 = rows[journal.manifest.effectiveActiveIndex];
  if (active2 !== void 0)
    routing.activeRow = rowRef(active2);
  const family = journal.manifest.routing.activeIndexByFamily;
  const refs = {};
  for (const name of ["claude", "gemini"]) {
    const cursor = family?.[name] ?? journal.manifest.effectiveActiveIndex;
    const row = rows.length ? rows[cursor % rows.length] : void 0;
    if (row !== void 0)
      refs[name] = rowRef(row);
  }
  if (Object.keys(refs).length)
    routing.activeRowByFamily = refs;
  return routing;
}
function assertImportedRow(row, manifest, id) {
  healthyRow(row);
  if (row.id !== id || row.identity !== void 0 || rowRef(row).credentialEpoch !== 1 || row.credential?.type !== "oauth" || row.credential.refresh !== manifest.refreshToken || row.credential.access !== void 0 || row.credential.expires !== void 0 || row.enabled !== (manifest.metadata.enabled !== false))
    throw new AccountMigrationError("successor credential, lineage, identity or enabled flag differs from manifest");
  const metadata = decodeProviderState(row.providerState);
  if (!isDeepStrictEqual(encodeProviderState(metadata), encodeProviderState({ schemaVersion: 1, metadata: manifest.metadata })) || !isDeepStrictEqual(row.quota, manifest.quota === void 0 ? void 0 : encodeQuotaState(manifest.quota)))
    throw new AccountMigrationError("successor full metadata, quota or presence differs from manifest");
}
async function verifyImported(store, journal) {
  await assertStateOwnership(generationPaths(journal.legacyPath, journal.id), journal, true);
  const rows = await rowsOf(store);
  if (rows.length !== journal.mapping.length)
    throw new AccountMigrationError("successor roster length differs from manifest");
  rows.forEach((row, index) => {
    const mapped = journal.mapping[index];
    const manifest = journal.manifest.accounts[index];
    if (!mapped || !manifest)
      throw new AccountMigrationError("successor manifest mapping is incomplete");
    assertImportedRow(row, manifest, mapped.id);
  });
  const settings = await settingsOf(store);
  if (!isDeepStrictEqual(decodeAccountStoreGeneration(settings[ACCOUNT_STORE_GENERATION_SETTINGS_KEY]), generationJson(journal)))
    throw new AccountMigrationError("successor generation differs from journal");
  if (!isDeepStrictEqual(settings[ROUTING_SETTINGS_KEY], encodeRoutingSettings(expectedRouting(journal, rows))))
    throw new AccountMigrationError("successor order or cursor presence differs from manifest");
}
async function verifyCopies(paths, journal, retired) {
  if (journal.sourceKind === "absent")
    return;
  const backup = await secureRead(join(paths.backupsDir, `${journal.sourceSha256}.json`));
  if (digest(backup) !== journal.sourceSha256)
    throw new AccountMigrationError("backup independent digest differs");
  const capture2 = await secureRead(join(paths.transfersDir, `${journal.id}.capture.json`));
  if (digest(capture2) !== journal.captureSha256 || !isDeepStrictEqual(jsonBytes(capture2), captureJson(journal)))
    throw new AccountMigrationError("journal differs from its exclusive capture snapshot");
  const expected = parseLegacyAccountStorage(new TextDecoder("utf-8", { fatal: true }).decode(backup), journal.manifest.normalizationClock);
  if (!isDeepStrictEqual(manifestJson(expected), manifestJson(journal.manifest)))
    throw new AccountMigrationError("captured manifest differs from its verified original source");
  if (retired) {
    const bytes = await secureRead(join(paths.retiredDir, `${journal.id}.json`));
    if (!bytes.equals(backup) || digest(bytes) !== journal.retiredSha256)
      throw new AccountMigrationError("retired copy and backup association differs");
  }
}
function captureJson(journal) {
  return {
    schemaVersion: 1,
    id: journal.id,
    legacyPath: journal.legacyPath,
    storeDir: journal.storeDir,
    sourceKind: journal.sourceKind,
    sourceSha256: journal.sourceSha256,
    manifest: manifestJson(journal.manifest),
    mapping: journal.mapping
  };
}
async function synchronizedSnapshot(paths, boundary) {
  await syncFile(paths.configPath);
  const statePresent = await exists(paths.statePath);
  if (statePresent)
    await syncFile(paths.statePath);
  await syncDirectory(paths.storeDir, boundary);
  return {
    config: await secureRead(paths.configPath),
    ...statePresent ? { state: await secureRead(paths.statePath) } : {}
  };
}
async function assertStateOwnership(paths, journal, complete) {
  if (complete) {
    const config = object(jsonBytes(await secureRead(paths.configPath)), "successor config");
    const pool = object(config.commonAuthPool, "successor pool");
    const entries = object(pool.rows, "successor entries");
    if (Object.keys(entries).length !== journal.mapping.length || Object.keys(entries).some((id) => !journal.mapping.some((row) => row.id === id)))
      throw new AccountMigrationError("native entry presence differs from manifest");
    const retired = pool.retiredEpochs === void 0 ? {} : object(pool.retiredEpochs, "retired epochs");
    journal.mapping.forEach((mapped, index) => {
      const entry = object(entries[mapped.id], "successor entry");
      const quota = journal.manifest.accounts[index]?.quota;
      if (entry.credentialEpoch !== 1 || Object.hasOwn(retired, mapped.id) || Object.hasOwn(entry, "quota") !== (quota !== void 0) || quota !== void 0 && !isDeepStrictEqual(entry.quota, encodeQuotaState(quota)))
        throw new AccountMigrationError("native epoch or full quota presence differs from manifest");
    });
  }
  if (!await exists(paths.statePath)) {
    if (complete && journal.mapping.length)
      throw new AccountMigrationError("successor state is missing");
    return;
  }
  const state = object(jsonBytes(await secureRead(paths.statePath)), "successor state");
  const accounts = state.accounts === void 0 ? {} : object(state.accounts, "successor state accounts");
  const ids = Object.keys(accounts);
  if (ids.some((id) => !journal.mapping.some((row) => row.id === id)) || complete && ids.length !== journal.mapping.length)
    throw new AccountMigrationError("successor state contains unrelated or missing credentials");
}
async function management(store, journal, clear = false) {
  const targets = journal.rollback?.rows ?? journal.mapping.map((row) => row.id);
  await store.updateSettings((settings) => {
    const prior = settings[MANAGEMENT_SETTINGS_KEY];
    if (prior !== void 0) {
      const p = object(prior, "management");
      if (p.id !== journal.id || p.kind !== "migration" || !isDeepStrictEqual(p.targets, targets))
        throw new AccountMigrationError("management settings belong to another operation");
    }
    if (clear)
      delete settings[MANAGEMENT_SETTINGS_KEY];
    else
      settings[MANAGEMENT_SETTINGS_KEY] = {
        id: journal.id,
        kind: "migration",
        targets,
        progress: {
          step: journal.phase,
          completedTargets: journal.operation === "rollback" ? [] : journal.completedRows
        }
      };
    return settings;
  });
}
function receipt(journal) {
  if (journal.status === "pending")
    throw new AccountMigrationError("pending journal has no serving receipt");
  return {
    id: journal.id,
    status: journal.status,
    legacyPath: journal.legacyPath,
    storeDir: journal.storeDir,
    sourceKind: journal.sourceKind,
    durability: journal.verification?.durability ?? accountMigrationDurability(),
    restartRequired: journal.sourceKind === "file" || journal.operation === "rollback"
  };
}
async function currentSuccessor(store, paths, journal) {
  const config = object(jsonBytes(await secureRead(paths.configPath)), "active config");
  if (config.version !== 1 || !Array.isArray(config.accounts))
    throw new AccountMigrationError("active config lacks its native roster");
  const pool = object(config.commonAuthPool, "active native pool");
  if (pool.schemaVersion !== 1)
    throw new AccountMigrationError("active native pool schema differs");
  const entries = object(pool.rows, "active entries");
  if (pool.retiredEpochs !== void 0) {
    for (const [id, epoch] of Object.entries(object(pool.retiredEpochs, "retained epochs"))) {
      if (!UUID.test(id) || !Number.isSafeInteger(epoch) || typeof epoch !== "number" || epoch < 1)
        throw new AccountMigrationError("retained epoch record is invalid");
    }
  }
  const nativeIds = config.accounts.map((item) => text(object(item, "active roster row").id, UUID, "active row id"));
  if (new Set(nativeIds).size !== nativeIds.length || Object.keys(entries).length !== nativeIds.length || Object.keys(entries).some((id) => !nativeIds.includes(id)))
    throw new AccountMigrationError("active native entry/roster presence differs");
  let stateAccounts = {};
  if (await exists(paths.statePath)) {
    const state = object(jsonBytes(await secureRead(paths.statePath)), "active state");
    if (state.version !== 1)
      throw new AccountMigrationError("active native state schema differs");
    stateAccounts = object(state.accounts, "active state accounts");
  }
  if (Object.keys(stateAccounts).length !== nativeIds.length || Object.keys(stateAccounts).some((id) => !nativeIds.includes(id)))
    throw new AccountMigrationError("active state contains orphan or missing credentials");
  const rows = await rowsOf(store);
  if (!isDeepStrictEqual(rows.map((row) => row.id), nativeIds))
    throw new AccountMigrationError("public and native active roster order differs");
  rows.forEach((row) => {
    healthyRow(row);
    const entry = object(entries[row.id], "active native entry");
    if (entry.credentialEpoch !== rowRef(row).credentialEpoch || Object.hasOwn(entry, "quota") !== (row.quota !== void 0) || row.quota !== void 0 && !isDeepStrictEqual(entry.quota, row.quota))
      throw new AccountMigrationError("active native epoch or quota presence differs from public row");
  });
  const settings = await settingsOf(store);
  if (!isDeepStrictEqual(decodeAccountStoreGeneration(settings[ACCOUNT_STORE_GENERATION_SETTINGS_KEY]), generationJson(journal)))
    throw new AccountMigrationError("active generation setting differs from journal");
  decodeRoutingSettings(settings[ROUTING_SETTINGS_KEY]);
}
function openAdmissionStore(modules, paths, now) {
  return modules.store.openPoolStore({
    provider: ACCOUNT_STORE_PROVIDER,
    configPath: paths.configPath,
    statePath: paths.statePath,
    quota: QUOTA_CODEC,
    providerState: {
      validate: isValidProviderState,
      credentialBound: providerStateCredentialBound,
      merge() {
        throw new AccountMigrationError("binding/admission performs no provider-state writes");
      },
      onReplace() {
        throw new AccountMigrationError("binding/admission performs no credential replacements");
      }
    },
    requireCredentialStamps: true,
    now
  });
}
async function trustedCurrentGeneration(store, paths, journal) {
  const config = object(jsonBytes(await secureRead(paths.configPath)), "bound config");
  if (config.version !== 1 || !Array.isArray(config.accounts))
    throw new AccountMigrationError("bound config lacks its native roster");
  const pool = object(config.commonAuthPool, "bound native pool");
  if (pool.schemaVersion !== 1)
    throw new AccountMigrationError("bound native pool schema differs");
  object(pool.rows, "bound native entries");
  if (await exists(paths.statePath)) {
    const state = object(jsonBytes(await secureRead(paths.statePath)), "bound native state");
    if (state.version !== 1)
      throw new AccountMigrationError("bound native state schema differs");
    object(state.accounts, "bound state accounts");
  }
  const settings = await settingsOf(store);
  if (!isDeepStrictEqual(decodeAccountStoreGeneration(settings[ACCOUNT_STORE_GENERATION_SETTINGS_KEY]), generationJson(journal)))
    throw new AccountMigrationError("bound generation setting differs from completed journal");
  return settings;
}
async function readAccountStoreBinding(legacyPath, modules, now, expectedGeneration) {
  try {
    const paths = await resolvePublishedAccountStorePaths(legacyPath);
    if (!paths)
      return await exists(legacyPath) ? { status: "pending" } : { status: "initialization-required" };
    const journal = await readJournal(paths);
    if (!journal)
      throw new AccountMigrationError("published binding journal missing");
    if (expectedGeneration !== void 0 && journal.id !== expectedGeneration)
      throw new AccountMigrationError("bound repository generation differs from pointer");
    if (journal.status === "pending")
      return {
        status: "pending",
        phase: journal.phase,
        operation: journal.operation
      };
    if (journal.status === "inactive")
      return { status: "inactive", id: journal.id };
    if (await exists(legacyPath))
      throw new AccountMigrationError("legacy source was recreated after activation");
    await verifyCopies(paths, journal, true);
    const settings = await trustedCurrentGeneration(openAdmissionStore(modules, paths, now), paths, journal);
    const pending = settings[MANAGEMENT_SETTINGS_KEY];
    if (pending !== void 0) {
      const record2 = object(pending, "repository management");
      if (record2.kind === "migration")
        return { status: "pending", phase: "activate", operation: "migrate" };
      if (record2.kind !== "clear" && record2.kind !== "replace-pool")
        throw new AccountMigrationError("unknown management owner prevents binding");
    }
    return { status: "bound", receipt: receipt(journal), paths };
  } catch (error) {
    return {
      status: "error",
      reason: error instanceof AccountMigrationError ? error.reason : "journal, backup or generation binding validation failed"
    };
  }
}
async function assertLegacyAccountStorageWritable(legacyPath) {
  const paths = await resolvePublishedAccountStorePaths(resolve(legacyPath));
  if (paths === void 0)
    return;
  const journal = await readJournal(paths);
  if (journal === void 0 && (await exists(paths.configPath) || await exists(paths.statePath)))
    throw new AccountMigrationError("unowned successor files refuse legacy writes");
  if (journal !== void 0 && journal.status !== "inactive")
    throw new AccountMigrationError("legacy storage is owned by the account store; use offline rollback before old-build writes");
}
async function capture(modules, paths, lease, options, previous) {
  await options.onBoundary?.("before-capture");
  const captured = await modules.fs.withLock(paths.legacyPath, { name: "accounts", ttlMs: 1e4, timeoutMs: 2e3, renew: true }, async (accountsLease) => {
    await accountsLease.assertOwned();
    await lease.assertOwned();
    const bytes = await secureRead(paths.legacyPath);
    const manifest = parseLegacyAccountStorage(new TextDecoder("utf-8", { fatal: true }).decode(bytes), options.now());
    const sourceSha256 = digest(bytes);
    await options.onBoundary?.("capture:before-backup");
    await exclusiveBytes(join(paths.backupsDir, `${sourceSha256}.json`), bytes, sourceSha256, options.onBoundary);
    const journal = {
      schemaVersion: 1,
      id: pathGenerationId(paths),
      legacyPath: paths.legacyPath,
      storeDir: paths.storeDir,
      status: "pending",
      operation: "migrate",
      phase: "capture",
      sourceKind: "file",
      sourceSha256,
      manifest,
      mapping: manifest.accounts.map((row) => ({
        id: randomUUID(),
        ordinal: row.ordinal
      })),
      completedRows: []
    };
    const captureBytes = Buffer.from(`${JSON.stringify(captureJson(journal), null, 2)}
`);
    journal.captureSha256 = digest(captureBytes);
    await exclusiveBytes(join(paths.transfersDir, `${journal.id}.capture.json`), captureBytes, journal.captureSha256, options.onBoundary);
    await accountsLease.assertOwned();
    await lease.assertOwned();
    if (previous !== void 0) {
      const archived = Buffer.from(`${JSON.stringify(journalJson(previous), null, 2)}
`);
      await exclusiveBytes(join(paths.transfersDir, `${previous.id}.journal.json`), archived, digest(archived), options.onBoundary);
    }
    await saveJournal(modules, paths, lease, journal, true, options.onBoundary);
    return journal;
  });
  return captured;
}
async function build(store, modules, paths, lease, journal, options) {
  await options.onBoundary?.("before-build");
  await assertStateOwnership(paths, journal, false);
  if (!journal.mapping.length && !await exists(paths.configPath)) {
    const bootstrap = Buffer.from('{"version":1,"accounts":[]}\n');
    await exclusiveBytes(paths.configPath, bootstrap, digest(bootstrap), options.onBoundary);
  }
  await store.initialize();
  const known = await rowsOf(store);
  if (known.some((row) => !journal.mapping.some((mapped) => mapped.id === row.id)))
    throw new AccountMigrationError("build found unrelated successor rows");
  for (let index = 0; index < journal.mapping.length; index++) {
    const mapped = journal.mapping[index];
    const source = journal.manifest.accounts[index];
    if (!mapped || !source)
      throw new AccountMigrationError("captured row mapping is incomplete");
    await lease.assertOwned();
    const before = (await rowsOf(store)).find((row2) => row2.id === mapped.id);
    if (journal.completedRows.includes(mapped.id)) {
      if (!before)
        throw new AccountMigrationError("acknowledged successor row disappeared");
      assertImportedRow(before, source, mapped.id);
      continue;
    }
    if (before === void 0) {
      const result = await store.add({
        id: mapped.id,
        credential: { type: "oauth", refresh: source.refreshToken },
        providerState: encodeProviderState({
          schemaVersion: 1,
          metadata: source.metadata
        })
      }, { extraLocks: [legacyAccountsLock(paths.legacyPath)] });
      if (result.id !== mapped.id)
        throw new AccountMigrationError("public add deduplicated onto an unrelated UUID");
    } else {
      healthyRow(before, true);
      if (before.credential?.type !== "oauth" || before.credential.refresh !== source.refreshToken)
        throw new AccountMigrationError("unacknowledged row differs from captured credential");
    }
    const row = (await rowsOf(store)).find((candidate) => candidate.id === mapped.id);
    if (!row)
      throw new AccountMigrationError("public add has no successor row");
    const fence = rowRef(row);
    if (source.metadata.enabled === false)
      await store.disable(mapped.id, "legacy-disabled", {
        attribution: fence,
        extraLocks: [legacyAccountsLock(paths.legacyPath)]
      });
    else if (row.torn || !row.enabled)
      await store.enable(mapped.id, {
        attribution: fence,
        extraLocks: [legacyAccountsLock(paths.legacyPath)]
      });
    if (source.quota !== void 0) {
      const fresh = (await rowsOf(store)).find((candidate) => candidate.id === mapped.id);
      if (!fresh)
        throw new AccountMigrationError("quota successor row disappeared");
      await store.recordQuota(mapped.id, rowRef(fresh), encodeQuotaState(source.quota));
    }
    const actual = (await rowsOf(store)).find((candidate) => candidate.id === mapped.id);
    if (!actual)
      throw new AccountMigrationError("imported row disappeared");
    assertImportedRow(actual, source, mapped.id);
    journal.completedRows.push(mapped.id);
    await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
    await management(store, journal);
  }
  await store.reorder(journal.mapping.map((row) => row.id));
  const routing = expectedRouting(journal, await rowsOf(store));
  await store.updateSettings((settings) => {
    settings[ROUTING_SETTINGS_KEY] = encodeRoutingSettings(routing);
    return settings;
  });
  await store.updateSettings((settings) => {
    const prior = settings[ACCOUNT_STORE_GENERATION_SETTINGS_KEY];
    if (prior !== void 0 && !isDeepStrictEqual(decodeAccountStoreGeneration(prior), generationJson(journal)))
      throw new AccountMigrationError("build cannot overwrite another generation");
    settings[ACCOUNT_STORE_GENERATION_SETTINGS_KEY] = generationJson(journal);
    return settings;
  });
  await management(store, journal);
  await options.onBoundary?.("after-build");
}
async function verify(store, paths, journal, options) {
  await options.onBoundary?.("before-verify");
  await verifyCopies(paths, journal, false);
  await assertStateOwnership(paths, journal, true);
  await verifyImported(store, journal);
  const snapshot2 = await synchronizedSnapshot(paths, options.onBoundary);
  await verifyImported(store, journal);
  journal.verification = {
    manifestSha256: digest(canonical2(manifestJson(journal.manifest))),
    configSha256: digest(snapshot2.config),
    ...snapshot2.state === void 0 ? {} : { stateSha256: digest(snapshot2.state) },
    statePresent: snapshot2.state !== void 0,
    durability: accountMigrationDurability()
  };
  await options.onBoundary?.("after-verify");
}
async function retire(store, modules, paths, lease, journal, options) {
  await options.onBoundary?.("before-retire");
  await verifyImported(store, journal);
  await assertStateOwnership(paths, journal, true);
  await synchronizedSnapshot(paths, options.onBoundary);
  await verifyImported(store, journal);
  await verifyCopies(paths, journal, false);
  const sourceSha256 = journal.sourceSha256;
  if (journal.sourceKind !== "file" || sourceSha256 === void 0)
    throw new AccountMigrationError("file retirement requires a captured source hash");
  await modules.fs.withLock(paths.legacyPath, { name: "accounts", ttlMs: 1e4, timeoutMs: 2e3, renew: true }, async (accountsLease) => {
    await lease.assertOwned();
    await accountsLease.assertOwned();
    const retiredPath = join(paths.retiredDir, `${journal.id}.json`);
    if (await exists(paths.legacyPath)) {
      const source = await secureRead(paths.legacyPath);
      if (digest(source) !== sourceSha256)
        throw new AccountMigrationError("legacy source changed since capture");
      await exclusiveBytes(retiredPath, source, sourceSha256, options.onBoundary);
      await lease.assertOwned();
      await accountsLease.assertOwned();
      if (digest(await secureRead(paths.legacyPath)) !== journal.sourceSha256)
        throw new AccountMigrationError("legacy source changed before unlink");
      await syncDirectory(dirname(paths.legacyPath), options.onBoundary);
      await lease.assertOwned();
      await accountsLease.assertOwned();
      await unlink(paths.legacyPath);
    } else {
      if (!journal.verification || digest(await secureRead(retiredPath)) !== journal.sourceSha256)
        throw new AccountMigrationError("missing source has no verified retirement association");
    }
    try {
      await syncDirectory(dirname(paths.legacyPath), options.onBoundary);
    } catch (error) {
      await lease.assertOwned();
      await accountsLease.assertOwned();
      if (!await exists(paths.legacyPath)) {
        try {
          const recovery = await secureRead(retiredPath);
          await exclusiveBytes(paths.legacyPath, recovery, sourceSha256);
        } catch {
          throw new AccountMigrationError("retirement directory sync failed; verified recovery copies retained and exclusive source restoration could not be acknowledged");
        }
      }
      throw error;
    }
    journal.retiredSha256 = journal.sourceSha256;
    await verifyCopies(paths, journal, true);
  });
  await options.onBoundary?.("after-retire");
}
async function discardInactive(store, paths, journal) {
  await makeCancelledSeedReady(store, paths, journal);
  const targets = journal.rollback?.rows ?? journal.mapping.map((row) => row.id);
  const owned = {
    ...journal,
    mapping: targets.map((id, ordinal) => ({ id, ordinal }))
  };
  await assertStateOwnership(paths, owned, false);
  for (const id of targets) {
    const rows = await rowsOf(store);
    const state = await exists(paths.statePath) ? object(jsonBytes(await secureRead(paths.statePath)), "inactive state") : {};
    const accounts = state.accounts === void 0 ? {} : object(state.accounts, "inactive state accounts");
    if (rows.some((row) => row.id === id) || Object.hasOwn(accounts, id))
      await store.remove(id);
  }
  if ((await rowsOf(store)).length)
    throw new AccountMigrationError("inactive successor contains unrelated rows");
  await management(store, journal, true);
  await store.updateSettings((settings) => {
    const prior = settings[ACCOUNT_STORE_GENERATION_SETTINGS_KEY];
    if (prior !== void 0 && !isDeepStrictEqual(decodeAccountStoreGeneration(prior), generationJson(journal)))
      throw new AccountMigrationError("inactive generation setting belongs to another journal");
    delete settings[ACCOUNT_STORE_GENERATION_SETTINGS_KEY];
    return settings;
  });
}
async function makeCancelledSeedReady(store, paths, journal) {
  const read = await store.read();
  if (read.status === "pending-migration") {
    const config = jsonBytes(await secureRead(paths.configPath));
    if (!journal.cancelled || journal.mapping.length || !isDeepStrictEqual(config, { version: 1, accounts: [] }))
      throw new AccountMigrationError("cancellation cannot adopt an unrelated pending config");
    await store.initialize();
  } else if (read.status === "error")
    throw new AccountMigrationError("cancellation successor could not be read");
}
async function finishCancellation(store, modules, paths, lease, journal, options) {
  if (!journal.cancelled || journal.sourceKind !== "file" || digest(await secureRead(paths.legacyPath)) !== journal.sourceSha256)
    throw new AccountMigrationError("cancellation requires its unchanged unserved source");
  await verifyCopies(paths, journal, false);
  await makeCancelledSeedReady(store, paths, journal);
  await management(store, journal, true);
  await modules.fs.withLock(paths.legacyPath, { name: "accounts", ttlMs: 1e4, timeoutMs: 2e3, renew: true }, async (accountsLease) => {
    await accountsLease.assertOwned();
    await lease.assertOwned();
    if (digest(await secureRead(paths.legacyPath)) !== journal.sourceSha256)
      throw new AccountMigrationError("cancellation source changed before acknowledgment");
    journal.status = "inactive";
    journal.phase = "activate";
    await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
  });
  return { status: "completed", receipt: receipt(journal) };
}
function createAccountMigrationFactory(modules) {
  return async (options) => {
    if (options.offline?.processesStopped !== true)
      throw new AccountMigrationError("stopped processes and timers must be explicitly confirmed");
    resolveAccountStorePaths(options.legacyPath);
    try {
      return await withParentTopology(modules, options.legacyPath, async (parentLease) => {
        const prior = await readPointer(options.legacyPath);
        if (prior)
          await finishPointerPublication(options.legacyPath, prior, parentLease);
        let paths = prior ? generationPaths(options.legacyPath, prior.id) : void 0;
        let previous;
        if (paths) {
          const existing = await readJournal(paths);
          if (!existing)
            throw new AccountMigrationError("published generation journal missing");
          if (existing.status === "inactive") {
            previous = existing;
            await modules.fs.withLock(paths.configPath, {
              name: MANAGEMENT_LOCK_NAME,
              ttlMs: 1e4,
              timeoutMs: 2e3,
              renew: true
            }, async (oldLease) => {
              if (!paths)
                throw new AccountMigrationError("inactive physical paths missing");
              const oldStore = openMigrationStore(modules, paths, options.now, writeObserver(paths, oldLease, options.onBoundary));
              await discardInactive(oldStore, paths, existing);
            });
            paths = void 0;
          }
        }
        if (paths === void 0) {
          if (!await exists(options.legacyPath))
            throw new AccountMigrationError("absent source requires explicit fresh initialization");
          paths = await allocateGeneration(options.legacyPath);
        }
        const physical = paths;
        return modules.fs.withLock(physical.configPath, {
          name: MANAGEMENT_LOCK_NAME,
          ttlMs: 1e4,
          timeoutMs: 2e3,
          renew: true
        }, async (lease) => {
          let journal = await readJournal(physical);
          if (journal === void 0) {
            journal = await capture(modules, physical, lease, options, previous);
            await modules.fs.withLock(physical.legacyPath, {
              name: "accounts",
              ttlMs: 1e4,
              timeoutMs: 2e3,
              renew: true
            }, async (accountsLease) => {
              await accountsLease.assertOwned();
              if (digest(await secureRead(physical.legacyPath)) !== journal?.sourceSha256)
                throw new AccountMigrationError("source changed before pointer publication");
              if (!journal)
                throw new AccountMigrationError("capture journal missing");
              await publishGenerationPointer(modules, physical, journal, parentLease, prior, options.onBoundary);
            });
            await options.onBoundary?.("after-capture");
          }
          await assertPublishedAccountStoreGeneration(physical);
          const store = openMigrationStore(modules, physical, options.now, writeObserver(physical, lease, options.onBoundary));
          if (journal.status === "active") {
            if (await exists(physical.legacyPath))
              throw new AccountMigrationError("legacy source was recreated after activation");
            await verifyCopies(physical, journal, true);
            await currentSuccessor(store, physical, journal);
            await management(store, journal, true);
            return { status: "completed", receipt: receipt(journal) };
          }
          if (journal.operation === "rollback")
            throw new AccountMigrationError("resume offline rollback before re-migration");
          if (journal.sourceKind === "absent")
            throw new AccountMigrationError("resume explicit fresh initialization; never adopt an appearing source");
          await verifyCopies(physical, journal, false);
          if (journal.phase === "capture" || journal.phase === "build") {
            journal.phase = "build";
            await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
            await build(store, modules, physical, lease, journal, options);
            journal.phase = "verify";
            await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
          }
          if (journal.phase === "verify") {
            await verify(store, physical, journal, options);
            journal.phase = "retire";
            await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
            await management(store, journal);
          }
          if (journal.phase === "retire") {
            await retire(store, modules, physical, lease, journal, options);
            journal.phase = "activate";
            await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
          }
          await options.onBoundary?.("before-activate");
          await verifyImported(store, journal);
          await verifyCopies(physical, journal, true);
          if (await exists(physical.legacyPath))
            throw new AccountMigrationError("legacy source reappeared before activation");
          journal.status = "active";
          await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
          await management(store, journal, true);
          await options.onBoundary?.("after-activate");
          return { status: "completed", receipt: receipt(journal) };
        });
      });
    } catch (error) {
      const pending = pendingLockFailure(modules, error);
      if (pending)
        return pending;
      throw error;
    }
  };
}
function refMatches(ref, row) {
  return ref !== null && ref !== void 0 && isDeepStrictEqual(ref, rowRef(row));
}
function exportRouting(routing, rows) {
  const result = { ...routing };
  const global = rows.findIndex((row) => refMatches(routing.activeRow, row));
  const effective = rows.length ? Math.max(0, Math.min(routing.activeIndex ?? 0, rows.length - 1)) : 0;
  if (global >= 0 && global !== effective)
    result.activeIndex = global;
  const fallback = rows.length ? Math.max(0, Math.min(result.activeIndex ?? 0, rows.length - 1)) : 0;
  for (const family of ["claude", "gemini"]) {
    const index = rows.findIndex((row) => refMatches(routing.activeRowByFamily?.[family], row));
    const cursor = rows.length ? (routing.activeIndexByFamily?.[family] ?? fallback) % rows.length : 0;
    if (index >= 0 && index !== cursor)
      result.activeIndexByFamily = {
        ...result.activeIndexByFamily,
        [family]: index
      };
  }
  return result;
}
async function exportCurrent(store) {
  const rows = await rowsOf(store);
  const settings = await settingsOf(store);
  const routing = decodeRoutingSettings(settings[ROUTING_SETTINGS_KEY]);
  const accounts = rows.map((row, ordinal) => {
    healthyRow(row);
    if (row.credential?.type !== "oauth")
      throw new AccountMigrationError("rollback cannot export a non-OAuth row");
    const metadata = decodeProviderState(row.providerState).metadata;
    if (metadata.enabled !== false !== row.enabled)
      throw new AccountMigrationError("current enabled encoding differs from native row");
    return {
      ordinal,
      refreshToken: row.credential.refresh,
      metadata,
      ...row.quota === void 0 ? {} : { quota: decodeQuotaState(row.quota) }
    };
  });
  return {
    rows: rows.map((row) => row.id),
    exported: exportLegacyAccountStorage(accounts, exportRouting(routing, rows))
  };
}
async function rollbackSnapshot(paths, journal) {
  const rollback = journal.rollback;
  if (!rollback)
    throw new AccountMigrationError("rollback snapshot association is absent");
  const bytes = await secureRead(join(paths.transfersDir, `${rollback.id}.json`));
  if (digest(bytes) !== rollback.snapshotSha256)
    throw new AccountMigrationError("current-credential snapshot digest differs");
  const snapshot2 = exact(jsonBytes(bytes), ["config", "state", "exported"], "rollback snapshot");
  if (typeof snapshot2.config !== "string" || snapshot2.state !== void 0 && typeof snapshot2.state !== "string")
    throw new AccountMigrationError("rollback snapshot file encoding is invalid");
  const exported = object(snapshot2.exported, "rollback export");
  if (digest(`${JSON.stringify(exported, null, 2)}
`) !== rollback.exportSha256)
    throw new AccountMigrationError("rollback export association differs");
  if (exported.version !== 4)
    throw new AccountMigrationError("rollback export is not v4");
  const accounts = list(exported.accounts, "rollback export accounts").map((row, ordinal) => parseAccount(row, ordinal, 4, journal.manifest.normalizationClock));
  const copied = exportLegacyAccountStorage(accounts, legacyRouting(exported));
  if (!isDeepStrictEqual(copied, exported))
    throw new AccountMigrationError("rollback export does not roundtrip losslessly");
  return {
    config: snapshot2.config,
    ...snapshot2.state === void 0 ? {} : { state: snapshot2.state },
    exported: copied
  };
}
function createAccountRollbackFactory(modules) {
  return async (options) => {
    if (options.offline?.processesStopped !== true)
      throw new AccountMigrationError("stopped processes and timers must be explicitly confirmed");
    try {
      return await withParentTopology(modules, options.legacyPath, async () => {
        const paths = await resolvePublishedAccountStorePaths(options.legacyPath);
        if (!paths)
          throw new AccountMigrationError("rollback requires a published generation");
        return modules.fs.withLock(paths.configPath, {
          name: MANAGEMENT_LOCK_NAME,
          ttlMs: 1e4,
          timeoutMs: 2e3,
          renew: true
        }, async (lease) => {
          const initialJournal = await readJournal(paths);
          if (!initialJournal)
            throw new AccountMigrationError("rollback requires an owned migration generation");
          let journal = initialJournal;
          const store = openMigrationStore(modules, paths, options.now, writeObserver(paths, lease, options.onBoundary));
          if (journal.status === "inactive") {
            if (journal.cancelled) {
              return finishCancellation(store, modules, paths, lease, journal, options);
            } else {
              await rollbackSnapshot(paths, journal);
              if (digest(await secureRead(paths.legacyPath)) !== journal.rollback?.exportSha256)
                throw new AccountMigrationError("restored legacy bytes changed after rollback");
            }
            return { status: "completed", receipt: receipt(journal) };
          }
          if (journal.status === "pending" && journal.cancelled)
            return finishCancellation(store, modules, paths, lease, journal, options);
          if (journal.status === "pending" && journal.operation === "migrate") {
            if (journal.sourceKind === "absent")
              throw new AccountMigrationError("unserved fresh initialization resumes explicitly; no legacy file can be restored");
            if (!["capture", "build", "verify"].includes(journal.phase) || digest(await secureRead(paths.legacyPath)) !== journal.sourceSha256)
              throw new AccountMigrationError("pre-retirement cancellation requires unchanged, unserved legacy source");
            await verifyCopies(paths, journal, false);
            journal = {
              ...journal,
              status: "pending",
              operation: "rollback",
              phase: "capture",
              cancelled: true
            };
            await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
            return finishCancellation(store, modules, paths, lease, journal, options);
          }
          if (journal.status === "active") {
            const active2 = journal;
            await currentSuccessor(store, paths, journal);
            if (await exists(paths.legacyPath))
              throw new AccountMigrationError("rollback refuses an existing or recreated legacy source");
            await verifyCopies(paths, journal, true);
            await options.onBoundary?.("rollback:before-capture");
            await modules.fs.withLock(paths.configPath, { name: "save", ttlMs: 1e4, timeoutMs: 2e3, renew: true }, async (configLease) => {
              await modules.fs.withLock(paths.statePath, {
                name: "save",
                ttlMs: 1e4,
                timeoutMs: 2e3,
                renew: true
              }, async (stateLease) => {
                const current2 = await exportCurrent(store);
                const files = await synchronizedSnapshot(paths, options.onBoundary);
                const snapshot3 = Buffer.from(`${JSON.stringify({ config: files.config.toString("base64"), ...files.state === void 0 ? {} : { state: files.state.toString("base64") }, exported: current2.exported }, null, 2)}
`);
                const rollback2 = {
                  id: randomUUID(),
                  snapshotSha256: digest(snapshot3),
                  exportSha256: digest(`${JSON.stringify(current2.exported, null, 2)}
`),
                  rows: current2.rows,
                  successorInactive: false
                };
                await exclusiveBytes(join(paths.transfersDir, `${rollback2.id}.json`), snapshot3, rollback2.snapshotSha256, options.onBoundary);
                await configLease.assertOwned();
                await stateLease.assertOwned();
                journal = {
                  ...active2,
                  status: "pending",
                  operation: "rollback",
                  phase: "capture",
                  rollback: rollback2
                };
                await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
              });
            });
            await options.onBoundary?.("rollback:after-capture");
          }
          const rollback = journal.rollback;
          if (!rollback)
            throw new AccountMigrationError("rollback snapshot is incomplete");
          const snapshot2 = await rollbackSnapshot(paths, journal);
          if (journal.phase === "capture" || journal.phase === "build") {
            journal.phase = "build";
            await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
            await options.onBoundary?.("rollback:before-build");
            await management(store, journal);
            await options.onBoundary?.("rollback:after-build");
            journal.phase = "verify";
            await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
          }
          if (journal.phase === "verify") {
            await options.onBoundary?.("rollback:before-verify");
            await currentSuccessor(store, paths, journal);
            const current2 = await exportCurrent(store);
            if (!isDeepStrictEqual(current2.rows, rollback.rows) || !isDeepStrictEqual(current2.exported, snapshot2.exported))
              throw new AccountMigrationError("current credentials or full metadata changed during rollback");
            await synchronizedSnapshot(paths, options.onBoundary);
            await verifyCopies(paths, journal, true);
            await options.onBoundary?.("rollback:after-verify");
            journal.phase = "retire";
            await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
          }
          if (journal.phase === "retire") {
            await options.onBoundary?.("rollback:before-retire");
            rollback.successorInactive = true;
            await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
            await management(store, journal);
            await options.onBoundary?.("rollback:after-retire");
            journal.phase = "activate";
            await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
          }
          await options.onBoundary?.("rollback:before-activate");
          await currentSuccessor(store, paths, journal);
          const current = await exportCurrent(store);
          if (!isDeepStrictEqual(current.rows, rollback.rows) || !isDeepStrictEqual(current.exported, snapshot2.exported))
            throw new AccountMigrationError("current successor changed before exclusive legacy restoration");
          await synchronizedSnapshot(paths, options.onBoundary);
          const exportSha256 = rollback.exportSha256;
          await modules.fs.withLock(paths.legacyPath, {
            name: "accounts",
            ttlMs: 1e4,
            timeoutMs: 2e3,
            renew: true
          }, async (accountsLease) => {
            await lease.assertOwned();
            await accountsLease.assertOwned();
            const bytes = Buffer.from(`${JSON.stringify(snapshot2.exported, null, 2)}
`);
            await exclusiveBytes(paths.legacyPath, bytes, exportSha256, options.onBoundary);
            await accountsLease.assertOwned();
            journal.status = "inactive";
            await saveJournal(modules, paths, lease, journal, false, options.onBoundary);
          });
          await management(store, journal, true);
          await options.onBoundary?.("rollback:after-activate");
          return { status: "completed", receipt: receipt(journal) };
        });
      });
    } catch (error) {
      const pending = pendingLockFailure(modules, error);
      if (pending !== void 0)
        return pending;
      throw error;
    }
  };
}
async function assertSourceAbsent(paths) {
  if (await exists(paths.legacyPath))
    throw new AccountMigrationError("fresh initialization refuses an existing or appearing legacy source");
}
async function expectedFreshArtifacts(paths, journal) {
  if (journal.sourceKind !== "absent" || journal.operation !== "migrate" || journal.mapping.length)
    throw new AccountMigrationError("journal is not an owned fresh initialization");
  await assertSourceAbsent(paths);
  await verifyCopies(paths, journal, false);
  if (await exists(paths.statePath))
    throw new AccountMigrationError("fresh initialization found unrelated credential artifacts");
  if (!await exists(paths.configPath))
    return;
  if (journal.phase === "capture")
    throw new AccountMigrationError("fresh capture has an unexpected config artifact");
  const config = exact(jsonBytes(await secureRead(paths.configPath)), [
    "version",
    "accounts",
    "commonAuthPool",
    MANAGEMENT_SETTINGS_KEY,
    ROUTING_SETTINGS_KEY,
    ACCOUNT_STORE_GENERATION_SETTINGS_KEY
  ], "fresh config");
  if (config.version !== 1 || list(config.accounts, "fresh roster").length)
    throw new AccountMigrationError("fresh successor is not the expected empty roster");
  if (config.commonAuthPool === void 0) {
    if (journal.phase !== "build" || !isDeepStrictEqual(config, { version: 1, accounts: [] }))
      throw new AccountMigrationError("fresh seed has an unrelated association");
    return;
  }
  const pool = exact(config.commonAuthPool, ["schemaVersion", "rows", "retiredEpochs"], "fresh pool");
  if (pool.schemaVersion !== 1 || Object.keys(object(pool.rows, "fresh entries")).length || pool.retiredEpochs !== void 0 && Object.keys(object(pool.retiredEpochs, "fresh retired epochs")).length)
    throw new AccountMigrationError("fresh pool contains credential or epoch artifacts");
  const managementRecord = config[MANAGEMENT_SETTINGS_KEY];
  if (managementRecord !== void 0) {
    const m = exact(managementRecord, ["id", "kind", "targets", "progress"], "fresh management");
    const p = exact(m.progress, ["step", "completedTargets"], "fresh progress");
    if (m.id !== journal.id || m.kind !== "migration" || list(m.targets, "fresh targets").length || list(p.completedTargets, "fresh completions").length || !ACCOUNT_MIGRATION_PHASES.some((phase) => phase === p.step))
      throw new AccountMigrationError("fresh management ownership differs");
  }
  if (config[ROUTING_SETTINGS_KEY] !== void 0 && !isDeepStrictEqual(config[ROUTING_SETTINGS_KEY], { schemaVersion: 1 }))
    throw new AccountMigrationError("fresh cursor encoding has an unrelated association");
  if (config[ACCOUNT_STORE_GENERATION_SETTINGS_KEY] !== void 0 && !isDeepStrictEqual(decodeAccountStoreGeneration(config[ACCOUNT_STORE_GENERATION_SETTINGS_KEY]), generationJson(journal)))
    throw new AccountMigrationError("fresh generation setting differs");
}
async function initializeFreshAccountStore(modules, options) {
  resolveAccountStorePaths(options.legacyPath);
  try {
    return await withParentTopology(modules, options.legacyPath, async (parentLease) => {
      await assertSourceAbsent(resolveAccountStorePaths(options.legacyPath));
      const pointer = await readPointer(options.legacyPath);
      if (pointer)
        await finishPointerPublication(options.legacyPath, pointer, parentLease);
      const physical = pointer ? generationPaths(options.legacyPath, pointer.id) : await allocateGeneration(options.legacyPath);
      return modules.fs.withLock(physical.configPath, {
        name: MANAGEMENT_LOCK_NAME,
        ttlMs: 1e4,
        timeoutMs: 2e3,
        renew: true
      }, async (lease) => {
        let journal = await readJournal(physical);
        if (pointer === void 0) {
          await options.onBoundary?.("before-capture");
          await assertSourceAbsent(physical);
          await modules.fs.withLock(physical.legacyPath, {
            name: "accounts",
            ttlMs: 1e4,
            timeoutMs: 2e3,
            renew: true
          }, async (accountsLease) => {
            await assertSourceAbsent(physical);
            await accountsLease.assertOwned();
            await lease.assertOwned();
            if (journal !== void 0 || await exists(physical.configPath) || await exists(physical.statePath))
              throw new AccountMigrationError("fresh stage has unrelated artifacts");
            journal = {
              schemaVersion: 1,
              id: pathGenerationId(physical),
              legacyPath: physical.legacyPath,
              storeDir: physical.storeDir,
              sourceKind: "absent",
              status: "pending",
              operation: "migrate",
              phase: "capture",
              manifest: {
                sourceVersion: null,
                normalizationClock: options.now(),
                accounts: [],
                routing: { schemaVersion: 1 },
                effectiveActiveIndex: 0
              },
              mapping: [],
              completedRows: []
            };
            await saveJournal(modules, physical, lease, journal, true, options.onBoundary);
            await options.onBoundary?.("pointer:before-publication");
            await assertSourceAbsent(physical);
            await publishGenerationPointer(modules, physical, journal, parentLease, void 0, options.onBoundary);
            await options.onBoundary?.("pointer:after-publication");
          });
        }
        if (journal?.sourceKind !== "absent" || journal.operation !== "migrate" || journal.status === "inactive")
          throw new AccountMigrationError("fresh resume has no compatible pointed generation");
        await assertPublishedAccountStoreGeneration(physical);
        const guardBoundary = async (name) => {
          await assertSourceAbsent(physical);
          await options.onBoundary?.(name);
          await assertSourceAbsent(physical);
          await lease.assertOwned();
        };
        const store = openMigrationStore(modules, physical, options.now, writeObserver(physical, lease, guardBoundary));
        if (journal.status === "active") {
          await verifyCopies(physical, journal, false);
          await currentSuccessor(store, physical, journal);
          await management(store, journal, true);
          return { status: "completed", receipt: receipt(journal) };
        }
        await expectedFreshArtifacts(physical, journal);
        if (journal.phase === "capture") {
          await guardBoundary("after-capture");
          journal.phase = "build";
          await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
        }
        const phaseOptions = {
          now: options.now,
          onBoundary: guardBoundary
        };
        if (journal.phase === "build") {
          await build(store, modules, physical, lease, journal, phaseOptions);
          await expectedFreshArtifacts(physical, journal);
          journal.phase = "verify";
          await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
        }
        if (journal.phase === "verify") {
          await verify(store, physical, journal, phaseOptions);
          journal.phase = "retire";
          await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
          await management(store, journal);
        }
        if (journal.phase === "retire") {
          await guardBoundary("before-retire");
          await expectedFreshArtifacts(physical, journal);
          await verifyImported(store, journal);
          const retiring = journal;
          await modules.fs.withLock(physical.legacyPath, {
            name: "accounts",
            ttlMs: 1e4,
            timeoutMs: 2e3,
            renew: true
          }, async (accountsLease) => {
            await assertSourceAbsent(physical);
            await accountsLease.assertOwned();
            retiring.sourceAbsenceVerified = true;
            await saveJournal(modules, physical, lease, retiring, false, options.onBoundary);
          });
          await guardBoundary("after-retire");
          journal.phase = "activate";
          await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
        }
        await guardBoundary("before-activate");
        await expectedFreshArtifacts(physical, journal);
        await verifyImported(store, journal);
        journal.status = "active";
        await saveJournal(modules, physical, lease, journal, false, options.onBoundary);
        await management(store, journal, true);
        await guardBoundary("after-activate");
        return { status: "completed", receipt: receipt(journal) };
      });
    });
  } catch (error) {
    const pending = pendingLockFailure(modules, error);
    if (pending)
      return pending;
    throw error;
  }
}
async function allocateGeneration(legacyPath) {
  if (await exists(resolveAccountStorePaths(legacyPath).storeDir))
    throw new AccountMigrationError("foreign logical directory refuses generation allocation");
  const paths = generationPaths(legacyPath, randomUUID());
  await mkdir(paths.storeDir, { mode: 448 });
  await prepareDirectories(paths);
  return paths;
}
async function publishGenerationPointer(modules, paths, journal, parentLease, prior, boundary) {
  await parentLease.assertOwned();
  const currentJournal = await readJournal(paths);
  if (!currentJournal || currentJournal.id !== journal.id || !isDeepStrictEqual(journalJson(currentJournal), journalJson(journal)))
    throw new AccountMigrationError("publication requires its complete synced canonical journal");
  await syncFile(paths.migrationPath);
  await syncDirectory(paths.storeDir);
  const pointer = {
    schemaVersion: 1,
    id: journal.id,
    directoryBasename: basename(paths.storeDir)
  };
  const path2 = accountStorePointerPath(paths.legacyPath);
  if (prior === void 0) {
    const stage = `${path2}.${journal.id}.tmp`;
    const bytes = Buffer.from(`${JSON.stringify(pointer, null, 2)}
`);
    await exclusiveBytes(stage, bytes, digest(bytes));
    await parentLease.assertOwned();
    await boundary?.("pointer:before-link");
    if (await exists(resolveAccountStorePaths(paths.legacyPath).storeDir))
      throw new AccountMigrationError("foreign logical store directory appeared before publication");
    if (journal.sourceKind === "absent")
      await assertSourceAbsent(paths);
    else if (digest(await secureRead(paths.legacyPath)) !== journal.sourceSha256)
      throw new AccountMigrationError("captured source changed immediately before pointer link");
    try {
      await link(stage, path2);
    } catch (error) {
      if (errno(error) === "EEXIST")
        throw new AccountMigrationError("foreign or competing pointer publication refuses overwrite");
      throw new AccountMigrationError("exclusive pointer hard-link publication failed");
    }
    await boundary?.("pointer:after-link-before-parent-sync");
    await syncDirectory(dirname(path2));
    if (!isDeepStrictEqual(await readPointer(paths.legacyPath), pointer))
      throw new AccountMigrationError("pointer publication readback differs");
    await boundary?.("pointer:after-sync-before-stage-cleanup");
    await unlink(stage);
  } else {
    const oldPaths = generationPaths(paths.legacyPath, prior.id);
    const oldJournal = await readJournal(oldPaths);
    if (oldJournal?.status !== "inactive")
      throw new AccountMigrationError("pointer transition requires an owned inactive prior generation");
    await verifyCopies(oldPaths, oldJournal, !oldJournal.cancelled);
    const stageName = journal.id;
    await modules.fs.writeJsonAtomic(path2, pointer, {
      stageName: () => stageName,
      beforeRename: async () => {
        await parentLease.assertOwned();
        if (!isDeepStrictEqual(await readPointer(paths.legacyPath), prior) || (await readJournal(oldPaths))?.status !== "inactive")
          throw new AccountMigrationError("inactive pointer changed before transition");
        await syncFile(`${path2}.${stageName}.tmp`);
      }
    });
    await syncFile(path2);
    await syncDirectory(dirname(path2));
  }
  await parentLease.assertOwned();
}
function withParentTopology(modules, legacyPath, body) {
  return modules.fs.withLock(legacyPath, {
    name: MANAGEMENT_LOCK_NAME,
    ttlMs: 1e4,
    timeoutMs: 2e3,
    renew: true
  }, body);
}
function writeObserver(paths, lease, boundary) {
  return async (step, info) => {
    await lease.assertOwned();
    await assertPublishedAccountStoreGeneration(paths);
    if (step.startsWith("after-")) {
      await syncFile(step.includes("config") ? paths.configPath : paths.statePath);
      await syncDirectory(paths.storeDir, boundary);
    }
    await boundary?.(`public:${info.operation}:${step}`);
    await lease.assertOwned();
    await assertPublishedAccountStoreGeneration(paths);
  };
}
async function finishPointerPublication(legacyPath, pointer, lease) {
  const path2 = accountStorePointerPath(legacyPath);
  await syncFile(path2);
  await syncDirectory(dirname(path2));
  const stage = `${path2}.${pointer.id}.tmp`;
  if (!await exists(stage))
    return;
  const bytes = await secureRead(stage);
  if (!isDeepStrictEqual(decodeAccountStorePointer(jsonBytes(bytes), legacyPath), pointer))
    throw new AccountMigrationError("pointer stage differs from publication authority");
  const [published, temporary] = await Promise.all([lstat(path2), lstat(stage)]);
  if (published.dev !== temporary.dev || published.ino !== temporary.ino)
    throw new AccountMigrationError("pointer stage is not the published hard link");
  await lease.assertOwned();
  await unlink(stage);
  await syncDirectory(dirname(path2));
}

// ../core/dist/account-repository.js
var STORE_SAVE_LOCK = {
  name: "save",
  ttlMs: 1e4,
  timeoutMs: 15e3,
  renew: true
};
var TOPOLOGY_LEASE = {
  name: "antigravity-topology",
  ttlMs: 1e4,
  /** The store's own default bounded wait for a lock. */
  timeoutMs: 15e3,
  renew: true
};
var AccountRepositoryError = class extends Error {
  failure;
  constructor(failure, options) {
    super(failure.message, options);
    this.name = "AccountRepositoryError";
    this.failure = failure;
  }
};
function refusal(operation, kind, message, details = {}) {
  return new AccountRepositoryError({
    operation,
    kind,
    retryable: details.retryable ?? false,
    ambiguous: details.ambiguous ?? false,
    ...details.rowId !== void 0 ? { rowId: details.rowId } : {},
    message
  });
}
function utcDay(at) {
  return new Date(at).toISOString().slice(0, 10);
}
function mergeRateLimitResets(stored, incoming) {
  if (incoming === null)
    return stored === void 0 ? null : stored;
  const out = { ...stored ?? {} };
  for (const [key, value] of Object.entries(incoming)) {
    const prior = out[key];
    if (value === null) {
      if (prior === void 0)
        out[key] = null;
    } else if (typeof prior !== "number" || value > prior) {
      out[key] = value;
    }
  }
  return out;
}
function latest(...times) {
  let result;
  for (const time of times) {
    if (typeof time === "number" && (result === void 0 || time > result)) {
      result = time;
    }
  }
  return result;
}
function accessEvidenceAt(metadata) {
  return latest(metadata.verificationRequiredAt, metadata.accountIneligibleAt, metadata.eligibilityStateUpdatedAt);
}
function mergeExtensions(a, b) {
  if (a === void 0 && b === void 0)
    return void 0;
  return { ...a ?? {}, ...b ?? {} };
}
function mergeSameCredential(stored, incoming) {
  const out = {
    ...stored,
    ...incoming,
    addedAt: stored.addedAt,
    lastUsed: Math.max(stored.lastUsed, incoming.lastUsed)
  };
  if (stored.dailyRequestCounts != null) {
    out.dailyRequestCounts = stored.dailyRequestCounts;
  }
  if (incoming.rateLimitResetTimes !== void 0) {
    out.rateLimitResetTimes = mergeRateLimitResets(stored.rateLimitResetTimes, incoming.rateLimitResetTimes);
  }
  const extensions = mergeExtensions(stored.extensions, incoming.extensions);
  if (extensions !== void 0)
    out.extensions = extensions;
  return out;
}
var ROW_RETAINED_FIELDS = [
  "addedAt",
  "lastUsed",
  "enabled",
  "lastSwitchReason",
  "label",
  "dailyRequestCounts",
  "extensions"
];
var SAME_ACCOUNT_RETAINED_FIELDS = [
  "email",
  "projectId",
  "managedProjectId",
  "fingerprint",
  "fingerprintHistory",
  "capturedTierId",
  "capturedPaidTierId",
  "capturedTierAt",
  "capturedTierSchemaVersion"
];
function copyFields(from, to, keys) {
  for (const key of keys) {
    if (key in from)
      to[key] = from[key];
  }
}
function replacementMetadata(previous, replacement) {
  const incoming = replacement.incoming?.metadata;
  if (previous === void 0)
    return incoming;
  const sameAccount = replacement.previousIdentity !== void 0 && replacement.identity !== void 0 && replacement.previousIdentity === replacement.identity;
  const kept = {};
  copyFields(previous, kept, ROW_RETAINED_FIELDS);
  if (sameAccount)
    copyFields(previous, kept, SAME_ACCOUNT_RETAINED_FIELDS);
  const base = {
    ...kept,
    addedAt: previous.addedAt,
    lastUsed: previous.lastUsed
  };
  if (incoming === void 0)
    return base;
  return mergeSameCredential(base, incoming);
}
var ACCOUNT_STATE_POLICY = {
  merge(onDisk, incoming) {
    const extensions = mergeExtensions(onDisk.extensions, incoming.extensions);
    return {
      schemaVersion: PROVIDER_STATE_SCHEMA_VERSION,
      metadata: mergeSameCredential(onDisk.metadata, incoming.metadata),
      ...extensions !== void 0 ? { extensions } : {}
    };
  },
  onReplace(previous, replacement) {
    const metadata = replacementMetadata(previous?.metadata, replacement);
    if (metadata === void 0)
      return void 0;
    const extensions = mergeExtensions(previous?.extensions, replacement.incoming?.extensions);
    return {
      schemaVersion: PROVIDER_STATE_SCHEMA_VERSION,
      metadata,
      ...extensions !== void 0 ? { extensions } : {}
    };
  }
};
function applyProjectObservation(metadata, observation) {
  const next = { ...metadata };
  if (observation.projectId !== void 0)
    next.projectId = observation.projectId;
  if (observation.managedProjectId !== void 0) {
    next.managedProjectId = observation.managedProjectId;
  }
  return next;
}
function applyFingerprintObservation(metadata, observation) {
  return {
    ...metadata,
    fingerprint: observation.fingerprint,
    fingerprintHistory: [...observation.history]
  };
}
function applyTierObservation(metadata, observation) {
  if (typeof metadata.capturedTierAt === "number" && observation.observedAt < metadata.capturedTierAt) {
    return metadata;
  }
  return {
    ...metadata,
    capturedTierId: observation.tierId,
    capturedPaidTierId: observation.paidTierId,
    capturedTierAt: observation.observedAt,
    capturedTierSchemaVersion: observation.schemaVersion
  };
}
function applyCooldownObservation(metadata, observation) {
  const next = { ...metadata };
  if (observation === null) {
    delete next.coolingDownUntil;
    delete next.cooldownReason;
  } else {
    next.coolingDownUntil = observation.until;
    next.cooldownReason = observation.reason;
  }
  return next;
}
function applyRateLimitObservation(metadata, resets) {
  return {
    ...metadata,
    rateLimitResetTimes: mergeRateLimitResets(metadata.rateLimitResetTimes, resets)
  };
}
function applySwitch(metadata, reason) {
  return { ...metadata, lastSwitchReason: reason };
}
function applyUsage(metadata, observation, now) {
  const today = utcDay(now);
  const stored = metadata.dailyRequestCounts;
  const counts = stored != null && stored.date === today ? { ...stored } : { date: today, claude: 0, gemini: 0 };
  counts[observation.family] += 1;
  return {
    ...metadata,
    lastUsed: Math.max(metadata.lastUsed, observation.at),
    dailyRequestCounts: counts
  };
}
function applyAccessVerdict(metadata, verdict) {
  const evidenceAt = accessEvidenceAt(metadata);
  if (evidenceAt !== void 0 && verdict.observedAt < evidenceAt) {
    return void 0;
  }
  const next = { ...metadata };
  switch (verdict.kind) {
    case "verification-required": {
      next.verificationRequired = true;
      next.verificationRequiredAt = verdict.observedAt;
      const reason = verdict.reason?.trim();
      if (reason)
        next.verificationRequiredReason = reason;
      else
        delete next.verificationRequiredReason;
      const url = verdict.verificationUrl?.trim();
      if (url)
        next.verificationUrl = url;
      if (next.accountIneligible === true || next.accountIneligibleAt != null || next.accountIneligibleReason != null) {
        next.accountIneligible = false;
        delete next.accountIneligibleAt;
        delete next.accountIneligibleReason;
        next.eligibilityStateUpdatedAt = verdict.observedAt;
      }
      return { metadata: next, transition: "disable" };
    }
    case "ineligible": {
      next.accountIneligible = true;
      next.accountIneligibleAt = verdict.observedAt;
      next.accountIneligibleReason = verdict.reason.trim() || "Google marked this account as ineligible.";
      next.eligibilityStateUpdatedAt = verdict.observedAt;
      next.verificationRequired = false;
      delete next.verificationRequiredAt;
      delete next.verificationRequiredReason;
      delete next.verificationUrl;
      return { metadata: next, transition: "disable" };
    }
    case "cleared": {
      const wasBlocked = metadata.verificationRequired === true || metadata.accountIneligible === true;
      const hadEligibility = metadata.accountIneligible === true || metadata.eligibilityStateUpdatedAt != null;
      next.verificationRequired = false;
      delete next.verificationRequiredAt;
      delete next.verificationRequiredReason;
      delete next.verificationUrl;
      next.accountIneligible = false;
      delete next.accountIneligibleAt;
      delete next.accountIneligibleReason;
      if (hadEligibility)
        next.eligibilityStateUpdatedAt = verdict.observedAt;
      return {
        metadata: next,
        transition: verdict.enable && wasBlocked ? "enable" : "keep"
      };
    }
  }
}
function envelopeOf(raw) {
  return raw === void 0 || raw === null ? void 0 : decodeProviderState(raw);
}
function shownEnvelope(operation, current, row) {
  if (row.providerStateDropped !== void 0) {
    throw new CallbackRefusal(refusal(operation, "metadata-dropped", `row ${row.id} holds metadata the store does not show (${row.providerStateDropped})`, { rowId: row.id }));
  }
  return envelopeOf(current);
}
function metadataOrBase(envelope, row, now) {
  return envelope?.metadata ?? { addedAt: row.addedAt ?? now, lastUsed: 0 };
}
function encodeEnvelope(prior, metadata) {
  return encodeProviderState({
    schemaVersion: PROVIDER_STATE_SCHEMA_VERSION,
    metadata,
    ...prior?.extensions !== void 0 ? { extensions: prior.extensions } : {}
  });
}
function metadataOfStored(raw) {
  return envelopeOf(raw)?.metadata;
}
function metadataView(row) {
  if (row.providerStateDropped !== void 0) {
    return { status: "dropped", reason: row.providerStateDropped };
  }
  if (row.providerState === void 0)
    return { status: "absent" };
  return {
    status: "present",
    metadata: decodeProviderState(row.providerState).metadata
  };
}
function quotaView(row) {
  return row.quota === void 0 ? { status: "absent" } : { status: "present", quota: decodeQuotaState(row.quota) };
}
function toAccountRow(row, index) {
  const credential = row.credential;
  return {
    ref: rowRefOf(row),
    index,
    enabled: row.enabled,
    ...row.disabledReason !== void 0 ? { disabledReason: row.disabledReason } : {},
    ...row.addedAt !== void 0 ? { storeAddedAt: row.addedAt } : {},
    ...credential?.type === "oauth" ? {
      credential: {
        refreshToken: credential.refresh,
        ...credential.access !== void 0 ? { accessToken: credential.access } : {},
        ...credential.expires !== void 0 ? { expiresAt: credential.expires } : {}
      }
    } : {},
    usable: row.candidate,
    stamp: row.stamp ?? (credential === void 0 ? "none" : "missing"),
    ...row.torn ? { torn: true } : {},
    ...row.unbound ? { unbound: true } : {},
    ...row.invalid !== void 0 ? { invalid: row.invalid } : {},
    metadata: metadataView(row),
    quota: quotaView(row)
  };
}
function isManagementKind(value) {
  return value === "migration" || value === "clear" || value === "replace-pool";
}
function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function isStringList(value) {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}
var MANAGEMENT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
var MANAGEMENT_STEPS = {
  clear: ["remove"],
  "replace-pool": ["remove", "add", "publish", "verified"],
  migration: ACCOUNT_MIGRATION_MANAGEMENT_STEPS
};
function canonicalJson(value) {
  const sorted = (item) => {
    if (Array.isArray(item))
      return item.map(sorted);
    if (item === null || typeof item !== "object")
      return item;
    const out = {};
    for (const key of Object.keys(item).sort()) {
      const child = item[key];
      if (child !== void 0)
        out[key] = sorted(child);
    }
    return out;
  };
  return JSON.stringify(sorted(value));
}
var SHA256_HEX = /^[0-9a-f]{64}$/;
function replacementInputDigest(inputs) {
  return createHash2("sha256").update(canonicalJson(inputs.map(encodeLoginInput))).digest("hex");
}
function publicManagementRecord(record2) {
  return {
    id: record2.id,
    kind: record2.kind,
    targets: [...record2.targets],
    progress: {
      step: record2.progress.step,
      completedTargets: [...record2.progress.completedTargets]
    }
  };
}
function uniqueIds(value, path2) {
  if (!isStringList(value)) {
    throw new AccountCodecError(path2, "must be a list of ids");
  }
  const seen = /* @__PURE__ */ new Set();
  for (const id of value) {
    if (!id)
      throw new AccountCodecError(path2, "must not hold an empty id");
    if (seen.has(id))
      throw new AccountCodecError(path2, "must not repeat an id");
    seen.add(id);
  }
  return [...value];
}
function decodeManagementRecord(raw) {
  if (!isRecord(raw)) {
    throw new AccountCodecError("$", "must be an object");
  }
  const record2 = raw;
  const progress = record2.progress;
  if (typeof record2.id !== "string" || !MANAGEMENT_ID.test(record2.id)) {
    throw new AccountCodecError("$.id", "must be a lowercase UUID");
  }
  if (!isManagementKind(record2.kind)) {
    throw new AccountCodecError("$.kind", "must be a management kind");
  }
  const targets = uniqueIds(record2.targets, "$.targets");
  if (!isRecord(progress)) {
    throw new AccountCodecError("$.progress", "must be an object");
  }
  const { step } = progress;
  const steps = MANAGEMENT_STEPS[record2.kind];
  if (typeof step !== "string" || !steps.includes(step)) {
    throw new AccountCodecError("$.progress.step", `must be a step of a ${record2.kind} record`);
  }
  const completedTargets = uniqueIds(progress.completedTargets, "$.progress.completedTargets");
  if (step === "remove" && completedTargets.some((id) => !targets.includes(id))) {
    throw new AccountCodecError("$.progress.completedTargets", "must name only targets while rows are being removed");
  }
  const inputDigest = record2.inputDigest;
  if (record2.publication !== void 0 && record2.kind !== "replace-pool")
    throw new AccountCodecError("$.publication", "belongs only to a replace-pool record");
  if (record2.kind === "replace-pool") {
    if (typeof inputDigest !== "string" || !SHA256_HEX.test(inputDigest)) {
      throw new AccountCodecError("$.inputDigest", "must be the SHA-256 of the replacement inputs");
    }
  } else if (inputDigest !== void 0) {
    throw new AccountCodecError("$.inputDigest", "belongs only to a replace-pool record");
  }
  return {
    id: record2.id,
    kind: record2.kind,
    targets,
    progress: { step, completedTargets },
    ...typeof inputDigest === "string" ? { inputDigest } : {},
    ...record2.publication !== void 0 ? { publication: decodePublicationPlan(record2.publication, record2.id) } : {}
  };
}
function decodePublicationPlan(raw, operationId) {
  if (!isRecord(raw) || raw.operationId !== operationId || !Array.isArray(raw.remove) || !Array.isArray(raw.finalize)) {
    throw new AccountCodecError("$.publication", "must hold this operation\u2019s native publication plan");
  }
  const order = uniqueIds(raw.order, "$.publication.order");
  const attribution = (value) => {
    if (!isRecord(value) || typeof value.credentialEpoch !== "number" || !Number.isSafeInteger(value.credentialEpoch) || value.credentialEpoch < 1 || value.identity !== void 0 && (typeof value.identity !== "string" || !value.identity)) {
      throw new AccountCodecError("$.publication.attribution", "must hold an exact credential fence");
    }
    return {
      credentialEpoch: value.credentialEpoch,
      ...typeof value.identity === "string" ? { identity: value.identity } : {}
    };
  };
  const remove2 = raw.remove.map((item) => {
    if (!isRecord(item) || typeof item.id !== "string" || !item.id || typeof item.fingerprint !== "string" || !SHA256_HEX.test(item.fingerprint))
      throw new AccountCodecError("$.publication.remove", "must hold a row and secret fingerprint");
    return {
      id: item.id,
      attribution: attribution(item.attribution),
      fingerprint: item.fingerprint
    };
  });
  const finalize = raw.finalize.map((item) => {
    if (!isRecord(item) || typeof item.id !== "string" || !order.includes(item.id) || item.reservation !== operationId || typeof item.enabled !== "boolean" || (item.enabled ? item.disabledReason !== void 0 : typeof item.disabledReason !== "string"))
      throw new AccountCodecError("$.publication.finalize", "must hold this operation\u2019s reserved row");
    return {
      id: item.id,
      attribution: attribution(item.attribution),
      reservation: operationId,
      enabled: item.enabled,
      ...typeof item.disabledReason === "string" ? { disabledReason: item.disabledReason } : {}
    };
  });
  uniqueIds([...remove2.map((row) => row.id), ...finalize.map((row) => row.id)], "$.publication.rows");
  return { operationId, remove: remove2, finalize, order };
}
function encodePublicationPlan(plan) {
  return {
    operationId: plan.operationId,
    remove: plan.remove.map((row) => ({
      id: row.id,
      attribution: { ...row.attribution },
      ...row.fingerprint !== void 0 ? { fingerprint: row.fingerprint } : {}
    })),
    finalize: plan.finalize.map((row) => ({
      ...row,
      attribution: { ...row.attribution }
    })),
    order: [...plan.order]
  };
}
function encodeManagementRecord(record2) {
  return {
    id: record2.id,
    kind: record2.kind,
    targets: [...record2.targets],
    progress: {
      step: record2.progress.step,
      completedTargets: [...record2.progress.completedTargets]
    },
    ...record2.inputDigest !== void 0 ? { inputDigest: record2.inputDigest } : {},
    ...record2.publication !== void 0 ? { publication: encodePublicationPlan(record2.publication) } : {}
  };
}
function decodeTransferFile(raw, managementId) {
  if (!isRecord(raw) || raw.schemaVersion !== 1 || raw.managementId !== managementId || !Array.isArray(raw.inputs)) {
    throw new AccountCodecError("transfer", "does not belong to this management record");
  }
  const inputs = raw.inputs.map(decodeLoginInput);
  uniqueIds(inputs.map((input) => input.id), "transfer.inputs[].id");
  if (inputs.some((input) => !input.refreshToken.trim())) {
    throw new AccountCodecError("transfer.inputs[].refreshToken", "must not be empty");
  }
  return inputs;
}
function encodeLoginInput(input) {
  return {
    id: input.id,
    refreshToken: input.refreshToken,
    ...input.identity !== void 0 ? { identity: input.identity } : {},
    metadata: encodeProviderMetadata(input.metadata)
  };
}
function decodeLoginInput(raw) {
  if (!isRecord(raw)) {
    throw new AccountCodecError("$.inputs[]", "must be an object");
  }
  const value = raw;
  if (typeof value.id !== "string" || typeof value.refreshToken !== "string") {
    throw new AccountCodecError("$.inputs[]", "must name an id and a refresh token");
  }
  if (value.identity !== void 0 && typeof value.identity !== "string") {
    throw new AccountCodecError("$.inputs[].identity", "must be a string");
  }
  return {
    id: value.id,
    refreshToken: value.refreshToken,
    ...typeof value.identity === "string" ? { identity: value.identity } : {},
    metadata: decodeProviderMetadata(value.metadata)
  };
}
function unbound(operation, binding) {
  switch (binding.status) {
    case "pending":
      return refusal(operation, "pending-migration", "the account store has a migration or rollback in progress", { retryable: true });
    case "initialization-required":
      return refusal(operation, "pending-migration", "the account store has not been initialized", { retryable: true });
    case "inactive":
      return refusal(operation, "load-error", "the account-store generation was rolled back");
    case "error":
      return refusal(operation, "load-error", binding.reason);
  }
}
function generationMismatch(settings, id, paths) {
  try {
    const generation = decodeAccountStoreGeneration(settings[ACCOUNT_STORE_GENERATION_SETTINGS_KEY]);
    return generation.id === id && generation.storeDir === paths.storeDir ? void 0 : "the store now belongs to another account-store generation";
  } catch {
    return "the store holds no valid account-store generation";
  }
}
function managementLock(paths) {
  return { name: MANAGEMENT_LOCK_NAME, path: paths.configPath };
}
var CallbackRefusal = class extends Error {
  error;
  constructor(error) {
    super(error.message);
    this.name = "CallbackRefusal";
    this.error = error;
  }
};
var StoreAccountRepository = class {
  store;
  decline;
  storeFailure;
  locks;
  storeModule;
  /** Cached promise for the validated generation ID. Failed attempts are discarded. */
  binding;
  /** The canonical config path the topology lease is named after. */
  leaseTarget;
  paths;
  now;
  exchange;
  /** Every started operation; each leaves the set once its promise settles. */
  inFlight = /* @__PURE__ */ new Set();
  /**
   * Failures since the last `flush`, kept so each is reported once: `flush`
   * and `dispose` resolve with them in their report and then forget them.
   */
  failures = [];
  completed = 0;
  /**
   * The refresh running for each credential, keyed by `rowRefKey` (row id,
   * epoch and identity), so concurrent refreshes of one credential in this
   * process share a single exchange.
   */
  refreshes = /* @__PURE__ */ new Map();
  closing = false;
  constructor(modules, options, factoryOptions) {
    const module = modules.store;
    this.storeModule = module;
    this.locks = modules.fs;
    this.paths = options.paths;
    this.now = options.now;
    this.exchange = options.exchange;
    this.decline = module.DECLINE_TRANSITION;
    this.storeFailure = module.PoolOperationError;
    this.store = module.openPoolStore({
      provider: ACCOUNT_STORE_PROVIDER,
      configPath: options.paths.configPath,
      statePath: options.paths.statePath,
      quota: QUOTA_CODEC,
      providerState: createProviderStateCodec(ACCOUNT_STATE_POLICY),
      requireCredentialStamps: true,
      now: options.now,
      ...factoryOptions.onLockEvent !== void 0 ? { onLockEvent: factoryOptions.onLockEvent } : {}
    });
  }
  // ---- failure conversion and tracking of started operations -------------
  failureOf(operation, rowId2, error) {
    if (error instanceof AccountRepositoryError)
      return error;
    if (error instanceof CallbackRefusal)
      return error.error;
    if (error instanceof this.storeFailure) {
      if (error.cause instanceof CallbackRefusal)
        return error.cause.error;
      if (error.cause instanceof AccountRepositoryError)
        return error.cause;
      const id = error.rowId ?? rowId2;
      return new AccountRepositoryError({
        operation,
        kind: error.cause instanceof AccountCodecError ? "invalid-provider-state" : error.kind,
        retryable: error.retryable,
        ambiguous: error.phase === "after-first-write",
        ...id !== void 0 ? { rowId: id } : {},
        message: error.message
      }, { cause: error });
    }
    if (error instanceof this.locks.LockOwnershipError || error instanceof this.locks.LockContentionError) {
      return new AccountRepositoryError({
        operation,
        kind: error instanceof this.locks.LockOwnershipError ? "lock-ownership" : "lock-contention",
        retryable: true,
        ambiguous: false,
        ...rowId2 !== void 0 ? { rowId: rowId2 } : {},
        message: error.message
      }, { cause: error });
    }
    if (error instanceof AccountCodecError) {
      return new AccountRepositoryError({
        operation,
        kind: "invalid-input",
        retryable: false,
        ambiguous: false,
        ...rowId2 !== void 0 ? { rowId: rowId2 } : {},
        message: error.message
      }, { cause: error });
    }
    return new AccountRepositoryError({
      operation,
      kind: "unexpected",
      retryable: false,
      // Nothing says how far a write got before an unknown error.
      ambiguous: operation !== "read" && operation !== "flush",
      ...rowId2 !== void 0 ? { rowId: rowId2 } : {},
      message: error instanceof Error ? error.message : "unexpected failure"
    }, { cause: error });
  }
  /**
   * Runs one operation as owned work: refused once `dispose` has begun,
   * counted by `flush`, and its failure recorded for the flush report while
   * the caller still receives it.
   */
  run(operation, rowId2, body) {
    if (this.closing) {
      return Promise.reject(refusal(operation, "disposed", "the account repository is disposed", {
        ...rowId2 !== void 0 ? { rowId: rowId2 } : {}
      }));
    }
    const work = (async () => {
      try {
        const result = await body();
        if (operation !== "read")
          this.completed += 1;
        return result;
      } catch (error) {
        const failure = this.failureOf(operation, rowId2, error);
        this.failures.push(failure.failure);
        throw failure;
      }
    })();
    this.inFlight.add(work);
    const forget = () => this.inFlight.delete(work);
    work.then(forget, forget);
    return work;
  }
  /**
   * Runs `body` holding the topology lease (`TOPOLOGY_LEASE`), named after
   * the config file's canonical path so every repository on the pool, in
   * any process, takes the same lease. `body` checks the lease before each
   * write it makes; a lease found lost stops it there.
   */
  async withTopology(operation, body) {
    await this.bindGeneration(operation);
    this.leaseTarget ??= realpath2(dirname2(this.paths.configPath)).then((dir) => join2(dir, basename2(this.paths.configPath)));
    const target = await this.leaseTarget.catch((error) => {
      this.leaseTarget = void 0;
      throw error;
    });
    return this.locks.withLock(target, TOPOLOGY_LEASE, async (lease) => {
      await lease.assertOwned();
      return body(lease);
    });
  }
  /**
   * Verify which completed active generation owns these physical paths.
   * Cache only successful binding; separate journal and row checks still
   * decide serving readiness.
   */
  bindGeneration(operation) {
    if (this.binding === void 0) {
      const binding = this.readBinding().then((result) => {
        if (result.status !== "bound")
          throw unbound(operation, result);
        if (!isDeepStrictEqual2(result.paths, this.paths)) {
          throw refusal(operation, "load-error", "the published account-store generation is not this repository's");
        }
        return result.receipt.id;
      });
      this.binding = binding;
      binding.catch(() => {
        if (this.binding === binding)
          this.binding = void 0;
      });
    }
    return this.binding;
  }
  /**
   * Read the migration's published-generation binding. When its directory
   * exists, acquire config then state save locks to avoid validating a
   * partial store write.
   */
  async readBinding() {
    const read = () => readAccountStoreBinding(this.paths.legacyPath, { store: this.storeModule }, this.now);
    const directory = await stat(this.paths.storeDir).catch(() => void 0);
    if (directory === void 0 || !directory.isDirectory())
      return read();
    return this.locks.withLock(this.paths.configPath, STORE_SAVE_LOCK, () => this.locks.withLock(this.paths.statePath, STORE_SAVE_LOCK, read));
  }
  /**
   * Read current settings and refuse if their generation no longer matches
   * this repository's binding.
   */
  async boundSettings(operation) {
    const id = await this.bindGeneration(operation);
    const settings = await this.readSettings(operation);
    const mismatch = generationMismatch(settings, id, this.paths);
    if (mismatch !== void 0)
      throw refusal(operation, "load-error", mismatch);
    return settings;
  }
  async admit(operation, rowId2) {
    const settings = await this.boundSettings(operation);
    const raw = settings[MANAGEMENT_SETTINGS_KEY];
    const pending = raw === void 0 ? void 0 : decodeManagementRecord(raw);
    if (pending !== void 0) {
      throw refusal(operation, "management-pending", `a ${pending.kind} of the account pool is pending`, { retryable: true, ...rowId2 !== void 0 ? { rowId: rowId2 } : {} });
    }
  }
  async readSettings(operation) {
    const read = await this.store.readSettings();
    if (read.status === "error") {
      throw refusal(operation, "load-error", `the ${read.file} file could not be read: ${read.reason}`, {
        retryable: true
      });
    }
    return read.settings;
  }
  async readManagement(operation) {
    const raw = (await this.readSettings(operation))[MANAGEMENT_SETTINGS_KEY];
    return raw === void 0 ? void 0 : decodeManagementRecord(raw);
  }
  async readRows(operation) {
    const load = await this.store.read();
    if (load.status === "pending-migration") {
      throw refusal(operation, "pending-migration", "the account pool awaits migration", {
        retryable: true
      });
    }
    if (load.status === "error") {
      throw refusal(operation, "load-error", `the ${load.file} file could not be read: ${load.reason}`, {
        retryable: true
      });
    }
    return load.rows;
  }
  async accountRowFor(operation, ref) {
    const rows = await this.readRows(operation);
    const index = rows.findIndex((row2) => row2.id === ref.id);
    const row = rows[index];
    if (row === void 0) {
      throw refusal(operation, "unknown-row", `no row ${ref.id} in the pool`, {
        rowId: ref.id
      });
    }
    return { index, row };
  }
  // ---- reads -------------------------------------------------------------
  read() {
    return this.run("read", void 0, async () => {
      let generation;
      try {
        generation = await this.bindGeneration("read");
      } catch (error) {
        if (!(error instanceof AccountRepositoryError))
          throw error;
        return error.failure.kind === "pending-migration" ? { status: "pending-migration" } : { status: "error", file: "config", reason: error.failure.message };
      }
      const load = await this.store.read();
      if (load.status === "pending-migration")
        return { status: "pending-migration" };
      if (load.status === "error") {
        return { status: "error", file: load.file, reason: load.reason };
      }
      const settingsRead = await this.store.readSettings();
      if (settingsRead.status === "error") {
        return {
          status: "error",
          file: settingsRead.file,
          reason: settingsRead.reason
        };
      }
      const settings = settingsRead.settings;
      const mismatch = generationMismatch(settings, generation, this.paths);
      if (mismatch !== void 0) {
        return { status: "error", file: "settings", reason: mismatch };
      }
      let routing;
      try {
        const management2 = settings[MANAGEMENT_SETTINGS_KEY];
        if (management2 !== void 0) {
          return {
            status: "management-pending",
            management: publicManagementRecord(decodeManagementRecord(management2))
          };
        }
        const rawRouting = settings[ROUTING_SETTINGS_KEY];
        routing = rawRouting === void 0 ? void 0 : decodeRoutingSettings(rawRouting);
      } catch (error) {
        if (error instanceof AccountCodecError) {
          return { status: "error", file: "settings", reason: error.message };
        }
        throw error;
      }
      return {
        status: "ready",
        rows: load.rows.map((row, index) => toAccountRow(row, index)),
        ...routing !== void 0 ? { routing } : {}
      };
    });
  }
  settled() {
    return this.store.pullsSettled();
  }
  // ---- credentials ------------------------------------------------------
  login(input) {
    return this.run("login", input.id, () => this.withTopology("login", async (lease) => {
      await this.admit("login", input.id);
      return this.addLogin(input, lease);
    }));
  }
  /**
   * Matches a login to the pool (exact email first, then the secret) and
   * adds it. An email match holding another secret is a re-authentication,
   * which needs the caller's expected ref (`replaceCredential`); a secret
   * held by a row recorded for another email is a contradiction. Both refuse
   * before anything is written.
   */
  async addLogin(input, lease) {
    if (!input.refreshToken.trim()) {
      throw refusal("login", "invalid-input", "a login needs a refresh token", {
        rowId: input.id
      });
    }
    const rows = await this.readRows("login");
    const secretRow = rows.find((row2) => row2.credential?.type === "oauth" && row2.credential.refresh === input.refreshToken);
    const email = input.metadata.email;
    if (typeof email === "string") {
      const emailRows = rows.filter((row2) => metadataOfStored(row2.providerState)?.email === email);
      const other = emailRows.find((row2) => row2 !== secretRow);
      if (other !== void 0) {
        throw refusal("login", "duplicate-identity", `row ${other.id} already holds this account; re-authenticate it with its ref instead of adding a second row`, { rowId: other.id });
      }
      const secretEmail = secretRow === void 0 ? void 0 : metadataOfStored(secretRow.providerState)?.email;
      if (typeof secretEmail === "string" && secretEmail !== email) {
        throw refusal("login", "duplicate-secret", `row ${secretRow?.id} holds this credential for another account`, { ...secretRow !== void 0 ? { rowId: secretRow.id } : {} });
      }
    }
    await lease.assertOwned();
    const added = await this.store.add({
      id: input.id,
      credential: { type: "oauth", refresh: input.refreshToken },
      ...input.identity !== void 0 ? { identity: input.identity } : {},
      providerState: encodeProviderState({
        schemaVersion: PROVIDER_STATE_SCHEMA_VERSION,
        metadata: input.metadata
      })
    });
    const row = (await this.readRows("login")).find((r) => r.id === added.id);
    if (row === void 0) {
      throw refusal("login", "unknown-row", `row ${added.id} was removed right after the login`, {
        rowId: added.id,
        retryable: true
      });
    }
    if (added.outcome === "exists") {
      throw refusal("login", "management-pending", "a staged row cannot be used as a login");
    }
    return { ref: rowRefOf(row), outcome: added.outcome };
  }
  replaceCredential(expected, input) {
    return this.run("replaceCredential", expected.id, () => this.withTopology("replaceCredential", async (lease) => {
      await this.admit("replaceCredential", expected.id);
      if (!input.refreshToken.trim()) {
        throw refusal("replaceCredential", "invalid-input", "a replacement needs a refresh token", {
          rowId: expected.id
        });
      }
      await lease.assertOwned();
      const replaced = await this.store.replace(expected.id, { type: "oauth", refresh: input.refreshToken }, {
        ...input.identity !== void 0 ? { identity: input.identity } : {},
        ...input.metadata !== void 0 ? {
          providerState: encodeProviderState({
            schemaVersion: PROVIDER_STATE_SCHEMA_VERSION,
            metadata: input.metadata
          })
        } : {}
      }, { attribution: credentialFenceOf(expected) });
      const ref = input.identity === void 0 ? { id: replaced.id, credentialEpoch: replaced.credentialEpoch } : {
        id: replaced.id,
        credentialEpoch: replaced.credentialEpoch,
        identity: input.identity
      };
      if (input.disabled === "enable") {
        try {
          await lease.assertOwned();
          await this.store.enable(ref.id, {
            attribution: credentialFenceOf(ref),
            providerState: (current, row) => this.withEnabledEncoding("replaceCredential", current, row, true)
          });
        } catch (error) {
          this.failures.push(this.failureOf("replaceCredential", ref.id, error).failure);
        }
      }
      return { ref };
    }));
  }
  refresh(ref, options) {
    const key = rowRefKey(ref);
    const pending = this.refreshes.get(key);
    if (pending !== void 0)
      return pending;
    const work = this.run("refresh", ref.id, () => this.refreshOnce(ref, options));
    this.refreshes.set(key, work);
    const forget = () => {
      if (this.refreshes.get(key) === work)
        this.refreshes.delete(key);
    };
    work.then(forget, forget);
    return work;
  }
  async refreshOnce(ref, options) {
    await this.admit("refresh", ref.id);
    const { index } = await this.accountRowFor("refresh", ref);
    let stale;
    const refuse = async (row) => {
      const mismatch = refMismatchReason(row, ref);
      if (mismatch !== void 0) {
        stale = mismatch;
        return mismatch;
      }
      return options?.refuse?.(toAccountRow(row, index));
    };
    const outcome = await this.store.refresh(ref.id, async (credential, row) => {
      const result = await this.exchange({
        refreshToken: credential.refresh,
        row: toAccountRow(row, index)
      });
      const providerState = result.metadata === void 0 ? void 0 : this.refreshedState(row, result.metadata);
      return {
        access: result.accessToken,
        refresh: result.refreshToken,
        expires: result.expiresAt,
        ...result.identity !== void 0 ? { identity: result.identity } : {},
        ...providerState !== void 0 ? { providerState } : {}
      };
    }, {
      providerLock: refreshProviderLock(this.paths.statePath, ref),
      refuse
    });
    switch (outcome.status) {
      case "rotated": {
        const credential = outcome.credential;
        if (credential.type !== "oauth" || credential.access === void 0 || credential.expires === void 0) {
          throw refusal("refresh", "unexpected", `row ${ref.id} committed a refresh without an access token`, {
            rowId: ref.id,
            ambiguous: true
          });
        }
        const identity = outcome.identity ?? ref.identity;
        return {
          status: "rotated",
          ref: identity === void 0 ? { id: ref.id, credentialEpoch: ref.credentialEpoch } : { id: ref.id, credentialEpoch: ref.credentialEpoch, identity },
          accessToken: credential.access,
          expiresAt: credential.expires
        };
      }
      case "identity-contradicted":
        return {
          status: "identity-contradicted",
          ref,
          expectedIdentity: outcome.expectedIdentity,
          returnedIdentity: outcome.returnedIdentity
        };
      case "refused":
        if (stale !== void 0 && outcome.reason === stale) {
          throw refusal("refresh", "attribution", stale, {
            rowId: ref.id,
            retryable: true
          });
        }
        return { status: "refused", ref, reason: outcome.reason };
    }
  }
  /**
   * The provider state a refresh brings: the metadata read under the row
   * lock with the fields the exchange reported laid over it. At commit the
   * store merges it with the value on disk (`ACCOUNT_STATE_POLICY.merge`),
   * which keeps the stored `addedAt` and `dailyRequestCounts`, the later
   * `lastUsed` and the later reset time of each rate limit.
   */
  refreshedState(row, learnt) {
    if (row.providerStateDropped !== void 0)
      return void 0;
    const envelope = envelopeOf(row.providerState);
    const metadata = {
      ...metadataOrBase(envelope, row, this.now())
    };
    for (const [key, value] of Object.entries(learnt)) {
      if (value !== void 0)
        Object.assign(metadata, { [key]: value });
    }
    return encodeEnvelope(envelope, metadata);
  }
  recordIdentity(ref, identity) {
    return this.run("recordIdentity", ref.id, async () => {
      await this.admit("recordIdentity", ref.id);
      await this.store.recordIdentity(ref.id, identity, {
        credentialEpoch: ref.credentialEpoch
      });
      return {
        ref: { id: ref.id, credentialEpoch: ref.credentialEpoch, identity }
      };
    });
  }
  // ---- enabled flag and access -------------------------------------------
  /**
   * The row's metadata with `enabled` recording the flag an enable or
   * disable sets, written with that change; a row with no metadata keeps none.
   */
  withEnabledEncoding(operation, current, row, enabled) {
    const envelope = shownEnvelope(operation, current, row);
    if (envelope === void 0)
      return void 0;
    return encodeEnvelope(envelope, { ...envelope.metadata, enabled });
  }
  setEnabled(ref, input) {
    return this.run("setEnabled", ref.id, async () => {
      await this.admit("setEnabled", ref.id);
      const { index, row: seen } = await this.accountRowFor("setEnabled", ref);
      const mutator = async (current, row) => {
        const envelope = shownEnvelope("setEnabled", current, row);
        if (input.enabled && input.actor === "user" && envelope?.metadata.accountIneligible === true) {
          throw new CallbackRefusal(refusal("setEnabled", "account-ineligible", `row ${ref.id} is marked ineligible; a user enable is refused`, {
            rowId: ref.id
          }));
        }
        const transition = input.metadata ? await input.metadata(envelope?.metadata, toAccountRow(row, index)) : { kind: "keep" };
        if (transition.kind === "decline")
          return this.decline;
        if (transition.kind === "clear")
          return void 0;
        const metadata = transition.kind === "set" ? transition.metadata : envelope?.metadata;
        if (metadata === void 0)
          return void 0;
        return encodeEnvelope(envelope, { ...metadata, enabled: input.enabled });
      };
      const options = seen.providerStateDropped !== void 0 && input.metadata === void 0 ? { attribution: credentialFenceOf(ref) } : { attribution: credentialFenceOf(ref), providerState: mutator };
      const result = input.enabled ? await this.store.enable(ref.id, options) : await this.store.disable(ref.id, input.reason ?? (input.actor === "user" ? "disabled-by-user" : "disabled"), options);
      return this.transitionResult(ref, result);
    });
  }
  transitionResult(ref, result) {
    if (result.declined)
      return { ref, declined: true };
    const metadata = metadataOfStored(result.providerState);
    return {
      ref,
      ...result.providerStateOutcome !== void 0 ? { metadataOutcome: result.providerStateOutcome } : {},
      ...metadata !== void 0 ? { metadata } : {}
    };
  }
  recordAccessVerdict(ref, verdict) {
    return this.run("recordAccessVerdict", ref.id, async () => {
      await this.admit("recordAccessVerdict", ref.id);
      const fence = credentialFenceOf(ref);
      const plan = (current, row) => {
        const envelope = shownEnvelope("recordAccessVerdict", current, row);
        const applied = applyAccessVerdict(metadataOrBase(envelope, row, this.now()), verdict);
        return { envelope, applied };
      };
      if (verdict.kind !== "cleared") {
        const result2 = await this.store.disable(ref.id, verdict.kind === "ineligible" ? "account-ineligible" : "verification-required", {
          attribution: fence,
          providerState: (current, row) => {
            const { envelope, applied } = plan(current, row);
            if (applied === void 0)
              return this.decline;
            return encodeEnvelope(envelope, {
              ...applied.metadata,
              enabled: false
            });
          }
        });
        return this.transitionResult(ref, result2);
      }
      if (verdict.enable) {
        const result2 = await this.store.enable(ref.id, {
          attribution: fence,
          providerState: (current, row) => {
            const { envelope, applied } = plan(current, row);
            if (applied === void 0 || applied.transition !== "enable") {
              return this.decline;
            }
            return encodeEnvelope(envelope, {
              ...applied.metadata,
              enabled: true
            });
          }
        });
        if (!result2.declined)
          return this.transitionResult(ref, result2);
      }
      let stale = false;
      const result = await this.store.updateProviderState(ref.id, fence, (current, row) => {
        const { envelope, applied } = plan(current, row);
        if (applied === void 0) {
          stale = true;
          return current;
        }
        return encodeEnvelope(envelope, applied.metadata);
      });
      if (stale)
        return { ref, declined: true };
      const metadata = metadataOfStored(result.providerState);
      return {
        ref,
        metadataOutcome: result.outcome,
        ...metadata !== void 0 ? { metadata } : {}
      };
    });
  }
  // ---- metadata ----------------------------------------------------------
  updateMetadata(ref, mutator) {
    return this.run("updateMetadata", ref.id, async () => {
      await this.admit("updateMetadata", ref.id);
      const { index } = await this.accountRowFor("updateMetadata", ref);
      const result = await this.store.updateProviderState(ref.id, credentialFenceOf(ref), async (current, row) => {
        const envelope = shownEnvelope("updateMetadata", current, row);
        const update = await mutator(envelope?.metadata, toAccountRow(row, index));
        if (update.kind === "keep")
          return current;
        if (update.kind === "clear")
          return void 0;
        return encodeEnvelope(envelope, update.metadata);
      });
      return this.metadataResult(ref, result);
    });
  }
  metadataResult(ref, result) {
    const metadata = metadataOfStored(result.providerState);
    return {
      ref,
      outcome: result.outcome,
      ...metadata !== void 0 ? { metadata } : {}
    };
  }
  /**
   * One fenced metadata write: `apply` receives the metadata read under the
   * row lock, or `metadataOrBase`'s starting value for a row with none, and
   * returns the next metadata.
   */
  applyToMetadata(operation, ref, apply) {
    return this.run(operation, ref.id, async () => {
      await this.admit(operation, ref.id);
      const result = await this.store.updateProviderState(ref.id, credentialFenceOf(ref), (current, row) => {
        const envelope = shownEnvelope(operation, current, row);
        const before = metadataOrBase(envelope, row, this.now());
        const after = apply(before);
        return after === before && envelope !== void 0 ? current : encodeEnvelope(envelope, after);
      });
      return this.metadataResult(ref, result);
    });
  }
  recordProject(ref, observation) {
    return this.applyToMetadata("recordProject", ref, (m) => applyProjectObservation(m, observation));
  }
  recordFingerprint(ref, observation) {
    return this.applyToMetadata("recordFingerprint", ref, (m) => applyFingerprintObservation(m, observation));
  }
  recordTier(ref, observation) {
    return this.applyToMetadata("recordTier", ref, (m) => applyTierObservation(m, observation));
  }
  recordCooldown(ref, observation) {
    return this.applyToMetadata("recordCooldown", ref, (m) => applyCooldownObservation(m, observation));
  }
  recordRateLimits(ref, resets) {
    return this.applyToMetadata("recordRateLimits", ref, (m) => applyRateLimitObservation(m, resets));
  }
  recordSwitch(ref, reason) {
    return this.applyToMetadata("recordSwitch", ref, (m) => applySwitch(m, reason));
  }
  recordUsage(ref, observation) {
    return this.run("recordUsage", ref.id, async () => {
      await this.admit("recordUsage", ref.id);
      let result;
      try {
        result = await this.store.updateProviderState(ref.id, credentialFenceOf(ref), (current, row) => {
          const envelope = shownEnvelope("recordUsage", current, row);
          return encodeEnvelope(envelope, applyUsage(metadataOrBase(envelope, row, this.now()), observation, this.now()));
        });
      } catch (error) {
        const failure = this.failureOf("recordUsage", ref.id, error);
        throw new AccountRepositoryError({
          ...failure.failure,
          retryable: failure.failure.ambiguous ? false : failure.failure.retryable
        }, { cause: error });
      }
      const metadata = metadataOfStored(result.providerState);
      if (metadata?.dailyRequestCounts == null) {
        throw refusal("recordUsage", "unexpected", `row ${ref.id} shows no request counts after the increment`, {
          rowId: ref.id,
          ambiguous: true
        });
      }
      return {
        ref,
        lastUsed: metadata.lastUsed,
        dailyRequestCounts: metadata.dailyRequestCounts
      };
    });
  }
  recordQuota(ref, observation) {
    return this.run("recordQuota", ref.id, async () => {
      await this.admit("recordQuota", ref.id);
      let encoded;
      try {
        encoded = encodeQuotaState(observation);
      } catch (error) {
        throw refusal("recordQuota", "invalid-quota", error instanceof Error ? error.message : "invalid quota", {
          rowId: ref.id
        });
      }
      await this.store.recordQuota(ref.id, credentialFenceOf(ref), encoded);
    });
  }
  // ---- selection and roster ---------------------------------------------
  selectAccount(target, row) {
    return this.run("selectAccount", row?.id, async () => {
      await this.admit("selectAccount", row?.id);
      await this.store.updateSettings((settings) => {
        const raw = settings[ROUTING_SETTINGS_KEY];
        const routing = raw === void 0 ? { schemaVersion: ROUTING_SETTINGS_SCHEMA_VERSION } : decodeRoutingSettings(raw);
        if (target === "active") {
          routing.activeRow = row;
        } else {
          routing.activeRowByFamily = {
            ...routing.activeRowByFamily ?? {},
            [target]: row
          };
        }
        return {
          ...settings,
          [ROUTING_SETTINGS_KEY]: encodeRoutingSettings(routing)
        };
      }, {});
    });
  }
  reorder(ids) {
    return this.run("reorder", void 0, async () => {
      await this.admit("reorder");
      await this.store.reorder(ids);
    });
  }
  remove(ref) {
    return this.run("remove", ref.id, async () => {
      await this.admit("remove", ref.id);
      await this.store.remove(ref.id, {
        // Runs under every lock before anything is written. A pending
        // management record refuses the removal, since that operation owns
        // the pool's rows until it finishes; a row that no longer holds
        // `ref` refuses it as stale.
        protect: (_id, view) => {
          if (view.config[MANAGEMENT_SETTINGS_KEY] !== void 0) {
            throw new CallbackRefusal(refusal("remove", "management-pending", "a management operation of the pool is pending", {
              rowId: ref.id,
              retryable: true
            }));
          }
          if (view.row === void 0)
            return void 0;
          const mismatch = refMismatchReason(view.row, ref);
          if (mismatch !== void 0) {
            throw new CallbackRefusal(refusal("remove", "attribution", mismatch, {
              rowId: ref.id,
              retryable: true
            }));
          }
          return void 0;
        }
      });
    });
  }
  // ---- management --------------------------------------------------------
  clear() {
    return this.run("clear", void 0, () => this.withTopology("clear", async (lease) => {
      await this.boundSettings("clear");
      let record2 = await this.readManagement("clear");
      if (record2 !== void 0 && record2.kind !== "clear") {
        throw refusal("clear", "management-pending", `a ${record2.kind} of the account pool is pending`, {
          retryable: true
        });
      }
      if (record2 === void 0) {
        const rows = await this.readRows("clear");
        record2 = await this.startManagement("clear", {
          id: randomUUID2(),
          kind: "clear",
          targets: rows.map((row) => row.id),
          progress: { step: "remove", completedTargets: [] }
        }, lease);
      }
      return this.continueManagement("clear", record2, async (current) => this.removeTargets("clear", current, lease), lease);
    }));
  }
  replacePool(inputs) {
    return this.run("replacePool", void 0, () => this.withTopology("replacePool", async (lease) => {
      this.checkPoolInputs(inputs);
      const pending = await this.readManagement("replacePool");
      if (this.store.publishRoster && this.store.publication && this.storeModule.fingerprintOf && (pending === void 0 || pending.publication !== void 0)) {
        return this.replacePublishedPool(inputs, lease);
      }
      const inputDigest = replacementInputDigest(inputs);
      const inputIds = inputs.map((input) => input.id);
      await this.boundSettings("replacePool");
      let record2 = await this.readManagement("replacePool");
      if (record2 !== void 0) {
        if (record2.kind !== "replace-pool") {
          throw refusal("replacePool", "management-pending", `a ${record2.kind} of the account pool is pending`, {
            retryable: true
          });
        }
        if (record2.inputDigest !== inputDigest) {
          throw refusal("replacePool", "management-pending", "another pool replacement is pending", {
            retryable: true
          });
        }
      } else {
        const rows = await this.readRows("replacePool");
        const held2 = new Set(rows.map((row) => row.id));
        const reused = inputs.find((input) => held2.has(input.id));
        if (reused !== void 0) {
          throw refusal("replacePool", "invalid-input", `input ${reused.id} names a row the pool already holds; a replacement adds new rows`, { rowId: reused.id });
        }
        if (rows.length > 0) {
          throw refusal("replacePool", "replacement-unavailable", "Replacing a non-empty account pool is temporarily unavailable. Existing accounts are unchanged.");
        }
        const id = randomUUID2();
        await lease.assertOwned();
        await this.writeTransfer(id, inputs);
        record2 = await this.startManagement("replacePool", {
          id,
          kind: "replace-pool",
          targets: rows.map((row) => row.id),
          progress: { step: "remove", completedTargets: [] },
          inputDigest
        }, lease);
      }
      return this.continueManagement("replacePool", record2, async (current) => {
        let next = current;
        if (next.progress.step !== "verified") {
          if (next.progress.step === "remove") {
            if (next.targets.length > 0) {
              throw refusal("replacePool", "replacement-unavailable", "Replacing a non-empty account pool is temporarily unavailable. Existing accounts are unchanged.");
            }
            next = await this.removeTargets("replacePool", next, lease);
            next = await this.saveProgress("replacePool", next, "add", [], lease);
          }
          const pending2 = await this.readTransfer(next.id);
          if (replacementInputDigest(pending2) !== next.inputDigest) {
            throw new AccountCodecError("transfer", "does not hold the inputs this replacement was started with");
          }
          if (next.progress.completedTargets.some((id) => !inputIds.includes(id))) {
            throw new AccountCodecError("$.progress.completedTargets", "must name only inputs of the transfer file while they are added");
          }
          for (const input of pending2) {
            if (next.progress.completedTargets.includes(input.id))
              continue;
            await this.addLogin(input, lease);
            next = await this.saveProgress("replacePool", next, "add", [...next.progress.completedTargets, input.id], lease);
          }
          await this.verifyPool(pending2);
          next = await this.saveProgress("replacePool", next, "verified", inputIds, lease);
        } else {
          if (next.progress.completedTargets.length !== inputIds.length || next.progress.completedTargets.some((id, i) => id !== inputIds[i])) {
            throw new AccountCodecError("$.progress.completedTargets", "must name the inputs once the replacement is verified");
          }
          await this.verifyPool(inputs);
        }
        await lease.assertOwned();
        await this.discardTransfer(next.id);
        return next;
      }, lease);
    }));
  }
  // Keep prepared accounts disabled and marked with this operation's identifier.
  // Save their credential refs and the old accounts' refs before publishRoster
  // replaces the account list in one write. A restart replays that saved plan;
  // the store's permanent receipt prevents the operation from publishing twice.
  async replacePublishedPool(inputs, lease) {
    const publish = this.store.publishRoster;
    const publication2 = this.store.publication;
    const fingerprint = this.storeModule.fingerprintOf;
    if (!publish || !publication2 || !fingerprint)
      throw refusal("replacePool", "replacement-unavailable", "Atomic roster publication is unavailable");
    await this.boundSettings("replacePool");
    const inputDigest = replacementInputDigest(inputs);
    let record2 = await this.readManagement("replacePool");
    if (record2) {
      if (record2.kind !== "replace-pool" || record2.inputDigest !== inputDigest || !record2.publication)
        throw refusal("replacePool", "management-pending", "another management operation needs recovery");
    } else {
      const rows = (await this.readRows("replacePool")).filter((row) => row.invalid !== "roster");
      const reused = inputs.find((input) => rows.some((row) => row.id === input.id));
      if (reused)
        throw refusal("replacePool", "invalid-input", `input ${reused.id} names a row the pool already holds; a replacement adds new rows`, { rowId: reused.id });
      const remove2 = rows.map((row) => {
        if (row.invalid || row.torn || row.stamp !== "bound" || !row.credential || !row.credentialEpoch || row.staged)
          throw refusal("replacePool", "invalid-input", `complete row ${row.id} before replacing the pool`);
        return {
          id: row.id,
          attribution: {
            credentialEpoch: row.credentialEpoch,
            ...row.identity !== void 0 ? { identity: row.identity } : {}
          },
          fingerprint: fingerprint(row.credential)
        };
      });
      const id = randomUUID2();
      await lease.assertOwned();
      await this.writeTransfer(id, inputs);
      record2 = await this.startManagement("replacePool", {
        id,
        kind: "replace-pool",
        targets: remove2.map((row) => row.id),
        inputDigest,
        progress: { step: "add", completedTargets: [] },
        publication: {
          operationId: id,
          remove: remove2,
          finalize: [],
          order: inputs.map((input) => input.id)
        }
      }, lease);
    }
    return this.continueManagement("replacePool", record2, async (current) => {
      let next = current;
      let plan = next.publication;
      if (!plan || !isDeepStrictEqual2(plan.order, inputs.map((input) => input.id)))
        throw new AccountCodecError("$.publication.order", "must match the original replacement inputs");
      const protect = async (view) => {
        await lease.assertOwned();
        const raw = view.config[MANAGEMENT_SETTINGS_KEY];
        return raw !== void 0 && canonicalJson(encodeManagementRecord(decodeManagementRecord(raw))) === canonicalJson(encodeManagementRecord(next)) ? void 0 : "the replacement journal no longer holds this operation";
      };
      if (next.progress.step === "add") {
        const pending = await this.readTransfer(next.id);
        if (replacementInputDigest(pending) !== inputDigest)
          throw new AccountCodecError("transfer", "does not hold the original replacement inputs");
        for (const input of pending) {
          if (plan.finalize.some((row) => row.id === input.id))
            continue;
          await lease.assertOwned();
          const added = await this.store.add({
            id: input.id,
            credential: { type: "oauth", refresh: input.refreshToken },
            ...input.identity !== void 0 ? { identity: input.identity } : {},
            providerState: encodeProviderState({
              schemaVersion: PROVIDER_STATE_SCHEMA_VERSION,
              metadata: input.metadata
            }),
            disabled: { reason: "replacement-pending" },
            stage: { reservation: next.id }
          }, { onExisting: "stage-duplicate", protect });
          if (added.id !== input.id || !added.credentialEpoch)
            throw refusal("replacePool", "unexpected", "staging did not return the requested credential ref", { rowId: input.id });
          const enabled = input.metadata.enabled !== false;
          plan = {
            ...plan,
            finalize: [
              ...plan.finalize,
              {
                id: input.id,
                attribution: {
                  credentialEpoch: added.credentialEpoch,
                  ...input.identity !== void 0 ? { identity: input.identity } : {}
                },
                reservation: next.id,
                enabled,
                ...!enabled ? { disabledReason: "disabled-by-user" } : {}
              }
            ]
          };
          next = await this.saveProgress("replacePool", next, "add", plan.finalize.map((row) => row.id), lease, plan);
        }
        next = await this.saveProgress("replacePool", next, "publish", inputs.map((input) => input.id), lease);
      }
      if (next.progress.step === "publish") {
        await lease.assertOwned();
        const existing = await publication2.call(this.store, next.id);
        this.assertPublicationReceipt(plan, existing);
        if (!existing)
          await this.verifyPool(inputs, false, {
            reservation: next.id,
            finalize: plan.finalize
          });
        await publish.call(this.store, plan, { protect });
        const receipt2 = await publication2.call(this.store, next.id);
        this.assertPublicationReceipt(plan, receipt2);
        if (receipt2?.phase !== "cleaned")
          throw refusal("replacePool", "management-pending", "publication cleanup is pending; replay the same inputs", { retryable: true });
        await this.verifyPool(inputs, true);
        next = await this.saveProgress("replacePool", next, "verified", inputs.map((input) => input.id), lease);
      } else if (next.progress.step === "verified") {
        const receipt2 = await publication2.call(this.store, next.id);
        this.assertPublicationReceipt(plan, receipt2);
        if (receipt2?.phase !== "cleaned")
          throw refusal("replacePool", "management-pending", "the native publication receipt is missing");
        await this.verifyPool(inputs, true);
      } else {
        throw new AccountCodecError("$.progress.step", "is not a native publication phase");
      }
      await lease.assertOwned();
      await this.discardTransfer(next.id);
      return next;
    }, lease);
  }
  assertPublicationReceipt(plan, receipt2) {
    if (!receipt2)
      return;
    const digest3 = createHash2("sha256").update(canonicalJson(encodePublicationPlan(plan))).digest("hex");
    const removed = plan.remove.map((row) => ({
      id: row.id,
      credentialEpoch: row.attribution.credentialEpoch
    }));
    const finalized = plan.finalize.map((row) => ({
      id: row.id,
      credentialEpoch: row.attribution.credentialEpoch,
      reservation: row.reservation,
      enabled: row.enabled
    }));
    if (receipt2.operationId !== plan.operationId || receipt2.planDigest !== digest3 || !isDeepStrictEqual2(receipt2.removed, removed) || !isDeepStrictEqual2(receipt2.finalized, finalized)) {
      throw refusal("replacePool", "publication-mismatch", "the native receipt does not prove this replacement plan");
    }
  }
  checkPoolInputs(inputs) {
    const ids = /* @__PURE__ */ new Set();
    const secrets = /* @__PURE__ */ new Set();
    const emails = /* @__PURE__ */ new Set();
    const identities = /* @__PURE__ */ new Set();
    for (const input of inputs) {
      encodeProviderState({
        schemaVersion: PROVIDER_STATE_SCHEMA_VERSION,
        metadata: input.metadata
      });
      if (!input.id || input.id.trim() !== input.id || ["__proto__", "constructor", "prototype"].includes(input.id) || !input.refreshToken.trim() || ids.has(input.id)) {
        throw refusal("replacePool", "invalid-input", "every input needs a refresh token and its own id");
      }
      if (secrets.has(input.refreshToken)) {
        throw refusal("replacePool", "duplicate-secret", "two inputs hold the same credential");
      }
      if (input.identity !== void 0) {
        if (!input.identity || identities.has(input.identity))
          throw refusal("replacePool", "duplicate-identity", "every input needs its own non-empty recorded identity");
        identities.add(input.identity);
      }
      const email = input.metadata.email;
      if (typeof email === "string" && emails.has(email)) {
        throw refusal("replacePool", "duplicate-identity", "two inputs name the same account");
      }
      if (typeof email === "string")
        emails.add(email);
      ids.add(input.id);
      secrets.add(input.refreshToken);
    }
  }
  async startManagement(operation, record2, lease) {
    await lease.assertOwned();
    await this.store.updateSettings((settings) => {
      if (settings[MANAGEMENT_SETTINGS_KEY] !== void 0) {
        throw new CallbackRefusal(refusal(operation, "management-pending", "another management operation started first", {
          retryable: true
        }));
      }
      return {
        ...settings,
        [MANAGEMENT_SETTINGS_KEY]: encodeManagementRecord(record2)
      };
    }, { extraLocks: [managementLock(this.paths)] });
    return record2;
  }
  ownsManagement(settings, record2) {
    const raw = settings[MANAGEMENT_SETTINGS_KEY];
    if (raw === void 0)
      return false;
    try {
      const current = decodeManagementRecord(raw);
      return current.id === record2.id && current.kind === record2.kind && current.inputDigest === record2.inputDigest;
    } catch {
      return false;
    }
  }
  async saveProgress(operation, record2, step, completedTargets, lease, publication2) {
    const next = {
      ...record2,
      ...publication2 !== void 0 ? { publication: publication2 } : {},
      progress: { step, completedTargets }
    };
    await lease.assertOwned();
    await this.store.updateSettings((settings) => {
      if (!this.ownsManagement(settings, record2)) {
        throw new CallbackRefusal(refusal(operation, "management-pending", "the management record changed under this operation"));
      }
      return {
        ...settings,
        [MANAGEMENT_SETTINGS_KEY]: encodeManagementRecord(next)
      };
    }, { extraLocks: [managementLock(this.paths)] });
    return next;
  }
  async removeTargets(operation, record2, lease) {
    let next = record2;
    for (const target of record2.targets) {
      if (next.progress.completedTargets.includes(target))
        continue;
      await lease.assertOwned();
      try {
        await this.store.remove(target, {
          extraLocks: [managementLock(this.paths)],
          protect: (_id, view) => this.ownsManagement(view.config, record2) ? void 0 : "the management record changed under this removal"
        });
      } catch (error) {
        const failure = this.failureOf(operation, target, error);
        if (failure.failure.kind !== "unknown-row")
          throw failure;
      }
      next = await this.saveProgress(operation, next, next.progress.step, [...next.progress.completedTargets, target], lease);
    }
    return next;
  }
  /**
   * Runs a management operation's remaining steps, then drops its record.
   * A retryable failure (lock contention, a lost lease) leaves the record
   * pending and reports it instead of looping; the next call resumes.
   */
  async continueManagement(operation, record2, steps, lease) {
    let finished;
    try {
      finished = await steps(record2);
      await lease.assertOwned();
      await this.store.updateSettings((settings) => {
        if (!this.ownsManagement(settings, record2)) {
          throw new CallbackRefusal(refusal(operation, "management-pending", "the management journal no longer holds this operation; it was not cleared"));
        }
        const { [MANAGEMENT_SETTINGS_KEY]: _done, ...rest } = settings;
        return rest;
      }, { extraLocks: [managementLock(this.paths)] });
    } catch (error) {
      const failure = this.failureOf(operation, void 0, error);
      if (failure.failure.retryable) {
        const now = await this.readManagement(operation) ?? record2;
        return { management: publicManagementRecord(now), outcome: "pending" };
      }
      throw failure;
    }
    return {
      management: publicManagementRecord(finished),
      outcome: "completed"
    };
  }
  /**
   * Checks the pool a replacement leaves before the replacement is recorded
   * verified and its transfer file deleted. The pool must hold exactly the
   * inputs' rows, in input order, and each row must be valid and complete
   * (not invalid, not torn) with the input's id, its refresh token under a
   * bound stamp, its identity (absent only when the
   * input gives none), the metadata it requested and no quota reading. A
   * token present under another id, identity or metadata is not the input.
   * Any mismatch refuses, which leaves the journal and the transfer file in
   * place.
   */
  async verifyPool(inputs, published = false, preparation) {
    const allRows = await this.readRows("replacePool");
    const rows = preparation ? allRows.filter((row) => row.staged?.reservation === preparation.reservation) : published ? allRows.filter((row) => row.invalid !== "roster") : allRows;
    const mismatch = (input, problem) => refusal("replacePool", "unexpected", `input ${input.id} ${problem} ${preparation ? "during preparation" : "after the replacement"}`, { rowId: input.id });
    for (const input of inputs) {
      const row = rows.find((candidate) => candidate.id === input.id);
      if (row === void 0 || row.invalid !== void 0 || row.torn === true || row.credential?.type !== "oauth" || row.credential.refresh !== input.refreshToken || row.stamp !== "bound") {
        throw mismatch(input, "is not in the pool");
      }
      if (preparation && (row.enabled || row.credentialEpoch !== preparation.finalize.find((ref) => ref.id === input.id)?.attribution.credentialEpoch))
        throw mismatch(input, "does not hold its disabled prepared credential");
      if (published && (row.staged || row.enabled !== (input.metadata.enabled !== false)))
        throw mismatch(input, "has not been finalized with its requested enabled state");
      if (row.identity !== input.identity) {
        throw mismatch(input, "is recorded for another identity");
      }
      if (row.providerStateDropped !== void 0 || row.providerState === void 0 || canonicalJson(encodeProviderMetadata(decodeProviderState(row.providerState).metadata)) !== canonicalJson(encodeProviderMetadata(input.metadata))) {
        throw mismatch(input, "does not hold its requested metadata");
      }
      if (row.quota !== void 0) {
        throw mismatch(input, "holds a quota reading");
      }
    }
    if (rows.length !== inputs.length || rows.some((row, index) => row.id !== inputs[index]?.id)) {
      throw refusal("replacePool", "unexpected", "the pool does not hold exactly the replacement inputs, in their order");
    }
  }
  transferPath(id) {
    return join2(this.paths.transfersDir, `${id}.json`);
  }
  async writeTransfer(id, inputs) {
    await mkdir2(this.paths.transfersDir, { recursive: true, mode: 448 });
    const body = {
      schemaVersion: 1,
      managementId: id,
      inputs: inputs.map(encodeLoginInput)
    };
    const handle = await open2(this.transferPath(id), "wx", 384);
    try {
      await handle.writeFile(JSON.stringify(body));
      await handle.sync();
    } finally {
      await handle.close();
    }
    for (const path2 of [this.paths.transfersDir, this.paths.storeDir]) {
      const directory = await open2(path2, "r");
      try {
        await directory.sync();
      } finally {
        await directory.close();
      }
    }
  }
  async readTransfer(id) {
    const raw = JSON.parse(await readFile(this.transferPath(id), "utf8"));
    return decodeTransferFile(raw, id);
  }
  async discardTransfer(id) {
    try {
      await unlink2(this.transferPath(id));
    } catch (error) {
      if (!(isRecord(error) && error.code === "ENOENT"))
        throw error;
    }
  }
  // ---- draining ----------------------------------------------------------
  flush() {
    return this.drain();
  }
  async drain() {
    while (this.inFlight.size > 0) {
      await Promise.allSettled([...this.inFlight]);
    }
    const report = { completed: this.completed, failures: this.failures };
    this.completed = 0;
    this.failures = [];
    return report;
  }
  async dispose() {
    this.closing = true;
    return this.drain();
  }
};
function createAccountRepositoryFactory(modules, factoryOptions = {}) {
  return (options) => new StoreAccountRepository(modules, options, factoryOptions);
}

// ../core/dist/fingerprint.js
var AGY_CLI_VERSION = "1.1.24";
var AGY_CLI_CHANGE_LIST = "974782877";
function normalizeHarnessPlatform(platform = process.platform) {
  return platform === "win32" ? "windows" : platform || "unknown";
}
function normalizeHarnessArch(arch = process.arch) {
  switch (arch) {
    case "x64":
      return "amd64";
    case "ia32":
      return "386";
    default:
      return arch || "unknown";
  }
}
function buildAntigravityHarnessUserAgent(version = AGY_CLI_VERSION, platform = process.platform, arch = process.arch, authMethod = "consumer") {
  const osType = normalizeHarnessPlatform(platform);
  const normalizedArch = normalizeHarnessArch(arch);
  const changeList = version === AGY_CLI_VERSION ? `; cl=${AGY_CLI_CHANGE_LIST}` : "";
  return `antigravity/cli/${version} (aidev_client; os_type=${osType}; arch=${normalizedArch}${changeList}; auth_method=${authMethod})`;
}
function buildAntigravityHarnessLoadCodeAssistUserAgent(version = AGY_CLI_VERSION) {
  return buildAntigravityHarnessUserAgent(version);
}
function buildAntigravityLoadCodeAssistMetadata() {
  return { ideType: "ANTIGRAVITY" };
}
function buildAntigravityHarnessBootstrapHeaders(accessToken) {
  return {
    "User-Agent": buildAntigravityHarnessLoadCodeAssistUserAgent(),
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
    "Accept-Encoding": "gzip"
  };
}

// ../core/dist/model-registry.js
var DEFAULT_MODALITIES = {
  input: ["text", "image", "pdf"],
  output: ["text"]
};
var MODEL_RELEASE_DATE = "";
var DEFAULT_COST = { input: 0, output: 0 };
var DEFAULT_OPTIONS = {};
function defineModel(id, model) {
  return {
    id,
    release_date: MODEL_RELEASE_DATE,
    attachment: model.modalities.input.some((modality) => modality !== "text"),
    temperature: true,
    tool_call: true,
    cost: { ...DEFAULT_COST },
    options: { ...DEFAULT_OPTIONS },
    ...model
  };
}
var ALL_MODEL_DEFINITIONS = {
  "antigravity-gemini-3.1-pro": defineModel("antigravity-gemini-3.1-pro", {
    name: "Gemini 3.1 Pro (Antigravity)",
    reasoning: true,
    limit: { context: 1048576, output: 65535 },
    modalities: DEFAULT_MODALITIES,
    variants: {
      low: { thinkingLevel: "low" },
      high: { thinkingLevel: "high" }
    }
  }),
  "antigravity-gemini-3.8-flash": defineModel("antigravity-gemini-3.8-flash", {
    name: "Gemini 3.8 Flash (Antigravity)",
    reasoning: true,
    limit: { context: 1048576, output: 65536 },
    modalities: DEFAULT_MODALITIES,
    variants: {
      low: { thinkingLevel: "low" },
      high: { thinkingLevel: "high" }
    }
  }),
  "antigravity-gemini-3.7-flash": defineModel("antigravity-gemini-3.7-flash", {
    name: "Gemini 3.7 Flash (Antigravity)",
    reasoning: true,
    limit: { context: 1048576, output: 65536 },
    modalities: DEFAULT_MODALITIES,
    variants: {
      low: { thinkingLevel: "low" },
      high: { thinkingLevel: "high" }
    }
  }),
  "antigravity-gemini-3.6-flash": defineModel("antigravity-gemini-3.6-flash", {
    name: "Gemini 3.6 Flash (Antigravity)",
    reasoning: true,
    limit: { context: 1048576, output: 65536 },
    modalities: DEFAULT_MODALITIES,
    variants: {
      low: { thinkingLevel: "low" },
      high: { thinkingLevel: "high" }
    }
  }),
  "antigravity-gemini-3.5-flash": defineModel("antigravity-gemini-3.5-flash", {
    name: "Gemini 3.5 Flash (Antigravity)",
    reasoning: true,
    limit: { context: 1048576, output: 65536 },
    modalities: DEFAULT_MODALITIES,
    variants: {
      low: { thinkingLevel: "low" },
      high: { thinkingLevel: "high" }
    }
  }),
  "antigravity-claude-sonnet-4-6-thinking": defineModel("antigravity-claude-sonnet-4-6-thinking", {
    name: "Claude Sonnet 4.6 Thinking (Antigravity)",
    reasoning: true,
    limit: { context: 25e4, output: 64e3 },
    modalities: DEFAULT_MODALITIES,
    variants: {
      low: { disabled: true },
      high: { disabled: true }
    }
  }),
  "antigravity-claude-opus-4-6-thinking": defineModel("antigravity-claude-opus-4-6-thinking", {
    name: "Claude Opus 4.6 Thinking (Antigravity)",
    reasoning: true,
    limit: { context: 25e4, output: 64e3 },
    modalities: DEFAULT_MODALITIES,
    variants: {
      low: { disabled: true },
      high: { disabled: true }
    }
  }),
  "antigravity-gemini-3.1-flash-image": defineModel("antigravity-gemini-3.1-flash-image", {
    name: "Gemini 3.1 Flash Image (Antigravity)",
    reasoning: false,
    limit: { context: 66e3, output: 33e3 },
    modalities: {
      input: ["text", "image"],
      output: ["text", "image"]
    }
  }),
  "antigravity-gpt-oss-120b-medium": defineModel("antigravity-gpt-oss-120b-medium", {
    name: "GPT-OSS 120B Medium (Antigravity)",
    reasoning: true,
    limit: { context: 131072, output: 32768 },
    modalities: DEFAULT_MODALITIES
  }),
  "gemini-2.5-flash": defineModel("gemini-2.5-flash", {
    name: "Gemini 2.5 Flash (Gemini CLI)",
    reasoning: true,
    limit: { context: 1048576, output: 65536 },
    modalities: DEFAULT_MODALITIES
  }),
  "gemini-2.5-pro": defineModel("gemini-2.5-pro", {
    name: "Gemini 2.5 Pro (Gemini CLI)",
    reasoning: true,
    limit: { context: 1048576, output: 65536 },
    modalities: DEFAULT_MODALITIES
  }),
  "gemini-3-flash-preview": defineModel("gemini-3-flash-preview", {
    name: "Gemini 3 Flash Preview (Gemini CLI)",
    reasoning: true,
    limit: { context: 1048576, output: 65536 },
    modalities: DEFAULT_MODALITIES
  }),
  "gemini-3.1-pro-preview": defineModel("gemini-3.1-pro-preview", {
    name: "Gemini 3.1 Pro Preview (Gemini CLI)",
    reasoning: true,
    limit: { context: 1048576, output: 65535 },
    modalities: DEFAULT_MODALITIES
  }),
  "gemini-3.5-flash-preview": defineModel("gemini-3.5-flash-preview", {
    name: "Gemini 3.5 Flash Preview (Gemini CLI)",
    reasoning: true,
    limit: { context: 1048576, output: 65536 },
    modalities: DEFAULT_MODALITIES
  }),
  "gemini-3.1-flash-image": defineModel("gemini-3.1-flash-image", {
    name: "Gemini 3.1 Flash Image (Gemini CLI)",
    reasoning: false,
    limit: { context: 66e3, output: 33e3 },
    modalities: {
      input: ["text", "image"],
      output: ["text", "image"]
    }
  }),
  "gemini-3.1-flash-image-preview": defineModel("gemini-3.1-flash-image-preview", {
    name: "Gemini 3.1 Flash Image Preview (Gemini CLI)",
    reasoning: false,
    limit: { context: 66e3, output: 33e3 },
    modalities: {
      input: ["text", "image"],
      output: ["text", "image"]
    }
  }),
  "gemini-3.1-pro-preview-customtools": defineModel("gemini-3.1-pro-preview-customtools", {
    name: "Gemini 3.1 Pro Preview Custom Tools (Gemini CLI)",
    reasoning: true,
    limit: { context: 1048576, output: 65535 },
    modalities: DEFAULT_MODALITIES
  })
};
var RESOLVER_ALIASES = {
  "gemini-3.1-pro-low": "gemini-3.1-pro",
  "gemini-3.1-pro-high": "gemini-3.1-pro",
  "gemini-3-flash-low": "gemini-3-flash",
  "gemini-3-flash-medium": "gemini-3-flash",
  "gemini-3-flash-high": "gemini-3-flash",
  "gemini-3.5-flash-low": "gemini-3.5-flash",
  "gemini-3.5-flash-medium": "gemini-3.5-flash",
  "gemini-3.5-flash-high": "gemini-3.5-flash",
  "gemini-3.6-flash-low": "gemini-3.6-flash",
  "gemini-3.6-flash-medium": "gemini-3.6-flash",
  "gemini-3.6-flash-high": "gemini-3.6-flash",
  "gemini-3.7-flash-low": "gemini-3.7-flash",
  "gemini-3.7-flash-medium": "gemini-3.7-flash",
  "gemini-3.7-flash-high": "gemini-3.7-flash",
  "gemini-3.8-flash-low": "gemini-3.8-flash",
  "gemini-3.8-flash-medium": "gemini-3.8-flash",
  "gemini-3.8-flash-high": "gemini-3.8-flash",
  "gemini-claude-opus-4-6-thinking-low": "claude-opus-4-6-thinking",
  "gemini-claude-opus-4-6-thinking-medium": "claude-opus-4-6-thinking",
  "gemini-claude-opus-4-6-thinking-high": "claude-opus-4-6-thinking",
  "gemini-claude-sonnet-4-6-thinking-low": "claude-sonnet-4-6",
  "gemini-claude-sonnet-4-6-thinking-medium": "claude-sonnet-4-6",
  "gemini-claude-sonnet-4-6-thinking-high": "claude-sonnet-4-6",
  "gemini-claude-sonnet-4-6": "claude-sonnet-4-6",
  "claude-sonnet-4-6-thinking": "claude-sonnet-4-6",
  "claude-sonnet-4-6-thinking-low": "claude-sonnet-4-6",
  "claude-sonnet-4-6-thinking-medium": "claude-sonnet-4-6",
  "claude-sonnet-4-6-thinking-high": "claude-sonnet-4-6",
  "gpt-oss-120b": "gpt-oss-120b-medium"
};
var QUOTA_GROUP_BY_MODEL_ID = {
  "claude-opus-4-6-thinking": "non-gemini",
  "claude-opus-4-6": "non-gemini",
  "claude-sonnet-4-6-thinking": "non-gemini",
  "claude-sonnet-4-6": "non-gemini",
  "gemini-pro-agent": "gemini",
  "gemini-3.1-pro": "gemini",
  "gemini-3.1-pro-low": "gemini",
  "gemini-3.1-pro-high": "gemini",
  "gemini-3-flash": "gemini",
  "gemini-3-flash-agent": "gemini",
  "gemini-3.5-flash-low": "gemini",
  "gemini-3.5-flash-extra-low": "gemini",
  "gemini-3.6-flash-low": "gemini",
  "gemini-3.6-flash-medium": "gemini",
  "gemini-3.6-flash-high": "gemini",
  "gemini-3.6-flash-tiered": "gemini",
  "gemini-3.7-flash-low": "gemini",
  "gemini-3.7-flash-medium": "gemini",
  "gemini-3.7-flash-high": "gemini",
  "gemini-3.7-flash-tiered": "gemini",
  "gemini-3.8-flash-low": "gemini",
  "gemini-3.8-flash-medium": "gemini",
  "gemini-3.8-flash-high": "gemini",
  "gemini-3.8-flash-tiered": "gemini",
  "gemini-3.1-flash-image": "gemini",
  "gpt-oss-120b": "non-gemini",
  "gpt-oss-120b-medium": "non-gemini"
};
var ANTIGRAVITY_OPENCODE_MODEL_IDS = [
  "antigravity-gemini-3.8-flash",
  "antigravity-gemini-3.6-flash",
  "antigravity-gemini-3.5-flash",
  "antigravity-gemini-3.1-pro",
  "antigravity-claude-sonnet-4-6-thinking",
  "antigravity-claude-opus-4-6-thinking",
  "antigravity-gemini-3.1-flash-image",
  "antigravity-gpt-oss-120b-medium"
];

// --- Dynamic Model Catalog & Google CloudCode Sync ---
var DYNAMIC_MODELS_CACHE_FILE = "antigravity-models-cache.json";
function getDynamicModelsCachePath() {
  try {
    const configDir = typeof getLegacyWindowsConfigDir === "function" ? getLegacyWindowsConfigDir() : (process.env.USERPROFILE ? join(process.env.USERPROFILE, ".config", "opencode") : "");
    return configDir ? join(configDir, DYNAMIC_MODELS_CACHE_FILE) : "";
  } catch {
    return "";
  }
}
function loadDynamicModelsCache() {
  try {
    const p = getDynamicModelsCachePath();
    if (p && existsSync(p)) {
      const data = JSON.parse(readFileSync(p, "utf-8"));
      if (Array.isArray(data.models) && data.models.length > 0) {
        return data;
      }
    }
  } catch {}
  return null;
}
function ensureDynamicModelDefinition(id) {
  if (ALL_MODEL_DEFINITIONS[id]) return ALL_MODEL_DEFINITIONS[id];
  const match = id.match(/^antigravity-gemini-(\d+(?:\.\d+)?)-(flash|pro)/i);
  if (match) {
    const ver = match[1];
    const type = match[2].toLowerCase();
    const capType = type.charAt(0).toUpperCase() + type.slice(1);
    const isPro = type === "pro";
    ALL_MODEL_DEFINITIONS[id] = defineModel(id, {
      name: `Gemini ${ver} ${capType} (Antigravity)`,
      reasoning: true,
      limit: { context: 1048576, output: isPro ? 65535 : 65536 },
      modalities: DEFAULT_MODALITIES,
      variants: {
        low: { thinkingLevel: "low" },
        high: { thinkingLevel: "high" }
      }
    });
    return ALL_MODEL_DEFINITIONS[id];
  }
  return null;
}

try {
  const initCache = loadDynamicModelsCache();
  if (initCache && Array.isArray(initCache.models) && initCache.models.length > 0) {
    for (const mId of initCache.models) {
      ensureDynamicModelDefinition(mId);
    }
    ANTIGRAVITY_OPENCODE_MODEL_IDS = [...initCache.models];
  }
} catch {}

function pickModelDefinitions(ids) {
  return Object.fromEntries(ids.map((id) => [id, ALL_MODEL_DEFINITIONS[id] || ensureDynamicModelDefinition(id)]).filter(([, def]) => Boolean(def)));
}
var OPENCODE_MODEL_DEFINITIONS = pickModelDefinitions(ANTIGRAVITY_OPENCODE_MODEL_IDS);
function getResolverAliasMap() {
  return RESOLVER_ALIASES;
}
function getQuotaGroupForModel(modelId) {
  const normalized = modelId.toLowerCase();
  return QUOTA_GROUP_BY_MODEL_ID[normalized] ?? // Check Claude / GPT-OSS substrings BEFORE the `gemini` substring so
  // a `gemini-claude-*` alias (which is a Claude route exposed under
  // a `gemini-` namespace) attributes to the non-gemini pool rather
  // than the gemini pool. Substring matching is required because the
  // alias IDs start with `gemini-` but contain `claude`.
  (normalized.includes("claude") || normalized.includes("gpt-oss") ? "non-gemini" : normalized.startsWith("gemini") || normalized.startsWith("tab_") ? "gemini" : void 0);
}

// ../core/dist/account-selector.js
var ACCOUNT_SESSION_STATE_TTL_MS = 24 * 60 * 60 * 1e3;

// ../core/dist/account-storage.js
import { chmod, copyFile, mkdir as mkdir5, readFile as readFile3, unlink as unlink4 } from "node:fs/promises";

// ../core/dist/atomic-write.js
import { randomUUID as randomUUID3 } from "node:crypto";
import { mkdir as mkdir3, rename, rm, writeFile } from "node:fs/promises";
import { dirname as dirname3 } from "node:path";
async function writeJsonAtomic(path2, value, options) {
  const serialized = `${JSON.stringify(value, null, 2)}
`;
  const tempPath = `${path2}.${randomUUID3()}.tmp`;
  await mkdir3(dirname3(path2), { recursive: true });
  let renamed = false;
  try {
    await writeFile(tempPath, serialized, {
      encoding: "utf8",
      mode: 384
    });
    const beforeRename = options?.beforeRename;
    if (beforeRename)
      await beforeRename(tempPath);
    await rename(tempPath, path2);
    renamed = true;
  } finally {
    if (!renamed) {
      await rm(tempPath, { force: true }).catch(() => {
      });
    }
  }
}

// ../core/dist/file-lock.js
import { randomUUID as randomUUID4 } from "node:crypto";
import { mkdir as mkdir4, readFile as readFile2, rename as rename2, rm as rm2, stat as stat2, unlink as unlink3, writeFile as writeFile2 } from "node:fs/promises";
import { dirname as dirname4, join as join3 } from "node:path";
var RENEW_MIN_INTERVAL_MS = 1e3;
var MARKER_CLAIM_MAX_ATTEMPTS = 8;
var MARKER_CLAIM_BACKOFF_MS = 25;
var FileLockOwnershipError = class extends Error {
  details;
  constructor(message, details) {
    super(message);
    this.name = "FileLockOwnershipError";
    this.details = details;
  }
};
var MARKER_TTL_MS = 3e4;
async function readLockPayload(path2) {
  try {
    const text2 = await readFile2(path2, "utf8");
    const parsed = JSON.parse(text2);
    if (typeof parsed === "object" && parsed !== null && typeof parsed.ownerId === "string" && typeof parsed.expiresAt === "number") {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}
async function readMarkerPayload(path2) {
  try {
    const text2 = await readFile2(path2, "utf8");
    const parsed = JSON.parse(text2);
    if (typeof parsed === "object" && parsed !== null && typeof parsed.ownerId === "string" && typeof parsed.pid === "number" && typeof parsed.createdAt === "number") {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}
function isProcessAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0)
    return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    const code2 = err.code;
    if (code2 === "ESRCH")
      return false;
    return true;
  }
}
async function rmEvictingDir(evictingPath) {
  await rm2(evictingPath, { force: true }).catch(() => {
  });
  await rm2(dirname4(evictingPath), { recursive: true, force: true }).catch(() => {
  });
}
async function sleep(ms) {
  await new Promise((resolve7) => setTimeout(resolve7, ms));
}
async function acquireFencedFileLock(options) {
  const lockPath = `${options.path}.${options.name}.lock`;
  const evictingDir = `${lockPath}.evicting`;
  const evictingPath = join3(evictingDir, "owner.json");
  const ownerId = randomUUID4();
  const now = options.now ?? Date.now;
  const tryAcquire = async (expiresAt) => {
    const payload = JSON.stringify({ ownerId, expiresAt });
    try {
      await mkdir4(dirname4(lockPath), { recursive: true });
      await writeFile2(lockPath, payload, {
        flag: "wx",
        encoding: "utf8",
        mode: 384
      });
      return buildLock(lockPath, evictingPath, ownerId, options, now);
    } catch (err) {
      if (err.code === "EEXIST") {
        return null;
      }
      throw err;
    }
  };
  for (; ; ) {
    const firstTry = await tryAcquire(now() + options.ttlMs);
    if (firstTry)
      return firstTry;
    const observed = await readLockPayload(lockPath);
    const lockStats = await stat2(lockPath).catch(() => null);
    if (!lockStats)
      continue;
    const currentTime = now();
    const looksLive = observed !== null && typeof observed.ownerId === "string" && observed.expiresAt > currentTime;
    if (looksLive) {
      return null;
    }
    const looksValid = observed !== null;
    if (!looksValid) {
      const ageMs = currentTime - lockStats.mtimeMs;
      if (ageMs < options.ttlMs)
        return null;
    }
    await options.onStep?.("stale-marker-stat");
    let markerClaimed = false;
    for (let attempt = 0; attempt < MARKER_CLAIM_MAX_ATTEMPTS; attempt++) {
      try {
        await mkdir4(evictingDir, { recursive: true, mode: 448 });
        await writeFile2(evictingPath, JSON.stringify({
          ownerId,
          pid: process.pid,
          createdAt: now()
        }), {
          flag: "wx",
          encoding: "utf8",
          mode: 384
        });
        markerClaimed = true;
        break;
      } catch (err) {
        if (err.code !== "EEXIST")
          throw err;
        const existing = await readMarkerPayload(evictingPath);
        if (existing) {
          const ageMs = now() - existing.createdAt;
          const deadPid = !isProcessAlive(existing.pid);
          if (deadPid || ageMs > MARKER_TTL_MS) {
            await rmEvictingDir(evictingPath);
            continue;
          }
        }
        await sleep(MARKER_CLAIM_BACKOFF_MS);
      }
    }
    if (!markerClaimed) {
      return null;
    }
    await options.onStep?.("stale-marker-claimed");
    let markerPayload = await readMarkerPayload(evictingPath);
    if (markerPayload?.ownerId !== ownerId)
      continue;
    const observedAgain = await readLockPayload(lockPath);
    const refreshed = observedAgain !== null && observedAgain.ownerId !== ownerId && observedAgain.expiresAt > now();
    if (refreshed) {
      await rmEvictingDir(evictingPath);
      return null;
    }
    await options.onStep?.("stale-lock-confirmed");
    markerPayload = await readMarkerPayload(evictingPath);
    if (markerPayload?.ownerId !== ownerId)
      continue;
    try {
      await unlink3(lockPath);
    } catch (err) {
      const code2 = err.code;
      if (code2 !== "ENOENT") {
        await rmEvictingDir(evictingPath);
        continue;
      }
    }
    await options.onStep?.("eviction-marker-acquired");
    const reentry = await tryAcquire(now() + options.ttlMs);
    if (reentry) {
      await rmEvictingDir(evictingPath);
      return reentry;
    }
    await rmEvictingDir(evictingPath);
  }
}
function buildLock(lockPath, evictingPath, ownerId, options, now) {
  let renewTimer = null;
  let inFlightRenew = null;
  let released = false;
  let lost = false;
  let lostResolve = null;
  let lostPromise = new Promise((resolve7) => {
    lostResolve = resolve7;
  });
  const markLost = () => {
    if (lost)
      return;
    lost = true;
    if (renewTimer !== null) {
      clearInterval(renewTimer);
      renewTimer = null;
    }
    const resolve7 = lostResolve;
    lostResolve = null;
    resolve7?.();
  };
  const setupRenew = () => {
    if (options.renew === false)
      return;
    const interval = options.renewIntervalMs ?? Math.max(RENEW_MIN_INTERVAL_MS, Math.floor(options.ttlMs / 3));
    const renew = async () => {
      if (released || lost)
        return;
      try {
        const observed = await readLockPayload(lockPath);
        if (released || lost)
          return;
        await options.onStep?.("renew-read");
        if (released || lost)
          return;
        if (observed === null) {
          markLost();
          return;
        }
        if (observed.ownerId !== ownerId) {
          markLost();
          return;
        }
        if (observed.expiresAt > now()) {
          if (released || lost)
            return;
          const tempPath = `${lockPath}.${ownerId}.tmp`;
          let shouldCommit = false;
          try {
            await writeFile2(tempPath, JSON.stringify({
              ownerId,
              expiresAt: now() + options.ttlMs
            }), { encoding: "utf8", mode: 384 });
            if (released || lost) {
              await unlink3(tempPath).catch(() => {
              });
              return;
            }
            const currentObserved = await readLockPayload(lockPath);
            if (released || lost) {
              await unlink3(tempPath).catch(() => {
              });
              return;
            }
            if (!currentObserved || currentObserved.ownerId !== ownerId) {
              markLost();
              await unlink3(tempPath).catch(() => {
              });
              return;
            }
            shouldCommit = true;
            await rename2(tempPath, lockPath);
            await options.onStep?.("renew-committed");
            if (released || lost)
              return;
            const committed = await readLockPayload(lockPath);
            if (released || lost)
              return;
            if (!committed || committed.ownerId !== ownerId) {
              markLost();
              return;
            }
          } catch {
            markLost();
            if (!shouldCommit) {
              await unlink3(tempPath).catch(() => {
              });
            }
          }
        }
      } catch {
      }
    };
    const tick = () => {
      if (released)
        return;
      if (inFlightRenew)
        return;
      inFlightRenew = renew().finally(() => {
        inFlightRenew = null;
      });
    };
    renewTimer = setInterval(tick, interval);
    if (renewTimer && typeof renewTimer.unref === "function") {
      ;
      renewTimer.unref();
    }
  };
  const release = async () => {
    if (released)
      return;
    released = true;
    if (renewTimer !== null) {
      clearInterval(renewTimer);
      renewTimer = null;
    }
    const pendingRenew = inFlightRenew;
    inFlightRenew = null;
    if (pendingRenew) {
      try {
        await pendingRenew;
      } catch {
      }
    }
    try {
      const observed = await readLockPayload(lockPath);
      if (!observed || observed.ownerId !== ownerId) {
        await rmEvictingDir(evictingPath).catch(() => {
        });
        return;
      }
      try {
        await unlink3(lockPath);
      } catch (err) {
        if (err.code !== "ENOENT")
          throw err;
      }
      await rmEvictingDir(evictingPath).catch(() => {
      });
    } finally {
      markLost();
      renewTimer = null;
      inFlightRenew = null;
      lostResolve = null;
      lostPromise = null;
    }
  };
  const assertOwned = async () => {
    const observed = await readLockPayload(lockPath);
    if (!observed || observed.ownerId !== ownerId) {
      throw new FileLockOwnershipError(`file lock ${lockPath} is not owned by ${ownerId}`, {
        path: lockPath,
        expectedOwner: ownerId,
        observedOwner: observed?.ownerId,
        observedExpiresAt: observed?.expiresAt
      });
    }
    if (observed.expiresAt <= now()) {
      throw new FileLockOwnershipError(`file lock ${lockPath} has expired`, {
        path: lockPath,
        expectedOwner: ownerId,
        observedOwner: observed.ownerId,
        observedExpiresAt: observed.expiresAt
      });
    }
  };
  setupRenew();
  return {
    ownerId,
    assertOwned,
    release,
    whenLost: () => lostPromise ?? Promise.resolve(),
    hasLost: () => lost
  };
}

// ../core/dist/logger.js
var ENV_CONSOLE_LOG = "ANTIGRAVITY_CORE_CONSOLE_LOG";
var _sink = null;
function isTruthyFlag(flag) {
  return flag === "1" || flag?.toLowerCase() === "true";
}
function isConsoleLogEnabled() {
  return isTruthyFlag(process.env[ENV_CONSOLE_LOG]);
}
function writeConsoleLog(level, ...args) {
  switch (level) {
    case "debug":
      console.debug(...args);
      break;
    case "info":
      console.info(...args);
      break;
    case "warn":
      console.warn(...args);
      break;
    case "error":
      console.error(...args);
      break;
  }
}
function createLogger(module) {
  const service = `antigravity.${module}`;
  const log8 = (level, message, extra) => {
    if (_sink) {
      try {
        _sink({ service, level, message, extra });
      } catch {
      }
    }
    if (isConsoleLogEnabled()) {
      const prefix = `[${service}]`;
      const args = extra ? [prefix, message, extra] : [prefix, message];
      writeConsoleLog(level, ...args);
    }
  };
  return {
    debug: (message, extra) => log8("debug", message, extra),
    info: (message, extra) => log8("info", message, extra),
    warn: (message, extra) => log8("warn", message, extra),
    error: (message, extra) => log8("error", message, extra)
  };
}

// ../core/dist/account-storage.js
var log = createLogger("account-storage");
var AccountStorageLockContentionError = class extends Error {
  details;
  constructor(message, details) {
    super(message);
    this.name = "AccountStorageLockContentionError";
    this.details = details;
  }
};
var AccountStorageUnreadableError = class extends Error {
  details;
  constructor(message, details) {
    super(message);
    this.name = "AccountStorageUnreadableError";
    this.details = details;
  }
};
var RETRY_DELAYS_MS = [100, 200, 400, 800, 1e3];
var DEFAULT_SLEEP = (ms) => new Promise((resolve7) => setTimeout(resolve7, ms));
var DEFAULT_BUILD_BACKUP_PATH = (path2, now) => `${path2}.corrupt-${now.toISOString().replace(/[:.]/g, "-")}`;
async function ensureSecurePermissions(path2) {
  try {
    await chmod(path2, 384);
  } catch {
  }
}
async function backupCorruptFile(sourcePath, buildBackupPath, now) {
  const backupPath = buildBackupPath(sourcePath, now);
  if (!backupPath)
    return null;
  try {
    await copyFile(sourcePath, backupPath);
    await ensureSecurePermissions(backupPath);
    return backupPath;
  } catch (backupError) {
    log.warn("Failed to back up corrupt account storage file", {
      sourcePath,
      backupPath,
      error: String(backupError)
    });
    return null;
  }
}
function deduplicateAccountsByEmail(accounts) {
  const emailToNewestIndex = /* @__PURE__ */ new Map();
  const indicesToKeep = /* @__PURE__ */ new Set();
  for (let i = 0; i < accounts.length; i++) {
    const acc = accounts[i];
    if (!acc)
      continue;
    if (!acc.email) {
      indicesToKeep.add(i);
      continue;
    }
    const existingIndex = emailToNewestIndex.get(acc.email);
    if (existingIndex === void 0) {
      emailToNewestIndex.set(acc.email, i);
      continue;
    }
    const existing = accounts[existingIndex];
    if (!existing) {
      emailToNewestIndex.set(acc.email, i);
      continue;
    }
    const currLastUsed = acc.lastUsed || 0;
    const existLastUsed = existing.lastUsed || 0;
    const currAddedAt = acc.addedAt || 0;
    const existAddedAt = existing.addedAt || 0;
    const isNewer = currLastUsed > existLastUsed || currLastUsed === existLastUsed && currAddedAt > existAddedAt;
    if (isNewer) {
      emailToNewestIndex.set(acc.email, i);
    }
  }
  for (const idx of emailToNewestIndex.values()) {
    indicesToKeep.add(idx);
  }
  const result = [];
  for (let i = 0; i < accounts.length; i++) {
    if (indicesToKeep.has(i)) {
      const acc = accounts[i];
      if (acc) {
        result.push(acc);
      }
    }
  }
  return result;
}
function migrateV1ToV2(v1) {
  return {
    version: 2,
    accounts: v1.accounts.map((acc) => {
      const rateLimitResetTimes = {};
      if (acc.isRateLimited && acc.rateLimitResetTime && acc.rateLimitResetTime > Date.now()) {
        rateLimitResetTimes.claude = acc.rateLimitResetTime;
        rateLimitResetTimes.gemini = acc.rateLimitResetTime;
      }
      return {
        email: acc.email,
        refreshToken: acc.refreshToken,
        projectId: acc.projectId,
        managedProjectId: acc.managedProjectId,
        addedAt: acc.addedAt,
        lastUsed: acc.lastUsed,
        lastSwitchReason: acc.lastSwitchReason,
        rateLimitResetTimes: Object.keys(rateLimitResetTimes).length > 0 ? rateLimitResetTimes : void 0
      };
    }),
    activeIndex: v1.activeIndex
  };
}
function migrateV2ToV3(v2) {
  return {
    version: 3,
    accounts: v2.accounts.map((acc) => {
      const rateLimitResetTimes = {};
      if (acc.rateLimitResetTimes?.claude && acc.rateLimitResetTimes.claude > Date.now()) {
        rateLimitResetTimes.claude = acc.rateLimitResetTimes.claude;
      }
      if (acc.rateLimitResetTimes?.gemini && acc.rateLimitResetTimes.gemini > Date.now()) {
        rateLimitResetTimes["gemini-antigravity"] = acc.rateLimitResetTimes.gemini;
      }
      return {
        email: acc.email,
        refreshToken: acc.refreshToken,
        projectId: acc.projectId,
        managedProjectId: acc.managedProjectId,
        addedAt: acc.addedAt,
        lastUsed: acc.lastUsed,
        lastSwitchReason: acc.lastSwitchReason,
        rateLimitResetTimes: Object.keys(rateLimitResetTimes).length > 0 ? rateLimitResetTimes : void 0
      };
    }),
    activeIndex: v2.activeIndex
  };
}
function migrateV3ToV4(v3) {
  return {
    version: 4,
    accounts: v3.accounts.map((acc) => ({
      ...acc,
      fingerprint: void 0,
      fingerprintHistory: void 0
    })),
    activeIndex: v3.activeIndex,
    activeIndexByFamily: v3.activeIndexByFamily
  };
}
function mergeAccountStorage(existing, incoming) {
  const accountMap = /* @__PURE__ */ new Map();
  for (const acc of existing.accounts) {
    if (acc.refreshToken) {
      accountMap.set(acc.refreshToken, acc);
    }
  }
  for (const acc of incoming.accounts) {
    if (!acc.refreshToken)
      continue;
    const existingAcc = accountMap.get(acc.refreshToken);
    if (existingAcc) {
      const eligibilitySource = (acc.eligibilityStateUpdatedAt ?? 0) >= (existingAcc.eligibilityStateUpdatedAt ?? 0) ? acc : existingAcc;
      const merged = {
        ...existingAcc,
        ...acc,
        projectId: acc.projectId ?? existingAcc.projectId,
        managedProjectId: acc.managedProjectId ?? existingAcc.managedProjectId,
        rateLimitResetTimes: {
          ...existingAcc.rateLimitResetTimes,
          ...acc.rateLimitResetTimes
        },
        lastUsed: Math.max(existingAcc.lastUsed || 0, acc.lastUsed || 0),
        accountIneligible: eligibilitySource.accountIneligible,
        accountIneligibleAt: eligibilitySource.accountIneligibleAt,
        accountIneligibleReason: eligibilitySource.accountIneligibleReason,
        eligibilityStateUpdatedAt: eligibilitySource.eligibilityStateUpdatedAt
      };
      if (merged.accountIneligible) {
        merged.enabled = false;
      }
      accountMap.set(acc.refreshToken, merged);
    } else {
      accountMap.set(acc.refreshToken, acc);
    }
  }
  return {
    version: 4,
    accounts: Array.from(accountMap.values()),
    activeIndex: incoming.activeIndex,
    activeIndexByFamily: incoming.activeIndexByFamily
  };
}
async function readAndNormalizeV4(path2) {
  let raw;
  try {
    raw = await readFile3(path2, "utf-8");
  } catch (error) {
    const code2 = error.code;
    if (code2 === "ENOENT") {
      return { state: "missing" };
    }
    return {
      state: "unreadable",
      reason: "io-error",
      detail: `${code2 ?? "UNKNOWN"}: ${error.message ?? String(error)}`
    };
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (parseError) {
    return {
      state: "unreadable",
      reason: "malformed-json",
      detail: parseError.message ?? String(parseError)
    };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return {
      state: "unreadable",
      reason: "invalid-shape",
      detail: "top-level value is not an object"
    };
  }
  const candidate = parsed;
  if (!Array.isArray(candidate.accounts)) {
    return {
      state: "unreadable",
      reason: "invalid-shape",
      detail: "`accounts` is missing or not an array"
    };
  }
  const parsedVersion = candidate.version;
  if (parsedVersion !== 1 && parsedVersion !== 2 && parsedVersion !== 3 && parsedVersion !== 4) {
    return {
      state: "unreadable",
      reason: "unsupported-version",
      detail: `unsupported version: ${String(parsedVersion)}`
    };
  }
  let storage = null;
  switch (parsedVersion) {
    case 1:
      storage = migrateV3ToV4(migrateV2ToV3(migrateV1ToV2(parsed)));
      break;
    case 2:
      storage = migrateV3ToV4(migrateV2ToV3(parsed));
      break;
    case 3:
      storage = migrateV3ToV4(parsed);
      break;
    case 4:
      storage = parsed;
      break;
  }
  if (!storage) {
    return {
      state: "unreadable",
      reason: "unsupported-version",
      detail: `unhandled version after switch: ${String(parsedVersion)}`
    };
  }
  for (let i = 0; i < storage.accounts.length; i++) {
    const detail = validateV4AccountRecord(storage.accounts[i], i);
    if (detail !== null) {
      return {
        state: "unreadable",
        reason: "invalid-shape",
        detail
      };
    }
  }
  const deduplicatedAccounts = deduplicateAccountsByEmail(storage.accounts);
  let activeIndex = typeof storage.activeIndex === "number" && Number.isFinite(storage.activeIndex) ? storage.activeIndex : 0;
  if (deduplicatedAccounts.length > 0) {
    activeIndex = Math.min(activeIndex, deduplicatedAccounts.length - 1);
    activeIndex = Math.max(activeIndex, 0);
  } else {
    activeIndex = 0;
  }
  return {
    state: "ok",
    storage: {
      version: 4,
      accounts: deduplicatedAccounts,
      activeIndex,
      activeIndexByFamily: storage.activeIndexByFamily
    }
  };
}
function validateV4AccountRecord(record2, index) {
  if (record2 === null || typeof record2 !== "object" || Array.isArray(record2)) {
    return `accounts[${index}] is not an object`;
  }
  const acc = record2;
  if (typeof acc.refreshToken !== "string" || acc.refreshToken.length === 0) {
    return `accounts[${index}].refreshToken is missing or not a non-empty string`;
  }
  if (typeof acc.addedAt !== "number" || !Number.isFinite(acc.addedAt)) {
    return `accounts[${index}].addedAt is missing or not a finite number`;
  }
  if (typeof acc.lastUsed !== "number" || !Number.isFinite(acc.lastUsed)) {
    return `accounts[${index}].lastUsed is missing or not a finite number`;
  }
  return null;
}
async function loadAccountStorage(path2) {
  const buildBackupPath = DEFAULT_BUILD_BACKUP_PATH;
  const now = () => /* @__PURE__ */ new Date();
  await assertLegacyAccountStorageWritable(path2);
  await ensureSecurePermissions(path2);
  const outcome = await readAndNormalizeV4(path2);
  if (outcome.state === "missing") {
    return null;
  }
  if (outcome.state === "unreadable") {
    const backupPath = await backupCorruptFile(path2, buildBackupPath, now());
    throw new AccountStorageUnreadableError(`Account storage at ${path2} is unreadable (${outcome.reason}: ${outcome.detail}).` + (backupPath ? ` A backup was written to ${backupPath}. The plugin will refuse to write until the file is removed or repaired.` : " A backup could not be written; the file has been left in place. The plugin will refuse to write until the file is removed or repaired."), {
      path: path2,
      reason: outcome.reason,
      detail: outcome.detail,
      backupPath
    });
  }
  if (outcome.storage.version === 4) {
    const onDiskVersion = await readVersionOnly(path2);
    if (onDiskVersion !== null && onDiskVersion !== 4) {
      try {
        await saveAccountStorage(path2, outcome.storage);
        log.info("Migration to v4 complete");
      } catch (saveError) {
        log.warn("Failed to persist migrated storage", {
          error: String(saveError)
        });
      }
    }
  }
  return outcome.storage;
}
async function readVersionOnly(path2) {
  try {
    const raw = await readFile3(path2, "utf-8");
    const parsed = JSON.parse(raw);
    return typeof parsed.version === "number" ? parsed.version : null;
  } catch {
    return null;
  }
}
async function acquireWithRetry(path2, sleep3) {
  for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt++) {
    const lock = await acquireFencedFileLock({
      path: path2,
      name: "accounts",
      ttlMs: 1e4,
      renew: true
    });
    if (lock) {
      return lock;
    }
    if (attempt < RETRY_DELAYS_MS.length) {
      const delay = RETRY_DELAYS_MS[attempt];
      if (delay !== void 0) {
        await sleep3(delay);
      }
    }
  }
  throw new AccountStorageLockContentionError(`account storage lock contention at ${path2} after ${RETRY_DELAYS_MS.length + 1} attempts`, {
    path: path2,
    attempts: RETRY_DELAYS_MS.length + 1
  });
}
async function mutateAccountStorage(path2, mutate, options = {}) {
  const sleep3 = options.sleep ?? DEFAULT_SLEEP;
  const buildBackupPath = options.buildBackupPath ?? DEFAULT_BUILD_BACKUP_PATH;
  const now = options.now ?? (() => /* @__PURE__ */ new Date());
  const lock = await acquireWithRetry(path2, sleep3);
  try {
    await assertLegacyAccountStorageWritable(path2);
    const outcome = await readAndNormalizeV4(path2);
    if (outcome.state === "unreadable") {
      const backupPath = await backupCorruptFile(path2, buildBackupPath, now());
      throw new AccountStorageUnreadableError(`Refusing to write: account storage at ${path2} is unreadable (${outcome.reason}: ${outcome.detail}).` + (backupPath ? ` A backup of the existing file was written to ${backupPath} and the on-disk file has been left untouched. Repair or remove the existing file before retrying.` : " A backup could not be written; the on-disk file has been left untouched. Repair or remove the existing file before retrying."), {
        path: path2,
        reason: outcome.reason,
        detail: outcome.detail,
        backupPath
      });
    }
    const existing = outcome.state === "ok" ? outcome.storage : { version: 4, accounts: [], activeIndex: 0 };
    const next = await mutate(existing);
    const finalStorage = next ?? existing;
    await lock.assertOwned();
    await writeJsonAtomic(path2, finalStorage);
    return finalStorage;
  } finally {
    try {
      await lock.release();
    } catch (releaseError) {
      log.warn("Failed to release account storage lock", {
        error: String(releaseError)
      });
    }
  }
}
async function saveAccountStorage(path2, incoming) {
  return mutateAccountStorage(path2, (current) => mergeAccountStorage(current, incoming));
}

// ../core/dist/auth.js
var ACCESS_TOKEN_EXPIRY_BUFFER_MS = 60 * 1e3;
function parseRefreshParts(refresh) {
  const [refreshToken = "", projectId = "", managedProjectId = ""] = (refresh ?? "").split("|");
  return {
    refreshToken,
    projectId: projectId || void 0,
    managedProjectId: managedProjectId || void 0
  };
}
function formatRefreshParts(parts) {
  const projectSegment = parts.projectId ?? "";
  const base = `${parts.refreshToken}|${projectSegment}`;
  return parts.managedProjectId ? `${base}|${parts.managedProjectId}` : base;
}
function accessTokenExpired(auth) {
  if (!auth.access || typeof auth.expires !== "number") {
    return true;
  }
  return auth.expires <= Date.now() + ACCESS_TOKEN_EXPIRY_BUFFER_MS;
}
function calculateTokenExpiry(requestTimeMs, expiresInSeconds) {
  const seconds = typeof expiresInSeconds === "number" ? expiresInSeconds : 3600;
  if (Number.isNaN(seconds) || seconds <= 0) {
    return requestTimeMs;
  }
  return requestTimeMs + seconds * 1e3;
}

// ../core/dist/agy-request-metadata.js
var DEFAULT_SESSION_STATE_TTL_MS = 24 * 60 * 60 * 1e3;

// ../core/dist/agy-transport.js
import { Buffer as Buffer2 } from "node:buffer";
import * as net from "node:net";
import { PassThrough, Readable, Transform } from "node:stream";
import * as tls from "node:tls";
import { createGunzip } from "node:zlib";
var DEFAULT_HTTPS_PORT = 443;
var DEFAULT_PROXY_PORT = 8080;
var DEFAULT_AGY_RESPONSE_HEADER_TIMEOUT_MS = 18e4;
var DEFAULT_AGY_IDLE_TIMEOUT_MS = 18e4;
function headersToRecord(headers) {
  const result = {};
  if (!headers)
    return result;
  const normalized = new Headers(headers);
  normalized.forEach((value, key) => {
    result[key.toLowerCase()] = value;
  });
  return result;
}
function getHeader(headers, name) {
  return headers[name.toLowerCase()];
}
function bodyToBuffer(body) {
  if (body == null)
    return Buffer2.alloc(0);
  if (typeof body === "string")
    return Buffer2.from(body);
  if (body instanceof Uint8Array)
    return Buffer2.from(body);
  if (body instanceof ArrayBuffer)
    return Buffer2.from(body);
  throw new Error("agy transport only supports string/byte request bodies");
}
function shouldUseChunkedBody(url) {
  return url.pathname.includes(":streamGenerateContent");
}
function buildAgyCliHeaderPairs(url, init = {}) {
  const parsedUrl = new URL(url);
  const headers = headersToRecord(init.headers);
  const body = bodyToBuffer(init.body);
  const host = parsedUrl.port ? `${parsedUrl.hostname}:${parsedUrl.port}` : parsedUrl.hostname;
  const userAgent = getHeader(headers, "User-Agent") ?? buildAntigravityHarnessUserAgent();
  const authorization = getHeader(headers, "Authorization");
  const contentType = getHeader(headers, "Content-Type") ?? "application/json";
  const acceptEncoding = getHeader(headers, "Accept-Encoding") ?? "gzip";
  const chunked = shouldUseChunkedBody(parsedUrl);
  const pairs = [
    ["Host", host],
    ["User-Agent", userAgent]
  ];
  if (chunked) {
    pairs.push(["Transfer-Encoding", "chunked"]);
  } else {
    pairs.push(["Content-Length", String(body.byteLength)]);
  }
  if (authorization) {
    pairs.push(["Authorization", authorization]);
  }
  pairs.push(["Content-Type", contentType]);
  pairs.push(["Accept-Encoding", acceptEncoding]);
  return pairs;
}
function noProxyIncludes(hostname) {
  const raw = process.env.NO_PROXY || process.env.no_proxy || "";
  if (!raw)
    return false;
  const host = hostname.toLowerCase();
  return raw.split(",").map((entry) => entry.trim().toLowerCase()).some((entry) => {
    if (!entry)
      return false;
    if (entry === "*")
      return true;
    if (entry.startsWith("."))
      return host.endsWith(entry);
    return host === entry || host.endsWith(`.${entry}`);
  });
}
function getHttpsProxy(url) {
  if (url.protocol !== "https:" || noProxyIncludes(url.hostname))
    return void 0;
  const rawProxy = process.env.HTTPS_PROXY || process.env.https_proxy || process.env.ALL_PROXY || process.env.all_proxy;
  if (!rawProxy)
    return void 0;
  try {
    return new URL(rawProxy);
  } catch {
    return void 0;
  }
}
function waitForHead(socket, timeoutMs, onTimeout) {
  return new Promise((resolve7, reject) => {
    let buffer = Buffer2.alloc(0);
    const timeout = setTimeout(() => {
      onTimeout();
      cleanup2(() => reject(new Error(`Antigravity request timed out waiting for response headers after ${timeoutMs}ms`)));
    }, timeoutMs);
    const cleanup2 = (finish) => {
      socket.off("data", onData);
      socket.off("error", onError);
      socket.off("end", onClosed);
      socket.off("close", onClosed);
      clearTimeout(timeout);
      finish();
    };
    const onError = (error) => cleanup2(() => reject(error));
    const onClosed = () => cleanup2(() => reject(new Error("Socket closed before response headers")));
    const onData = (chunk) => {
      buffer = Buffer2.concat([buffer, chunk]);
      const marker = buffer.indexOf("\r\n\r\n");
      if (marker === -1)
        return;
      const head = buffer.subarray(0, marker).toString("latin1");
      const leftover = buffer.subarray(marker + 4);
      cleanup2(() => resolve7({ head, leftover }));
    };
    socket.on("data", onData);
    socket.once("error", onError);
    socket.once("end", onClosed);
    socket.once("close", onClosed);
  });
}
async function connectViaProxy(proxyUrl, targetUrl, timeoutMs, signal, onDebug) {
  const proxySocket = net.connect({
    host: proxyUrl.hostname,
    port: Number(proxyUrl.port || DEFAULT_PROXY_PORT),
    signal: signal ?? void 0
  });
  await new Promise((resolve7, reject) => {
    const timeout = setTimeout(() => {
      onDebug?.(`agy transport proxy connect timeout after ${timeoutMs}ms`);
      proxySocket.destroy();
      reject(new Error(`Antigravity request timed out connecting to HTTPS proxy after ${timeoutMs}ms`));
    }, timeoutMs);
    const cleanup2 = () => clearTimeout(timeout);
    proxySocket.once("connect", () => {
      cleanup2();
      resolve7();
    });
    proxySocket.once("error", (error) => {
      cleanup2();
      reject(error);
    });
  });
  const targetHost = targetUrl.hostname;
  const targetPort = Number(targetUrl.port || DEFAULT_HTTPS_PORT);
  const auth = proxyUrl.username ? `Proxy-Authorization: Basic ${Buffer2.from(`${decodeURIComponent(proxyUrl.username)}:${decodeURIComponent(proxyUrl.password)}`).toString("base64")}\r
` : "";
  proxySocket.write(`CONNECT ${targetHost}:${targetPort} HTTP/1.1\r
Host: ${targetHost}:${targetPort}\r
` + auth + "\r\n");
  const { head, leftover } = await waitForHead(proxySocket, timeoutMs, () => {
    onDebug?.(`agy transport proxy CONNECT response timeout after ${timeoutMs}ms`);
    proxySocket.destroy();
  });
  if (!/^HTTP\/1\.[01] 2\d\d\b/.test(head)) {
    proxySocket.destroy();
    throw new Error(`Proxy CONNECT failed: ${head.split("\r\n")[0] ?? "unknown"}`);
  }
  if (leftover.length > 0) {
    proxySocket.unshift(leftover);
  }
  return await new Promise((resolve7, reject) => {
    const tlsOptions = {
      socket: proxySocket,
      servername: targetHost,
      signal: signal ?? void 0
    };
    const tlsSocket = tls.connect(tlsOptions);
    const timeout = setTimeout(() => {
      onDebug?.(`agy transport proxy TLS handshake timeout after ${timeoutMs}ms`);
      tlsSocket.destroy();
      reject(new Error(`Antigravity request timed out during proxy TLS handshake after ${timeoutMs}ms`));
    }, timeoutMs);
    const cleanup2 = () => clearTimeout(timeout);
    tlsSocket.once("secureConnect", () => {
      cleanup2();
      resolve7(tlsSocket);
    });
    tlsSocket.once("error", (error) => {
      cleanup2();
      reject(error);
    });
  });
}
async function connectDirect(targetUrl, timeoutMs, signal, onDebug) {
  return await new Promise((resolve7, reject) => {
    const tlsOptions = {
      host: targetUrl.hostname,
      port: Number(targetUrl.port || DEFAULT_HTTPS_PORT),
      servername: targetUrl.hostname,
      signal: signal ?? void 0
    };
    const socket = tls.connect(tlsOptions);
    const timeout = setTimeout(() => {
      onDebug?.(`agy transport TLS connect timeout after ${timeoutMs}ms`);
      socket.destroy();
      reject(new Error(`Antigravity request timed out connecting after ${timeoutMs}ms`));
    }, timeoutMs);
    const cleanup2 = () => clearTimeout(timeout);
    socket.once("secureConnect", () => {
      cleanup2();
      resolve7(socket);
    });
    socket.once("error", (error) => {
      cleanup2();
      reject(error);
    });
  });
}
async function connectTls(targetUrl, timeoutMs, signal, onDebug) {
  const proxyUrl = getHttpsProxy(targetUrl);
  return proxyUrl ? await connectViaProxy(proxyUrl, targetUrl, timeoutMs, signal, onDebug) : await connectDirect(targetUrl, timeoutMs, signal, onDebug);
}
function serializeRequest(url, init, body) {
  const method = init.method ?? "POST";
  const path2 = `${url.pathname}${url.search}`;
  const headerLines = buildAgyCliHeaderPairs(url.toString(), init).map(([key, value]) => `${key}: ${value}`).join("\r\n");
  const head = Buffer2.from(`${method} ${path2} HTTP/1.1\r
${headerLines}\r
\r
`);
  if (body.byteLength === 0) {
    return head;
  }
  if (!shouldUseChunkedBody(url)) {
    return Buffer2.concat([head, body]);
  }
  return Buffer2.concat([
    head,
    Buffer2.from(`${body.byteLength.toString(16)}\r
`),
    body,
    Buffer2.from("\r\n0\r\n\r\n")
  ]);
}
function parseResponseHead(head) {
  const lines = head.split("\r\n");
  const statusLine = lines.shift() ?? "";
  const match = /^HTTP\/1\.[01]\s+(\d{3})\s*(.*)$/.exec(statusLine);
  if (!match) {
    throw new Error(`Invalid HTTP response: ${statusLine}`);
  }
  const headers = new Headers();
  let chunked = false;
  let gzip = false;
  let contentLength;
  for (const line of lines) {
    const index = line.indexOf(":");
    if (index <= 0)
      continue;
    const key = line.slice(0, index);
    const value = line.slice(index + 1).trim();
    const lowerKey = key.toLowerCase();
    const lowerValue = value.toLowerCase();
    if (lowerKey === "transfer-encoding" && lowerValue.includes("chunked")) {
      chunked = true;
      continue;
    }
    if (lowerKey === "content-encoding" && lowerValue.includes("gzip")) {
      gzip = true;
      continue;
    }
    if (lowerKey === "content-length") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isFinite(parsed) && parsed >= 0) {
        contentLength = parsed;
      }
      if (gzip)
        continue;
    }
    headers.append(key, value);
  }
  return {
    status: Number(match[1]),
    statusText: match[2] ?? "",
    headers,
    chunked,
    gzip,
    contentLength
  };
}
var ContentLengthStream = class extends Transform {
  remaining;
  constructor(contentLength) {
    super();
    this.remaining = contentLength;
  }
  _transform(chunk, _encoding, callback) {
    if (this.remaining <= 0) {
      callback();
      return;
    }
    if (chunk.length <= this.remaining) {
      this.remaining -= chunk.length;
      this.push(chunk);
    } else {
      this.push(chunk.subarray(0, this.remaining));
      this.remaining = 0;
    }
    if (this.remaining <= 0) {
      this.push(null);
    }
    callback();
  }
};
var ChunkedDecodeStream = class extends Transform {
  buffer = Buffer2.alloc(0);
  _transform(chunk, _encoding, callback) {
    this.buffer = Buffer2.concat([this.buffer, chunk]);
    try {
      this.flushAvailableChunks();
      callback();
    } catch (error) {
      callback(error instanceof Error ? error : new Error(String(error)));
    }
  }
  _flush(callback) {
    try {
      this.flushAvailableChunks();
      callback();
    } catch (error) {
      callback(error instanceof Error ? error : new Error(String(error)));
    }
  }
  flushAvailableChunks() {
    while (true) {
      const lineEnd = this.buffer.indexOf("\r\n");
      if (lineEnd === -1)
        return;
      const sizeLine = this.buffer.subarray(0, lineEnd).toString("latin1");
      const sizeText = sizeLine.split(";", 1)[0]?.trim() ?? "";
      const size = Number.parseInt(sizeText, 16);
      if (!Number.isFinite(size)) {
        throw new Error(`Invalid chunk size: ${sizeLine}`);
      }
      const chunkStart = lineEnd + 2;
      const chunkEnd = chunkStart + size;
      const nextOffset = chunkEnd + 2;
      if (this.buffer.length < nextOffset)
        return;
      if (size === 0) {
        this.buffer = Buffer2.alloc(0);
        this.push(null);
        return;
      }
      this.push(this.buffer.subarray(chunkStart, chunkEnd));
      this.buffer = this.buffer.subarray(nextOffset);
    }
  }
};
function buildResponseStream(socket, leftover, head, signal, idleTimeoutMs, onDebug) {
  const source = new PassThrough();
  if (leftover.length > 0) {
    source.write(leftover);
  }
  socket.pipe(source);
  let responseBody = source;
  if (head.chunked) {
    responseBody = responseBody.pipe(new ChunkedDecodeStream());
  } else if (typeof head.contentLength === "number") {
    responseBody = responseBody.pipe(new ContentLengthStream(head.contentLength));
  }
  if (head.gzip) {
    responseBody = responseBody.pipe(createGunzip());
  }
  let idleTimer;
  const clearIdle = () => {
    if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = void 0;
    }
  };
  const armIdle = () => {
    if (!idleTimeoutMs || idleTimeoutMs <= 0)
      return;
    clearIdle();
    idleTimer = setTimeout(() => {
      onDebug?.(`agy transport idle timeout after ${idleTimeoutMs}ms with no body data`);
      socket.destroy(new Error(`Antigravity response stalled: no data for ${idleTimeoutMs}ms`));
    }, idleTimeoutMs);
  };
  socket.on("data", armIdle);
  armIdle();
  const abort = () => socket.destroy(new DOMException("The operation was aborted", "AbortError"));
  const cleanup2 = () => {
    clearIdle();
    socket.off("data", armIdle);
    signal?.removeEventListener("abort", abort);
  };
  if (signal?.aborted) {
    abort();
  } else {
    signal?.addEventListener("abort", abort, { once: true });
  }
  responseBody.once("end", () => {
    cleanup2();
    socket.destroy();
  });
  responseBody.once("error", () => {
    cleanup2();
    socket.destroy();
  });
  responseBody.once("close", cleanup2);
  return Readable.toWeb(responseBody);
}
async function fetchWithAgyCliTransport(url, init = {}, options = {}) {
  const parsedUrl = new URL(url);
  if (parsedUrl.protocol !== "https:") {
    throw new Error(`agy transport only supports https URLs: ${url}`);
  }
  if (options.signal?.aborted) {
    throw new DOMException("The operation was aborted", "AbortError");
  }
  const body = bodyToBuffer(init.body);
  const requestBytes = serializeRequest(parsedUrl, init, body);
  const timeoutMs = options.timeoutMs ?? DEFAULT_AGY_RESPONSE_HEADER_TIMEOUT_MS;
  const idleTimeoutMs = options.idleTimeoutMs ?? DEFAULT_AGY_IDLE_TIMEOUT_MS;
  options.onDebug?.(`agy transport connecting to ${parsedUrl.hostname} with header timeout ${timeoutMs}ms`);
  const socket = await connectTls(parsedUrl, timeoutMs, options.signal, options.onDebug);
  const abort = () => {
    socket.destroy(new DOMException("The operation was aborted", "AbortError"));
  };
  try {
    options.signal?.addEventListener("abort", abort, { once: true });
    socket.write(requestBytes);
    options.onDebug?.(`agy transport request dispatched (${requestBytes.byteLength} bytes)`);
    const { head, leftover } = await waitForHead(socket, timeoutMs, () => {
      options.onDebug?.(`agy transport response header timeout after ${timeoutMs}ms`);
      socket.destroy();
    });
    const parsedHead = parseResponseHead(head);
    options.onDebug?.(`agy transport response headers received: ${parsedHead.status} ${parsedHead.statusText}`);
    const bodyStream = buildResponseStream(socket, leftover, parsedHead, options.signal, idleTimeoutMs, options.onDebug);
    return new Response(bodyStream, {
      status: parsedHead.status,
      statusText: parsedHead.statusText,
      headers: parsedHead.headers
    });
  } catch (error) {
    socket.destroy();
    throw error;
  } finally {
    options.signal?.removeEventListener("abort", abort);
  }
}

// ../core/dist/antigravity/oauth.js
import { createHash as createHash3, randomBytes } from "node:crypto";

// ../core/dist/constants.js
var ANTIGRAVITY_CLIENT_ID = ("1071006060591-tmhssin2h21lcre235vtolojh4g403ep" + ".apps.googleusercontent.com");
var ANTIGRAVITY_CLIENT_SECRET = ("GOCSPX" + "-K58FWR486LdLJ1mLB8sXC4z6qDAf");
var ANTIGRAVITY_SCOPES = [
  "https://www.googleapis.com/auth/cloud-platform",
  "https://www.googleapis.com/auth/userinfo.email",
  "https://www.googleapis.com/auth/userinfo.profile",
  "https://www.googleapis.com/auth/cclog",
  "https://www.googleapis.com/auth/experimentsandconfigs"
];
var ANTIGRAVITY_REDIRECT_URI = "http://localhost:51121/oauth-callback";
var ANTIGRAVITY_ENDPOINT_DAILY = "https://daily-cloudcode-pa.googleapis.com";
var ANTIGRAVITY_ENDPOINT_PROD = "https://cloudcode-pa.googleapis.com";
var ANTIGRAVITY_ENDPOINT_FALLBACKS = [
  ANTIGRAVITY_ENDPOINT_DAILY,
  ANTIGRAVITY_ENDPOINT_PROD
];
var ANTIGRAVITY_LOAD_ENDPOINTS = [
  ANTIGRAVITY_ENDPOINT_DAILY,
  ANTIGRAVITY_ENDPOINT_PROD
];
var ANTIGRAVITY_DEFAULT_PROJECT_ID = "rising-fact-p41fc";
var ANTIGRAVITY_VERSION_FALLBACK = "1.18.3";
var ANTIGRAVITY_VERSION = ANTIGRAVITY_VERSION_FALLBACK;
var ANTIGRAVITY_HEADERS = {
  "User-Agent": `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Antigravity/${ANTIGRAVITY_VERSION} Chrome/138.0.7204.235 Electron/37.3.1 Safari/537.36`,
  "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
  "Client-Metadata": `{"ideType":"ANTIGRAVITY","platform":"${process.platform === "win32" ? "WINDOWS" : "MACOS"}","pluginType":"GEMINI"}`
};
var GEMINI_CLI_VERSION = "1.0.0";
var GEMINI_CLI_DEFAULT_MODEL = "gemini-2.5-pro";
function buildGeminiCliUserAgent(model) {
  const effectiveModel = model || GEMINI_CLI_DEFAULT_MODEL;
  const platform = process.platform || "darwin";
  const arch = process.arch || "arm64";
  return `GeminiCLI/${GEMINI_CLI_VERSION}/${effectiveModel} (${platform}; ${arch})`;
}
var GEMINI_CLI_HEADERS = {
  "User-Agent": "google-api-nodejs-client/9.15.1",
  "X-Goog-Api-Client": "gl-node/22.17.0",
  "Client-Metadata": "ideType=IDE_UNSPECIFIED,platform=PLATFORM_UNSPECIFIED,pluginType=GEMINI"
};
var ANTIGRAVITY_PROVIDER_ID = "google";

// ../core/dist/fetch-timeout.js
var ACTIVE_FETCH_TIMEOUT_MS = 15e3;
async function fetchWithActiveTimeout(input, init = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  const timeoutMs = options.timeoutMs ?? ACTIVE_FETCH_TIMEOUT_MS;
  const callerSignal = init.signal !== void 0 ? init.signal : input instanceof Request ? input.signal : void 0;
  const activeController = new AbortController();
  const detachCaller = forwardAbort(callerSignal, activeController);
  let detachTimeout = () => {
  };
  try {
    detachTimeout = forwardAbort(AbortSignal.timeout(timeoutMs), activeController);
    const response = await fetchImpl(input, {
      ...init,
      signal: activeController.signal
    });
    if (!callerSignal || !response.body) {
      detachCaller();
      return response;
    }
    return withBodyCleanup(response, detachCaller);
  } catch (error) {
    detachCaller();
    throw error;
  } finally {
    detachTimeout();
  }
}
function withBodyCleanup(response, cleanup2) {
  const reader = response.body.getReader();
  let finished = false;
  let canceled = false;
  let pulling = false;
  let sourceClosed = false;
  let bodyController;
  const finish = () => {
    if (finished)
      return;
    finished = true;
    cleanup2();
    reader.releaseLock();
  };
  const body = new ReadableStream(
    {
      start(controller) {
        bodyController = controller;
      },
      async pull(controller) {
        pulling = true;
        try {
          const next = await reader.read();
          if (canceled)
            return;
          if (next.done) {
            finish();
            controller.close();
          } else {
            controller.enqueue(next.value);
            if (sourceClosed) {
              finish();
              controller.close();
            }
          }
        } catch (error) {
          if (canceled)
            return;
          finish();
          controller.error(error);
        } finally {
          pulling = false;
        }
      },
      async cancel(reason) {
        canceled = true;
        try {
          await reader.cancel(reason);
        } finally {
          finish();
        }
      }
    },
    // Do not read ahead: the caller controls consumption of the network body.
    { highWaterMark: 0 }
  );
  void reader.closed.then(() => {
    sourceClosed = true;
    if (finished || canceled || pulling)
      return;
    finish();
    bodyController.close();
  }, (error) => {
    if (finished || canceled)
      return;
    finish();
    bodyController.error(error);
  });
  try {
    return preserveResponseMetadata(new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers
    }), response);
  } catch (error) {
    finish();
    throw error;
  }
}
function preserveResponseMetadata(wrapped, original) {
  Object.defineProperties(wrapped, {
    url: { value: original.url },
    type: { value: original.type },
    redirected: { value: original.redirected },
    clone: {
      value: () => preserveResponseMetadata(Response.prototype.clone.call(wrapped), original)
    }
  });
  return wrapped;
}

// ../core/dist/antigravity/oauth.js
var log2 = createLogger("oauth");
function generatePkcePair() {
  const verifier = randomBytes(32).toString("base64url");
  return {
    verifier,
    challenge: createHash3("sha256").update(verifier).digest("base64url")
  };
}
async function refreshAntigravityToken(refreshToken) {
  const startTime = Date.now();
  const response = await fetchWithActiveTimeout("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: ANTIGRAVITY_CLIENT_ID,
      client_secret: ANTIGRAVITY_CLIENT_SECRET
    })
  });
  if (!response.ok) {
    const errorText2 = await response.text().catch(() => "");
    throw new Error(`Antigravity token refresh failed (${response.status} ${response.statusText})${errorText2 ? ` - ${errorText2}` : ""}`);
  }
  const payload = await response.json();
  return {
    access: payload.access_token,
    refresh: payload.refresh_token ?? refreshToken,
    expires: calculateTokenExpiry(startTime, payload.expires_in)
  };
}
function encodeState(payload) {
  return Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
}
function decodeState(state) {
  const normalized = state.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + (4 - normalized.length % 4) % 4, "=");
  const json = Buffer.from(padded, "base64").toString("utf8");
  const parsed = JSON.parse(json);
  if (typeof parsed.verifier !== "string") {
    throw new Error("Missing PKCE verifier in state");
  }
  return {
    verifier: parsed.verifier,
    projectId: typeof parsed.projectId === "string" ? parsed.projectId : ""
  };
}
async function authorizeAntigravity(projectId = "") {
  const pkce = generatePkcePair();
  const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  url.searchParams.set("client_id", ANTIGRAVITY_CLIENT_ID);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("redirect_uri", ANTIGRAVITY_REDIRECT_URI);
  url.searchParams.set("scope", ANTIGRAVITY_SCOPES.join(" "));
  url.searchParams.set("code_challenge", pkce.challenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("state", encodeState({ verifier: pkce.verifier, projectId: projectId || "" }));
  url.searchParams.set("access_type", "offline");
  url.searchParams.set("prompt", "consent");
  return {
    url: url.toString(),
    verifier: pkce.verifier,
    projectId: projectId || ""
  };
}
async function fetchProjectID(accessToken) {
  const errors = [];
  const loadHeaders = buildAntigravityHarnessBootstrapHeaders(accessToken);
  const loadEndpoints = Array.from(/* @__PURE__ */ new Set([
    ...ANTIGRAVITY_LOAD_ENDPOINTS,
    ...ANTIGRAVITY_ENDPOINT_FALLBACKS
  ]));
  for (const baseEndpoint of loadEndpoints) {
    try {
      const url = `${baseEndpoint}/v1internal:loadCodeAssist`;
      const response = await fetchWithAgyCliTransport(url, {
        method: "POST",
        headers: loadHeaders,
        body: JSON.stringify({
          metadata: buildAntigravityLoadCodeAssistMetadata()
        })
      }, { timeoutMs: 1e4 });
      if (!response.ok) {
        const message = await response.text().catch(() => "");
        errors.push(`loadCodeAssist ${response.status} at ${baseEndpoint}${message ? `: ${message}` : ""}`);
        continue;
      }
      const data = await response.json();
      if (typeof data.cloudaicompanionProject === "string" && data.cloudaicompanionProject) {
        return data.cloudaicompanionProject;
      }
      if (data.cloudaicompanionProject && typeof data.cloudaicompanionProject.id === "string" && data.cloudaicompanionProject.id) {
        return data.cloudaicompanionProject.id;
      }
      errors.push(`loadCodeAssist missing project id at ${baseEndpoint}`);
    } catch (e) {
      errors.push(`loadCodeAssist error at ${baseEndpoint}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }
  if (errors.length) {
    log2.warn("Failed to resolve Antigravity project via loadCodeAssist", {
      errors: errors.join("; ")
    });
  }
  return "";
}
async function exchangeAntigravity(code2, state) {
  try {
    const { verifier, projectId } = decodeState(state);
    const startTime = Date.now();
    const tokenResponse = await fetchWithActiveTimeout("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        Accept: "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "User-Agent": GEMINI_CLI_HEADERS["User-Agent"]
      },
      body: new URLSearchParams({
        client_id: ANTIGRAVITY_CLIENT_ID,
        client_secret: ANTIGRAVITY_CLIENT_SECRET,
        code: code2,
        grant_type: "authorization_code",
        redirect_uri: ANTIGRAVITY_REDIRECT_URI,
        code_verifier: verifier
      })
    });
    if (!tokenResponse.ok) {
      const errorText2 = await tokenResponse.text();
      return { type: "failed", error: errorText2 };
    }
    const tokenPayload = await tokenResponse.json();
    const userInfoResponse = await fetchWithActiveTimeout("https://www.googleapis.com/oauth2/v1/userinfo?alt=json", {
      headers: {
        Authorization: `Bearer ${tokenPayload.access_token}`,
        "User-Agent": GEMINI_CLI_HEADERS["User-Agent"]
      }
    });
    const userInfo2 = userInfoResponse.ok ? await userInfoResponse.json() : {};
    const refreshToken = tokenPayload.refresh_token;
    if (!refreshToken) {
      return { type: "failed", error: "Missing refresh token in response" };
    }
    let effectiveProjectId = projectId;
    if (!effectiveProjectId) {
      effectiveProjectId = await fetchProjectID(tokenPayload.access_token);
    }
    const storedRefresh = `${refreshToken}|${effectiveProjectId || ""}`;
    return {
      type: "success",
      refresh: storedRefresh,
      access: tokenPayload.access_token,
      expires: calculateTokenExpiry(startTime, tokenPayload.expires_in),
      email: userInfo2.email,
      label: userInfo2.name?.trim() || void 0,
      projectId: effectiveProjectId || ""
    };
  } catch (error) {
    return {
      type: "failed",
      error: error instanceof Error ? error.message : "Unknown error"
    };
  }
}

// ../core/dist/quota-presentation.js
init_quota();

// ../core/dist/common-auth-runtime.js
function memoize(load) {
  let pending;
  return () => {
    if (!pending) {
      pending = load().catch((error) => {
        pending = void 0;
        throw error;
      });
    }
    return pending;
  };
}
var loadCommonAuthStore = memoize(() => Promise.resolve().then(() => (init_store(), store_exports)));
var loadCommonAuthFs = memoize(() => Promise.resolve().then(() => (init_fs(), fs_exports)));
var loadCommonAuthRouting = memoize(() => Promise.resolve().then(() => (init_routing(), routing_exports)));
var loadCommonAuthQuota = memoize(() => Promise.resolve().then(() => (init_quota(), quota_exports)));
var loadCommonAuthCommands = memoize(() => Promise.resolve().then(() => (init_commands(), commands_exports)));
var loadCommonAuthAuthMenu = memoize(() => Promise.resolve().then(() => (init_auth_menu(), auth_menu_exports)));
var loadCommonAuthClaustrum = memoize(() => Promise.resolve().then(() => (init_claustrum(), claustrum_exports)));
var loadCommonAuthLogger = memoize(() => Promise.resolve().then(() => (init_logger(), logger_exports)));
async function loadCommonAuthStoreModules() {
  const [store, fs3] = await Promise.all([
    loadCommonAuthStore(),
    loadCommonAuthFs()
  ]);
  return { store, fs: fs3 };
}
var loadCommonAuthPiSlot = memoize(() => Promise.resolve().then(() => (init_pi_slot(), pi_slot_exports)));

// ../core/dist/project.js
var log3 = createLogger("project");
var PROJECT_CONTEXT_CACHE_TTL_MS = 30 * 60 * 1e3;
var projectContextResultCache = /* @__PURE__ */ new Map();
var projectContextPendingCache = /* @__PURE__ */ new Map();
var provisionFailedKeys = /* @__PURE__ */ new Set();
function buildBootstrapRequestBody(extra = {}) {
  return {
    ...extra,
    metadata: buildAntigravityLoadCodeAssistMetadata()
  };
}
function getDefaultTierId(allowedTiers) {
  if (!allowedTiers || allowedTiers.length === 0) {
    return void 0;
  }
  for (const tier of allowedTiers) {
    if (tier?.isDefault) {
      return tier.id;
    }
  }
  return allowedTiers[0]?.id;
}
function wait(ms) {
  return new Promise((resolve7) => {
    setTimeout(resolve7, ms);
  });
}
function extractManagedProjectId(payload) {
  if (!payload) {
    return void 0;
  }
  if (typeof payload.cloudaicompanionProject === "string") {
    return payload.cloudaicompanionProject;
  }
  if (payload.cloudaicompanionProject && typeof payload.cloudaicompanionProject.id === "string") {
    return payload.cloudaicompanionProject.id;
  }
  return void 0;
}
function getCacheKeyFromRefresh(refresh) {
  const packedRefresh = refresh?.trim();
  if (!packedRefresh)
    return void 0;
  return parseRefreshParts(packedRefresh).refreshToken.trim() || packedRefresh;
}
function getCacheKey(auth) {
  return getCacheKeyFromRefresh(auth.refresh);
}
function invalidateProjectContextCache(refresh) {
  if (!refresh) {
    projectContextPendingCache.clear();
    projectContextResultCache.clear();
    provisionFailedKeys.clear();
    return;
  }
  const cacheKey = getCacheKeyFromRefresh(refresh);
  if (!cacheKey)
    return;
  projectContextPendingCache.delete(cacheKey);
  projectContextResultCache.delete(cacheKey);
  provisionFailedKeys.delete(cacheKey);
}
async function loadManagedProject(accessToken, _projectId) {
  const requestBody = buildBootstrapRequestBody();
  const loadHeaders = buildAntigravityHarnessBootstrapHeaders(accessToken);
  const loadEndpoints = Array.from(/* @__PURE__ */ new Set([
    ...ANTIGRAVITY_LOAD_ENDPOINTS,
    ...ANTIGRAVITY_ENDPOINT_FALLBACKS
  ]));
  for (const baseEndpoint of loadEndpoints) {
    try {
      const response = await fetchWithAgyCliTransport(`${baseEndpoint}/v1internal:loadCodeAssist`, {
        method: "POST",
        headers: loadHeaders,
        body: JSON.stringify(requestBody)
      });
      if (!response.ok) {
        continue;
      }
      return await response.json();
    } catch (error) {
      log3.debug("Failed to load managed project", {
        endpoint: baseEndpoint,
        error: String(error)
      });
    }
  }
  return null;
}
async function onboardManagedProject(accessToken, tierId, projectId, attempts = 10, delayMs = 5e3) {
  const requestBody = { tierId };
  const onboardEndpoints = Array.from(/* @__PURE__ */ new Set([
    ANTIGRAVITY_ENDPOINT_PROD,
    ...ANTIGRAVITY_LOAD_ENDPOINTS,
    ...ANTIGRAVITY_ENDPOINT_FALLBACKS
  ]));
  for (const baseEndpoint of onboardEndpoints) {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        const response = await fetchWithAgyCliTransport(`${baseEndpoint}/v1internal:onboardUser`, {
          method: "POST",
          headers: buildAntigravityHarnessBootstrapHeaders(accessToken),
          body: JSON.stringify(requestBody)
        });
        if (!response.ok) {
          log3.debug("Onboard request failed", {
            endpoint: baseEndpoint,
            status: response.status,
            statusText: response.statusText
          });
          break;
        }
        const payload = await response.json();
        const managedProjectId = payload.response?.cloudaicompanionProject?.id;
        if (payload.done && managedProjectId) {
          return managedProjectId;
        }
        if (payload.done && projectId) {
          return projectId;
        }
      } catch (error) {
        log3.debug("Failed to onboard managed project", {
          endpoint: baseEndpoint,
          error: String(error)
        });
        break;
      }
      await wait(delayMs);
    }
  }
  return void 0;
}
async function ensureProjectContext(auth) {
  const accessToken = auth.access;
  if (!accessToken) {
    return { auth, effectiveProjectId: "" };
  }
  const cacheKey = getCacheKey(auth);
  if (cacheKey) {
    const cached = projectContextResultCache.get(cacheKey);
    if (cached && Date.now() - cached.cachedAt < PROJECT_CONTEXT_CACHE_TTL_MS) {
      return cached.result;
    }
    if (cached) {
      projectContextResultCache.delete(cacheKey);
    }
    const pending = projectContextPendingCache.get(cacheKey);
    if (pending) {
      return pending;
    }
  }
  const resolveContext = async () => {
    const parts = parseRefreshParts(auth.refresh);
    if (parts.managedProjectId) {
      return { auth, effectiveProjectId: parts.managedProjectId };
    }
    const fallbackProjectId = ANTIGRAVITY_DEFAULT_PROJECT_ID;
    if (cacheKey && provisionFailedKeys.has(cacheKey)) {
      const effectiveProjectId = parts.projectId || fallbackProjectId;
      return { auth, effectiveProjectId };
    }
    const persistManagedProject = async (managedProjectId, capturedTier) => {
      const updatedAuth = {
        ...auth,
        refresh: formatRefreshParts({
          refreshToken: parts.refreshToken,
          projectId: parts.projectId,
          managedProjectId
        })
      };
      return {
        auth: updatedAuth,
        effectiveProjectId: managedProjectId,
        capturedTier
      };
    };
    const loadPayload = await loadManagedProject(accessToken, parts.projectId ?? fallbackProjectId);
    const capturedTierId = loadPayload?.currentTier?.id;
    const paidTierId = typeof loadPayload?.paidTier === "string" ? loadPayload.paidTier : loadPayload?.paidTier?.id;
    const tierFromPayload = capturedTierId ? {
      id: capturedTierId,
      ...paidTierId ? { paidId: paidTierId } : {},
      capturedAt: Date.now()
    } : void 0;
    const resolvedManagedProjectId = extractManagedProjectId(loadPayload);
    if (resolvedManagedProjectId) {
      return persistManagedProject(resolvedManagedProjectId, tierFromPayload);
    }
    const tierId = getDefaultTierId(loadPayload?.allowedTiers) ?? "free-tier";
    log3.debug("Auto-provisioning managed project", {
      tierId,
      projectId: parts.projectId
    });
    const provisionedProjectId = await onboardManagedProject(accessToken, tierId, parts.projectId);
    if (provisionedProjectId) {
      log3.debug("Successfully provisioned managed project", {
        provisionedProjectId
      });
      return persistManagedProject(provisionedProjectId, tierFromPayload);
    }
    log3.warn("Failed to provision managed project - account may not work correctly", {
      hasProjectId: !!parts.projectId
    });
    if (cacheKey) {
      provisionFailedKeys.add(cacheKey);
    }
    if (parts.projectId) {
      return {
        auth,
        effectiveProjectId: parts.projectId,
        capturedTier: tierFromPayload
      };
    }
    return {
      auth,
      effectiveProjectId: fallbackProjectId,
      capturedTier: tierFromPayload
    };
  };
  if (!cacheKey) {
    return resolveContext();
  }
  const promise = resolveContext().then((result) => {
    const nextKey = getCacheKey(result.auth) ?? cacheKey;
    projectContextPendingCache.delete(cacheKey);
    projectContextResultCache.set(nextKey, { result, cachedAt: Date.now() });
    if (nextKey !== cacheKey) {
      projectContextResultCache.delete(cacheKey);
    }
    return result;
  }).catch((error) => {
    projectContextPendingCache.delete(cacheKey);
    throw error;
  });
  projectContextPendingCache.set(cacheKey, promise);
  return promise;
}

// ../core/dist/quota-manager.js
import { createHash as createHash9 } from "node:crypto";
var log4 = createLogger("quota-manager");
var QUOTA_MANAGER_DEFAULT_BASE_BACKOFF_MS = 3e4;
var QUOTA_MANAGER_DEFAULT_MAX_BACKOFF_MS = 10 * 60 * 1e3;
var QUOTA_MANAGER_DEFAULT_TIMEOUT_MS = 1e4;
function defaultKeyOf(account) {
  if (account.email)
    return `e:${account.email.toLowerCase()}`;
  const token = account.refreshToken || "";
  return `t:${createHash9("sha256").update(token).digest("hex").slice(0, 16)}`;
}
function createQuotaManager(options) {
  const now = options.now ?? (() => Date.now());
  const baseBackoffMs = options.baseBackoffMs ?? QUOTA_MANAGER_DEFAULT_BASE_BACKOFF_MS;
  const maxBackoffMs = options.maxBackoffMs ?? QUOTA_MANAGER_DEFAULT_MAX_BACKOFF_MS;
  const fetchTimeoutMs = options.fetchTimeoutMs ?? QUOTA_MANAGER_DEFAULT_TIMEOUT_MS;
  const state = /* @__PURE__ */ new Map();
  let disposed = false;
  const keyOf = (account) => options.keyOf(account);
  const recordSuccess = (key) => {
    const entry = state.get(key);
    if (!entry)
      return;
    entry.consecutiveFailures = 0;
    entry.backoffUntil = 0;
  };
  const recordFailure = (key) => {
    const current = now();
    const entry = state.get(key) ?? {
      consecutiveFailures: 0,
      backoffUntil: 0
    };
    const failures = entry.consecutiveFailures + 1;
    const backoffMs = Math.min(maxBackoffMs, baseBackoffMs * 2 ** (failures - 1));
    entry.consecutiveFailures = failures;
    entry.backoffUntil = current + backoffMs;
    state.set(key, entry);
    return { backoffMs, backoffUntil: entry.backoffUntil };
  };
  const cacheResult = (key, result) => {
    const entry = state.get(key) ?? {
      consecutiveFailures: 0,
      backoffUntil: 0
    };
    entry.cached = result;
    state.set(key, entry);
  };
  const buildDisabledResult = (account, index) => ({
    index,
    email: account.email,
    status: "disabled",
    disabled: true,
    quota: void 0,
    geminiCliQuota: void 0,
    updatedAccount: void 0
  });
  const buildSkippedResult = (account, index, backoffUntil) => {
    const cached = state.get(keyOf(account))?.cached;
    if (cached) {
      return { ...cached, index };
    }
    return {
      index,
      email: account.email,
      status: "error",
      error: `quota refresh skipped (backoff until ${new Date(backoffUntil).toISOString()})`
    };
  };
  const refreshAccount = async (account, refreshOptions) => {
    if (disposed) {
      return {
        index: refreshOptions.index,
        email: account.email,
        status: "error",
        error: "quota manager disposed"
      };
    }
    const { index, force = false } = refreshOptions;
    const key = keyOf(account);
    if (account.enabled === false) {
      const result = buildDisabledResult(account, index);
      cacheResult(key, result);
      return result;
    }
    const current = now();
    const entry = state.get(key);
    if (!force && entry && entry.backoffUntil > current) {
      return buildSkippedResult(account, index, entry.backoffUntil);
    }
    const inflight = entry?.inflight;
    if (inflight) {
      const cached = await inflight;
      return { ...cached, index };
    }
    const controller = new AbortController();
    const stored = state.get(key) ?? {
      consecutiveFailures: 0,
      backoffUntil: 0
    };
    stored.controller = controller;
    state.set(key, stored);
    const promise = (async () => {
      let deadline;
      const forwardDeadline = () => controller.abort(deadline?.reason);
      try {
        deadline = AbortSignal.timeout(fetchTimeoutMs);
        deadline.addEventListener("abort", forwardDeadline, { once: true });
        const result = await options.fetchAccountQuota(account, controller.signal);
        if (disposed) {
          throw new Error("quota manager disposed mid-fetch");
        }
        const attributed = {
          ...result,
          index,
          ...result.status === "ok" ? { checkedAt: now() } : {}
        };
        cacheResult(key, attributed);
        if (result.status === "error") {
          const { backoffMs } = recordFailure(key);
          log4.debug("quota-refresh-failed", {
            key: hashKey(key),
            backoffMs,
            error: result.error ?? "attributed error result"
          });
          return attributed;
        }
        recordSuccess(key);
        return attributed;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (disposed) {
          const failureResult2 = {
            index,
            email: account.email,
            status: "error",
            error: message
          };
          cacheResult(key, failureResult2);
          return failureResult2;
        }
        const { backoffMs } = recordFailure(key);
        log4.debug("quota-refresh-failed", {
          key: hashKey(key),
          backoffMs,
          error: message
        });
        const failureResult = {
          index,
          email: account.email,
          status: "error",
          error: message
        };
        cacheResult(key, failureResult);
        return failureResult;
      } finally {
        deadline?.removeEventListener("abort", forwardDeadline);
        const finished = state.get(key);
        if (finished) {
          finished.inflight = void 0;
          finished.controller = void 0;
          state.set(key, finished);
        }
      }
    })();
    if (stored.controller === controller) {
      stored.inflight = promise;
      state.set(key, stored);
    }
    return promise;
  };
  const refreshAccounts = async (accounts, refreshOptions) => {
    const results = [];
    for (const account of accounts) {
      const index = refreshOptions.indexFor(account);
      const result = await refreshAccount(account, {
        index,
        force: refreshOptions.force
      });
      results.push(result);
    }
    return results;
  };
  const getCached = (account) => {
    const entry = state.get(keyOf(account));
    return entry?.cached;
  };
  const getBackoffUntil = (account) => {
    return state.get(keyOf(account))?.backoffUntil ?? 0;
  };
  const hashedLogLabel = (prefix, account) => {
    const identity = typeof account === "string" ? account : keyOf(account);
    return `${prefix} ${hashKey(identity)}`;
  };
  const dispose = async () => {
    if (disposed)
      return;
    disposed = true;
    const pending = Array.from(state.values(), (entry) => entry.inflight).filter((promise) => promise != null);
    for (const [, entry] of state) {
      entry.controller?.abort();
    }
    if (pending.length > 0) {
      await Promise.allSettled(pending);
    }
    for (const [, entry] of state) {
      entry.inflight = void 0;
    }
  };
  return {
    refreshAccount,
    refreshAccounts,
    getCached,
    getBackoffUntil,
    hashedLogLabel,
    dispose,
    classifyQuotaGroup,
    aggregateQuota,
    aggregateGeminiCliQuota
  };
}
function hashKey(key) {
  return createHash9("sha256").update(key).digest("hex").slice(0, 8);
}
function classifyQuotaGroup(modelName, displayName) {
  const registryGroup = getQuotaGroupForModel(modelName);
  if (registryGroup) {
    return registryGroup;
  }
  const combined = `${modelName} ${displayName ?? ""}`.toLowerCase();
  if (combined.includes("claude") || combined.includes("gpt-oss")) {
    return "non-gemini";
  }
  if (combined.includes("gemini")) {
    return "gemini";
  }
  return null;
}
function normalizeRemainingFraction(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  if (value < 0)
    return 0;
  if (value > 1)
    return 1;
  return value;
}
function parseResetTime(resetTime) {
  if (!resetTime)
    return null;
  const timestamp = Date.parse(resetTime);
  if (!Number.isFinite(timestamp)) {
    return null;
  }
  return timestamp;
}
function aggregateQuota(models) {
  const groups = {};
  const perModel = [];
  if (!models) {
    return { groups, perModel, modelCount: 0 };
  }
  let totalCount = 0;
  for (const [modelName, entry] of Object.entries(models)) {
    const group = classifyQuotaGroup(modelName, entry.displayName ?? entry.modelName);
    const quotaInfo = entry.quotaInfo;
    const remainingFraction = quotaInfo ? normalizeRemainingFraction(quotaInfo.remainingFraction) : void 0;
    const resetTime = quotaInfo?.resetTime;
    const resetTimestamp = parseResetTime(resetTime);
    totalCount += 1;
    perModel.push({
      modelId: modelName,
      displayName: entry.displayName ?? entry.modelName,
      group,
      remainingFraction: remainingFraction ?? 0,
      resetTime
    });
    if (!group) {
      continue;
    }
    const existing = groups[group];
    const nextCount = (existing?.modelCount ?? 0) + 1;
    const nextRemaining = remainingFraction === void 0 ? existing?.remainingFraction : existing?.remainingFraction === void 0 ? remainingFraction : Math.min(existing.remainingFraction, remainingFraction);
    let nextResetTime = existing?.resetTime;
    if (resetTimestamp !== null) {
      if (!existing?.resetTime) {
        nextResetTime = resetTime;
      } else {
        const existingTimestamp = parseResetTime(existing.resetTime);
        if (existingTimestamp === null || resetTimestamp < existingTimestamp) {
          nextResetTime = resetTime;
        }
      }
    }
    groups[group] = {
      remainingFraction: nextRemaining,
      resetTime: nextResetTime,
      modelCount: nextCount
    };
  }
  perModel.sort((a, b) => a.modelId.localeCompare(b.modelId));
  return { groups, perModel, modelCount: totalCount };
}
function mostConstrainedWindow(windows) {
  if (windows.length === 0)
    return void 0;
  let best = windows[0];
  for (let i = 1; i < windows.length; i++) {
    if (windows[i].remainingFraction < best.remainingFraction) {
      best = windows[i];
    }
  }
  return {
    remainingFraction: best.remainingFraction,
    resetTime: best.resetTime
  };
}
function poolForBucketId(bucketId) {
  if (bucketId.startsWith("gemini-"))
    return "gemini";
  if (bucketId.startsWith("3p-"))
    return "non-gemini";
  return null;
}
function parseDescriptionModelCount(description) {
  const prefixMatch = description.match(/^[^:]+:\s*/);
  const payload = prefixMatch ? description.slice(prefixMatch[0].length) : description;
  if (!payload)
    return 0;
  const entries = payload.split(",").map((entry) => entry.trim()).filter((entry) => entry.length > 0);
  return entries.length;
}
function windowDurationMs(window) {
  switch (window) {
    case "5h":
      return 5 * 60 * 60 * 1e3;
    case "weekly":
      return 7 * 24 * 60 * 60 * 1e3;
    default:
      return Number.MAX_SAFE_INTEGER;
  }
}
function aggregateQuotaSummary(response) {
  const groups = {};
  let totalCount = 0;
  for (const group of response.groups) {
    const windows = [];
    for (const bucket of group.buckets) {
      const pool2 = poolForBucketId(bucket.bucketId);
      if (!pool2)
        continue;
      windows.push({
        window: bucket.window,
        remainingFraction: normalizeRemainingFraction(bucket.remainingFraction),
        resetTime: bucket.resetTime
      });
    }
    if (windows.length === 0)
      continue;
    windows.sort((a, b) => windowDurationMs(a.window) - windowDurationMs(b.window));
    const constrained = mostConstrainedWindow(windows);
    const recognizedBucket = group.buckets.find((bucket) => poolForBucketId(bucket.bucketId));
    if (!recognizedBucket)
      continue;
    const pool = poolForBucketId(recognizedBucket.bucketId);
    if (!pool || !constrained)
      continue;
    const modelCount = group.description ? parseDescriptionModelCount(group.description) : 0;
    groups[pool] = {
      remainingFraction: constrained.remainingFraction,
      resetTime: constrained.resetTime,
      modelCount,
      windows
    };
    totalCount += modelCount;
  }
  return { groups, modelCount: totalCount };
}
async function fetchQuotaSummary(options) {
  const timeoutMs = options.timeoutMs ?? QUOTA_MANAGER_DEFAULT_TIMEOUT_MS;
  const userAgent = options.userAgent ?? buildAntigravityHarnessUserAgent();
  const transport = options.fetchVia ?? defaultTransport;
  const errors = [];
  if (options.endpoints.length === 0) {
    throw new Error("No endpoints configured for fetchQuotaSummary");
  }
  const tryBody = async (endpoint, projectId) => {
    const body = { project: projectId };
    try {
      const response = await transport(`${endpoint}/v1internal:retrieveUserQuotaSummary`, {
        method: "POST",
        headers: {
          "User-Agent": userAgent,
          Authorization: `Bearer ${options.accessToken}`,
          "Content-Type": "application/json",
          "Accept-Encoding": "gzip"
        },
        body: JSON.stringify(body)
      }, { timeoutMs });
      if (response.ok) {
        return {
          ok: true,
          summary: await response.json()
        };
      }
      const status = response.status;
      if (status === 403) {
        errors.push(`retrieveUserQuotaSummary 403 at ${endpoint} (project=${projectId.slice(0, 12)}\u2026)`);
        return { ok: false, reason: "403" };
      }
      if (status === 429 || status >= 500) {
        const message2 = await response.text().catch(() => "");
        errors.push(`retrieveUserQuotaSummary ${status} at ${endpoint}${message2 ? `: ${message2.trim().slice(0, 200)}` : ""}`);
        return { ok: false, reason: "transient" };
      }
      const message = await response.text().catch(() => "");
      errors.push(`retrieveUserQuotaSummary ${status} at ${endpoint}${message ? `: ${message.trim().slice(0, 200)}` : ""}`);
      return { ok: false, reason: "transient" };
    } catch (error) {
      errors.push(`retrieveUserQuotaSummary network error at ${endpoint}: ${error instanceof Error ? error.message : String(error)}`);
      return { ok: false, reason: "transient" };
    }
  };
  const primary = options.managedProjectId ?? options.projectId;
  let primaryGot403 = false;
  if (primary) {
    for (const endpoint of options.endpoints) {
      const result = await tryBody(endpoint, primary);
      if (result.ok)
        return { summary: result.summary };
      if (result.reason === "403")
        primaryGot403 = true;
    }
  }
  const fallbackId = primaryGot403 && options.managedProjectId && options.projectId && options.managedProjectId !== options.projectId ? options.projectId : void 0;
  if (fallbackId) {
    for (const endpoint of options.endpoints) {
      const result = await tryBody(endpoint, fallbackId);
      if (result.ok)
        return { summary: result.summary };
    }
  }
  throw new Error(errors.join("; ") || "fetchQuotaSummary failed: no project ID available");
}
function aggregateGeminiCliQuota(response) {
  const models = [];
  if (!response.buckets || response.buckets.length === 0) {
    return { models };
  }
  for (const bucket of response.buckets) {
    if (!bucket.modelId) {
      continue;
    }
    const modelId = bucket.modelId;
    const isRelevantModel = modelId.startsWith("gemini-3-") || modelId.startsWith("gemini-3.") || modelId.startsWith("gemini-2.5-");
    if (!isRelevantModel) {
      continue;
    }
    models.push({
      modelId: bucket.modelId,
      remainingFraction: normalizeRemainingFraction(bucket.remainingFraction),
      resetTime: bucket.resetTime
    });
  }
  models.sort((a, b) => a.modelId.localeCompare(b.modelId));
  return { models };
}
async function fetchAvailableModels(options) {
  const timeoutMs = options.timeoutMs ?? QUOTA_MANAGER_DEFAULT_TIMEOUT_MS;
  const userAgent = options.userAgent ?? buildAntigravityHarnessUserAgent();
  const errors = [];
  const transport = options.fetchVia ?? defaultTransport;
  for (const endpoint of options.endpoints) {
    const body = options.projectId ? { project: options.projectId } : {};
    try {
      const response = await transport(`${endpoint}/v1internal:fetchAvailableModels`, {
        method: "POST",
        headers: {
          "User-Agent": userAgent,
          Authorization: `Bearer ${options.accessToken}`,
          "Content-Type": "application/json",
          "Accept-Encoding": "gzip"
        },
        body: JSON.stringify(body)
      }, { timeoutMs });
      if (response.ok) {
        return await response.json();
      }
      const status = response.status;
      if (status === 403 && options.projectId) {
        try {
          const retryResponse = await transport(`${endpoint}/v1internal:fetchAvailableModels`, {
            method: "POST",
            headers: {
              "User-Agent": userAgent,
              Authorization: `Bearer ${options.accessToken}`,
              "Content-Type": "application/json",
              "Accept-Encoding": "gzip"
            },
            body: JSON.stringify({})
          }, { timeoutMs });
          if (retryResponse.ok) {
            return await retryResponse.json();
          }
        } catch {
        }
      }
      if (status === 429 || status >= 500) {
        const message2 = await response.text().catch(() => "");
        const snippet2 = message2.trim().slice(0, 200);
        errors.push(`fetchAvailableModels ${status} at ${endpoint}${snippet2 ? `: ${snippet2}` : ""}`);
        continue;
      }
      const message = await response.text().catch(() => "");
      const snippet = message.trim().slice(0, 200);
      errors.push(`fetchAvailableModels ${status} at ${endpoint}${snippet ? `: ${snippet}` : ""}`);
      break;
    } catch (error) {
      errors.push(`fetchAvailableModels network error at ${endpoint}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  throw new Error(errors.join("; ") || "fetchAvailableModels failed");
}
async function fetchGeminiCliQuota(options) {
  const timeoutMs = options.timeoutMs ?? QUOTA_MANAGER_DEFAULT_TIMEOUT_MS;
  const userAgent = options.userAgent ?? buildAntigravityHarnessUserAgent();
  const transport = options.fetchVia ?? defaultTransport;
  const errors = [];
  for (const endpoint of options.endpoints) {
    const body = options.projectId ? { project: options.projectId } : {};
    try {
      const response = await transport(`${endpoint}/v1internal:retrieveUserQuota`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${options.accessToken}`,
          "Content-Type": "application/json",
          "User-Agent": userAgent
        },
        body: JSON.stringify(body)
      }, { timeoutMs });
      if (response.ok) {
        return await response.json();
      }
      const status = response.status;
      if (status === 429 || status >= 500) {
        errors.push(`fetchGeminiCliQuota ${status} at ${endpoint}`);
        continue;
      }
      return { buckets: [] };
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }
  if (errors.length > 0) {
    throw new Error(errors.join("; ") || "fetchGeminiCliQuota failed");
  }
  return { buckets: [] };
}
async function defaultTransport(url, init, options) {
  return fetchWithActiveTimeout(url, init, { timeoutMs: options.timeoutMs });
}

// ../core/dist/transform/model-resolver.js
var MODEL_ALIASES = getResolverAliasMap();

// ../core/dist/vault-family.js
var ANTIGRAVITY_VAULT_FAMILY = Object.freeze({
  refreshAdapter: "antigravity",
  category: "antigravity-native",
  apiKeys: false
});
var ANTIGRAVITY_VAULT_ENROLLMENT_NAMES = Object.freeze({
  opencode: "antigravity-auth-opencode",
  pi: "antigravity-auth-pi"
});

// ../core/dist/vault-provider-state.js
var VAULT_PROVIDER_STATE_SCHEMA_VERSION = 1;
var VAULT_PROVIDER_STATE_LOCK = Object.freeze({
  name: "antigravity-vault-state",
  ttlMs: 1e4,
  timeoutMs: 1e4,
  renew: true
});
var EMPTY_FILE = Object.freeze({
  schemaVersion: VAULT_PROVIDER_STATE_SCHEMA_VERSION,
  accounts: Object.freeze({})
});

// src/plugin/oauth-login.ts
function expectedState(authorizationUrl) {
  try {
    return new URL(authorizationUrl).searchParams.get("state") ?? "";
  } catch {
    return "";
  }
}
function callbackParams(callbackUrl, expected) {
  const code2 = callbackUrl.searchParams.get("code");
  const state = callbackUrl.searchParams.get("state");
  if (!code2 || !state) throw new Error("Missing code or state in callback URL");
  if (expected && state !== expected) throw new Error("OAuth state mismatch");
  return { code: code2, state };
}
async function performOAuthLogin(request, deps) {
  const listener = await deps.startListener();
  try {
    const authorization = await deps.authorize(request.projectId ?? "");
    if (!request.noBrowser && !request.isHeadless) {
      await deps.openBrowser(authorization.url);
    }
    const params = callbackParams(
      await listener.waitForCallback(),
      expectedState(authorization.url)
    );
    const result = await deps.exchange(params.code, params.state);
    if (result.type === "failed") throw new Error(result.error);
    await deps.upsert(result);
    request.accounts.push(result);
    return result;
  } finally {
    await listener.close().catch(() => {
    });
  }
}

// src/plugin/storage.ts
import {
  appendFileSync as appendFileSync3,
  copyFileSync,
  existsSync as existsSync4,
  promises as fs2,
  mkdirSync as mkdirSync2,
  readFileSync,
  renameSync as renameSync3,
  unlinkSync as unlinkSync2,
  writeFileSync
} from "node:fs";
import { homedir as homedir2 } from "node:os";
import { dirname as dirname11, join as join9, resolve as resolve5 } from "node:path";

// src/common-auth-embedded/logger/engine.js
import { appendFileSync as appendFileSync2, chmodSync as chmodSync2, existsSync as existsSync3, renameSync as renameSync2, statSync as statSync4 } from "node:fs";

// src/common-auth-embedded/logger/redact.js
var SECRET_KEY_EXACT2 = /^(authorization|x-api-key|cookie|set-cookie|refresh|access|token)$/i;
var TOKEN_VALUE2 = /\b(Bearer\s+[\w.-]+|sk-[\w-]+|eyJ[\w.-]+)\b|ckh_[A-Za-z0-9_-]{20,}/g;
var MASK2 = "***REDACTED***";
var MAX_ERROR_DEPTH2 = 8;
function isError2(value) {
  return value instanceof Error || Object.prototype.toString.call(value) === "[object Error]";
}
function createRedactor2(options = {}) {
  const patterns = [TOKEN_VALUE2, ...options.extraValuePatterns ?? []].map((pattern) => new RegExp(pattern.source, pattern.flags.includes("g") ? pattern.flags : `${pattern.flags}g`));
  function isSecretKey(key) {
    const normalized = key.toLowerCase().replace(/[-_]/g, "");
    return SECRET_KEY_EXACT2.test(key) || normalized.includes("apikey") || normalized.endsWith("secret") || normalized.endsWith("password") || normalized.endsWith("token") && !normalized.endsWith("tokens") || !!options.extraSecretKeys?.(normalized);
  }
  function errorEntries(error) {
    const fields = error;
    const entries = [
      ["name", error.name],
      ["message", error.message],
      ["stack", error.stack]
    ];
    for (const key of ["code", "status", "cause"])
      if (fields[key] !== void 0)
        entries.push([key, fields[key]]);
    const listed = new Set(entries.map(([key]) => key));
    for (const entry of Object.entries(error))
      if (!listed.has(entry[0]))
        entries.push(entry);
    return entries;
  }
  function walk(value, keys, seen, errorDepth = 0) {
    if (typeof value === "string") {
      return patterns.reduce((text2, pattern) => text2.replace(pattern, MASK2), value);
    }
    if (!value || typeof value !== "object")
      return value;
    if (seen.has(value))
      return "[Circular]";
    seen.add(value);
    try {
      if (Array.isArray(value))
        return value.map((item) => walk(item, keys, seen, errorDepth));
      const error = isError2(value);
      if (error && errorDepth >= MAX_ERROR_DEPTH2)
        return "[Truncated]";
      const childDepth = error ? errorDepth + 1 : errorDepth;
      return Object.fromEntries((error ? errorEntries(value) : Object.entries(value)).map(([key, item]) => [
        key,
        keys && isSecretKey(key) ? MASK2 : walk(item, keys, seen, childDepth)
      ]));
    } finally {
      seen.delete(value);
    }
  }
  return {
    redact: (value) => walk(value, true, /* @__PURE__ */ new WeakSet()),
    // Schema keys describe arguments, not credentials; only their string values are scrubbed.
    redactStrings: (value) => walk(value, false, /* @__PURE__ */ new WeakSet())
  };
}
var defaultRedactor2 = createRedactor2();
var redact2 = defaultRedactor2.redact;
var redactStrings2 = defaultRedactor2.redactStrings;

// src/common-auth-embedded/logger/engine.js
var ORDER2 = {
  error: 0,
  warn: 1,
  info: 2,
  debug: 3,
  trace: 4
};
var MAX_BYTES2 = 5 * 1024 * 1024;
var ROTATE_KEEP2 = 3;
function chmodPrivate2(path2) {
  try {
    chmodSync2(path2, 384);
  } catch {
  }
}
function rotateIfNeeded2(f) {
  try {
    if (!(existsSync3(f) && statSync4(f).size >= MAX_BYTES2))
      return;
    for (let i = ROTATE_KEEP2 - 1; i >= 1; i--) {
      if (existsSync3(`${f}.${i}`)) {
        const rotated2 = `${f}.${i + 1}`;
        renameSync2(`${f}.${i}`, rotated2);
        chmodPrivate2(rotated2);
      }
    }
    const rotated = `${f}.1`;
    renameSync2(f, rotated);
    chmodPrivate2(rotated);
  } catch {
  }
}
function safeSerialize2(data) {
  try {
    return ` ${JSON.stringify(data)}`;
  } catch {
    return " [unserializable]";
  }
}
function createEngine2(options) {
  let logFileSource;
  let initLevelSource;
  let runtimeLevel;
  let redactor = createRedactor2();
  let captureSink;
  let buffer = [];
  let timer;
  function configure(next) {
    logFileSource = next.file;
    initLevelSource = next.level;
    redactor = createRedactor2(next);
    captureSink = next.captureSink;
  }
  function setLogLevel3(l) {
    if (l === void 0 || l in ORDER2)
      runtimeLevel = l;
  }
  function logFilePath() {
    if (logFileSource === void 0)
      return void 0;
    const resolved = typeof logFileSource === "function" ? logFileSource() : logFileSource;
    return resolved || void 0;
  }
  function configuredLevel() {
    if (runtimeLevel)
      return runtimeLevel;
    const floor = typeof initLevelSource === "function" ? initLevelSource() : initLevelSource;
    if (floor && floor in ORDER2)
      return floor;
    return "info";
  }
  function flushLogs3() {
    if (timer) {
      clearTimeout(timer);
      timer = void 0;
    }
    if (!buffer.length)
      return;
    let file;
    try {
      file = logFilePath();
    } catch {
      buffer = [];
      return;
    }
    const text2 = buffer.join("");
    buffer = [];
    if (!file)
      return;
    try {
      rotateIfNeeded2(file);
      if (existsSync3(file))
        chmodPrivate2(file);
      appendFileSync2(file, text2, { encoding: "utf8", mode: 384 });
    } catch {
    }
  }
  function schedule() {
    if (!timer)
      timer = setTimeout(() => {
        timer = void 0;
        flushLogs3();
      }, 500);
  }
  function emit(channel, level, message, data) {
    if (logFileSource === void 0 && captureSink === void 0)
      return;
    try {
      if (ORDER2[level] > ORDER2[configuredLevel()])
        return;
      const scrubbedMessage = redactor.redactStrings(message);
      let scrubbedData;
      try {
        scrubbedData = redactor.redact(data);
      } catch {
        scrubbedData = "[unserializable]";
      }
      const line = `[${(/* @__PURE__ */ new Date()).toISOString()}] ${level.toUpperCase()} [${channel}] ${scrubbedMessage}` + (data === void 0 ? "" : safeSerialize2(scrubbedData)) + "\n";
      try {
        captureSink?.({
          channel,
          level,
          message: scrubbedMessage,
          data: scrubbedData
        });
      } catch {
      }
      if (logFileSource === void 0)
        return;
      buffer.push(line);
      if (buffer.length >= 50)
        flushLogs3();
      else
        schedule();
    } catch {
    }
  }
  function createLogger5(channel) {
    return {
      error: (m, d) => emit(channel, "error", m, d),
      warn: (m, d) => emit(channel, "warn", m, d),
      info: (m, d) => emit(channel, "info", m, d),
      debug: (m, d) => emit(channel, "debug", m, d),
      trace: (m, d) => emit(channel, "trace", m, d)
    };
  }
  function reset() {
    buffer = [];
    if (timer) {
      clearTimeout(timer);
      timer = void 0;
    }
    logFileSource = void 0;
    initLevelSource = void 0;
    runtimeLevel = void 0;
    redactor = createRedactor2();
    captureSink = void 0;
  }
  if (options)
    configure(options);
  return { configure, createLogger: createLogger5, setLogLevel: setLogLevel3, flushLogs: flushLogs3, reset };
}
function createLoggerInstance2(options) {
  const { configure, createLogger: createLogger5, setLogLevel: setLogLevel3, flushLogs: flushLogs3 } = createEngine2(options);
  return { configure, createLogger: createLogger5, setLogLevel: setLogLevel3, flushLogs: flushLogs3 };
}
var defaultEngine2 = createEngine2();

// src/logging/provider-key-policy.ts
function isProviderSecretKey(normalizedKey) {
  return /token|refresh|access|project|fingerprint|deviceid|sessionid|sessiontoken|secret|password|apikey|clientsecret/.test(
    normalizedKey
  );
}

// src/plugin/debug.ts
import {
  createWriteStream,
  mkdirSync,
  readdirSync as readdirSync2,
  statSync as statSync5,
  unlinkSync
} from "node:fs";
import { homedir } from "node:os";
import { join as join8 } from "node:path";
import { env } from "node:process";

// src/plugin/logging-utils.ts
function isTruthyFlag2(flag) {
  return flag === "1" || flag?.toLowerCase() === "true";
}
function parseDebugLevel(flag) {
  const trimmed = flag.trim();
  if (trimmed === "2" || trimmed === "verbose") return 2;
  if (trimmed === "1" || trimmed === "true") return 1;
  return 0;
}
function deriveDebugPolicy(input) {
  const envDebugFlag = input.envDebugFlag ?? "";
  const debugLevel = input.configDebug ? envDebugFlag === "2" || envDebugFlag === "verbose" ? 2 : 1 : parseDebugLevel(envDebugFlag);
  const debugEnabled = debugLevel >= 1;
  const verboseEnabled = debugLevel >= 2;
  const debugTuiEnabled = debugEnabled && (input.configDebugTui || isTruthyFlag2(input.envDebugTuiFlag));
  return {
    debugLevel,
    debugEnabled,
    debugTuiEnabled,
    verboseEnabled
  };
}
function formatAccountLabel(email, accountIndex) {
  return email || `Account ${accountIndex + 1}`;
}
function formatAccountContextLabel(email, accountIndex) {
  if (email) {
    return email;
  }
  if (accountIndex >= 0) {
    return `Account ${accountIndex + 1}`;
  }
  return "All accounts";
}
function formatErrorForLog(error) {
  if (error instanceof Error) {
    return error.stack ?? error.message;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}
function truncateTextForLog(text2, maxChars) {
  if (text2.length <= maxChars) {
    return text2;
  }
  return `${text2.slice(0, maxChars)}... (truncated ${text2.length - maxChars} chars)`;
}
function formatBodyPreviewForLog(body, maxChars) {
  if (body == null) {
    return void 0;
  }
  if (typeof body === "string") {
    return truncateTextForLog(body, maxChars);
  }
  if (body instanceof URLSearchParams) {
    return truncateTextForLog(body.toString(), maxChars);
  }
  if (typeof Blob !== "undefined" && body instanceof Blob) {
    return `[Blob size=${body.size}]`;
  }
  if (typeof FormData !== "undefined" && body instanceof FormData) {
    return "[FormData payload omitted]";
  }
  return `[${body.constructor?.name ?? typeof body} payload omitted]`;
}
function writeConsoleLog2(level, ...args) {
  switch (level) {
    case "debug":
      console.debug(...args);
      break;
    case "info":
      console.info(...args);
      break;
    case "warn":
      console.warn(...args);
      break;
    case "error":
      console.error(...args);
      break;
  }
}
function redactSensitive(value) {
  if (typeof value !== "string" || value.length === 0) return "";
  if (value.length <= 8) return "****";
  return `${value.slice(0, 4)}****${value.slice(-4)}`;
}
var SENSITIVE_FIELD_PATTERN = /token|refresh|access|project|fingerprint|deviceId|sessionId|sessionToken|secret|password|apiKey|clientSecret/i;
function redactSensitiveFields(value) {
  if (value == null) return value;
  if (Array.isArray(value)) return value.map(redactSensitiveFields);
  if (typeof value === "object") {
    const record2 = value;
    const redacted = {};
    for (const [key, entry] of Object.entries(record2)) {
      if (SENSITIVE_FIELD_PATTERN.test(key) && typeof entry === "string") {
        redacted[key] = redactSensitive(entry);
      } else {
        redacted[key] = redactSensitiveFields(entry);
      }
    }
    return redacted;
  }
  return value;
}
function redactJsonBodyString(body) {
  let parsed;
  try {
    parsed = JSON.parse(body);
  } catch {
    return body;
  }
  if (parsed == null || typeof parsed !== "object") return body;
  return JSON.stringify(redactSensitiveFields(parsed));
}
function redactBodyForLog(body) {
  if (typeof body === "string") return redactJsonBodyString(body);
  return body;
}

// src/plugin/debug.ts
var MAX_BODY_PREVIEW_CHARS = 12e3;
var MAX_BODY_LOG_CHARS = 5e4;
var liveLogFilePaths = /* @__PURE__ */ new Set();
function getConfigDir() {
  const platform = process.platform;
  if (platform === "win32") {
    return join8(
      env.APPDATA || join8(homedir(), "AppData", "Roaming"),
      "opencode"
    );
  }
  const xdgConfig2 = env.XDG_CONFIG_HOME || join8(homedir(), ".config");
  return join8(xdgConfig2, "opencode");
}
function getLogsDir(customLogDir) {
  const logsDir = customLogDir || join8(getConfigDir(), "antigravity-logs");
  try {
    mkdirSync(logsDir, { recursive: true, mode: 448 });
  } catch {
  }
  return logsDir;
}
function createLogFilePath(customLogDir) {
  const logsDir = getLogsDir(customLogDir);
  cleanupOldLogs(logsDir, 25);
  const timestamp = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-");
  let candidate = join8(logsDir, `antigravity-debug-${timestamp}.log`);
  for (let suffix = 2; liveLogFilePaths.has(candidate); suffix++) {
    candidate = join8(logsDir, `antigravity-debug-${timestamp}-${suffix}.log`);
  }
  return candidate;
}
function cleanupOldLogs(logsDir, maxFiles) {
  try {
    const files = readdirSync2(logsDir).filter(
      (file) => file.startsWith("antigravity-debug-") && file.endsWith(".log")
    ).map((file) => join8(logsDir, file));
    if (files.length <= maxFiles) {
      return;
    }
    const sortedFiles = files.map((file) => ({
      file,
      mtime: statSync5(file).mtimeMs
    })).sort((a, b) => b.mtime - a.mtime);
    for (let i = maxFiles; i < sortedFiles.length; i++) {
      const file = sortedFiles[i].file;
      if (liveLogFilePaths.has(file)) continue;
      try {
        unlinkSync(file);
      } catch {
      }
    }
  } catch {
  }
}
function createLogWriter(filePath) {
  if (!filePath) {
    return { writer: () => {
    }, stream: null };
  }
  try {
    const stream = createWriteStream(filePath, { flags: "a", mode: 384 });
    stream.on("error", () => {
    });
    liveLogFilePaths.add(filePath);
    return {
      stream,
      writer: (line) => {
        const timestamp = (/* @__PURE__ */ new Date()).toISOString();
        const formatted = `[${timestamp}] ${line}`;
        stream.write(`${formatted}
`);
      }
    };
  } catch {
    return { writer: () => {
    }, stream: null };
  }
}
function createDebugState(config) {
  if (!config) {
    const { debugEnabled: debugEnabled2 } = deriveDebugPolicy({
      configDebug: false,
      configDebugTui: false,
      envDebugFlag: env.OPENCODE_ANTIGRAVITY_DEBUG,
      envDebugTuiFlag: env.OPENCODE_ANTIGRAVITY_DEBUG_TUI
    });
    const debugTuiEnabled2 = isTruthyFlag2(env.OPENCODE_ANTIGRAVITY_DEBUG_TUI);
    const logFilePath2 = debugEnabled2 ? createLogFilePath() : void 0;
    const { writer: logWriter2, stream: logStream2 } = createLogWriter(logFilePath2);
    return {
      debugEnabled: debugEnabled2,
      debugTuiEnabled: debugTuiEnabled2,
      logFilePath: logFilePath2,
      logWriter: logWriter2,
      logStream: logStream2
    };
  }
  const envDebugFlag = env.OPENCODE_ANTIGRAVITY_DEBUG ?? "";
  const { debugEnabled } = deriveDebugPolicy({
    configDebug: config.debug,
    configDebugTui: config.debug_tui,
    envDebugFlag,
    envDebugTuiFlag: env.OPENCODE_ANTIGRAVITY_DEBUG_TUI
  });
  const debugTuiEnabled = config.debug_tui || isTruthyFlag2(env.OPENCODE_ANTIGRAVITY_DEBUG_TUI);
  const logFilePath = debugEnabled ? createLogFilePath(config.log_dir) : void 0;
  const { writer: logWriter, stream: logStream } = createLogWriter(logFilePath);
  if (debugEnabled) {
    ensureGitignoreSync(getConfigDir());
  }
  return {
    debugEnabled,
    debugTuiEnabled,
    logFilePath,
    logWriter,
    logStream
  };
}
function createDebugHandle(readState, counter, closeState) {
  const logDebug = (line) => {
    readState().logWriter(line);
  };
  const runWithDebugEnabled = (action) => {
    if (!readState().debugEnabled) return;
    action();
  };
  return {
    isDebugEnabled: () => readState().debugEnabled,
    isDebugTuiEnabled: () => readState().debugTuiEnabled,
    getLogFilePath: () => readState().logFilePath,
    startAntigravityDebugRequest(meta) {
      const state = readState();
      if (!state.debugEnabled) {
        return null;
      }
      const id = `ANTIGRAVITY-${++counter.value}`;
      const method = meta.method ?? "GET";
      logDebug(
        `[Antigravity Debug ${id}] pid=${process.pid} ${method} ${meta.resolvedUrl}`
      );
      if (meta.originalUrl && meta.originalUrl !== meta.resolvedUrl) {
        logDebug(`[Antigravity Debug ${id}] Original URL: ${meta.originalUrl}`);
      }
      if (meta.projectId) {
        logDebug(
          `[Antigravity Debug ${id}] Project: ${redactSensitive(meta.projectId)}`
        );
      }
      logDebug(
        `[Antigravity Debug ${id}] Streaming: ${meta.streaming ? "yes" : "no"}`
      );
      logDebug(
        `[Antigravity Debug ${id}] Headers: ${JSON.stringify(maskHeaders(meta.headers))}`
      );
      const bodyPreview = formatBodyPreviewForLog(
        redactBodyForLog(meta.body),
        MAX_BODY_PREVIEW_CHARS
      );
      if (bodyPreview) {
        logDebug(`[Antigravity Debug ${id}] Body Preview: ${bodyPreview}`);
      }
      return { id, streaming: meta.streaming, startedAt: Date.now() };
    },
    logAntigravityDebugResponse(context, response, meta = {}) {
      const state = readState();
      if (!state.debugEnabled || !context) {
        return;
      }
      const durationMs = Date.now() - context.startedAt;
      logDebug(
        `[Antigravity Debug ${context.id}] Response ${response.status} ${response.statusText} (${durationMs}ms)`
      );
      logDebug(
        `[Antigravity Debug ${context.id}] Response Headers: ${JSON.stringify(
          maskHeaders(meta.headersOverride ?? response.headers)
        )}`
      );
      if (meta.note) {
        logDebug(`[Antigravity Debug ${context.id}] Note: ${meta.note}`);
      }
      if (meta.error) {
        logDebug(
          `[Antigravity Debug ${context.id}] Error: ${formatErrorForLog(meta.error)}`
        );
      }
      if (meta.body) {
        logDebug(
          `[Antigravity Debug ${context.id}] Response Body Preview: ${truncateTextForLog(meta.body, MAX_BODY_PREVIEW_CHARS)}`
        );
      }
    },
    logAccountContext(label, info) {
      runWithDebugEnabled(() => {
        const accountLabel = formatAccountContextLabel(info.email, info.index);
        const indexLabel = info.index >= 0 ? `${info.index + 1}/${info.totalAccounts}` : `-/${info.totalAccounts}`;
        let rateLimitInfo = "";
        if (info.rateLimitState && Object.keys(info.rateLimitState).length > 0) {
          const now = Date.now();
          const activeRateLimits = {};
          for (const [key, resetTime] of Object.entries(info.rateLimitState)) {
            if (typeof resetTime === "number" && resetTime > now) {
              const remainingSec = Math.ceil((resetTime - now) / 1e3);
              activeRateLimits[key] = `${remainingSec}s`;
            }
          }
          if (Object.keys(activeRateLimits).length > 0) {
            rateLimitInfo = ` rateLimits=${JSON.stringify(activeRateLimits)}`;
          }
        }
        logDebug(
          `[Account] ${label}: ${accountLabel} (${indexLabel}) family=${info.family}${rateLimitInfo}`
        );
      });
    },
    logRateLimitEvent(accountIndex, email, family, status, retryAfterMs, bodyInfo) {
      runWithDebugEnabled(() => {
        const accountLabel = formatAccountLabel(email, accountIndex);
        logDebug(
          `[RateLimit] ${status} on ${accountLabel} family=${family} retryAfterMs=${retryAfterMs}`
        );
        if (bodyInfo.message) {
          logDebug(`[RateLimit] message: ${bodyInfo.message}`);
        }
        if (bodyInfo.quotaResetTime) {
          logDebug(`[RateLimit] quotaResetTime: ${bodyInfo.quotaResetTime}`);
        }
        if (bodyInfo.retryDelayMs !== void 0 && bodyInfo.retryDelayMs !== null) {
          logDebug(`[RateLimit] body retryDelayMs: ${bodyInfo.retryDelayMs}`);
        }
        if (bodyInfo.reason) {
          logDebug(`[RateLimit] reason: ${bodyInfo.reason}`);
        }
      });
    },
    logRateLimitSnapshot(family, accounts) {
      runWithDebugEnabled(() => {
        const now = Date.now();
        const entries = accounts.map((account) => {
          const label = formatAccountLabel(account.email, account.index);
          const reset = account.rateLimitResetTimes?.[family];
          if (typeof reset !== "number") {
            return `${label}=ready`;
          }
          const remaining = Math.max(0, reset - now);
          const seconds = Math.ceil(remaining / 1e3);
          return `${label}=wait ${seconds}s`;
        });
        logDebug(`[RateLimit] snapshot family=${family} ${entries.join(" | ")}`);
      });
    },
    async logResponseBody(context, response, status) {
      const state = readState();
      if (!state.debugEnabled || !context) return void 0;
      try {
        const text2 = await response.clone().text();
        const preview = truncateTextForLog(text2, MAX_BODY_LOG_CHARS);
        logDebug(
          `[Antigravity Debug ${context.id}] Response Body (${status}): ${preview}`
        );
        return text2;
      } catch (e) {
        logDebug(
          `[Antigravity Debug ${context.id}] Failed to read response body: ${formatErrorForLog(e)}`
        );
        return void 0;
      }
    },
    logModelFamily(url, extractedModel, family) {
      runWithDebugEnabled(() => {
        logDebug(
          `[ModelFamily] url=${url} model=${extractedModel ?? "unknown"} family=${family}`
        );
      });
    },
    debugLogToFile(message) {
      runWithDebugEnabled(() => {
        logDebug(message);
      });
    },
    logToast(message, variant) {
      runWithDebugEnabled(() => {
        const variantLabel = variant.toUpperCase();
        logDebug(`[Toast/${variantLabel}] ${message}`);
      });
    },
    logRetryAttempt(attempt, maxAttempts, reason, delayMs) {
      runWithDebugEnabled(() => {
        const delayInfo = delayMs !== void 0 ? ` delay=${delayMs}ms` : "";
        const maxInfo = maxAttempts < 0 ? "\u221E" : maxAttempts.toString();
        logDebug(
          `[Retry] Attempt ${attempt}/${maxInfo} reason=${reason}${delayInfo}`
        );
      });
    },
    logCacheStats(model, cacheReadTokens, cacheWriteTokens, totalInputTokens) {
      runWithDebugEnabled(() => {
        const cacheHitRate = totalInputTokens > 0 ? Math.round(cacheReadTokens / totalInputTokens * 100) : 0;
        const status = cacheReadTokens > 0 ? "HIT" : cacheWriteTokens > 0 ? "WRITE" : "MISS";
        logDebug(
          `[Cache] ${status} model=${model} read=${cacheReadTokens} write=${cacheWriteTokens} total=${totalInputTokens} hitRate=${cacheHitRate}%`
        );
      });
    },
    logQuotaStatus(accountEmail, accountIndex, quotaPercent, family) {
      runWithDebugEnabled(() => {
        const accountLabel = formatAccountLabel(accountEmail, accountIndex);
        const familyInfo = family ? ` family=${family}` : "";
        const status = quotaPercent <= 0 ? "EXHAUSTED" : quotaPercent < 20 ? "LOW" : "OK";
        logDebug(
          `[Quota] ${accountLabel} remaining=${quotaPercent.toFixed(1)}% status=${status}${familyInfo}`
        );
      });
    },
    logQuotaFetch(event, accountCount, details) {
      runWithDebugEnabled(() => {
        const countInfo = accountCount !== void 0 ? ` accounts=${accountCount}` : "";
        const detailsInfo = details ? ` ${details}` : "";
        logDebug(
          `[QuotaFetch] ${event.toUpperCase()}${countInfo}${detailsInfo}`
        );
      });
    },
    logModelUsed(requestedModel, actualModel, accountEmail) {
      runWithDebugEnabled(() => {
        const accountInfo = accountEmail ? ` account=${accountEmail}` : "";
        if (requestedModel !== actualModel) {
          logDebug(
            `[Model] requested=${requestedModel} actual=${actualModel}${accountInfo}`
          );
        } else {
          logDebug(`[Model] ${actualModel}${accountInfo}`);
        }
      });
    },
    close: closeState
  };
}
function maskHeaders(headers) {
  if (!headers) {
    return {};
  }
  const result = {};
  const SENSITIVE_HEADERS = /* @__PURE__ */ new Set([
    "authorization",
    "x-api-key",
    "x-goog-api-key",
    "cookie",
    "set-cookie"
  ]);
  const parsed = headers instanceof Headers ? headers : new Headers(headers);
  parsed.forEach((value, key) => {
    if (SENSITIVE_HEADERS.has(key.toLowerCase())) {
      result[key] = "[redacted]";
    } else if (key.toLowerCase() === "user-agent") {
      result[key] = redactSensitive(value);
    } else {
      result[key] = value;
    }
  });
  return redactSensitiveFields(result);
}
var debugState = null;
var legacyRequestCounter = { value: 0 };
function getDebugState() {
  debugState ??= createDebugState(null);
  return debugState;
}
var legacyDebug = createDebugHandle(
  getDebugState,
  legacyRequestCounter,
  () => closeDebugLog()
);
function closeDebugLog() {
  const state = debugState;
  const current = state?.logStream;
  if (!state || !current) return Promise.resolve();
  state.logStream = null;
  if (state.logFilePath) liveLogFilePaths.delete(state.logFilePath);
  return new Promise((resolve7) => {
    current.once("close", () => resolve7());
    current.once("error", () => resolve7());
    try {
      current.end();
    } catch {
      resolve7();
    }
  });
}
function isDebugTuiEnabled() {
  return legacyDebug.isDebugTuiEnabled();
}
function logQuotaStatus(accountEmail, accountIndex, quotaPercent, family) {
  legacyDebug.logQuotaStatus(accountEmail, accountIndex, quotaPercent, family);
}
function logQuotaFetch(event, accountCount, details) {
  legacyDebug.logQuotaFetch(event, accountCount, details);
}

// src/plugin/logger.ts
var ENV_CONSOLE_LOG2 = "OPENCODE_ANTIGRAVITY_CONSOLE_LOG";
var LOG_LEVEL_FROM_OPERATOR = {
  error: "error",
  warn: "warn",
  info: "info",
  debug: "debug",
  trace: "debug"
};
function createLocationLogger(options) {
  let configuredLevel = options.level ? LOG_LEVEL_FROM_OPERATOR[options.level] ?? "debug" : "debug";
  const emit = (record2) => {
    if (options.sink && options.sinkEnabled()) {
      try {
        const pending = options.sink(record2);
        if (isThenable(pending)) {
          pending.then(void 0, () => {
          });
        }
      } catch {
      }
    }
    if (isConsoleLogEnabled2()) {
      const prefix = `[${record2.service}]`;
      const args = record2.extra ? [prefix, record2.message, record2.extra] : [prefix, record2.message];
      try {
        writeConsoleLog2(record2.level, ...args);
      } catch {
      }
    }
  };
  const engine = createLoggerInstance2({
    level: () => configuredLevel,
    extraSecretKeys: isProviderSecretKey,
    captureSink: ({ channel, level, message, data }) => {
      const extra = data !== null && typeof data === "object" && !Array.isArray(data) ? Object.fromEntries(Object.entries(data)) : void 0;
      emit({
        service: channel,
        level: level === "trace" ? "debug" : level,
        message,
        extra
      });
    }
  });
  return {
    createLogger(module) {
      const channel = engine.createLogger(`antigravity.${module}`);
      return {
        debug: (message, extra) => channel.debug(message, extra),
        info: (message, extra) => channel.info(message, extra),
        warn: (message, extra) => channel.warn(message, extra),
        error: (message, extra) => channel.error(message, extra)
      };
    },
    setLevel(level) {
      configuredLevel = LOG_LEVEL_FROM_OPERATOR[level] ?? "debug";
    },
    coreLogSink: ({ service, level, message, extra }) => {
      engine.createLogger(service)[level](message, extra);
    }
  };
}
function createAppLogSink(client) {
  return (record2) => {
    const app = client.app;
    if (app && typeof app.log === "function") {
      return app.log({ body: record2 });
    }
    return void 0;
  };
}
function isThenable(value) {
  return value !== null && (typeof value === "object" || typeof value === "function") && typeof value.then === "function";
}
function isConsoleLogEnabled2() {
  return isTruthyFlag2(process.env[ENV_CONSOLE_LOG2]);
}
var legacyClient = null;
var legacyLogger;
function getLegacyLogger() {
  legacyLogger ??= createLocationLogger({
    sink: (record2) => legacyClient ? createAppLogSink(legacyClient)(record2) : void 0,
    sinkEnabled: isDebugTuiEnabled
  });
  return legacyLogger;
}
function createLogger4(module) {
  let channel;
  const log8 = (level, message, extra) => {
    channel ??= getLegacyLogger().createLogger(module);
    channel[level](message, extra);
  };
  return {
    debug: (message, extra) => log8("debug", message, extra),
    info: (message, extra) => log8("info", message, extra),
    warn: (message, extra) => log8("warn", message, extra),
    error: (message, extra) => log8("error", message, extra)
  };
}

// src/plugin/storage.ts
var log5 = createLogger4("storage");
var mutateAccountStorage2 = async (path2, mutate) => {
  await assertLegacyPoolInUse(path2);
  return mutateAccountStorage(path2, mutate);
};
var GITIGNORE_ENTRIES = [
  "antigravity-accounts.json",
  "antigravity-accounts.json.*.tmp",
  // The account store's generation directories hold credential files; its
  // pointer file names the current generation only.
  "antigravity-accounts.json.store*",
  "antigravity-signature-cache.json",
  "antigravity-logs/"
];
async function ensureGitignore(configDir) {
  const gitignorePath = join9(configDir, ".gitignore");
  try {
    let content;
    let existingLines = [];
    try {
      content = await fs2.readFile(gitignorePath, "utf-8");
      existingLines = content.split("\n").map((line) => line.trim());
    } catch (error) {
      if (error.code !== "ENOENT") {
        return;
      }
      content = "";
    }
    const missingEntries = GITIGNORE_ENTRIES.filter(
      (entry) => !existingLines.includes(entry)
    );
    if (missingEntries.length === 0) {
      return;
    }
    if (content === "") {
      await fs2.writeFile(
        gitignorePath,
        `${missingEntries.join("\n")}
`,
        "utf-8"
      );
      log5.info("Created .gitignore in config directory");
    } else {
      const suffix = content.endsWith("\n") ? "" : "\n";
      await fs2.appendFile(
        gitignorePath,
        `${suffix + missingEntries.join("\n")}
`,
        "utf-8"
      );
      log5.info("Updated .gitignore with missing entries", {
        added: missingEntries
      });
    }
  } catch (error) {
    log5.warn("Failed to update .gitignore with account storage entries", {
      error: String(error)
    });
  }
}
function ensureGitignoreSync(configDir) {
  const gitignorePath = join9(configDir, ".gitignore");
  try {
    let content;
    let existingLines = [];
    if (existsSync4(gitignorePath)) {
      content = readFileSync(gitignorePath, "utf-8");
      existingLines = content.split("\n").map((line) => line.trim());
    } else {
      content = "";
    }
    const missingEntries = GITIGNORE_ENTRIES.filter(
      (entry) => !existingLines.includes(entry)
    );
    if (missingEntries.length === 0) {
      return;
    }
    if (content === "") {
      writeFileSync(gitignorePath, `${missingEntries.join("\n")}
`, "utf-8");
      log5.info("Created .gitignore in config directory");
    } else {
      const suffix = content.endsWith("\n") ? "" : "\n";
      appendFileSync3(
        gitignorePath,
        `${suffix + missingEntries.join("\n")}
`,
        "utf-8"
      );
      log5.info("Updated .gitignore with missing entries", {
        added: missingEntries
      });
    }
  } catch (error) {
    log5.warn("Failed to update .gitignore with account storage entries", {
      error: String(error)
    });
  }
}
function getLegacyWindowsConfigDir() {
  return join9(
    process.env.APPDATA || join9(homedir2(), "AppData", "Roaming"),
    "opencode"
  );
}
function getConfigDir2() {
  if (process.env.OPENCODE_CONFIG_DIR) {
    return process.env.OPENCODE_CONFIG_DIR;
  }
  const xdgConfig2 = process.env.XDG_CONFIG_HOME || join9(homedir2(), ".config");
  return join9(xdgConfig2, "opencode");
}
function migrateLegacyWindowsConfig() {
  if (process.platform !== "win32") {
    return false;
  }
  const newPath = join9(getConfigDir2(), "antigravity-accounts.json");
  const legacyPath = join9(
    getLegacyWindowsConfigDir(),
    "antigravity-accounts.json"
  );
  if (!existsSync4(legacyPath) || existsSync4(newPath)) {
    return false;
  }
  try {
    const newConfigDir = getConfigDir2();
    mkdirSync2(newConfigDir, { recursive: true });
    try {
      renameSync3(legacyPath, newPath);
      log5.info("Migrated Windows config via rename", {
        from: legacyPath,
        to: newPath
      });
    } catch {
      copyFileSync(legacyPath, newPath);
      unlinkSync2(legacyPath);
      log5.info("Migrated Windows config via copy+delete", {
        from: legacyPath,
        to: newPath
      });
    }
    return true;
  } catch (error) {
    log5.warn("Failed to migrate legacy Windows config, will use legacy path", {
      legacyPath,
      newPath,
      error: String(error)
    });
    return false;
  }
}
function getStoragePathWithMigration() {
  const newPath = join9(getConfigDir2(), "antigravity-accounts.json");
  if (process.platform === "win32") {
    migrateLegacyWindowsConfig();
    if (!existsSync4(newPath)) {
      const legacyPath = join9(
        getLegacyWindowsConfigDir(),
        "antigravity-accounts.json"
      );
      if (existsSync4(legacyPath)) {
        log5.info("Using legacy Windows config path (migration failed)", {
          legacyPath,
          newPath
        });
        return legacyPath;
      }
    }
  }
  return newPath;
}
function getStoragePath() {
  return getStoragePathWithMigration();
}
var LegacyAccountPoolRetiredError = class extends Error {
  legacyPath;
  constructor(legacyPath, options) {
    super(
      `Account pool file ${legacyPath} is owned by the account store and is no longer read or written. Use the account store, or roll it back with \`antigravity-auth rollback --offline\` before using an older build.`,
      options
    );
    this.name = "LegacyAccountPoolRetiredError";
    this.legacyPath = legacyPath;
  }
};
async function assertLegacyPoolInUse(legacyPath) {
  try {
    await assertLegacyAccountStorageWritable(resolve5(legacyPath));
  } catch (error) {
    throw new LegacyAccountPoolRetiredError(legacyPath, { cause: error });
  }
}
async function loadAccounts() {
  const path2 = getStoragePath();
  await assertLegacyPoolInUse(path2);
  await ensureGitignore(dirname11(path2));
  return loadAccountStorage(path2);
}

// src/plugin/persist-account-pool.ts
function clampInt(value, min, max) {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, Math.floor(value)));
}
function applyUpserts(current, results, replaceAll) {
  const now = Date.now();
  const accounts = replaceAll ? [] : [...current.accounts];
  const indexByRefreshToken = /* @__PURE__ */ new Map();
  const indexByEmail = /* @__PURE__ */ new Map();
  for (let i = 0; i < accounts.length; i++) {
    const acc = accounts[i];
    if (!acc) continue;
    if (acc.refreshToken) {
      indexByRefreshToken.set(acc.refreshToken, i);
    }
    if (acc.email) {
      indexByEmail.set(acc.email, i);
    }
  }
  for (const result of results) {
    const parts = parseRefreshParts(result.refresh);
    if (!parts.refreshToken) {
      continue;
    }
    const existingByEmail = result.email ? indexByEmail.get(result.email) : void 0;
    const existingByToken = indexByRefreshToken.get(parts.refreshToken);
    const existingIndex = existingByEmail ?? existingByToken;
    if (existingIndex === void 0) {
      const newIndex = accounts.length;
      indexByRefreshToken.set(parts.refreshToken, newIndex);
      if (result.email) {
        indexByEmail.set(result.email, newIndex);
      }
      accounts.push({
        email: result.email,
        label: result.label,
        refreshToken: parts.refreshToken,
        projectId: parts.projectId,
        managedProjectId: parts.managedProjectId,
        addedAt: now,
        lastUsed: now,
        enabled: true
      });
      continue;
    }
    const existing = accounts[existingIndex];
    if (!existing) continue;
    const oldToken = existing.refreshToken;
    accounts[existingIndex] = {
      ...existing,
      email: result.email ?? existing.email,
      label: result.label ?? existing.label,
      refreshToken: parts.refreshToken,
      projectId: parts.projectId ?? existing.projectId,
      managedProjectId: parts.managedProjectId ?? existing.managedProjectId,
      lastUsed: now
    };
    if (oldToken !== parts.refreshToken) {
      indexByRefreshToken.delete(oldToken);
      indexByRefreshToken.set(parts.refreshToken, existingIndex);
    }
  }
  if (accounts.length === 0) {
    return void 0;
  }
  const activeIndex = replaceAll ? 0 : typeof current.activeIndex === "number" && Number.isFinite(current.activeIndex) ? current.activeIndex : 0;
  const clamped = clampInt(activeIndex, 0, accounts.length - 1);
  return {
    version: 4,
    accounts,
    activeIndex: clamped,
    activeIndexByFamily: {
      claude: clamped,
      gemini: clamped
    }
  };
}
async function persistAccountPool(results, replaceAll = false) {
  if (results.length === 0) {
    return;
  }
  const path2 = getStoragePath();
  const emptyV4 = () => ({
    version: 4,
    accounts: [],
    activeIndex: 0
  });
  if (replaceAll) {
    await mutateAccountStorage2(
      path2,
      () => applyUpserts(emptyV4(), results, true)
    );
    return;
  }
  await mutateAccountStorage2(
    path2,
    (current) => applyUpserts(current, results, false)
  );
}

// ../../node_modules/.bun/xdg-basedir@5.1.0/node_modules/xdg-basedir/index.js
import os from "os";
import path from "path";
var homeDirectory = os.homedir();
var { env: env2 } = process;
var xdgData = env2.XDG_DATA_HOME || (homeDirectory ? path.join(homeDirectory, ".local", "share") : void 0);
var xdgConfig = env2.XDG_CONFIG_HOME || (homeDirectory ? path.join(homeDirectory, ".config") : void 0);
var xdgState = env2.XDG_STATE_HOME || (homeDirectory ? path.join(homeDirectory, ".local", "state") : void 0);
var xdgCache = env2.XDG_CACHE_HOME || (homeDirectory ? path.join(homeDirectory, ".cache") : void 0);
var xdgRuntime = env2.XDG_RUNTIME_DIR || void 0;
var xdgDataDirectories = (env2.XDG_DATA_DIRS || "/usr/local/share/:/usr/share/").split(":");
if (xdgData) {
  xdgDataDirectories.unshift(xdgData);
}
var xdgConfigDirectories = (env2.XDG_CONFIG_DIRS || "/etc/xdg").split(":");
if (xdgConfig) {
  xdgConfigDirectories.unshift(xdgConfig);
}

// src/sidebar-state.ts
var ACTIVE_ROUTING_MAX_AGE_MS = 24 * 60 * 60 * 1e3;
var sidebarWriteChain = Promise.resolve();

// src/plugin/token.ts
var log6 = createLogger4("token");
function parseOAuthErrorPayload(text2) {
  if (!text2) {
    return {};
  }
  try {
    const payload = JSON.parse(text2);
    if (!payload || typeof payload !== "object") {
      return { description: text2 };
    }
    let code2;
    if (typeof payload.error === "string") {
      code2 = payload.error;
    } else if (payload.error && typeof payload.error === "object") {
      code2 = payload.error.status ?? payload.error.code;
      if (!payload.error_description && payload.error.message) {
        return { code: code2, description: payload.error.message };
      }
    }
    const description = payload.error_description;
    if (description) {
      return { code: code2, description };
    }
    if (payload.error && typeof payload.error === "object" && payload.error.message) {
      return { code: code2, description: payload.error.message };
    }
    return { code: code2 };
  } catch {
    return { description: text2 };
  }
}
var AntigravityTokenRefreshError = class extends Error {
  code;
  description;
  status;
  statusText;
  constructor(options) {
    super(options.message);
    this.name = "AntigravityTokenRefreshError";
    this.code = options.code;
    this.description = options.description;
    this.status = options.status;
    this.statusText = options.statusText;
  }
};
async function exchangeRefreshToken(refreshToken, now) {
  const startTime = now();
  const response = await fetchWithActiveTimeout(
    "https://oauth2.googleapis.com/token",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded"
      },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: refreshToken,
        client_id: ANTIGRAVITY_CLIENT_ID,
        client_secret: ANTIGRAVITY_CLIENT_SECRET
      })
    }
  );
  if (!response.ok) {
    let errorText2;
    try {
      errorText2 = await response.text();
    } catch {
      errorText2 = void 0;
    }
    const { code: code2, description } = parseOAuthErrorPayload(errorText2);
    const details = [code2, description ?? errorText2].filter(Boolean).join(": ");
    const baseMessage = `Antigravity token refresh failed (${response.status} ${response.statusText})`;
    const message = details ? `${baseMessage} - ${details}` : baseMessage;
    log6.warn("Token refresh failed", {
      status: response.status,
      code: code2,
      details
    });
    if (code2 === "invalid_grant") {
      log6.warn(
        "Google revoked the stored refresh token - reauthentication required"
      );
      invalidateProjectContextCache(refreshToken);
    }
    throw new AntigravityTokenRefreshError({
      message,
      code: code2,
      description: description ?? errorText2,
      status: response.status,
      statusText: response.statusText
    });
  }
  const payload = await response.json();
  return {
    accessToken: typeof payload.access_token === "string" && payload.access_token ? payload.access_token : void 0,
    refreshToken: typeof payload.refresh_token === "string" && payload.refresh_token ? payload.refresh_token : refreshToken,
    expiresAt: calculateTokenExpiry(startTime, payload.expires_in)
  };
}
async function refreshAccessToken(auth, _client, _providerId) {
  const parts = parseRefreshParts(auth.refresh);
  if (!parts.refreshToken) {
    return void 0;
  }
  try {
    const grant = await exchangeRefreshToken(parts.refreshToken, Date.now);
    const refreshedParts = {
      refreshToken: grant.refreshToken,
      projectId: parts.projectId,
      managedProjectId: parts.managedProjectId
    };
    return {
      ...auth,
      access: grant.accessToken,
      expires: grant.expiresAt,
      refresh: formatRefreshParts(refreshedParts)
    };
  } catch (error) {
    if (error instanceof AntigravityTokenRefreshError) {
      throw error;
    }
    log6.error("Unexpected token refresh error", { error: String(error) });
    return void 0;
  }
}

// src/plugin/quota.ts
var log7 = createLogger4("quota");
async function checkAccountsQuotaWith(accounts, fetchAccountQuota) {
  const manager = createQuotaManager({
    fetchAccountQuota,
    keyOf: defaultKeyOf
  });
  try {
    return await manager.refreshAccounts(accounts, {
      indexFor: (account) => accounts.indexOf(account),
      force: true
    });
  } finally {
    manager.dispose();
  }
}
async function checkAccountsQuotaStandalone(accounts, options) {
  if (!options.refresh) {
    return accounts.map((account, index) => ({
      index,
      email: account.email,
      status: account.enabled === false ? "disabled" : "ok",
      disabled: account.enabled === false,
      quota: {
        groups: account.cachedQuota ?? {},
        modelCount: Object.keys(account.cachedQuota ?? {}).length
      }
    }));
  }
  return checkAccountsQuotaWith(
    accounts,
    makeFetchAccountQuota(void 0, ANTIGRAVITY_PROVIDER_ID)
  );
}
async function fetchLegacyModelsFallback(options) {
  try {
    const modelsResponse = await fetchAvailableModels({
      accessToken: options.accessToken,
      projectId: options.projectId,
      endpoints: ANTIGRAVITY_ENDPOINT_FALLBACKS,
      userAgent: buildAntigravityHarnessUserAgent(),
      timeoutMs: 1e4,
      ...options.fetchVia ? { fetchVia: options.fetchVia } : {}
    });
    if (modelsResponse.models) {
      return aggregateQuota(modelsResponse.models);
    }
    return {
      groups: {},
      modelCount: 0,
      error: "Failed to fetch Antigravity quota (legacy fallback)"
    };
  } catch {
    return {
      groups: {},
      modelCount: 0,
      error: "Failed to fetch Antigravity quota"
    };
  }
}
async function fetchQuotaPayloads(options) {
  const { accessToken, managedProjectId, projectId, fetchVia } = options;
  const fetchSummaryPayload = (async () => {
    try {
      const summaryResult = await fetchQuotaSummary({
        accessToken,
        managedProjectId,
        projectId,
        endpoints: ANTIGRAVITY_ENDPOINT_FALLBACKS,
        userAgent: buildAntigravityHarnessUserAgent(),
        timeoutMs: 1e4,
        ...fetchVia ? { fetchVia } : {}
      });
      return {
        result: aggregateQuotaSummary(summaryResult.summary),
        fellBackToLegacy: summaryResult.fellBackToLegacy ?? false
      };
    } catch {
      return {
        result: await fetchLegacyModelsFallback({
          accessToken,
          projectId,
          fetchVia
        }),
        fellBackToLegacy: true
      };
    }
  })();
  let geminiCliFetchError;
  const fetchGeminiCliPayload = fetchGeminiCliQuota({
    accessToken,
    projectId,
    endpoints: ANTIGRAVITY_ENDPOINT_FALLBACKS,
    userAgent: buildGeminiCliUserAgent(),
    timeoutMs: 1e4,
    ...fetchVia ? { fetchVia } : {}
  }).catch((error) => {
    geminiCliFetchError = error instanceof Error ? error.message : String(error);
    options.logger.debug("fetchGeminiCliQuota failed", {
      error: geminiCliFetchError
    });
    return { buckets: void 0 };
  });
  const [summary, geminiCliResponse] = await Promise.all([
    fetchSummaryPayload,
    fetchGeminiCliPayload
  ]);
  return {
    quota: summary.result,
    geminiCliQuota: annotateGeminiCliQuota(
      geminiCliResponse,
      geminiCliFetchError
    ),
    fellBackToLegacy: summary.fellBackToLegacy
  };
}
function annotateGeminiCliQuota(response, fetchError) {
  const result = aggregateGeminiCliQuota(response);
  if (response.buckets !== void 0 && response.buckets.length > 0) {
    return result;
  }
  return {
    ...result,
    error: fetchError ?? (result.models.length === 0 ? "No Gemini CLI quota available" : void 0)
  };
}
function makeFetchAccountQuota(client, providerId, fetchVia) {
  return async (account, signal) => {
    const index = 0;
    const disabled = account.enabled === false;
    if (disabled) {
      return {
        index,
        email: account.email,
        status: "disabled",
        disabled: true
      };
    }
    if (signal.aborted) {
      return {
        index,
        email: account.email,
        status: "error",
        error: signal.reason instanceof Error ? signal.reason.message : "aborted"
      };
    }
    let auth = buildAuthFromAccount(account);
    let rotatedRefresh;
    try {
      if (accessTokenExpired(auth)) {
        const refreshed = await refreshAccessToken(
          auth,
          client,
          providerId
        );
        if (!refreshed) {
          throw new Error("Token refresh failed");
        }
        if (refreshed.refresh !== auth.refresh) {
          rotatedRefresh = refreshed.refresh;
        }
        auth = refreshed;
      }
      const projectContext = await ensureProjectContext(auth);
      auth = projectContext.auth;
      const updatedAccount = applyAccountUpdates(
        account,
        auth,
        projectContext.capturedTier
      );
      if (rotatedRefresh && client) {
        await persistRotatedRefresh(client, providerId, auth).catch(() => {
        });
      }
      let quotaResult;
      let fellBackToLegacy = false;
      const authParts = parseRefreshParts(auth.refresh);
      const managedProjectId = authParts.managedProjectId ?? account.managedProjectId;
      const payloads = await fetchQuotaPayloads({
        accessToken: auth.access ?? "",
        managedProjectId,
        projectId: projectContext.effectiveProjectId,
        fetchVia,
        logger: log7
      });
      quotaResult = payloads.quota;
      fellBackToLegacy = payloads.fellBackToLegacy;
      const annotated = payloads.geminiCliQuota;
      for (const [family, groupQuota] of Object.entries(quotaResult.groups)) {
        const remainingPercent = (groupQuota.remainingFraction ?? 0) * 100;
        logQuotaStatus(account.email, index, remainingPercent, family);
      }
      const legacyTag = fellBackToLegacy ? " legacy=1" : "";
      logQuotaFetch("complete", 1, `ok=1 errors=0${legacyTag}`);
      return {
        index,
        email: account.email,
        status: "ok",
        disabled: false,
        quota: quotaResult,
        geminiCliQuota: annotated,
        updatedAccount
      };
    } catch (error) {
      logQuotaFetch(
        "error",
        void 0,
        `account=${account.email ?? index} error=${error instanceof Error ? error.message : String(error)}`
      );
      return {
        index,
        email: account.email,
        status: "error",
        error: error instanceof Error ? error.message : String(error),
        disabled: false
      };
    }
  };
}
function buildAuthFromAccount(account) {
  return {
    type: "oauth",
    refresh: formatRefreshParts({
      refreshToken: account.refreshToken,
      projectId: account.projectId,
      managedProjectId: account.managedProjectId
    }),
    access: void 0,
    expires: void 0
  };
}
function applyAccountUpdates(account, auth, capturedTier) {
  const parts = parseRefreshParts(auth.refresh);
  if (!parts.refreshToken) {
    return void 0;
  }
  const updated = {
    ...account,
    refreshToken: parts.refreshToken,
    projectId: parts.projectId ?? account.projectId,
    managedProjectId: parts.managedProjectId ?? account.managedProjectId,
    // Persist the captured tier alongside the project-context write. Only
    // present when the loadCodeAssist payload returned a non-empty currentTier.id.
    ...capturedTier ? {
      capturedTierId: capturedTier.id,
      ...capturedTier.paidId !== void 0 ? { capturedPaidTierId: capturedTier.paidId } : {},
      capturedTierAt: capturedTier.capturedAt
    } : {}
  };
  const changed = updated.refreshToken !== account.refreshToken || updated.projectId !== account.projectId || updated.managedProjectId !== account.managedProjectId || updated.capturedTierId !== account.capturedTierId || updated.capturedPaidTierId !== account.capturedPaidTierId || // capturedAt represents when the tier was LAST CONFIRMED, not when it
  // changed -- always update it on a successful observation so consumers
  // can gate staleness on that timestamp even when the id stays the same.
  capturedTier !== void 0 && updated.capturedTierAt !== account.capturedTierAt;
  return changed ? updated : void 0;
}
async function persistRotatedRefresh(client, providerId, auth) {
  await client.auth.set({
    path: { id: providerId },
    body: {
      type: "oauth",
      refresh: auth.refresh,
      access: auth.access ?? "",
      expires: auth.expires ?? 0
    }
  });
}

// src/plugin/server.ts
import { existsSync as existsSync5, readFileSync as readFileSync2 } from "node:fs";
import { createServer } from "node:http";
var redirectUri = new URL(ANTIGRAVITY_REDIRECT_URI);
var callbackPath = redirectUri.pathname || "/";
function isOrbStackDockerHost() {
  if (!existsSync5("/.dockerenv")) {
    return false;
  }
  try {
    if (existsSync5("/proc/version")) {
      const version = readFileSync2("/proc/version", "utf8").toLowerCase();
      if (version.includes("orbstack")) {
        return true;
      }
    }
    const hostname = process.env.HOSTNAME || "";
    if (hostname.startsWith("orbstack-") || hostname.endsWith(".orb") || hostname === "orbstack") {
      return true;
    }
    if (existsSync5("/etc/resolv.conf")) {
      const resolv = readFileSync2("/etc/resolv.conf", "utf8");
      if (resolv.includes("orb.local") || resolv.includes("orbstack")) {
        return true;
      }
    }
    if (process.platform === "linux" && existsSync5("/.dockerenv")) {
      if (existsSync5("/run/host-services")) {
        return true;
      }
    }
  } catch {
  }
  return false;
}
function isWSL() {
  if (process.platform !== "linux") return false;
  try {
    const release = readFileSync2("/proc/version", "utf8").toLowerCase();
    return release.includes("microsoft") || release.includes("wsl");
  } catch {
    return false;
  }
}
function isRemoteEnvironment() {
  if (process.env.SSH_CLIENT || process.env.SSH_TTY || process.env.SSH_CONNECTION) {
    return true;
  }
  if (process.env.REMOTE_CONTAINERS || process.env.CODESPACES) {
    return true;
  }
  return false;
}
function getBindAddress() {
  const envBind = process.env.OPENCODE_ANTIGRAVITY_OAUTH_BIND;
  if (envBind) {
    return envBind;
  }
  if (isOrbStackDockerHost()) {
    return "127.0.0.1";
  }
  if (isWSL() || isRemoteEnvironment()) {
    return "0.0.0.0";
  }
  return "127.0.0.1";
}
async function startOAuthListener({
  timeoutMs = 5 * 60 * 1e3
} = {}) {
  const port = redirectUri.port ? Number.parseInt(redirectUri.port, 10) : redirectUri.protocol === "https:" ? 443 : 80;
  const origin = `${redirectUri.protocol}//${redirectUri.host}`;
  let settled = false;
  let resolveCallback;
  let rejectCallback;
  let timeoutHandle;
  const callbackPromise = new Promise((resolve7, reject) => {
    resolveCallback = (url) => {
      if (settled) return;
      settled = true;
      if (timeoutHandle) clearTimeout(timeoutHandle);
      resolve7(url);
    };
    rejectCallback = (error) => {
      if (settled) return;
      settled = true;
      if (timeoutHandle) clearTimeout(timeoutHandle);
      reject(error);
    };
  });
  const successResponse = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Authentication Successful</title>
    <style>
      :root {
        --bg: #FAFAFA;
        --card-bg: #FFFFFF;
        --text-primary: #1F2937;
        --text-secondary: #6B7280;
        --accent: #2563EB;
        --success: #10B981;
        --border: #E5E7EB;
      }
      @media (prefers-color-scheme: dark) {
        :root {
          --bg: #111827;
          --card-bg: #1F2937;
          --text-primary: #F9FAFB;
          --text-secondary: #9CA3AF;
          --accent: #3B82F6;
          --success: #34D399;
          --border: #374151;
        }
      }
      body {
        margin: 0;
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background: var(--bg);
        color: var(--text-primary);
        padding: 1rem;
      }
      .card {
        background: var(--card-bg);
        border-radius: 16px;
        padding: 3rem 2rem;
        width: 100%;
        max-width: 400px;
        text-align: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        border: 1px solid var(--border);
      }
      .icon-wrapper {
        width: 64px;
        height: 64px;
        background: rgba(16, 185, 129, 0.1);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0 auto 1.5rem;
      }
      .icon {
        width: 32px;
        height: 32px;
        color: var(--success);
      }
      h1 {
        font-size: 1.5rem;
        font-weight: 600;
        margin: 0 0 0.5rem;
        letter-spacing: -0.025em;
      }
      p {
        color: var(--text-secondary);
        font-size: 0.95rem;
        line-height: 1.5;
        margin: 0 0 2rem;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: var(--text-primary);
        color: var(--card-bg);
        font-weight: 500;
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        text-decoration: none;
        transition: opacity 0.2s;
        font-size: 0.95rem;
        border: none;
        cursor: pointer;
        width: 100%;
        box-sizing: border-box;
      }
      .btn:hover {
        opacity: 0.9;
      }
      .sub-text {
        margin-top: 1rem;
        font-size: 0.8rem;
        color: var(--text-secondary);
      }
    </style>
  </head>
  <body>
    <div class="card">
      <div class="icon-wrapper">
        <svg class="icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <h1>All set!</h1>
      <p>You've successfully authenticated with Antigravity. You can now return to Opencode.</p>
      <button class="btn" onclick="closeWindow()">Close this tab</button>
      <div class="sub-text">Usage Tip: Most browsers block auto-closing. If the button doesn't work, please close the tab manually.</div>
    </div>
    <script>
      function closeWindow() {
        window.close();
        // Fallback if window.close() is blocked
        document.querySelector('.btn').textContent = "Tab cannot be closed automatically";
        document.querySelector('.btn').style.opacity = "0.5";
        document.querySelector('.btn').style.cursor = "default";
      }
    </script>
  </body>
</html>`;
  timeoutHandle = setTimeout(() => {
    rejectCallback(new Error("Timed out waiting for OAuth callback"));
  }, timeoutMs);
  timeoutHandle.unref?.();
  const server = createServer((request, response) => {
    if (!request.url) {
      response.writeHead(400, { "Content-Type": "text/plain" });
      response.end("Invalid request");
      return;
    }
    const url = new URL(request.url, origin);
    if (url.pathname !== callbackPath) {
      response.writeHead(404, { "Content-Type": "text/plain" });
      response.end("Not found");
      return;
    }
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(successResponse);
    resolveCallback(url);
    setImmediate(() => {
      server.close();
    });
  });
  const bindAddress = getBindAddress();
  await new Promise((resolve7, reject) => {
    const handleError = (error) => {
      server.off("error", handleError);
      if (error.code === "EADDRINUSE") {
        reject(
          new Error(
            `Port ${port} is already in use. Another process is occupying this port. Please terminate the process or try again later.`
          )
        );
        return;
      }
      reject(error);
    };
    server.once("error", handleError);
    server.listen(port, bindAddress, () => {
      server.off("error", handleError);
      resolve7();
    });
  });
  server.on("error", (error) => {
    rejectCallback(error instanceof Error ? error : new Error(String(error)));
  });
  return {
    waitForCallback: () => callbackPromise,
    close: () => new Promise((resolve7, reject) => {
      server.close((error) => {
        if (error && error.code !== "ERR_SERVER_NOT_RUNNING") {
          reject(error);
          return;
        }
        if (!settled) {
          rejectCallback(new Error("OAuth listener closed before callback"));
        }
        resolve7();
      });
    })
  };
}

// src/cli.ts
var HELP = `Usage: antigravity-auth <command> [options]

Commands:
  login [--project <id>] [--no-browser]
  list [--json]
  quota [--json] [--refresh]
  init
  migrate --offline [--yes]
  rollback --offline [--yes]

migrate moves the account file into the account store; rollback restores
it. Both require --offline: stop every OpenCode and Antigravity process
first. Without --yes you are asked to confirm.

Options:
  --help  Show help
`;
function parseArgs(argv) {
  const [command, ...args] = argv;
  if (command === "--help") {
    return args.length === 0 ? { ok: true, value: { command: "help" } } : { ok: false, error: `Unknown argument: ${args[0]}` };
  }
  if (!command) return { ok: false, error: "Missing command" };
  if (command === "login") {
    let projectId;
    let noBrowser = false;
    for (let index = 0; index < args.length; index += 1) {
      const arg = args[index];
      if (arg === "--no-browser") {
        noBrowser = true;
        continue;
      }
      if (arg === "--project") {
        const value = args[index + 1];
        if (!value || value.startsWith("--")) {
          return { ok: false, error: "Missing value for --project" };
        }
        projectId = value;
        index += 1;
        continue;
      }
      return { ok: false, error: `Unknown option for login: ${arg}` };
    }
    return { ok: true, value: { command, projectId, noBrowser } };
  }
  if (command === "list") {
    let json = false;
    for (const arg of args) {
      if (arg === "--json") json = true;
      else return { ok: false, error: `Unknown option for list: ${arg}` };
    }
    return { ok: true, value: { command, json } };
  }
  if (command === "quota") {
    let json = false;
    let refresh = false;
    for (const arg of args) {
      if (arg === "--json") json = true;
      else if (arg === "--refresh") refresh = true;
      else return { ok: false, error: `Unknown option for quota: ${arg}` };
    }
    return { ok: true, value: { command, json, refresh } };
  }
  if (command === "init") {
    if (args.length > 0)
      return { ok: false, error: `Unknown option for init: ${args[0]}` };
    return { ok: true, value: { command } };
  }
  if (command === "migrate" || command === "rollback") {
    let offline = false;
    let confirmed = false;
    for (const arg of args) {
      if (arg === "--offline") offline = true;
      else if (arg === "--yes") confirmed = true;
      else return { ok: false, error: `Unknown option for ${command}: ${arg}` };
    }
    if (!offline) {
      return {
        ok: false,
        error: `${command} runs only offline: stop every OpenCode and Antigravity process, then pass --offline`
      };
    }
    return { ok: true, value: { command, confirmed } };
  }
  return { ok: false, error: `Unknown command: ${command}` };
}
function describeOutcome(operation, outcome) {
  if (outcome.status === "pending") {
    return {
      code: 1,
      text: `${operation} did not finish (${outcome.reason}); another process holds the account store. Stop it and run the command again.
`
    };
  }
  const receipt2 = outcome.receipt;
  const lines = [
    `${operation} completed: generation ${receipt2.id} is ${receipt2.status}.`,
    `Account store: ${receipt2.storeDir}`,
    ...receipt2.restartRequired ? ["Restart OpenCode before using Antigravity accounts."] : []
  ];
  return { code: 0, text: `${lines.join("\n")}
` };
}
function accountStatus(account) {
  if (account.enabled === false) return "disabled";
  if (account.accountIneligible) return "ineligible";
  if (account.verificationRequired) return "verification-required";
  return "active";
}
function accountSummary(storage) {
  return {
    accounts: (storage?.accounts ?? []).map((account, index) => ({
      index: index + 1,
      email: account.email ?? `Account ${index + 1}`,
      status: accountStatus(account)
    }))
  };
}
function formatTable(headers, rows) {
  const widths = headers.map(
    (header, column) => Math.max(header.length, ...rows.map((row) => row[column]?.length ?? 0))
  );
  const formatRow = (row) => row.map(
    (value, column) => column === row.length - 1 ? value : value.padEnd((widths[column] ?? value.length) + 2)
  ).join("");
  return `${[formatRow(headers), ...rows.map(formatRow)].join("\n")}
`;
}
function quotaSummary(results) {
  return {
    accounts: results.map((result) => ({
      index: result.index + 1,
      email: result.email ?? `Account ${result.index + 1}`,
      status: result.status,
      ...result.error ? { error: result.error } : {},
      groups: Object.entries(result.quota?.groups ?? {}).map(
        ([name, group]) => ({
          name,
          ...typeof group.remainingFraction === "number" ? { remainingPercent: group.remainingFraction * 100 } : {},
          ...group.resetTime ? { resetTime: group.resetTime } : {}
        })
      )
    }))
  };
}
function formatQuotaTable(results) {
  const rows = [];
  for (const account of quotaSummary(results).accounts) {
    if (account.groups.length === 0) {
      rows.push([account.email, account.status, "-", "-", account.error ?? "-"]);
      continue;
    }
    for (const group of account.groups) {
      rows.push([
        account.email,
        account.status,
        group.name,
        group.remainingPercent === void 0 ? "-" : `${group.remainingPercent}%`,
        group.resetTime ?? "-"
      ]);
    }
  }
  return formatTable(["ACCOUNT", "STATUS", "GROUP", "REMAINING", "RESET"], rows);
}
async function runCli(argv, deps) {
  const parsed = parseArgs(argv);
  if (!parsed.ok) {
    deps.stderr.write(`${parsed.error}
`);
    return 2;
  }
  if (parsed.value.command === "help") {
    deps.stdout.write(HELP);
    return 0;
  }
  try {
    if (parsed.value.command === "init") {
      const legacyPath = deps.accountStore.legacyPath();
      const outcome = await deps.accountStore.initialize(legacyPath);
      const result = describeOutcome("Initialization", outcome);
      (result.code === 0 ? deps.stdout : deps.stderr).write(result.text);
      return result.code;
    }
    if (parsed.value.command === "migrate" || parsed.value.command === "rollback") {
      const operation = parsed.value.command;
      if (!parsed.value.confirmed) {
        const answer = await deps.prompt(
          `${operation === "migrate" ? "Migrate" : "Roll back"} the Antigravity account store? Every OpenCode and Antigravity process must be stopped. Type "yes" to continue: `
        );
        if (answer.trim().toLowerCase() !== "yes") {
          deps.stderr.write(`${operation} cancelled; nothing was changed.
`);
          return 1;
        }
      }
      const legacyPath = deps.accountStore.legacyPath();
      const outcome = operation === "migrate" ? await deps.accountStore.migrate(legacyPath) : await deps.accountStore.rollback(legacyPath);
      const result = describeOutcome(
        operation === "migrate" ? "Migration" : "Rollback",
        outcome
      );
      (result.code === 0 ? deps.stdout : deps.stderr).write(result.text);
      return result.code;
    }
    if (parsed.value.command === "login") {
      const result = await deps.performLogin(
        {
          projectId: parsed.value.projectId,
          noBrowser: parsed.value.noBrowser,
          isHeadless: deps.isHeadless?.() ?? false,
          refreshAccountIndex: void 0,
          accounts: [],
          startFresh: true
        },
        deps.openBrowser
      );
      deps.stdout.write(
        `Authenticated ${result.email ?? "Antigravity account"}
`
      );
      return 0;
    }
    const source = await deps.accountStore.read(deps.accountStore.legacyPath());
    if (source.kind === "unavailable") {
      deps.stderr.write(`Accounts are unavailable: ${source.reason}
`);
      return 1;
    }
    const storage = source.kind === "legacy" ? await deps.loadAccounts() : source.kind === "store" ? { version: 4, accounts: source.accounts, activeIndex: 0 } : null;
    if (parsed.value.command === "list") {
      const summary = accountSummary(storage);
      deps.stdout.write(
        parsed.value.json ? `${JSON.stringify(summary)}
` : formatTable(
          ["INDEX", "EMAIL", "STATUS"],
          summary.accounts.map((account) => [
            String(account.index),
            account.email,
            account.status
          ])
        )
      );
      return 0;
    }
    const results = await deps.getQuota(storage?.accounts ?? [], {
      refresh: parsed.value.refresh
    });
    deps.stdout.write(
      parsed.value.json ? `${JSON.stringify(quotaSummary(results))}
` : formatQuotaTable(results)
    );
    return 0;
  } catch (error) {
    deps.stderr.write(
      `${error instanceof Error ? error.message : String(error)}
`
    );
    return 1;
  }
}
var execFileAsync = promisify(execFile);
async function openBrowserDefault(url) {
  if (process.platform === "win32") {
    const overrideBrowser = process.env.ANTIGRAVITY_BROWSER;
    if (overrideBrowser) {
      try {
        await execFileAsync(overrideBrowser, [url]);
        return;
      } catch {}
    }
    const command = `Start-Process '${url.replaceAll("'", "''")}'`;
    await execFileAsync("powershell.exe", [
      "-NoProfile",
      "-NonInteractive",
      "-WindowStyle",
      "Hidden",
      "-EncodedCommand",
      Buffer.from(command, "utf16le").toString("base64")
    ]);
    return;
  }
  await execFileAsync(process.platform === "darwin" ? "open" : "xdg-open", [
    url
  ]);
}
function createDefaultCliDependencies() {
  return {
    stdout: process.stdout,
    stderr: process.stderr,
    prompt: async (message) => {
      const readline = createInterface({
        input: process.stdin,
        output: process.stdout
      });
      try {
        return (await readline.question(message)).trim();
      } finally {
        readline.close();
      }
    },
    openBrowser: openBrowserDefault,
    isHeadless: () => Boolean(
      process.env.SSH_CONNECTION || process.env.SSH_CLIENT || process.env.SSH_TTY || process.env.OPENCODE_HEADLESS
    ),
    performLogin: async (request, openBrowser) => performOAuthLogin(request, {
      authorize: authorizeAntigravity,
      exchange: exchangeAntigravity,
      startListener: startOAuthListener,
      openBrowser,
      upsert: async (result) => {
        const legacyPath = resolve6(getStoragePath());
        const modules = await loadCommonAuthStoreModules();
        const admission = await readAccountStoreBinding(legacyPath, modules, Date.now);
        if (admission.status === "bound") {
          const repository = createAccountRepositoryFactory(modules)({
            paths: admission.paths,
            now: Date.now,
            exchange: async ({ refreshToken }) => {
              const res = await refreshAntigravityToken(refreshToken);
              return {
                accessToken: res.access,
                refreshToken: res.refresh,
                expiresAt: res.expires
              };
            }
          });
          try {
            const read = await repository.read();
            const parts = parseRefreshParts(result.refresh);
            const now = Date.now();
            const existingRow = read.status === "ready" ? read.rows.find(
              (r) => r.metadata?.status === "present" && r.metadata.metadata?.email === result.email
            ) : void 0;
            if (existingRow) {
              await repository.replaceCredential(existingRow.ref, {
                refreshToken: parts.refreshToken,
                metadata: {
                  addedAt: now,
                  lastUsed: now,
                  ...(result.email !== void 0 ? { email: result.email } : {}),
                  ...(result.label !== void 0 ? { label: result.label } : {}),
                  ...(parts.projectId !== void 0 ? { projectId: parts.projectId } : {}),
                  ...(parts.managedProjectId !== void 0 ? { managedProjectId: parts.managedProjectId } : {})
                },
                disabled: "keep"
              });
            } else {
              await repository.login({
                id: randomUUID(),
                refreshToken: parts.refreshToken,
                metadata: {
                  addedAt: now,
                  lastUsed: now,
                  enabled: true,
                  ...(result.email !== void 0 ? { email: result.email } : {}),
                  ...(result.label !== void 0 ? { label: result.label } : {}),
                  ...(parts.projectId !== void 0 ? { projectId: parts.projectId } : {}),
                  ...(parts.managedProjectId !== void 0 ? { managedProjectId: parts.managedProjectId } : {})
                }
              });
            }
            return;
          } finally {
            await repository.dispose();
          }
        }
        await persistAccountPool(
          [result],
          false
        );
      }
    }),
    loadAccounts,
    getQuota: (accounts, options) => checkAccountsQuotaStandalone(accounts, options),
    accountStore: createDefaultAccountStoreOperations()
  };
}
function present(value) {
  return value === null ? void 0 : value;
}
function cliAccountOf(row) {
  const metadata = row.metadata.status === "present" ? row.metadata.metadata : void 0;
  const groups = row.quota.status === "present" ? row.quota.quota.cachedQuota : void 0;
  const cachedQuota = {};
  for (const [name, group] of Object.entries(groups ?? {})) {
    cachedQuota[name] = {
      modelCount: group.modelCount,
      ...typeof group.remainingFraction === "number" ? { remainingFraction: group.remainingFraction } : {},
      ...typeof group.resetTime === "string" ? { resetTime: group.resetTime } : {}
    };
  }
  const email = present(metadata?.email);
  const projectId = present(metadata?.projectId);
  const managedProjectId = present(metadata?.managedProjectId);
  return {
    refreshToken: row.credential?.refreshToken ?? "",
    addedAt: metadata?.addedAt ?? row.storeAddedAt ?? 0,
    lastUsed: metadata?.lastUsed ?? 0,
    enabled: row.enabled,
    ...email !== void 0 ? { email } : {},
    ...projectId !== void 0 ? { projectId } : {},
    ...managedProjectId !== void 0 ? { managedProjectId } : {},
    ...metadata?.verificationRequired === true ? { verificationRequired: true } : {},
    ...metadata?.accountIneligible === true ? { accountIneligible: true } : {},
    ...Object.keys(cachedQuota).length > 0 ? { cachedQuota } : {}
  };
}
async function readAccountStore(legacyPath) {
  const modules = await loadCommonAuthStoreModules();
  const admission = await readAccountStoreBinding(legacyPath, modules, Date.now);
  switch (admission.status) {
    case "initialization-required":
      return { kind: "uninitialized" };
    case "inactive":
      return { kind: "legacy" };
    case "pending":
      return admission.operation === void 0 ? { kind: "legacy" } : {
        kind: "unavailable",
        reason: `an account-store ${admission.operation} is unfinished; run \`antigravity-auth ${admission.operation} --offline\` again`
      };
    case "error":
      return { kind: "unavailable", reason: admission.reason };
    case "bound":
      break;
  }
  const repository = createAccountRepositoryFactory(modules)({
    paths: admission.paths,
    now: Date.now,
    exchange: async ({ refreshToken }) => {
      const result = await refreshAntigravityToken(refreshToken);
      return {
        accessToken: result.access,
        refreshToken: result.refresh,
        expiresAt: result.expires
      };
    }
  });
  try {
    const read = await repository.read();
    if (read.status !== "ready") {
      return {
        kind: "unavailable",
        reason: `the account store is ${read.status}`
      };
    }
    return { kind: "store", accounts: read.rows.map(cliAccountOf) };
  } finally {
    await repository.dispose();
  }
}
function createDefaultAccountStoreOperations() {
  const offline = { processesStopped: true };
  return {
    legacyPath: () => resolve6(getStoragePath()),
    migrate: async (legacyPath) => createAccountMigrationFactory(await loadCommonAuthStoreModules())({
      legacyPath,
      offline,
      now: Date.now
    }),
    rollback: async (legacyPath) => createAccountRollbackFactory(await loadCommonAuthStoreModules())({
      legacyPath,
      offline,
      now: Date.now
    }),
    initialize: async (legacyPath) => initializeFreshAccountStore(await loadCommonAuthStoreModules(), {
      legacyPath,
      now: Date.now
    }),
    read: readAccountStore
  };
}
if (import.meta.main || (typeof process !== "undefined" && process.argv && process.argv[1])) {
  process.exitCode = await runCli(
    process.argv.slice(2),
    createDefaultCliDependencies()
  );
}
export {
  cliAccountOf,
  createDefaultAccountStoreOperations,
  createDefaultCliDependencies,
  performOAuthLogin,
  runCli
};
//# sourceMappingURL=cli.js.map
