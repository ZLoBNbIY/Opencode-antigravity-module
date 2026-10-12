/**
 * OpenCode 2 (2.0.22) server plugin. It sends the host's Google model
 * requests for this plugin's models to Antigravity accounts through a
 * loopback bridge, and serves the `antigravity-auth` v1 RPC with each
 * location's account state and commands. `createGaAntigravityPlugin` is the
 * plugin the host loads; `createGaPluginFromServices` builds one over a
 * given location-services factory. Host SDK imports are type-only.
 */
import { randomUUID } from 'node:crypto';
import { createServer, } from 'node:http';
import { buildAntigravityHarnessUserAgent, fetchWithAgyCliTransport, getPublicModelDefinitions, loadCommonAuthCommands, } from '@cortexkit/antigravity-auth-core';
import { createGaLocationServices } from "../../plugin/ga-location-services.js";
import { createLocationRuntime, } from "../../plugin/shared/runtime.js";
import { redactAccountForSidebar, } from "../../sidebar-state.js";
import { assertLoopbackProxyGuard, } from "../proxy-guard.js";
import { ANTIGRAVITY_MENU_COMMAND_NAME, ANTIGRAVITY_RPC_DEFINITION, ANTIGRAVITY_RPC_LIMITS, ANTIGRAVITY_RPC_VERSION, AntigravityApplyInputSchema, AntigravityApplyOutputSchema, AntigravityApplyResultSchema, AntigravityNotificationPayloadSchema, AntigravityStateInputSchema, AntigravityStateOutputSchema, } from "../rpc/protocol.js";
import { registerGaVaultActivation } from "./auth.js";
// Raw request sender
/**
 * How long a response body may stall with no bytes before the raw sender
 * destroys the socket: five minutes, unchanged from the retired OpenCode 2
 * beta adapter this plugin replaces.
 */
export const GA_RAW_IDLE_TIMEOUT_MS = 300_000;
/** The Antigravity streaming endpoint path appended to an endpoint origin. */
export const GA_STREAM_PATH = '/v1internal:streamGenerateContent?alt=sse';
/**
 * Choose the dispatch for one activation. With a `send` override, requests
 * go to it and the observer is never called. Otherwise each request builds
 * one transport-options object, hands its `signal` property to the observer
 * synchronously, and passes that same object to the unchanged production
 * sender. The observer cannot change the dispatch: its result is ignored
 * and a synchronous throw is swallowed.
 */
