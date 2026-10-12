import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "@opentui/solid/jsx-runtime";
/** @jsxImportSource @opentui/solid */
/**
 * Read-only OpenTUI sidebar for the Antigravity plugin.
 *
 * Mirrors the fleet sibling layout (see `anthropic-auth-live` /
 * `openai-auth-live` `packages/opencode/src/tui.tsx`): a single bordered
 * column with a labelled header badge, a Quota section that lists one
 * `AccountBlock` per visible account, a Routing section that surfaces the
 * most recent session route, and a Health section that only appears when
 * something is wrong. The Antigravity data model is richer than the
 * Claude/Codex one (per-account Gemini + Non-Gemini quota pools, a health
 * score, and per-session routing decisions), so the fleet components are
 * adapted rather than copied verbatim:
 *
 * - `QuotaRow` reads `remainingPercent + resetAt` from the Antigravity
 *   `SidebarQuotaEntry` shape and colors via `quotaTone` (remaining
 *   threshold) instead of `usageTone` (used threshold).
 * - `AccountBlock` derives its status word (`active` / `idle` /
 *   `cooling` / `off` / `blocked`) from the Antigravity account state and
 *   surfaces health as a muted secondary line rather than a top-level
 *   bar — fleet parity for "Quota first, health second".
 * - `Routing` resolves to a single `Route` `StatRow` carrying the most
 *   recent `activeRouting` entry, since Antigravity does not maintain a
 *   per-session sidebar state alongside the slot-rendered tree.
 *
 * Hard rules for this file:
 *
 * - NO direct writes to the host terminal anywhere in the render path.
 *   The host terminal is the frame buffer; one stray byte corrupts every
 *   subsequent cell. Errors flow through `createTuiFileLogger()`.
 * - NO imports from `./plugin/storage`, `./plugin/accounts`, OAuth code,
 *   or anything that touches tokens.
 * - The component uses Solid's `onCleanup` to release the polling timer
 *   on unmount so a route change can never leak an interval.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createSlot } from '@opentui/solid';
import { createSignal, For, onCleanup, onMount, Show } from 'solid-js';
import { formatQuotaReading, quotaReadingParts } from './quota-presentation';
import { getRpcDir } from './rpc/rpc-dir';
import { readSidebarState, } from './sidebar-state';
import { createTuiFileLogger } from './tui/file-logger';
import { createV1MenuTransport, dispatchV1Notification, } from './tui/host-v1';
import { computeEffectiveOrder, DEFAULT_PREFS, DEFAULT_SLOT_ORDER, PLUGIN_KEY, queueTuiPreferenceUpdate, readTuiPreferencesFile, resolveAntigravityAuthPrefs, watchTuiPreferences, } from './tui-preferences';
const ID = 'cortexkit.antigravity-auth';
const POLL_INTERVAL_MS = 2000;
const RPC_POLL_MS = 500;
const SINGLE_BORDER = { type: 'single' };
// Read package metadata from either the raw src/ entry or its generated
// src/tui-compiled/ counterpart. Avoid a JSON import because package.json sits
// outside the declaration build's rootDir.
const PLUGIN_VERSION = (() => {
    const here = dirname(fileURLToPath(import.meta.url));
    for (const packageFile of [
        join(here, '..', 'package.json'),
        join(here, '..', '..', 'package.json'),
    ]) {
        try {
            const raw = readFileSync(packageFile, 'utf8');
            const version = JSON.parse(raw).version;
            if (version)
                return version;
        }
        catch {
            // Try the path for the other TUI entry layout.
        }
    }
    return '';
})();
// Module-scoped state — TEST ISOLATION CONTRACT:
//
// `rpcPollStarted`, notification cursor/deduplication state, `rpcInFlight`, and the lazy
// `sidebarController` below persist across tests via the cached ES
// module Bun loads once per `--isolate` file. Tests must NOT assert
// fresh-process behaviour from these variables — by the time the first
// `startRpcNotificationPolling` runs, all four carry stale values from
// prior tests in the same file. Test isolation comes from:
//   1. fresh-importing `tui.tsx` via a cache-busted dynamic `import`
//      so the module re-evaluates with fresh module-scoped bindings, and
//   2. constructing a fresh `SidebarController` via
//      `createSidebarController(prefs)` and passing it through
//      `SidebarPanel.props.controller` — never through
//      `getSidebarController()`, which lazily seeds the module-scoped
//      singleton.
let rpcPollStarted = false;
const notificationCursorBySession = new Map();
const dispatchedNotificationIds = new Set();
let rpcInFlight = false;
const GLOBAL_NOTIFICATION_CURSOR = '__global__';
const MAX_NOTIFICATION_CURSORS = 256;
const QUOTA_LABELS = {
    gemini: 'Gm',
    'non-gemini': 'NG',
};
const QUOTA_ORDER = ['gemini', 'non-gemini'];
const WINDOW_GUTTER = {
    weekly: '7d',
    '5h': '5h',
};
const FALLBACK_THEME = {
    primary: '#3b82f6',
    secondary: '#a855f7',
    accent: '#7c3aed',
    error: '#ef4444',
    warning: '#eab308',
    success: '#22c55e',
    info: '#0ea5e9',
    text: '#e5e7eb',
    textMuted: '#6b7280',
    selectedListItemText: '#ffffff',
    background: '#0b0d12',
    backgroundPanel: '#11131a',
    backgroundElement: '#1a1d27',
    backgroundMenu: '#1a1d27',
    border: '#2a2d3a',
    borderActive: '#7c3aed',
    borderSubtle: '#2a2d3a',
    diffAdded: '#22c55e',
    diffRemoved: '#ef4444',
    diffContext: '#6b7280',
    diffHunkHeader: '#7c3aed',
    diffHighlightAdded: '#166534',
    diffHighlightRemoved: '#7f1d1d',
    diffAddedBg: '#0a1f12',
    diffRemovedBg: '#1f0a0a',
    diffContextBg: '#0b0d12',
    diffLineNumber: '#4b5563',
    diffAddedLineNumberBg: '#0a1f12',
    diffRemovedLineNumberBg: '#1f0a0a',
    markdownText: '#e5e7eb',
    markdownHeading: '#7c3aed',
    markdownLink: '#3b82f6',
    markdownLinkText: '#60a5fa',
    markdownCode: '#22c55e',
    markdownBlockQuote: '#6b7280',
    markdownEmph: '#eab308',
    markdownStrong: '#7c3aed',
    markdownHorizontalRule: '#2a2d3a',
    markdownListItem: '#7c3aed',
    markdownListEnumeration: '#a855f7',
    markdownImage: '#3b82f6',
    markdownImageText: '#60a5fa',
    markdownCodeBlock: '#11131a',
    syntaxComment: '#6b7280',
    syntaxKeyword: '#a855f7',
    syntaxFunction: '#3b82f6',
    syntaxVariable: '#e5e7eb',
    syntaxString: '#22c55e',
    syntaxNumber: '#eab308',
    syntaxType: '#7c3aed',
    syntaxOperator: '#e5e7eb',
    syntaxPunctuation: '#6b7280',
    thinkingOpacity: 0.6,
};
// Mirror the fleet siblings' tone chain: every tone falls through to a
// sibling token, so a sparse custom theme still renders readably.
function toneColor(theme, tone) {
    switch (tone) {
        case 'ok':
            return theme.success ?? theme.accent;
        case 'warn':
            return theme.warning ?? theme.accent;
        case 'err':
            return theme.error ?? theme.accent;
        case 'muted':
            return theme.textMuted ?? theme.text;
        case 'accent':
            return theme.accent ?? theme.text;
        default:
            return theme.text;
    }
}
function quotaTone(usedPct, appearance) {
    if (usedPct < appearance.warnThreshold)
        return 'ok';
    if (usedPct < appearance.errorThreshold)
        return 'warn';
    return 'err';
}
function quotaBarSegments(remainingPct, appearance) {
    const width = appearance.barWidth;
    const usedCells = Math.max(0, Math.min(Math.round((remainingPct / 100) * width), width));
    const tone = quotaTone(100 - remainingPct, appearance);
    return [
        { text: appearance.barFilledChar.repeat(usedCells), tone },
        { text: appearance.barEmptyChar.repeat(width - usedCells), tone },
    ].filter((segment) => segment.text.length > 0);
}
const EMPTY_STATE = {
    version: 1,
    checkedAt: 0,
    accounts: [],
    activeRouting: {},
    routingAuthoritative: false,
};
function resolveLogger(logger) {
    if (logger)
        return logger;
    try {
        return createTuiFileLogger();
    }
    catch {
        // Fall back to a stub that drops everything — the sidebar must still
        // render even if file logging cannot be initialized.
        return noopLogger();
    }
}
function noopLogger() {
    const drop = () => undefined;
    return {
        debug: drop,
        info: drop,
        warn: drop,
        error: drop,
        getLogPath: () => undefined,
    };
}
// Module-scoped controller singleton, initialized at plugin startup. The
// watcher is intentionally never disposed — collapse/prefs state survives
// sidebar remounts (route changes) for the lifetime of the TUI process,
// mirroring the fleet siblings.
//
// TEST ISOLATION: this singleton, like `rpcPollStarted` above, persists
// across tests via the cached ES module. Tests construct a controller
// via `createSidebarController(prefs)` and pass it through
// `SidebarPanel.props.controller` — they MUST NOT rely on this lazy
// singleton for isolation. See the block above for the full contract.
let sidebarController = null;
// The TUI may unmount and remount sidebar_content when the user switches
// views. A remount re-runs the component body, so any signal created inside
// the component would reset to its seed. The controller lives in the plugin
// closure (process lifetime) and owns the durable prefs/collapse signals
// plus the single shared watcher subscription, so collapse and live pref
// reloads survive the remount.
//
// Exported so tests can construct a controller with a controlled initial
// prefs snapshot without touching the module-scoped singleton.
export function createSidebarController(initialPrefs) {
    const [prefs, setPrefs] = createSignal(initialPrefs);
    const seedCollapsed = initialPrefs.rememberCollapsed && initialPrefs.collapsed != null
        ? initialPrefs.collapsed
        : initialPrefs.startCollapsed;
    const [collapsed, setCollapsed] = createSignal(seedCollapsed);
    let lastPersistedCollapsed = initialPrefs.collapsed;
    let lastApplied = JSON.stringify(initialPrefs);
    // The watcher lives for the plugin/process lifetime — it is intentionally
    // never disposed. Collapse guard mirrors the race-fix in toggleCollapsed:
    // lastPersistedCollapsed is advanced only once our own write lands, so
    // watcher echoes of the previous persisted value are rejected by the
    // `!==` check and cannot revert a user click.
    watchTuiPreferences(() => {
        void (async () => {
            const next = resolveAntigravityAuthPrefs(await readTuiPreferencesFile());
            const serialized = JSON.stringify(next);
            if (serialized === lastApplied)
                return;
            lastApplied = serialized;
            setPrefs(next);
            if (next.rememberCollapsed &&
                next.collapsed != null &&
                next.collapsed !== lastPersistedCollapsed) {
                lastPersistedCollapsed = next.collapsed;
                setCollapsed(next.collapsed);
            }
        })();
    });
    function toggleCollapsed() {
        const next = !collapsed();
        setCollapsed(next);
        if (prefs().rememberCollapsed) {
            void queueTuiPreferenceUpdate(PLUGIN_KEY, ['collapsed'], next).then(() => {
                lastPersistedCollapsed = next;
            });
        }
    }
    return { prefs, collapsed, toggleCollapsed };
}
// Lazy module-scoped accessor used by the plugin entry. Tests should NOT go
// through this — they construct their own controller via createSidebarController
// and pass it via SidebarPanelProps.controller.
function getSidebarController() {
    if (!sidebarController) {
        sidebarController = createSidebarController(DEFAULT_PREFS);
    }
    return sidebarController;
}
// --- Shared helpers (fleet shape, antigravity data) ------------------------
function clamp(value, min, max) {
    if (value < min)
        return min;
    if (value > max)
        return max;
    return value;
}
// Render a "reset in Nm/Nh/NdNh" string from an epoch-ms reset time.
// Empty string when no resetAt is cached. The fleet's `formatResetIn`
// reads ISO strings; Antigravity persists resetAt as a numeric epoch, so
// the wrapper adapts to that without changing the shape of the output.
function formatResetIn(resetAt, now) {
    if (!resetAt)
        return '';
    const ms = resetAt - now();
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
function formatError(value) {
    if (value instanceof Error)
        return value.message;
    try {
        return JSON.stringify(value);
    }
    catch {
        return String(value);
    }
}
// --- Fleet components (adapted to antigravity data) ------------------------
// Section header — fleet pattern: bold title, themed text color, top margin
// for vertical breathing room between sections.
function SectionHeader(props) {
    return (_jsx("box", { width: '100%', marginTop: 1, children: _jsx("text", { fg: toneColor(props.theme(), 'text'), children: _jsx("b", { children: props.title }) }) }));
}
// Fleet StatRow: muted label left, value (optionally tone-tinted, bold)
// right. Mirrors the layout the Claude/Codex sidebars use for routing
// rows, plan rows, and "resets N" rows.
function StatRow(props) {
    return (_jsxs("box", { width: '100%', flexDirection: 'row', justifyContent: 'space-between', children: [_jsx("text", { fg: props.theme().textMuted, children: props.label }), _jsx("text", { fg: toneColor(props.theme(), props.tone ?? 'text'), children: _jsx("b", { children: props.value }) })] }));
}
// Fleet CollapsedRow: muted label left, caller-supplied value right. Used
// for the collapsed sidebar view; the Antigravity adapter renders one
// CollapsedRow per visible account (Claude's sibling collapses to a
// single primary-quota line, but Antigravity's multi-quota model fits a
// per-account row better when the sidebar is collapsed).
function CollapsedRow(props) {
    return (_jsxs("box", { width: '100%', flexDirection: 'row', justifyContent: 'space-between', children: [_jsx("text", { fg: props.theme().textMuted, children: props.label }), props.children] }));
}
// The bar fills with remaining quota. The shared formatter supplies the
// figure, reset and reading age; the right column aligns reset and age text.
function QuotaRow(props) {
    const parts = () => quotaReadingParts(props.label, props.entry, props.now());
    const remaining = () => parts().remaining;
    const reset = () => parts().detail;
    return (_jsx(Show, { when: remaining() != null, fallback: _jsxs("box", { width: '100%', flexDirection: 'row', justifyContent: 'space-between', children: [_jsx("text", { fg: props.theme().textMuted, children: props.label.padEnd(5) }), _jsx("text", { fg: props.theme().textMuted, children: parts().figure })] }), children: _jsxs("box", { width: '100%', flexDirection: 'row', justifyContent: 'space-between', children: [_jsxs("box", { flexDirection: 'row', children: [_jsx("text", { width: 5, flexShrink: 0, fg: props.theme().textMuted, children: props.label }), _jsx("box", { width: props.appearance.barWidth, flexShrink: 0, flexDirection: 'row', children: _jsx(For, { each: quotaBarSegments(remaining() ?? 0, props.appearance), children: (segment) => (_jsx("text", { fg: toneColor(props.theme(), segment.tone), children: segment.text })) }) }), _jsx("text", { fg: toneColor(props.theme(), quotaTone(100 - (remaining() ?? 0), props.appearance)), children: ` ${parts().figure}` })] }), _jsx(Show, { when: reset(), children: _jsx("text", { fg: props.theme().textMuted, children: reset() }) })] }) }));
}
// Fleet AccountBlock, adapted to Antigravity's per-account data. Header
// row is account label (left) + status word (right). The body renders one
// QuotaRow per present quota group in the fleet's stable order, then a
// muted secondary line with the account's health score and, when
// relevant, a cooldown countdown. Status word priorities (first match
// wins):
//   - `off` when the account is disabled
//   - `cooling` when cooldownUntil is still in the future
//   - `active` when current === true
//   - `idle` for the fallback (current === false) case
function AccountBlock(props) {
    const active = () => props.active ?? props.account.current;
    const statusWord = () => {
        if (!props.account.enabled)
            return 'off';
        const cd = props.account.cooldownUntil;
        if (typeof cd === 'number' && cd > props.now())
            return 'cooling';
        return active() ? 'active' : 'idle';
    };
    const statusTone = () => {
        if (!props.account.enabled)
            return 'muted';
        const cd = props.account.cooldownUntil;
        if (typeof cd === 'number' && cd > props.now())
            return 'warn';
        return active() ? 'ok' : 'muted';
    };
    const cooldownMs = () => {
        const cd = props.account.cooldownUntil;
        if (typeof cd !== 'number')
            return 0;
        return Math.max(0, cd - props.now());
    };
    const healthText = () => {
        const base = `health ${Math.round(clamp(props.account.health, 0, 100))}`;
        return cooldownMs() > 0
            ? `${base} · cooling ${formatWait(cooldownMs())}`
            : base;
    };
    return (_jsxs("box", { width: '100%', flexDirection: 'column', marginTop: props.marginTop ?? 0, children: [_jsxs("box", { width: '100%', flexDirection: 'row', justifyContent: 'space-between', children: [_jsx("text", { fg: props.theme().text, children: _jsx("b", { children: props.account.label }) }), _jsx("text", { fg: toneColor(props.theme(), statusTone()), children: _jsx("b", { children: statusWord() }) })] }), _jsx(For, { each: QUOTA_ORDER, children: (key) => {
                    const poolEntry = props.account.quota[key];
                    const windows = poolEntry?.windows;
                    // Legacy: no windows array — render a single row with the pool label.
                    const hasWindows = windows && windows.length > 0;
                    if (!hasWindows) {
                        return (_jsx(QuotaRow, { theme: props.theme, appearance: props.appearance, label: QUOTA_LABELS[key], entry: poolEntry, now: props.now }));
                    }
                    return (_jsx(_Fragment, { children: windows.map((w) => (_jsx(QuotaRow, { theme: props.theme, appearance: props.appearance, label: `${QUOTA_LABELS[key]} ${WINDOW_GUTTER[w.window] ?? w.window}`, entry: {
                                remainingPercent: w.remainingPercent,
                                resetAt: w.resetAt,
                                checkedAt: w.checkedAt,
                            }, now: props.now }))) }));
                } }), _jsx("box", { width: '100%', flexDirection: 'row', children: _jsx("text", { fg: props.theme().textMuted, children: `   ${healthText()}` }) })] }));
}
function formatWait(ms) {
    const seconds = Math.ceil(ms / 1000);
    if (seconds < 60)
        return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remaining = seconds % 60;
    return remaining > 0 ? `${minutes}m ${remaining}s` : `${minutes}m`;
}
// --- SidebarPanel ----------------------------------------------------------
export function SidebarPanel(props) {
    const logger = resolveLogger(props.logger);
    const now = props.now ?? (() => Date.now());
    const pollMs = props.pollIntervalMs ?? POLL_INTERVAL_MS;
    const controller = props.controller ?? getSidebarController();
    const collapsed = controller.collapsed;
    const prefs = controller.prefs;
    // Live host theme — falls back to a sensible dark palette when the host
    // does not expose one. Solid tracks `theme()` so a theme switch re-renders
    // every styled span/border without a manual subscription.
    const theme = () => props.theme?.() ?? FALLBACK_THEME;
    const [state, setState] = createSignal({
        loaded: EMPTY_STATE,
        lastReadAt: 0,
        lastError: null,
    });
    const refresh = () => {
        try {
            const loaded = readSidebarState(props.stateFile);
            setState({
                loaded,
                lastReadAt: now(),
                lastError: null,
            });
        }
        catch (error) {
            logger.warn('sidebar-poll-failed', { error: formatError(error) });
            setState((prev) => ({
                ...prev,
                lastReadAt: now(),
                lastError: formatError(error),
            }));
        }
    };
    onMount(() => {
        refresh();
        const interval = setInterval(refresh, pollMs);
        onCleanup(() => clearInterval(interval));
    });
    const hasData = () => state().loaded.accounts.length > 0;
    const backoffActive = () => {
        const until = state().loaded.quotaBackoffUntil;
        return typeof until === 'number' && until > now();
    };
    const lastError = () => state().lastError ?? state().loaded.lastError;
    const degraded = () => backoffActive() || !!lastError();
    // Honors sections.fallbackAccounts. Both the expanded (AccountBlock list)
    // and the collapsed (CollapsedRow list) paths use the same filter so the
    // user sees the same account set in either mode.
    const visibleAccounts = () => {
        const showFallback = prefs().sections.fallbackAccounts;
        if (showFallback)
            return state().loaded.accounts;
        return state().loaded.accounts.filter((account) => account.current);
    };
    const currentRoute = () => {
        const routes = state().loaded.activeRouting;
        const entry = props.sessionId
            ? routes[props.sessionId]
            : Object.values(routes).sort((a, b) => b.updatedAt - a.updatedAt)[0];
        if (!entry)
            return null;
        return {
            strategy: entry.strategy,
            family: entry.modelFamily,
            style: entry.headerStyle,
        };
    };
    // Header badge: ▼/▶ {label}. The fleet shows the version string on the
    // right when no degraded state is present; the antigravity adapter keeps
    // that right-alignment and surfaces `degraded` as a "LIMITED" badge
    // instead of the "1/1 ready" count the previous revision rendered.
    const headerLabel = () => {
        const name = prefs().header.label;
        return !hasData() ? name : collapsed() ? `\u25b6 ${name}` : `\u25bc ${name}`;
    };
    return (_jsxs("box", { width: '100%', flexDirection: 'column', border: SINGLE_BORDER, borderColor: theme().borderActive, paddingTop: 1, paddingBottom: 1, paddingLeft: 1, paddingRight: 1, children: [_jsxs("box", { width: '100%', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', onMouseDown: () => {
                    // Mirror the fleet guard: only toggle when there is data to expand
                    // into. Without this a click on the empty-awaiting header would just
                    // toggle the affordance for nothing.
                    if (hasData())
                        controller.toggleCollapsed();
                }, children: [_jsx("box", { paddingLeft: 1, paddingRight: 1, backgroundColor: theme().accent, children: _jsx("text", { fg: theme().background, children: _jsx("b", { children: headerLabel() }) }) }), _jsx(Show, { when: degraded(), fallback: _jsx(Show, { when: prefs().header.showVersion && PLUGIN_VERSION !== '', children: _jsx("text", { fg: theme().textMuted, children: `v${PLUGIN_VERSION}` }) }), children: _jsx("box", { paddingLeft: 1, paddingRight: 1, backgroundColor: theme().warning, children: _jsx("text", { fg: theme().background, children: _jsx("b", { children: 'LIMITED' }) }) }) })] }), _jsx(Show, { when: collapsed() && hasData(), children: (() => {
                    const account = () => visibleAccounts().find((entry) => entry.current) ??
                        visibleAccounts()[0];
                    const remaining = () => {
                        const q = account()?.quota;
                        // The lowest remaining percentage among dated readings determines the warning tone.
                        const gemini = quotaReadingParts('Gm', q?.gemini, now()).remaining;
                        const nonGemini = quotaReadingParts('NG', q?.['non-gemini'], now()).remaining;
                        if (gemini === null && nonGemini === null)
                            return null;
                        return Math.min(gemini ?? 100, nonGemini ?? 100);
                    };
                    const poolText = (key) => {
                        const entry = account()?.quota[key];
                        if (!entry)
                            return `${QUOTA_LABELS[key]}: ${formatQuotaReading(QUOTA_LABELS[key], undefined, now())}`;
                        // Show binding window when available, else just pool label.
                        const bindingWindow = entry.windows?.reduce((best, w) => best === null || w.remainingPercent < best.remainingPercent
                            ? w
                            : best, null);
                        const gutter = bindingWindow
                            ? ` ${WINDOW_GUTTER[bindingWindow.window] ?? bindingWindow.window}`
                            : '';
                        const text = formatQuotaReading(`${QUOTA_LABELS[key]}${gutter}`, bindingWindow ?? entry, now());
                        return bindingWindow ? `${QUOTA_LABELS[key]} ${text}` : text;
                    };
                    const unavailable = () => {
                        const selected = account();
                        return (selected != null &&
                            (!selected.enabled ||
                                (selected.cooldownUntil != null &&
                                    selected.cooldownUntil > now())));
                    };
                    return (_jsx(Show, { when: account(), children: (selected) => (_jsx(CollapsedRow, { theme: theme, label: selected().label, children: _jsxs("box", { flexDirection: 'row', children: [_jsx("text", { fg: toneColor(theme(), remaining() == null
                                            ? 'muted'
                                            : quotaTone(100 - (remaining() ?? 100), prefs().appearance)), children: _jsx("b", { children: account()?.quota.gemini == null &&
                                                account()?.quota['non-gemini'] == null
                                                ? '—'
                                                : `${poolText('gemini')} · ${poolText('non-gemini')}` }) }), _jsx("text", { fg: toneColor(theme(), unavailable()
                                            ? 'err'
                                            : remaining() == null
                                                ? 'muted'
                                                : quotaTone(100 - (remaining() ?? 100), prefs().appearance)), children: unavailable() ? ' ⊘' : ' ●' })] }) })) }));
                })() }), _jsx(Show, { when: !collapsed() || !hasData(), children: _jsxs(Show, { when: hasData(), fallback: _jsx("box", { marginTop: 1, width: '100%', children: _jsx("text", { fg: theme().textMuted, children: 'Waiting for quota\u2026' }) }), children: [_jsxs(Show, { when: prefs().sections.quota, children: [_jsx(SectionHeader, { theme: theme, title: 'Quota' }), _jsx(For, { each: visibleAccounts(), children: (account, index) => (_jsx(AccountBlock, { theme: theme, appearance: prefs().appearance, account: account, now: now, marginTop: index() === 0 ? 0 : 1 })) })] }), _jsxs(Show, { when: prefs().sections.routing, children: [_jsx(SectionHeader, { theme: theme, title: 'Routing' }), _jsx(Show, { when: currentRoute(), fallback: _jsx(StatRow, { theme: theme, label: 'Route', value: '\u2014', tone: 'muted' }), children: (route) => (_jsx(StatRow, { theme: theme, label: 'Route', value: `${route().strategy ? `${route().strategy} · ` : ''}${route().family}: ${route().style}`, tone: 'accent' })) })] }), _jsxs(Show, { when: degraded() && prefs().sections.health, children: [_jsx(SectionHeader, { theme: theme, title: 'Health' }), _jsx(Show, { when: backoffActive(), children: _jsx(StatRow, { theme: theme, label: 'Quota API', value: `backoff ${formatResetIn(state().loaded.quotaBackoffUntil, now)}`, tone: 'warn' }) }), _jsx(Show, { when: lastError(), children: _jsx(StatRow, { theme: theme, label: 'Last error', value: lastError() ?? '', tone: 'err' }) })] })] }) })] }));
}
/**
 * Solid slot registry binding exposed for hosts that want to mount the
 * sidebar inside their renderer. Hosts that already own a slot registry can
 * use `createSlot` directly; we re-export for convenience and to keep the
 * contract visible at the module entry point.
 */
