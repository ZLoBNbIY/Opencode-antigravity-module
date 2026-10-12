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
export const DOCUMENTED_LOOPBACK_EXCLUSION = 'NO_PROXY=127.0.0.1';
/** Only the hostname the bridge listens on; the guard covers nothing else. */
const BRIDGE_HOSTNAME = '127.0.0.1';
/** Thrown by {@link assertLoopbackProxyGuard} when the decision is a refusal. */
export class LoopbackProxyGuardError extends Error {
    name = 'LoopbackProxyGuardError';
    trigger;
    documentedLoopbackExclusion = DOCUMENTED_LOOPBACK_EXCLUSION;
    decision;
    constructor(decision) {
        super(decision.message);
        this.trigger = decision.trigger;
        this.decision = decision;
    }
}
/**
 * OpenCode sends the rewritten bridge request, so the guard must match its
 * pinned Linux/Bun variable selection. A non-empty raw lowercase value wins
 * before quoted-empty handling; reversing that order can select an uppercase
 * proxy that OpenCode would ignore, or trust an exclusion it would ignore.
 */
function selectLowerThenUpper(env, lower, upper) {
    const lowerRaw = env[lower];
    if (lowerRaw !== undefined && lowerRaw !== '')
        return { name: lower, raw: lowerRaw };
    const upperRaw = env[upper];
    if (upperRaw !== undefined)
        return { name: upper, raw: upperRaw };
    return null;
}
/** Empty, or exactly two double quotes, or exactly two single quotes. */
function isEmptyish(raw) {
    return raw === '' || raw === '""' || raw === "''";
}
/**
 * Accept only absolute HTTP(S) proxy URLs with a host and no surrounding
 * whitespace. Reject other forms rather than guess how to interpret them.
 */
function isSupportedProxyUrl(raw) {
    if (raw.trim() !== raw)
        return false;
    let parsed;
    try {
        parsed = new URL(raw);
    }
    catch {
        return false;
    }
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:')
        return false;
    return parsed.hostname !== '';
}
/**
 * The guard trims ASCII spaces around exclusion entries. It rejects entries
 * padded with other whitespace, even if a host implementation accepts them.
 */
function trimEntry(entry) {
    let start = 0;
    let end = entry.length;
    while (start < end && entry.charCodeAt(start) === 0x20)
        start++;
    while (end > start && entry.charCodeAt(end - 1) === 0x20)
        end--;
    return entry.slice(start, end);
}
/**
 * The guard's direct forms: `*`, `127.0.0.1` and `127.0.0.1:<bridge port>`,
 * each measured as sending the bridge request direct.
 *
 * Conservative policy: the host also matches label suffixes after stripping
 * one leading dot, and the measurements show `0.0.1` and `.0.0.1` going direct
 * too. The guard still refuses those spellings, and every other suffix form,
 * on purpose. General suffix matching would accept unmeasured spellings such
 * as `1` or `.127.0.0.1`. Refusing them only costs an error that asks for
 * NO_PROXY=127.0.0.1. It never changes where the host routes a request.
 */
function directFormOf(entry, bridgePort) {
    if (entry === '*')
        return 'wildcard';
    if (entry === BRIDGE_HOSTNAME)
        return 'loopback-host';
    if (entry === `${BRIDGE_HOSTNAME}:${bridgePort}`)
        return 'loopback-host-port';
    return null;
}
/**
 * Whether an entry looks like an attempt to exclude loopback. Used only to
 * pick between triggers (a) and (d) for the error text; both refuse.
 */
