/**
 * Host-neutral contract between the shared `/antigravity` menu drawer and the
 * two host adapters (OpenCode 1 in `host-v1.tsx`, OpenCode GA in
 * `ga/tui/host-ga.tsx`).
 *
 * The menu itself is built by the server with the shared command menu of
 * `@cortexkit/common-auth/commands` (0.11.4): one slash command, sections in
 * a fixed slot order, items and actions addressed by opaque ids, typed
 * inputs, confirmations, and a refreshed menu after every apply. The TUI
 * only renders that payload and sends back which action the user chose.
 *
 * The shapes below mirror the library's `CommandDialogPayload`,
 * `CommandApplyRequest` and `CommandApplyResult` field for field. They are
 * declared here, not imported, because this module ships in the TUI render
 * graph and must stay free of runtime imports: nothing here may pull in the
 * account store, OAuth, token or server code. The parsers validate every
 * payload that crosses the transport and refuse anything that does not match
 * exactly, so a server that sends a different shape fails visibly instead of
 * rendering a half-understood menu.
 */
/** The single slash command, without the slash. */
export declare const ANTIGRAVITY_MENU_COMMAND: "antigravity";
/** The drawer's title. */
export declare const ANTIGRAVITY_MENU_TITLE: "Antigravity";
/**
 * The section slots in the one order every renderer shows them (the shared
 * library's `SECTION_SLOTS`). Killswitch lives under `limits`, logging and
 * the wire dump under `diagnostics`, vault setup under `extra`.
 */
export declare const MENU_SECTION_SLOTS: readonly ["accounts", "quota", "routing", "limits", "cache", "diagnostics", "extra"];
export type MenuSectionSlot = (typeof MENU_SECTION_SLOTS)[number];
export interface MenuChoice {
    readonly value: string;
    readonly label: string;
}
export type MenuKnob = {
    readonly kind: 'choice';
    readonly id: string;
    readonly label: string;
    readonly choices: readonly MenuChoice[];
    readonly value?: string;
} | {
    readonly kind: 'toggle';
    readonly id: string;
    readonly label: string;
    readonly value: boolean;
} | {
    readonly kind: 'number';
    readonly id: string;
    readonly label: string;
    readonly value?: number;
    readonly min?: number;
    readonly max?: number;
    readonly required?: boolean;
} | {
    readonly kind: 'text';
    readonly id: string;
    readonly label: string;
    readonly value?: string;
    readonly placeholder?: string;
    readonly masked?: boolean;
    readonly required?: boolean;
};
export type KnobValue = string | number | boolean | null;
export interface MenuConfirmation {
    readonly message: string;
    readonly irreversible: boolean;
}
export interface MenuAction {
    readonly id: string;
    readonly label: string;
    readonly description?: string;
    readonly group?: string;
    readonly knobs: readonly MenuKnob[];
    readonly confirm?: MenuConfirmation;
}
export interface MenuAccount {
    readonly id: string;
    readonly label?: string;
    readonly enabled: boolean;
    readonly type: 'oauth' | 'api';
    readonly identity?: string;
}
export type MenuFactValue = string | number | boolean | null;
export interface MenuItem {
    readonly id: string;
    readonly label: string;
    readonly detail?: string;
    readonly group?: string;
    readonly status?: string;
    readonly account?: MenuAccount;
    readonly facts?: Readonly<Record<string, MenuFactValue>>;
    readonly actions: readonly MenuAction[];
}
export interface MenuSection {
    readonly id: string;
    readonly slot: MenuSectionSlot;
    readonly title: string;
    readonly lines: readonly string[];
    readonly items: readonly MenuItem[];
    readonly actions: readonly MenuAction[];
    readonly facts?: Readonly<Record<string, MenuFactValue>>;
}
export interface MenuModel {
    readonly command: string;
    readonly title: string;
    readonly sections: readonly MenuSection[];
}
/** What the TUI receives when the slash command opens the drawer. */
export interface MenuDialogPayload {
    readonly command: string;
    readonly menu: MenuModel;
}
/** A message the server pushes without opening the drawer. */
export interface MenuNotifyPayload {
    readonly command: string;
    readonly notify: {
        readonly message: string;
        readonly kind: 'info' | 'warning' | 'error';
    };
}
/** One chosen action. The adapter adds the session the drawer belongs to. */
export interface MenuApplyRequest {
    readonly command: string;
    readonly sectionId: string;
    readonly itemId?: string;
    readonly actionId: string;
    readonly values: Readonly<Record<string, KnobValue>>;
    readonly confirmed?: true;
}
export interface MenuApplyResult {
    readonly command: string;
    readonly ok: boolean;
    readonly text: string;
    readonly code?: string;
    readonly needsConfirmation?: boolean;
    readonly menu: MenuModel;
}
/** One row of a select dialog; `value` is what the drawer gets back. */
export interface MenuSelectOption {
    readonly title: string;
    readonly value: string;
    readonly description?: string;
    readonly category?: string;
    readonly footer?: string;
}
/**
 * The host's dialog primitives, as promises. Each adapter maps them onto its
 * host: OpenCode 1 mounts `DialogSelect`/`DialogPrompt`/`DialogConfirm`/
 * `DialogAlert` through `dialog.replace`; GA calls
 * `ui.dialog.select/prompt/confirm/alert`. `select` and `prompt` resolve
 * `undefined` when the user dismisses the dialog; the drawer then closes
 * rather than reopening a level up. `confirm` resolves false on dismissal.
 */
export interface MenuUi {
    select(input: {
        readonly title: string;
        readonly options: readonly MenuSelectOption[];
        readonly current?: string;
    }): Promise<string | undefined>;
    prompt(input: {
        readonly title: string;
        readonly description?: string;
        readonly placeholder?: string;
        readonly value?: string;
    }): Promise<string | undefined>;
    confirm(input: {
        readonly title: string;
        readonly message: string;
    }): Promise<boolean>;
    /** Shows a long message in full (a sign-in URL, a multi-line result). */
    alert(input: {
        readonly title: string;
        readonly message: string;
    }): Promise<void>;
    toast(message: string, kind?: 'info' | 'warning' | 'error'): void;
    clear(): void;
}
/** Sends one action to the server that built the menu. */
export type MenuApply = (request: MenuApplyRequest) => Promise<MenuApplyResult>;
export type MenuParseResult<T> = {
    readonly ok: true;
    readonly value: T;
} | {
    readonly ok: false;
    readonly issues: readonly string[];
};
/** Checks a drawer-opening payload. Issue texts name fields, never values. */
export declare function parseMenuDialogPayload(value: unknown): MenuParseResult<MenuDialogPayload>;
/** Checks a notify-only payload. */
export declare function parseMenuNotifyPayload(value: unknown): MenuParseResult<MenuNotifyPayload>;
/** Checks an apply answer, including its refreshed menu. */
export declare function parseMenuApplyResult(value: unknown): MenuParseResult<MenuApplyResult>;
/** What the drawer shows when an answer fails validation. */
export declare const MENU_REFUSED_TEXT = "Antigravity sent a menu this TUI does not understand; nothing was shown.";
//# sourceMappingURL=host-api.d.ts.map