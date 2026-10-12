import { quotaReadingParts } from './quota-presentation';
export const QUOTA_POOL_LABELS = {
    gemini: 'Gm',
    'non-gemini': 'NG',
};
const POOL_ORDER = ['gemini', 'non-gemini'];
function clamp(value) {
    if (!Number.isFinite(value))
        return 0;
    return Math.min(100, Math.max(0, value));
}
/** Remaining-percent tone: low remaining is a warning, near-empty an error. */
export function remainingTone(remaining) {
    if (remaining === null)
        return 'muted';
    if (remaining <= 10)
        return 'err';
    if (remaining <= 30)
        return 'warn';
    return 'ok';
}
/** `12m`, `3h20m`, `2d4h`; `now` once passed; empty without a reset time. */
export function formatResetIn(resetAt, now) {
    if (!resetAt)
        return '';
    const ms = resetAt - now;
    if (ms <= 0)
        return 'now';
    const mins = Math.floor(ms / 60_000);
    if (mins < 60)
        return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) {
        const rm = mins % 60;
        return rm > 0 ? `${hrs}h${rm}m` : `${hrs}h`;
    }
    const days = Math.floor(hrs / 24);
    const rh = hrs % 24;
    return rh > 0 ? `${days}d${rh}h` : `${days}d`;
}
/** `45s`, `3m`, `3m 20s`. */
export function formatWait(ms) {
    const seconds = Math.ceil(ms / 1000);
    if (seconds < 60)
        return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remaining = seconds % 60;
    return remaining > 0 ? `${minutes}m ${remaining}s` : `${minutes}m`;
}
function quotaRows(account, now) {
    const rows = [];
    for (const key of POOL_ORDER) {
        const entry = account.quota[key];
        const label = QUOTA_POOL_LABELS[key];
        if (!entry) {
            rows.push({
                label,
                remaining: null,
                figure: quotaReadingParts(label, undefined, now).figure,
                tone: 'muted',
                reset: '',
            });
            continue;
        }
        const windows = entry.windows ?? [];
        if (windows.length === 0) {
            const parts = quotaReadingParts(label, entry, now);
            rows.push({
                label,
                remaining: parts.remaining,
                figure: parts.figure,
                tone: remainingTone(parts.remaining),
                reset: parts.detail,
            });
            continue;
        }
        for (const window of windows) {
            const parts = quotaReadingParts(label, window, now);
            rows.push({
                label: `${label} ${parts.name}`,
                remaining: parts.remaining,
                figure: parts.figure,
                tone: remainingTone(parts.remaining),
                reset: parts.detail,
            });
        }
    }
    return rows;
}
/**
 * Status word, first match wins: `off` when disabled, `cooling` while a
 * cooldown runs, `active` for the current account, `idle` otherwise.
 */
export function projectAccount(account, now) {
    const cooling = typeof account.cooldownUntil === 'number' && account.cooldownUntil > now;
    const status = !account.enabled
        ? 'off'
        : cooling
            ? 'cooling'
            : account.current
                ? 'active'
                : 'idle';
    const statusTone = status === 'off'
        ? 'muted'
        : status === 'cooling'
            ? 'warn'
            : status === 'active'
                ? 'ok'
                : 'muted';
    const base = `health ${Math.round(clamp(account.health))}`;
    const health = cooling
        ? `${base} · cooling ${formatWait(account.cooldownUntil - now)}`
        : base;
    return {
        id: account.id,
        label: account.label,
        status,
        statusTone,
        quota: quotaRows(account, now),
        health,
    };
}
/** The whole sidebar body for one state reading. */
export function projectSidebar(input) {
    const accounts = input.accounts.map((account) => projectAccount(account, input.now));
    let route = null;
    if (input.route) {
        const target = input.accounts.find((account) => account.id === input.route?.accountId);
        route = [
            target?.label ?? 'unknown account',
            input.route.modelFamily,
            input.route.headerStyle,
        ].join(' · ');
    }
    const notices = [];
    if (input.status.quotaBackoffUntil !== null &&
        input.status.quotaBackoffUntil > input.now) {
        notices.push(`quota checks paused ${formatWait(input.status.quotaBackoffUntil - input.now)}`);
    }
    if (input.status.checkedAt === null)
        notices.push('quota not checked yet');
    if (accounts.length === 0)
        notices.push('no accounts');
    return { accounts, route, notices };
}
//# sourceMappingURL=sidebar-projection.js.map