function looksLikeLoopback(entry) {
    const folded = entry.toLowerCase();
    if (folded.includes('localhost'))
        return true;
    if (folded.includes('::1'))
        return true;
    if (folded.includes('127.'))
        return true;
    if (folded.startsWith('['))
        return true;
    // Label suffixes of 127.0.0.1 ("1", "0.1", "0.0.1", optionally dotted).
    const undotted = folded.startsWith('.') ? folded.slice(1) : folded;
    return undotted !== '' && `.${BRIDGE_HOSTNAME}`.endsWith(`.${undotted}`);
}
function exclusionAdvice(exclusionVariable) {
    if (exclusionVariable === 'no_proxy') {
        return (`Set ${DOCUMENTED_LOOPBACK_EXCLUSION}. Because no_proxy is set and takes precedence ` +
            'over NO_PROXY, also add 127.0.0.1 as its own comma-separated entry in no_proxy ' +
            '(or unset no_proxy), then restart OpenCode.');
    }
    return (`Set ${DOCUMENTED_LOOPBACK_EXCLUSION} (or add 127.0.0.1 as its own comma-separated ` +
        'entry to an existing NO_PROXY list), then restart OpenCode.');
}
function refuse(trigger, proxyVariable, exclusionVariable) {
    const lead = 'Antigravity stopped this request before sending it: the OpenCode host would route the ' +
        "plugin's local bridge request (http://127.0.0.1) through an HTTP proxy, or the proxy " +
        'settings cannot be checked safely.';
    let detail;
    switch (trigger) {
        case 'a-no-loopback-exclusion':
            detail = `${proxyVariable} is set and no proxy exclusion covers 127.0.0.1.`;
            break;
        case 'd-loopback-entry-not-direct':
            detail =
                `${proxyVariable} is set, but ${exclusionVariable} has no explicit loopback exclusion ` +
                    'accepted by the guard. Use 127.0.0.1, optionally with the exact bridge port, or *.';
            break;
        case 'c-proxy-not-url':
            detail =
                `${proxyVariable} is not an absolute http:// or https:// URL; fix or unset it. ` +
                    'Loopback must also stay excluded from the proxy.';
            break;
    }
    return {
        ok: false,
        trigger,
        proxyVariable,
        exclusionVariable,
        message: `${lead} ${detail} ${exclusionAdvice(exclusionVariable)}`,
    };
}
const BRIDGE_TARGET_PATTERN = /^http:\/\/127\.0\.0\.1:([1-9][0-9]{0,4})(?:[/?#]|$)/;
/**
 * Validate the bridge URL and return its port as written. A target that is
 * not `http://127.0.0.1:<port>` is a caller bug, not a user configuration
 * problem, so it throws instead of returning a refusal. The port must survive
 * URL normalisation: `:80` is the http default and disappears from the host
 * the request is sent with, so a `127.0.0.1:80` exclusion would not match it.
 */
function bridgePortOf(target) {
    const href = typeof target === 'string' ? target : target.href;
    const port = BRIDGE_TARGET_PATTERN.exec(href)?.[1];
    if (port !== undefined && Number(port) <= 65535) {
        const parsed = new URL(href);
        if (parsed.hostname === BRIDGE_HOSTNAME && parsed.port === port)
            return port;
    }
    throw new TypeError('loopback proxy guard only evaluates http://127.0.0.1:<port> bridge URLs');
}
/**
 * Allow the bridge request when no HTTP proxy applies, or the selected
 * exclusion list contains `*`, `127.0.0.1`, or that host with the bridge port.
 * Reject suffix spellings even when OpenCode accepts them, so the exclusion
 * stays explicit. No I/O or writes occur. Invalid bridge targets throw
 * `TypeError`.
 */
export function evaluateLoopbackProxyGuard(input) {
    const bridgePort = bridgePortOf(input.target);
    const env = input.env;
    const proxy = selectLowerThenUpper(env, 'http_proxy', 'HTTP_PROXY');
    if (proxy === null)
        return {
            ok: true,
            route: 'direct',
            basis: 'no-proxy-selected',
            proxyVariable: null,
        };
    if (isEmptyish(proxy.raw)) {
        return {
            ok: true,
            route: 'direct',
            basis: 'no-proxy-selected',
            proxyVariable: proxy.name,
        };
    }
    // The variable the host consults, even when its value turns out to be empty:
    // a quoted-empty no_proxy still shadows NO_PROXY, and the advice must say so.
    const exclusion = selectLowerThenUpper(env, 'no_proxy', 'NO_PROXY');
    const exclusionVariable = exclusion?.name ?? null;
    if (!isSupportedProxyUrl(proxy.raw)) {
        return refuse('c-proxy-not-url', proxy.name, exclusionVariable);
    }
    if (exclusion === null || isEmptyish(exclusion.raw)) {
        return refuse('a-no-loopback-exclusion', proxy.name, exclusionVariable);
    }
    let loopbackAttempt = false;
    for (const item of exclusion.raw.split(',')) {
        const entry = trimEntry(item);
        if (entry === '')
            continue;
        const form = directFormOf(entry, bridgePort);
        if (form !== null) {
            return {
                ok: true,
                route: 'direct',
                basis: 'excluded',
                proxyVariable: proxy.name,
                exclusionVariable: exclusion.name,
                directForm: form,
            };
        }
        if (looksLikeLoopback(entry))
            loopbackAttempt = true;
    }
    return refuse(loopbackAttempt ? 'd-loopback-entry-not-direct' : 'a-no-loopback-exclusion', proxy.name, exclusionVariable);
}
/**
 * Assertion form for host-hook wiring: returns the allowed decision, or throws
 * {@link LoopbackProxyGuardError} so the hook can stop the request before any
 * rewrite.
 */
export function assertLoopbackProxyGuard(input) {
    const decision = evaluateLoopbackProxyGuard(input);
    if (!decision.ok)
        throw new LoopbackProxyGuardError(decision);
    return decision;
}
//# sourceMappingURL=proxy-guard.js.map