import { formatQuota, NO_QUOTA_READING, quotaTextParts, quotaWindowName, } from './common-auth-embedded/quota/index.js';
export { NO_QUOTA_READING };
function projectReading(label, reading) {
    const checkedAt = reading?.checkedAt;
    if (!reading ||
        typeof checkedAt !== 'number' ||
        !Number.isFinite(checkedAt) ||
        checkedAt < 0 ||
        !Number.isFinite(reading.remainingPercent))
        return undefined;
    const limit = {
        scope: reading.window ? 'all' : label,
        label,
        kind: 'reading',
        checkedAt,
        remainingPercent: Math.max(0, Math.min(100, reading.remainingPercent)),
        ...(reading.window
            ? { windowMinutes: reading.window === 'weekly' ? 7 * 24 * 60 : 5 * 60 }
            : {}),
        ...(typeof reading.resetAt === 'number' &&
            Number.isFinite(reading.resetAt) &&
            Math.abs(reading.resetAt) <= 8.64e15
            ? { resetsAt: new Date(reading.resetAt).toISOString() }
            : {}),
    };
    return { scope: 'all', limits: [limit], checkedAt };
}
/** A quota figure needs its own read timestamp; snapshot writes never supply one. */
export function formatQuotaReading(label, reading, now) {
    return formatQuota(projectReading(label, reading), { now });
}
/** Use common-auth's formatQuota text for a bar row without separately formatting figures, resets or ages. */
export function quotaReadingParts(label, reading, now) {
    const projected = projectReading(label, reading);
    const limit = projected?.limits[0];
    if (!limit)
        return {
            name: label,
            figure: NO_QUOTA_READING,
            detail: '',
            remaining: null,
        };
    const full = quotaTextParts(projected, { now });
    const compact = quotaTextParts(projected, { now, form: 'compact' });
    const name = quotaWindowName(limit);
    const first = compact[0] ?? '';
    const figure = first.startsWith(`${name} `)
        ? first.slice(name.length + 1)
        : first;
    const reset = (full[0] ?? '').slice(first.length).replace(/^, /, '');
    return {
        name,
        figure,
        detail: [reset, ...full.slice(1)].filter(Boolean).join(' · '),
        remaining: limit.remainingPercent ?? null,
    };
}
//# sourceMappingURL=quota-presentation.js.map