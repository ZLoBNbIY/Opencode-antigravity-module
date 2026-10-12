/**
 * Structured provider logs fully mask credential and account-correlating keys.
 * Event IDs and diagnostic fields are intentionally not classified as secrets.
 * The public logger supplies lowercase keys with hyphens/underscores removed.
 * Keeping this policy dependency-free lets the TUI use it without loading any
 * provider state, storage, debug streams or OAuth code.
 */
export declare function isProviderSecretKey(normalizedKey: string): boolean;
//# sourceMappingURL=provider-key-policy.d.ts.map