export const sidebar_content = createSlot;
export function startRpcNotificationPolling(options) {
    if (rpcPollStarted)
        return;
    rpcPollStarted = true;
    options.schedule(async () => {
        if (rpcInFlight)
            return;
        rpcInFlight = true;
        try {
            const sessionId = options.currentSessionId();
            const cursorKey = sessionId ?? GLOBAL_NOTIFICATION_CURSOR;
            let cursor = notificationCursorBySession.get(cursorKey) ?? 0;
            const notifications = await options.pending(cursor, sessionId);
            for (const notification of [...notifications].sort((a, b) => a.id - b.id)) {
                if (notification.id <= cursor)
                    continue;
                cursor = Math.max(cursor, notification.id);
                if (dispatchedNotificationIds.has(notification.id))
                    continue;
                dispatchedNotificationIds.add(notification.id);
                if (dispatchedNotificationIds.size > 100) {
                    const oldestId = dispatchedNotificationIds.values().next().value;
                    if (oldestId !== undefined)
                        dispatchedNotificationIds.delete(oldestId);
                }
                await options.dispatch(notification);
            }
            if (!notificationCursorBySession.has(cursorKey)) {
                while (notificationCursorBySession.size >= MAX_NOTIFICATION_CURSORS) {
                    const oldest = notificationCursorBySession.keys().next().value;
                    if (oldest === undefined)
                        break;
                    notificationCursorBySession.delete(oldest);
                }
            }
            notificationCursorBySession.set(cursorKey, cursor);
        }
        catch (error) {
            // Surface the swallowed error through the file logger rather than
            // stdout/stderr (the host terminal is the frame buffer — any byte
            // written here corrupts every subsequent cell). Without this, a
            // transient RPC outage is invisible to operators. The catch stays
            // because one failed poll must never break the next — the scheduler
            // is a setInterval and a thrown error there would crash the
            // process.
            options.logger.warn('rpc-poll-failed', {
                error: error instanceof Error ? error.message : String(error),
            });
        }
        finally {
            rpcInFlight = false;
        }
    }, RPC_POLL_MS);
}
const tui = async (api) => {
    const logger = resolveLogger(undefined);
    const prefsRoot = await readTuiPreferencesFile();
    if (!sidebarController) {
        sidebarController = createSidebarController(resolveAntigravityAuthPrefs(prefsRoot));
    }
    // The `/antigravity` drawer: the server pushes the menu as a notification
    // on this process's private RPC; the drawer applies through the same RPC.
    const transport = createV1MenuTransport(getRpcDir(api.state.path.directory ?? ''), process.pid);
    startRpcNotificationPolling({
        pending: (lastReceivedId, sessionId) => transport.pending(lastReceivedId, sessionId),
        currentSessionId: () => {
            const current = api.route.current;
            const resolved = typeof current === 'function' ? current() : current;
            return resolved
                ?.params?.sessionID;
        },
        dispatch: (notification) => {
            logger.debug('rpc-notification-received', {
                id: notification.id,
                sessionId: notification.sessionId,
            });
            dispatchV1Notification(api, transport, notification, logger);
        },
        schedule: (poll, intervalMs) => {
            setInterval(() => void poll(), intervalMs);
        },
        logger,
    });
    // The host supplies the live theme via `api.theme.current` — the slot
    // callback's closure captures `api` so the accessor always reads the
    // current theme. A Solid re-render follows whenever the user switches.
    const liveTheme = () => api.theme.current;
    api.slots.register({
        order: computeEffectiveOrder(prefsRoot, PLUGIN_KEY, DEFAULT_SLOT_ORDER),
        slots: {
            sidebar_content: (_context, { session_id: sessionId }) => (_jsx(SidebarPanel, { logger: logger, theme: liveTheme, sessionId: sessionId })),
        },
    });
};
const plugin = {
    id: ID,
    tui,
};
export default plugin;
//# sourceMappingURL=tui.js.map