export function createGaRawSender(overrides = {}) {
    const send = overrides.send;
    if (send)
        return (input) => send(input);
    const observe = overrides.observeRawSenderSignal;
    return (input) => {
        const transportOptions = {
            signal: input.signal,
            idleTimeoutMs: GA_RAW_IDLE_TIMEOUT_MS,
        };
        if (observe) {
            try {
                observe(transportOptions.signal);
            }
            catch {
                // A diagnostic failure must not change or delay the dispatch.
            }
        }
        return fetchWithAgyCliTransport(`${input.endpoint}${GA_STREAM_PATH}`, {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${input.auth.access}`,
                'Content-Type': 'application/json',
                'Accept-Encoding': 'gzip',
                'User-Agent': buildAntigravityHarnessUserAgent(),
            },
            body: JSON.stringify(input.envelope),
        }, transportOptions);
    };
}
// Loopback bridge
/**
 * Native Google content requests the request hook may rewrite: POST to
 * `…/models/<id>:generateContent` or `…:streamGenerateContent`.
 */
export const GA_GOOGLE_CONTENT_PATH = /^\/[^?#]*\/models\/[^/:]+:(generateContent|streamGenerateContent)$/;
const BRIDGE_HOST = '127.0.0.1';
/**
 * Job ids are lowercase RFC 4122 UUIDs. End-to-end tests that measure how the
 * host sends the rewritten request match its path against
 * `^/agy/[0-9a-f-]{36}$` (`packages/e2e-tests/docker/ga-loopback-request-contract.ts`),
 * so a different id format would no longer be recognised as a bridge job.
 */
const JOB_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const JOB_PATH_PATTERN = /^\/agy\/([^/]+)$/;
/** A registered job the host never dispatched is dropped after this long. */
export const GA_UNCLAIMED_JOB_TTL_MS = 60_000;
export function isGaGoogleContentRequest(request) {
    if (request.method !== 'POST')
        return false;
    try {
        return GA_GOOGLE_CONTENT_PATH.test(new URL(request.url).pathname);
    }
    catch {
        return false;
    }
}
/** The HTTP 502 answer for a terminal failure before upstream headers. */
export function gaPreHeaderFailureResponse(error) {
    const message = error instanceof Error && error.message
        ? error.message
        : 'Antigravity request failed before a response arrived';
    return new Response(JSON.stringify({ error: { code: 502, message, status: 'UNAVAILABLE' } }), { status: 502, headers: { 'content-type': 'application/json' } });
}
export async function startGaLoopbackBridge(options) {
    const queued = new Map();
    const running = new Set();
    const sockets = new Set();
    // Post-header failures by job id, held until the job's adapted response
    // reads them or the hold expires.
    const failures = new Map();
    const recordFailure = (id, error) => {
        const timer = setTimeout(() => failures.delete(id), GA_UNCLAIMED_JOB_TTL_MS);
        timer.unref?.();
        failures.set(id, { error, timer });
    };
    const takeFailure = (id) => {
        const entry = failures.get(id);
        if (!entry)
            return undefined;
        clearTimeout(entry.timer);
        failures.delete(id);
        return entry.error;
    };
    let disposal = null;
    const report = (message) => {
        try {
            options.onError?.(message);
        }
        catch {
            // Reporting is best-effort.
        }
    };
    const server = createServer((request, response) => {
        void handle(request, response).catch((error) => {
            report(`bridge request failed: ${errorMessage(error)}`);
            if (!response.headersSent) {
                writeResponseHead(response, 500, 'application/json');
                response.end(JSON.stringify({ error: { message: 'bridge failure' } }));
            }
            else {
                response.destroy();
            }
        });
    });
    server.on('connection', (socket) => {
        sockets.add(socket);
        socket.once('close', () => sockets.delete(socket));
    });
    const handle = async (request, response) => {
        const match = JOB_PATH_PATTERN.exec(new URL(request.url ?? '/', 'http://bridge').pathname);
        const candidate = match?.[1];
        const id = candidate !== undefined && isGaJobId(candidate) ? candidate : null;
        const entry = id ? queued.get(id) : undefined;
        // The body is always `{}`; read and ignore it so the socket stays usable.
        request.resume();
        if (request.method !== 'POST' || !id || !entry || disposal) {
            writeResponseHead(response, 404, 'application/json');
            response.end(JSON.stringify({ error: { message: 'unknown job' } }));
            return;
        }
        // A job runs at most once.
        queued.delete(id);
        clearTimeout(entry.timer);
        const controller = new AbortController();
        running.add(controller);
        response.once('close', () => {
            if (!response.writableFinished) {
                controller.abort(new Error('The host closed the loopback request'));
            }
        });
        try {
            let upstream;
            try {
                upstream = await options.execute(entry.job, {
                    signal: controller.signal,
                    send: options.send,
                });
            }
            catch (error) {
                upstream = gaPreHeaderFailureResponse(error);
            }
            await pipeResponse(upstream, response, (error) => recordFailure(id, error));
        }
        finally {
            running.delete(controller);
        }
    };
    await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(0, BRIDGE_HOST, () => {
            server.off('error', reject);
            resolve();
        });
    });
    // The bridge must never be what keeps an idle host process alive.
    server.unref();
    const address = server.address();
    const origin = `http://${BRIDGE_HOST}:${address.port}`;
    return {
        port: address.port,
        origin,
        rewrite(original, job, env) {
            if (disposal)
                throw new Error('The Antigravity bridge is disposed');
            const id = randomUUID();
            const target = `${origin}/agy/${id}`;
            assertLoopbackProxyGuard({ env, target });
            const timer = setTimeout(() => {
                queued.delete(id);
            }, GA_UNCLAIMED_JOB_TTL_MS);
            timer.unref?.();
            queued.set(id, { job, timer });
            return new Request(target, {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                body: '{}',
                signal: original.signal,
            });
        },
        adaptResponse(request, response) {
            let url;
            try {
                url = new URL(request.url);
            }
            catch {
                return null;
            }
            if (url.origin !== origin)
                return null;
            const candidate = JOB_PATH_PATTERN.exec(url.pathname)?.[1];
            if (candidate === undefined || !isGaJobId(candidate))
                return null;
            const id = candidate;
            const source = response.body;
            if (!source)
                return null;
            const reader = source.getReader();
            const body = new ReadableStream({
                async pull(controller) {
                    try {
                        const { done, value } = await reader.read();
                        if (done) {
                            // The bridge ends a failed job's loopback body cleanly after
                            // its last byte and records the failure first, so the end of
                            // the body is where the genuine error is delivered.
                            const failure = takeFailure(id);
                            if (failure)
                                controller.error(failure);
                            else
                                controller.close();
                            return;
                        }
                        controller.enqueue(value);
                    }
                    catch (error) {
                        controller.error(takeFailure(id) ?? error);
                    }
                },
                cancel(reason) {
                    takeFailure(id);
                    return reader.cancel(reason);
                },
            });
            return new Response(body, {
                status: response.status,
                statusText: response.statusText,
                headers: response.headers,
            });
        },
        pendingJobs: () => queued.size + running.size,
        dispose() {
            if (!disposal) {
                disposal = (async () => {
                    for (const { timer } of queued.values())
                        clearTimeout(timer);
                    queued.clear();
                    for (const { timer } of failures.values())
                        clearTimeout(timer);
                    failures.clear();
                    const closed = new Promise((resolve) => {
                        server.close(() => resolve());
                    });
                    for (const controller of running) {
                        controller.abort(new Error('The Antigravity activation was disposed'));
                    }
                    for (const socket of sockets)
                        socket.destroy();
                    await closed;
                })();
            }
            return disposal;
        },
    };
}
/** Accept only job IDs produced by request rewrite. */
export function isGaJobId(value) {
    return JOB_ID_PATTERN.test(value);
}
function writeResponseHead(response, status, contentType) {
    response.writeHead(status, {
        'content-type': contentType,
        'cache-control': 'no-cache',
    });
}
/**
 * Stream a Response to the loopback client. Bytes pass through unchanged,
 * except that an event stream ending without its final blank line gets one,
 * so the host's SSE reader sees the last frame.
 *
 * When the upstream body fails, the failure is handed to `onFailure` first,
 * and then the loopback response is ended normally: the status, the headers
 * and every byte already written still reach the host. The job's
 * `http.response` adapter turns that end into the genuine error, so the host
 * receives the real content followed by the original failure, and never a
 * fabricated success. Setup registers that adapter before the request hook,
 * so every rewritten job has it.
 *
 * The response is not destroyed on failure. Bun's `ServerResponse` calls a
 * write's callback while the bytes are still in the response's own buffer
 * (its `writableLength` has not dropped yet), and destroying it then
 * discards those bytes and the unsent headers. The host's fetch would then
 * fail with a connection reset before any response exists, and its
 * `http.response` hook would never run.
 */
async function pipeResponse(upstream, response, onFailure) {
    const contentType = upstream.headers.get('content-type') ?? 'application/octet-stream';
    writeResponseHead(response, upstream.status, contentType);
    if (!upstream.body) {
        response.end();
        return;
    }
    const eventStream = contentType.startsWith('text/event-stream');
    const reader = upstream.body.getReader();
    let tail = '';
    let wroteAny = false;
    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done)
                break;
            if (value.byteLength === 0)
                continue;
            wroteAny = true;
            if (eventStream) {
                tail = (tail + Buffer.from(value).toString('latin1')).slice(-2);
            }
            if (!response.write(value)) {
                await new Promise((resolve) => {
                    response.once('drain', resolve);
                    response.once('close', resolve);
                });
            }
            if (response.destroyed) {
                await reader.cancel().catch(() => { });
                return;
            }
        }
    }
    catch (caught) {
        const error = caught instanceof Error ? caught : new Error(String(caught));
        // The captured upstream body error is recorded before the loopback body
        // ends, so the job's `http.response` hook adapter (`adaptResponse`) finds
        // it when the host reads the end of the body and fails the read with it.
        onFailure(error);
        response.end();
        return;
    }
    if (eventStream && wroteAny && tail !== '\n\n') {
        response.write(tail.endsWith('\n') ? '\n' : '\n\n');
    }
    response.end();
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
// Setup context check
/** Context capabilities setup requires, by property path. */
export const GA_REQUIRED_CONTEXT_CAPABILITIES = [
    'location.directory',
    'session.hook',
    'rpc.register',
    'provider.transform',
    'command.transform',
];
export class GaSetupContextError extends Error {
    missing;
    name = 'GaSetupContextError';
    constructor(missing) {
        super(`OpenCode GA plugin context is missing: ${missing.join(', ')}. ` +
            'The Antigravity GA plugin cannot start in this host.');
        this.missing = missing;
    }
}
/**
 * Validate host setup capabilities before allocating resources. Only
 * `session` and `location` are read before deciding:
 * - neither present: `'legacy'`, an OpenCode 1 core loader; setup returns
 *   `undefined` with no side effect;
 * - exactly one present, or both with a required capability missing: throws
 *   `GaSetupContextError` naming what is missing;
 * - otherwise `'ga'`.
 */
export function classifyGaSetupContext(context) {
    const record = context;
    const session = record.session;
    const location = record.location;
    if (session === undefined && location === undefined)
        return 'legacy';
    const missing = [];
    if (!isObject(location) || typeof location.directory !== 'string') {
        missing.push('location.directory');
    }
    if (!isObject(session) || typeof session.hook !== 'function') {
        missing.push('session.hook');
    }
    if (session !== undefined && location !== undefined && missing.length === 0) {
        const rpc = record.rpc;
        if ((!isObject(rpc) && typeof rpc !== 'function') ||
            typeof Reflect.get(rpc, 'register') !== 'function') {
            missing.push('rpc.register');
        }
        const provider = record.provider;
        if (!isObject(provider) || typeof provider.transform !== 'function') {
            missing.push('provider.transform');
        }
        const command = record.command;
        if (!isObject(command) || typeof command.transform !== 'function') {
            missing.push('command.transform');
        }
    }
    if (missing.length > 0)
        throw new GaSetupContextError(missing);
    return 'ga';
}
function isObject(value) {
    return typeof value === 'object' && value !== null;
}
// RPC store per activation
/**
 * A new opaque generation token. Each activation gets its own, so a client
 * still holding an older activation's token is detected and reset.
 */
export function createGaGeneration() {
    return `g-${randomUUID()}`;
}
/** Raised for input that fails the portable schema; carries no input value. */
export class GaRpcInputError extends Error {
    issues;
    name = 'GaRpcInputError';
    constructor(issues) {
        super(`Invalid Antigravity RPC input: ${issues
            .map((issue) => `${issue.path.join('.') || '(root)'} ${issue.message}`)
            .join('; ')}`);
        this.issues = issues;
    }
}
/** Raised when a collaborator produced a value that fails the contract. */
export class GaRpcContractError extends Error {
    name = 'GaRpcContractError';
}
const CONNECTION_TTL_MS = 3_000;
const DEFAULT_NOTIFICATIONS_PER_SCOPE = 100;
const DEFAULT_MAX_SCOPES = 256;
function scopeKey(scope) {
    return scope.kind === 'session' ? `session:${scope.sessionID}` : 'sessionless';
}
function routeDto(entry) {
    if (!entry)
        return null;
    return {
        accountId: entry.accountId,
        modelFamily: entry.modelFamily,
        headerStyle: entry.headerStyle,
        strategy: entry.strategy ?? null,
        updatedAt: entry.updatedAt,
    };
}
export function createGaRpcActivation(options) {
    const generation = options.generation ?? createGaGeneration();
    const now = options.now ?? Date.now;
    const perScope = options.notificationsPerScope ?? DEFAULT_NOTIFICATIONS_PER_SCOPE;
    const maxScopes = options.maxScopes ?? DEFAULT_MAX_SCOPES;
    const scopes = new Map();
    const running = new Set();
    let lastReadSeq = 0;
    let disposed = false;
    let disposal = null;
    const disposedOutput = () => ({
        version: ANTIGRAVITY_RPC_VERSION,
        kind: 'disposed',
        generation,
    });
    const queueFor = (scope) => {
        const key = scopeKey(scope);
        let queue = scopes.get(key);
        if (queue) {
            // Refresh recency so the least recently used scope is evicted first.
            scopes.delete(key);
        }
        else {
            queue = {
                lastIssued: 0,
                evictedThrough: 0,
                notifications: [],
                lastPullAt: 0,
            };
        }
        scopes.set(key, queue);
        while (scopes.size > maxScopes) {
            const oldest = scopes.keys().next().value;
            if (oldest === undefined)
                break;
            scopes.delete(oldest);
        }
        return queue;
    };
    /**
     * Run one collaborator call that disposal aborts and waits for. The host
     * call's own signal is forwarded, so a client that leaves aborts it too.
     */
    const track = async (signal, run) => {
        const controller = new AbortController();
        const forward = () => controller.abort(signal?.reason);
        if (signal?.aborted)
            forward();
        else
            signal?.addEventListener('abort', forward, { once: true });
        const done = run(controller.signal);
        const entry = { controller, done };
        running.add(entry);
        try {
            return await done;
        }
        finally {
            running.delete(entry);
            signal?.removeEventListener('abort', forward);
        }
    };
    const accountsDto = (accounts) => {
        if (accounts.kind === 'over-limit') {
            return {
                accountsStatus: {
                    kind: 'over-limit',
                    count: accounts.count,
                    limit: ANTIGRAVITY_RPC_LIMITS.accounts,
                },
                accounts: [],
            };
        }
        // A complete read longer than the wire limit would have to be shortened;
        // the source must report it as over the limit instead.
        if (accounts.rows.length > ANTIGRAVITY_RPC_LIMITS.accounts) {
            throw new GaRpcContractError('State source returned more accounts than the limit');
        }
        return {
            accountsStatus: { kind: 'complete' },
            accounts: accounts.rows.map(({ selector, row }) => ({
                selector,
                ...redactAccountForSidebar(row),
            })),
        };
    };
    const state = async (input, signal) => {
        const parsed = AntigravityStateInputSchema.parse(input);
        if (!parsed.ok)
            throw new GaRpcInputError(parsed.issues);
        if (disposed)
            return disposedOutput();
        const request = parsed.value;
        const read = await track(signal, (readSignal) => options.state.read({ scope: request.scope, signal: readSignal }));
        // A read that finishes after disposal is not reported.
        if (disposed)
            return disposedOutput();
        if (!Number.isSafeInteger(read.readSeq) || read.readSeq <= lastReadSeq) {
            throw new GaRpcContractError('State source returned a stale readSeq');
        }
        lastReadSeq = read.readSeq;
        const queue = queueFor(request.scope);
        queue.lastPullAt = now();
        let reset = null;
        if (request.generation === null)
            reset = 'initial';
        else if (request.generation !== generation)
            reset = 'generation-changed';
        else if (request.cursor > queue.lastIssued)
            reset = 'cursor-ahead';
        const acknowledged = reset === null ? request.cursor : 0;
        // Acknowledged notifications are no longer retained.
        queue.notifications = queue.notifications.filter((notification) => notification.cursor > acknowledged);
        const delivered = queue.notifications.slice(0, ANTIGRAVITY_RPC_LIMITS.notificationsPerState);
        const last = delivered.at(-1);
        const cursor = last
            ? last.cursor
            : Math.max(acknowledged, queue.evictedThrough);
        const output = {
            version: ANTIGRAVITY_RPC_VERSION,
            kind: 'snapshot',
            generation,
            scope: request.scope,
            reset,
            cursor,
            dropped: Math.max(0, queue.evictedThrough - acknowledged),
            more: queue.notifications.length > delivered.length,
            notifications: delivered,
            readSeq: read.readSeq,
            ...accountsDto(read.accounts),
            route: request.scope.kind === 'session' ? routeDto(read.route) : null,
            status: read.status,
            settings: read.settings,
        };
        const checked = AntigravityStateOutputSchema.parse(output);
        if (!checked.ok) {
            throw new GaRpcContractError('State source produced an invalid snapshot');
        }
        return output;
    };
    const apply = async (input, signal) => {
        const parsed = AntigravityApplyInputSchema.parse(input);
        if (!parsed.ok)
            throw new GaRpcInputError(parsed.issues);
        if (disposed)
            return disposedOutput();
        const request = parsed.value;
        if (request.generation !== generation) {
            return {
                version: ANTIGRAVITY_RPC_VERSION,
                kind: 'stale-generation',
                generation,
            };
        }
        const menuRequest = options.parseApplyRequest({
            ...request.request,
            ...(request.scope.kind === 'session'
                ? { sessionId: request.scope.sessionID }
                : {}),
        });
        if (!menuRequest) {
            throw new GaRpcInputError([
                { path: ['request'], message: 'not a menu action the menu accepts' },
            ]);
        }
        const result = await track(signal, (applySignal) => options.commands.apply({
            request: menuRequest,
            scope: request.scope,
            signal: applySignal,
        }));
        // A completion that arrives after disposal is not reported as applied.
        if (disposed)
            return disposedOutput();
        const checked = AntigravityApplyResultSchema.parse(result);
        if (!checked.ok || result.command !== ANTIGRAVITY_MENU_COMMAND_NAME) {
            throw new GaRpcContractError('Command service produced a result that is not a menu answer');
        }
        const output = {
            version: ANTIGRAVITY_RPC_VERSION,
            kind: 'applied',
            generation,
            scope: request.scope,
            result,
        };
        if (!AntigravityApplyOutputSchema.parse(output).ok) {
            throw new GaRpcContractError('Apply output failed the contract');
        }
        return output;
    };
    return {
        generation,
        handlers: { state, apply },
        notify(scope, payload) {
            if (disposed)
                return null;
            if (!AntigravityNotificationPayloadSchema.parse(payload).ok) {
                throw new GaRpcContractError('Notification payload failed the contract');
            }
            const queue = queueFor(scope);
            queue.lastIssued += 1;
            const cursor = queue.lastIssued;
            queue.notifications.push({ cursor, payload });
            while (queue.notifications.length > perScope) {
                const evicted = queue.notifications.shift();
                if (evicted)
                    queue.evictedThrough = evicted.cursor;
            }
            try {
                options.onChanged?.({ version: ANTIGRAVITY_RPC_VERSION, generation });
            }
            catch {
                // The event is a wake-up hint; clients still pull on their timer.
            }
            return cursor;
        },
        isConnected(scope) {
            if (disposed)
                return false;
            const queue = scopes.get(scopeKey(scope));
            return (queue !== undefined &&
                queue.lastPullAt > 0 &&
                now() - queue.lastPullAt < CONNECTION_TTL_MS);
        },
        get disposed() {
            return disposed;
        },
        dispose() {
            if (!disposal) {
                disposed = true;
                disposal = (async () => {
                    scopes.clear();
                    const pending = [...running];
                    for (const entry of pending) {
                        entry.controller.abort(new Error('The Antigravity activation was disposed'));
                    }
                    await Promise.allSettled(pending.map((entry) => entry.done));
                })();
            }
            return disposal;
        },
    };
}
// Host binding
/** The plugin id this adapter registers with the host. */
export const GA_PLUGIN_ID = 'cortexkit.antigravity-auth';
/** The host provider whose requests the hooks handle. */
export const GA_PROVIDER_ID = 'google';
const REQUEST_KIND_MATCHES_HOST = true;
void REQUEST_KIND_MATCHES_HOST;
/** Session headers the host sets on a model request. */
const PARENT_SESSION_HEADERS = [
    'x-opencode-parent-session-id',
    'x-parent-session-id',
];
/**
 * Whether the plugin owns a Google request: every title request (the host
 * may pick an off-catalog title model) and any request for a model this
 * plugin registered. Everything else passes through untouched.
 */
export function isGaOwnedRequest(event, isRegisteredModel) {
    // The hooks are registered for the Google provider only; the provider
    // check repeats that scope so a host that widened it still passes other
    // providers through untouched.
    if (event.model.providerID !== GA_PROVIDER_ID)
        return false;
    return event.kind === 'title' || isRegisteredModel(event.model.id);
}
/**
 * Request hook body: record an owned Google content request as a bridge job
 * and replace it with the bridge request. The original body is read from a
 * clone, so the host's request is never consumed when the rewrite is
 * refused. A proxy-guard refusal throws before any replacement; the host
 * then records it as the request's error and dispatches nothing.
 */
export async function rewriteGaHttpRequest(event, input) {
    if (!isGaOwnedRequest(event, input.isRegisteredModel))
        return;
    const original = event.request;
    if (!isGaGoogleContentRequest(original))
        return;
    const job = {
        sessionID: event.sessionID,
        parentSessionID: headerValue(original, PARENT_SESSION_HEADERS),
        kind: event.kind,
        modelID: event.model.id,
        variant: event.model.variant ?? null,
        url: original.url,
        body: await original.clone().text(),
    };
    event.request = input.bridge.rewrite(original, job, input.env);
}
/** Adapt only responses whose request belongs to a recognized bridge job. */
export function adaptGaHttpResponse(event, bridge) {
    const adapted = bridge.adaptResponse(event.request, event.response);
    if (adapted)
        event.response = adapted;
}
/**
 * Retry hook body. The bridge's job runner rotates accounts and retries
 * endpoints itself; a host retry on top would repeat that whole sequence.
 * Only this plugin's registered models are affected.
 */
export function decideGaRetry(event, isRegisteredModel) {
    if (event.model.providerID === GA_PROVIDER_ID &&
        isRegisteredModel(event.model.id)) {
        event.decision = { retry: false };
    }
}
// Model registration
/**
 * Convert one shared public catalog entry to the host's model record for the
 * Google provider. Only enabled variants are offered; a variant carries only
 * its id, which reaches the request hook as the model reference's `variant`
 * and is resolved by the request pipeline, the same way the OpenCode 1
 * adapter resolves variant suffixes. Title wire aliases are not catalog
 * entries and are never registered.
 *
 * The host's branded id types are plain strings at runtime. This module
 * loads no host schema code, so the brands are applied by type assertion on
 * values taken from the shared catalog.
 */
export function toGaModelInfo(id, definition) {
    const variants = Object.entries(definition.variants ?? {})
        .filter(([, variant]) => variant.disabled !== true)
        .map(([variantID]) => ({ id: variantID }));
    const released = Date.parse(definition.release_date);
    return {
        id: id,
        modelID: id,
        providerID: GA_PROVIDER_ID,
        name: definition.name,
        capabilities: {
            tools: definition.tool_call,
            input: [...definition.modalities.input],
            output: [...definition.modalities.output],
        },
        variants,
        time: { released: Number.isFinite(released) ? released : 0 },
        cost: [],
        status: 'active',
        enabled: true,
        limit: {
            context: definition.limit.context,
            output: definition.limit.output,
        },
    };
}
/** The host records for every public catalog model, keyed by model id. */
export function gaCatalogModels() {
    return new Map(Object.entries(getPublicModelDefinitions()).map(([id, definition]) => [
        id,
        toGaModelInfo(id, definition),
    ]));
}
/**
 * Provider transform body: add the catalog models to the Google provider,
 * keeping every model the provider already has under another id. When the
 * host has no Google provider record, nothing is registered.
 */
export function registerGaModels(editor, catalog) {
    const record = editor.get(GA_PROVIDER_ID);
    if (!record)
        return;
    const kept = [...record.models.values()].filter((model) => !catalog.has(model.id));
    editor.models.set(GA_PROVIDER_ID, [...kept, ...catalog.values()]);
}
/**
 * Writes a location's log records to stderr: the OpenCode 2 plugin context
 * offers plugins no log sink.
 */
function stderrLogSink(record) {
    try {
        process.stderr.write(`[antigravity] ${record.level} ${record.service}: ${record.message}\n`);
    }
    catch {
        // Logging must never break a request.
    }
}
function headerValue(request, names) {
    for (const name of names) {
        const value = request.headers.get(name);
        if (value)
            return value;
    }
    return null;
}
/**
 * Set up one activation. Returns `undefined` with no side effect for a
 * legacy context without `session` and `location`, and throws
 * `GaSetupContextError` for a partial one. Otherwise it builds the services,
 * the location runtime, the RPC activation and the loopback bridge for the
 * host-owned location directory; registers the `antigravity-auth` RPC, the
 * public catalog models on the Google provider, the `http.request` rewrite,
 * the `http.response` post-header error adapter and the registered-model
 * retry policy (all scoped to the Google provider);
 * and returns a Cleanup that removes only this activation's hooks and RPC
 * and stops everything else: producers are stopped and awaited, queued
 * quota snapshot writes drain, and then the remaining handles close.
 *
 * Any failure before the Cleanup is returned releases everything acquired
 * so far before the error propagates, so a failed setup leaves no hook,
 * port, timer or file handle behind.
 */
export async function setupGaActivation(context, factory, overrides = {}) {
    if (classifyGaSetupContext(context) === 'legacy')
        return undefined;
    const directory = context.location.directory;
    const send = createGaRawSender(overrides);
    const services = await factory({
        directory,
        overrides,
        ...(context.integration && { connections: context.integration.connection }),
    });
    const runtime = await createLocationRuntime({
        ...services.runtime,
        directory,
        logSink: stderrLogSink,
    }, services);
    // Everything below is registered on the runtime scope as a producer. The
    // scope stops producers newest first, so teardown runs: request, retry
    // and response hooks, model registration, RPC, activation, bridge,
    // quota and token-refresh tasks, then account services; queued snapshot
    // writes drain and the runtime's files and handles close.
    try {
        if (context.integration?.transform) {
            runtime.scope.add(await registerGaVaultActivation({
                integration: { transform: context.integration.transform },
            }), 'producer');
        }
        let serving = null;
        const requireServing = () => {
            if (!serving)
                throw new Error('Antigravity services are not started');
            return serving;
        };
        let rpcRegistration = null;
        const commandsModule = await loadCommonAuthCommands();
        const activation = createGaRpcActivation({
            state: {
                read: (input) => requireServing().state.read(input),
            },
            commands: {
                apply: (request) => requireServing().commands.apply(request),
            },
            parseApplyRequest: commandsModule.parseApplyRequest,
            onChanged: (event) => {
                void rpcRegistration?.events.emit('changed', event).catch(() => {
                    // A missed changed notification delays the client's next state request.
                });
            },
        });
        serving = await services.start({
            runtime,
            generation: activation.generation,
            send,
            notify: activation.notify,
            isConnected: activation.isConnected,
        });
        const started = serving;
        const catalog = gaCatalogModels();
        const isRegisteredModel = (modelID) => catalog.has(modelID);
        const bridge = await startGaLoopbackBridge({
            execute: started.execute,
            send,
            onError: (message) => runtime.logger.createLogger('bridge').warn(message),
        });
        runtime.scope.add(bridge, 'producer');
        runtime.scope.add(activation, 'producer');
        const handlers = {
            state: (input, call) => activation.handlers.state(input, call.signal),
            apply: (input, call) => activation.handlers.apply(input, call.signal),
        };
        rpcRegistration = await context.rpc.register(ANTIGRAVITY_RPC_DEFINITION, handlers);
        runtime.scope.add(rpcRegistration, 'producer');
        const modelRegistration = await context.provider.transform((editor) => registerGaModels(editor, catalog));
        runtime.scope.add(modelRegistration, 'producer');
        await context.provider.reload();
        // The native `/antigravity` command opens the menu in the session that
        // ran it. Its runs stop starting new work once the activation is torn
        // down: the abort is registered before the command, so teardown (newest
        // first) removes the command, then aborts what is still running.
        const commandRuns = new AbortController();
        runtime.scope.add({
            dispose: async () => {
                commandRuns.abort(new Error('The Antigravity activation was disposed'));
            },
        }, 'producer');
        const commandRegistration = await context.command.transform((editor) => editor.add({
            name: ANTIGRAVITY_MENU_COMMAND_NAME,
            description: 'Open the Antigravity menu: accounts, quota, routing, limits and diagnostics.',
            execute: ({ sessionID }) => started.commands.open({
                scope: { kind: 'session', sessionID },
                signal: commandRuns.signal,
            }),
        }));
        runtime.scope.add(commandRegistration, 'producer');
        await context.command.reload();
        const responseHook = await context.session.hook('http.response', (event) => adaptGaHttpResponse(event, bridge), { providerID: GA_PROVIDER_ID });
        runtime.scope.add(responseHook, 'producer');
        const retryHook = await context.session.hook('retry', (event) => decideGaRetry(event, isRegisteredModel), { providerID: GA_PROVIDER_ID });
        runtime.scope.add(retryHook, 'producer');
        // The `http.request` hook, which rewrites requests to the bridge, is
        // installed last, so every request it rewrites already has the
        // `http.response` adapter and the retry policy in place. Teardown removes
        // producers newest first, so this hook is removed first.
        const requestHook = await context.session.hook('http.request', (event) => rewriteGaHttpRequest(event, {
            bridge,
            isRegisteredModel,
            env: process.env,
        }), { providerID: GA_PROVIDER_ID });
        runtime.scope.add(requestHook, 'producer');
    }
    catch (error) {
        await runtime.dispose().catch(() => {
            // Preserve the initialization error if disposal also throws.
        });
        throw error;
    }
    let cleanup = null;
    return () => {
        cleanup ??= runtime.dispose();
        return cleanup;
    };
}
/** Build the OpenCode 2 plugin over the given services factory. */
export function createGaPluginFromServices(factory, overrides = {}) {
    return {
        id: GA_PLUGIN_ID,
        setup: (context) => setupGaActivation(context, factory, overrides),
    };
}
/**
 * The plugin the OpenCode 2 host loads: setup over the production location
 * services (`createGaLocationServices`), which open the location's account
 * store, keep its quota snapshots in memory and run the shared request
 * pipeline. `overrides` exist for tests; the host passes none.
 */
export function createGaAntigravityPlugin(overrides = {}) {
    return createGaPluginFromServices(createGaLocationServices, overrides);
}
//# sourceMappingURL=index.js.map