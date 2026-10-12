/**
 * Loopback proxy guard for the OpenCode 2 (GA 2.0.22) bridge.
 *
 * The GA adapter rewrites native Google model requests to a plugin-owned
 * bridge at `http://127.0.0.1:<port>`. The host sends that rewritten request
 * with its own `fetch`, which reads proxy settings from the environment. If
 * the host would send the bridge request to a proxy, the request either fails
 * or leaks the bridge traffic to a third party, so the adapter must refuse the
 * request before rewriting it and tell the user how to exclude loopback.
 *
 * This module is a pure decision over an environment snapshot. It never reads
 * or writes `process.env` by itself, never opens a socket, and never falls back
 * to Google's public endpoint: the caller passes the environment and the bridge
 * URL, and either rewrites (decision `ok: true`) or stops the request with the
 * returned error (decision `ok: false`).
 *
 * The rules mirror what the pinned host does for a plain-HTTP URL, as measured
 * on the GA 2.0.22 binary (Bun 1.4.2, revision 744846f8) and read from that Bun
 * revision's `ProxySettings::from_env` / `no_proxy_matches`:
 *
 * - Proxy selection: `http_proxy` when its raw value is non-empty, otherwise
 *   `HTTP_PROXY`. The selection happens on the raw value; only afterwards is a
 *   selected value of exactly `""` or `''` (two quote characters) treated as
 *   "no proxy". So a lowercase `http_proxy=""` suppresses `HTTP_PROXY`, while a
 *   genuinely empty `http_proxy=` falls through to `HTTP_PROXY`.
 * - `HTTPS_PROXY`, `https_proxy`, `ALL_PROXY` and `all_proxy` do not apply to
 *   an `http:` URL and are ignored.
 * - Exclusion selection: `no_proxy` when its raw value is non-empty, otherwise
 *   `NO_PROXY`, with the same raw-before-quote-stripping rule. The two lists
 *   are never merged.
 * - The selected list is split on commas only; each entry is trimmed.
 * - Only these exact spellings are read (`env.get(b"http_proxy")` and so on in
 *   the pinned source). A key with any other capitalisation, such as
 *   `Http_Proxy`, is ignored like any other unrelated variable.
 *
 * The guard is deliberately narrower than the host: it only treats an entry as
 * excluding the bridge when it is one of the loopback forms measured as direct
 * (`*`, `127.0.0.1`, `127.0.0.1:<bridge port>`). Anything else fails closed.
 * The measured rows are test evidence, not a shipped allowlist of
 * configurations.
 */
/** The exclusion the README documents and every guard error names. */
export declare const DOCUMENTED_LOOPBACK_EXCLUSION: "NO_PROXY=127.0.0.1";
/** An environment snapshot; `undefined` means the variable is unset. */
export type LoopbackProxyEnv = Readonly<Record<string, string | undefined>>;
export type ProxyVariableName = 'http_proxy' | 'HTTP_PROXY';
export type ExclusionVariableName = 'no_proxy' | 'NO_PROXY';
/**
 * Why a configuration was refused. The letters follow the guard contract:
 * (a) a proxy applies and no entry excludes the bridge;
 * (c) the proxy that applies is not an absolute http(s) URL;
 * (d) the exclusion list names loopback, but only in a form the host does not
 *     treat as direct (or that was never measured as direct).
 * The contract's trigger (b), a conflict without recorded precedence, has no
 * case here. The host reads only the exact lowercase and uppercase names, and
 * every conflict between those has a measured winner: lowercase when its raw
 * value is non-empty.
 */
export type LoopbackProxyGuardTrigger = 'a-no-loopback-exclusion' | 'c-proxy-not-url' | 'd-loopback-entry-not-direct';
/** The loopback exclusion form that let the bridge request go direct. */
export type LoopbackDirectForm = 'wildcard' | 'loopback-host' | 'loopback-host-port';
export type LoopbackProxyAllowed = {
    readonly ok: true;
    readonly route: 'direct';
    /** No proxy applies to an `http:` URL. */
    readonly basis: 'no-proxy-selected';
    /**
     * The proxy variable the host selected when its value was the quoted
     * empty string (`""` or `''`), or `null` when neither variable was set.
     */
    readonly proxyVariable: ProxyVariableName | null;
} | {
    readonly ok: true;
    readonly route: 'direct';
    /** A proxy applies, but the selected exclusion list covers the bridge. */
    readonly basis: 'excluded';
    readonly proxyVariable: ProxyVariableName;
    readonly exclusionVariable: ExclusionVariableName;
    readonly directForm: LoopbackDirectForm;
};
export type LoopbackProxyRefused = {
    readonly ok: false;
    readonly trigger: LoopbackProxyGuardTrigger;
    /** The proxy variable involved, when one was selected. Never its value. */
    readonly proxyVariable: ProxyVariableName | null;
    /** The exclusion variable the host would consult, when one was selected. */
    readonly exclusionVariable: ExclusionVariableName | null;
    /** User-facing text. Contains no environment values. */
    readonly message: string;
};
export type LoopbackProxyDecision = LoopbackProxyAllowed | LoopbackProxyRefused;
export type LoopbackProxyGuardInput = {
    /** Environment snapshot the host's `fetch` will read. Never modified. */
    readonly env: LoopbackProxyEnv;
    /** The rewritten bridge URL; must be `http://127.0.0.1:<port>...`. */
    readonly target: string | URL;
};
/** Thrown by {@link assertLoopbackProxyGuard} when the decision is a refusal. */
export declare class LoopbackProxyGuardError extends Error {
    readonly name = "LoopbackProxyGuardError";
    readonly trigger: LoopbackProxyGuardTrigger;
    readonly documentedLoopbackExclusion: "NO_PROXY=127.0.0.1";
    readonly decision: LoopbackProxyRefused;
    constructor(decision: LoopbackProxyRefused);
}
/**
 * Allow the bridge request when no HTTP proxy applies, or the selected
 * exclusion list contains `*`, `127.0.0.1`, or that host with the bridge port.
 * Reject suffix spellings even when OpenCode accepts them, so the exclusion
 * stays explicit. No I/O or writes occur. Invalid bridge targets throw
 * `TypeError`.
 */
export declare function evaluateLoopbackProxyGuard(input: LoopbackProxyGuardInput): LoopbackProxyDecision;
/**
 * Assertion form for host-hook wiring: returns the allowed decision, or throws
 * {@link LoopbackProxyGuardError} so the hook can stop the request before any
 * rewrite.
 */
export declare function assertLoopbackProxyGuard(input: LoopbackProxyGuardInput): LoopbackProxyAllowed;
//# sourceMappingURL=proxy-guard.d.ts.map