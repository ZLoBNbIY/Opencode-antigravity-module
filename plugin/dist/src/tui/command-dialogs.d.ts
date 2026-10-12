/**
 * The `/antigravity` drawer: one renderer for the server's command menu,
 * shared by the OpenCode 1 and OpenCode GA TUIs.
 *
 * The server builds the whole menu with the shared command menu of
 * `@cortexkit/common-auth/commands`: Accounts, Quota, Routing, Limits
 * (killswitch), Cache, Diagnostics (logging and wire dump) and the plugin's
 * extras (vault setup), each with its read-only lines, its items, and its
 * actions with their typed inputs and confirmations. This file only walks
 * that payload through the host's dialogs and sends back which action the
 * user chose, by the opaque section, item and action ids the server gave.
 * It never builds an account target of its own, never looks an account up
 * by position, and never retries a choice against a different target: an id
 * the server no longer knows comes back as a refused apply and the user sees
 * the server's message.
 *
 * Every redraw after an apply uses the menu that apply returned, which the
 * server built fresh for that answer; settings shown here are never a
 * replay of an earlier answer.
 *
 * The drawer talks to the host only through `MenuUi` (dialog primitives as
 * promises) and `MenuApply` (the transport), so the same code runs on both
 * hosts. Nothing here writes to the terminal or picks colors.
 */
import { type KnobValue, type MenuApply, type MenuDialogPayload, type MenuItem, type MenuKnob, type MenuModel, type MenuSection, type MenuSelectOption, type MenuUi } from './host-api';
/**
 * Raised by a transport when an answer fails validation, so the drawer can
 * tell a refused answer from an unreachable server.
 */
export declare class MenuRefusedError extends Error {
    readonly issues: readonly string[];
    constructor(issues: readonly string[]);
}
/** One option per section, in the order the menu gives them. */
export declare function sectionListOptions(menu: MenuModel): MenuSelectOption[];
/** Status text is a group header; every option navigates or runs an action. */
export declare function sectionOptions(section: MenuSection): MenuSelectOption[];
/** Item context stays in descriptions, never in rows that cannot be acted on. */
export declare function itemOptions(item: MenuItem): MenuSelectOption[];
/**
 * The value a typed `number` or `text` input sends. Empty is `null` (the
 * action reads that as "leave unset"); a number input sends a number when
 * the text parses as one and the text otherwise, so the server can say what
 * is wrong with it.
 */
export declare function promptValue(knob: MenuKnob, raw: string): KnobValue;
/** The first web link in a message, such as a sign-in URL. */
export declare function firstLink(text: string): string | undefined;
export interface DrawerOptions {
    readonly ui: MenuUi;
    readonly apply: MenuApply;
    /**
     * Copies text to the clipboard; returns false when the terminal cannot.
     * Absent when the host offers no clipboard.
     */
    readonly copy?: (text: string) => boolean;
    /** Receives drawer failures; must not write to the terminal. */
    readonly onError?: (message: string, detail: Record<string, unknown>) => void;
    /** Opens on this section instead of the section list, when it exists. */
    readonly startSection?: string;
}
/**
 * Opens the drawer on a payload the server pushed for `/antigravity`. The
 * returned promise settles when the user closes the drawer.
 */
export declare function openAntigravityMenu(options: DrawerOptions, payload: MenuDialogPayload): Promise<void>;
//# sourceMappingURL=command-dialogs.d.ts.map