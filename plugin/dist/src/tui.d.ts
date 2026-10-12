/** @jsxImportSource @opentui/solid */
import type { TuiPluginModule, TuiThemeCurrent } from '@opencode-ai/plugin/tui';
import { createSlot } from '@opentui/solid';
import { type JSX } from 'solid-js';
import { type TuiLogger } from './tui/file-logger';
import { type V1Notification } from './tui/host-v1';
import { type AntigravityAuthTuiPrefs } from './tui-preferences';
type Theme = TuiThemeCurrent;
export interface SidebarPanelProps {
    /** Override the file the TUI polls. Defaults to `getSidebarStateFile()`. */
    stateFile?: string;
    /** Override the polling interval. Defaults to 2000ms. */
    pollIntervalMs?: number;
    /** Override the logger; tests inject a logger that captures into memory. */
    logger?: TuiLogger;
    /** Optional override for the current epoch in milliseconds (tests). */
    now?: () => number;
    /** Optional prefs controller — when present, drives collapse/expand and
     * section toggles. Module-scoped controller is created at plugin init. */
    controller?: SidebarController;
    /** Optional live-theme accessor. The host's `api.theme.current` is wired
     * through here in production; tests pass a custom accessor to flip theme
     * and assert re-render. Falls back to FALLBACK_THEME when unset. */
    theme?: () => Theme;
    /** The slot session determines which route is relevant to this sidebar. */
    sessionId?: string;
}
export interface SidebarController {
    prefs: () => AntigravityAuthTuiPrefs;
    collapsed: () => boolean;
    toggleCollapsed: () => void;
}
export declare function createSidebarController(initialPrefs: AntigravityAuthTuiPrefs): SidebarController;
export declare function SidebarPanel(props: SidebarPanelProps): JSX.Element;
/**
 * Solid slot registry binding exposed for hosts that want to mount the
 * sidebar inside their renderer. Hosts that already own a slot registry can
 * use `createSlot` directly; we re-export for convenience and to keep the
 * contract visible at the module entry point.
 */
export declare const sidebar_content: typeof createSlot;
interface RpcNotificationPollOptions {
    pending: (lastReceivedId: number, sessionId?: string) => Promise<readonly V1Notification[]>;
    currentSessionId: () => string | undefined;
    dispatch: (notification: V1Notification) => void | Promise<void>;
    schedule: (poll: () => Promise<void>, intervalMs: number) => void;
    /**
     * File logger used to surface poll errors. Must be a file logger — the
     * host terminal is the frame buffer, so writes to stdout/stderr would
     * corrupt the sidebar render. The plugin production path uses
     * `resolveLogger(undefined)` to fall through to the on-disk file
     * logger.
     */
    logger: TuiLogger;
}
export declare function startRpcNotificationPolling(options: RpcNotificationPollOptions): void;
declare const plugin: TuiPluginModule & {
    id: string;
};
export default plugin;
//# sourceMappingURL=tui.d.ts.map