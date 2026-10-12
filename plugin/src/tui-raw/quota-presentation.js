import {
  formatQuota,
  NO_QUOTA_READING,
  quotaTextParts,
  quotaWindowName
} from "./common-auth-embedded/quota/index.js";

export { NO_QUOTA_READING };
function projectReading(label, reading) {
  const checkedAt = reading?.checkedAt;
  if (!reading || typeof checkedAt !== "number" || !Number.isFinite(checkedAt) || checkedAt < 0 || !Number.isFinite(reading.remainingPercent))
    return;
  return { scope: "all", limits: [{
    scope: reading.window ? "all" : label,
    label,
    kind: "reading",
    checkedAt,
    remainingPercent: Math.max(0, Math.min(100, reading.remainingPercent)),
    ...reading.window ? { windowMinutes: reading.window === "weekly" ? 10080 : 300 } : {},
    ...typeof reading.resetAt === "number" && Number.isFinite(reading.resetAt) && Math.abs(reading.resetAt) <= 8640000000000000 ? { resetsAt: new Date(reading.resetAt).toISOString() } : {}
  }], checkedAt };
}
export function formatQuotaReading(label, reading, now) {
  return formatQuota(projectReading(label, reading), { now });
}
export function quotaReadingParts(label, reading, now) {
  const projected = projectReading(label, reading), limit = projected?.limits[0];
  if (!limit)
    return {
      name: label,
      figure: NO_QUOTA_READING,
      detail: "",
      remaining: null
    };
  const full = quotaTextParts(projected, { now }), compact = quotaTextParts(projected, { now, form: "compact" }), name = quotaWindowName(limit), first = compact[0] ?? "", figure = first.startsWith(`${name} `) ? first.slice(name.length + 1) : first, reset = (full[0] ?? "").slice(first.length).replace(/^, /, "");
  return {
    name,
    figure,
    detail: [reset, ...full.slice(1)].filter(Boolean).join(" \xB7 "),
    remaining: limit.remainingPercent ?? null
  };
}
