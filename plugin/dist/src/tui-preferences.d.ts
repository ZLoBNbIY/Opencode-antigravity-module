export declare const TUI_PREFS_FILE_ENV = "OPENCODE_TUI_PREFERENCES_FILE";
export declare function getTuiPreferencesFile(): string;
export declare function readTuiPreferencesFile(): Promise<Record<string, unknown>>;
export declare const PLUGIN_KEY = "antigravity-auth";
export declare const DEFAULT_SLOT_ORDER = 160;
export interface AntigravityAuthTuiPrefs {
    forceToTop: boolean;
    order: number;
    startCollapsed: boolean;
    rememberCollapsed: boolean;
    collapsed: boolean | null;
    pollMs: number;
    refreshDebounceMs: number;
    header: {
        label: string;
        showVersion: boolean;
    };
    sections: {
        quota: boolean;
        fallbackAccounts: boolean;
        routing: boolean;
        health: boolean;
    };
    appearance: {
        barWidth: number;
        barFilledChar: string;
        barEmptyChar: string;
        warnThreshold: number;
        errorThreshold: number;
    };
}
export type AppearancePrefs = AntigravityAuthTuiPrefs['appearance'];
export declare const DEFAULT_PREFS: AntigravityAuthTuiPrefs;
export declare function resolveAntigravityAuthPrefs(root: Record<string, unknown>): AntigravityAuthTuiPrefs;
export declare function computeEffectiveOrder(root: Record<string, unknown>, pluginKey: string, defaultOrder: number): number;
type JsonValue = string | number | boolean | null;
export declare function queueTuiPreferenceUpdate(pluginKey: string, path: string[], value: JsonValue): Promise<void>;
export declare function watchTuiPreferences(onChange: () => void): () => void;
export {};
//# sourceMappingURL=tui-preferences.d.ts.map