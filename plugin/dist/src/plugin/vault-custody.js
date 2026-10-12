/**
 * Vault custody for the OpenCode host (OpenCode 1 and OpenCode 2 locations
 * alike): whether Antigravity accounts are served from the plugin's own
 * account store ("local") or from the Claustrum vault ("custody"), the
 * setup steps that switch between them, and the vault account source the
 * custody request path uses.
 *
 * Everything lives in an owner-only `antigravity-auth-vault` directory
 * beside the resolved account file: the non-secret mode file, the vault
 * roster and this host's enrollment files (written by the vault library).
 * The mode file holds only the mode; no token, project or account data is
 * written here. A missing mode file is local mode, so nothing connects to
 * the vault and no source starts while local custody is in force.
 *
 * Every custody entry re-reads the mode and checks the host's own auth slot
 * against it through the vault library: a real host login while the vault
 * holds the accounts refuses custody instead of silently picking one of the
 * two. The host supplies a reader for its slot; a slot that cannot be read
 * refuses custody rather than being treated as empty.
 */
import { chmod, mkdir, readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { createAntigravityVaultAccountSource, enrollmentAuthority, getAntigravityVaultEnrollmentName, loadCommonAuthClaustrum, loadCommonAuthFs, readVaultProviderState, resolveClaustrumConnectionPath, VAULT_ACCOUNT_REMEDY, } from '@cortexkit/antigravity-auth-core';
import { writeJsonAtomic } from '@cortexkit/antigravity-auth-core/atomic-write';
/** The host auth slot this plugin's provider lives in on OpenCode. */
export const OPENCODE_VAULT_PROVIDER = 'google';
/** The vault host name; one enrollment per host. */
export const OPENCODE_VAULT_HOST = 'opencode';
/** The enrollment name the vault operator sees and approves. */
export const OPENCODE_VAULT_ENROLLMENT_NAME = getAntigravityVaultEnrollmentName(OPENCODE_VAULT_HOST);
/** The vault directory's name, beside the resolved account file. */
export const OPENCODE_VAULT_DIR_NAME = 'antigravity-auth-vault';
/** The vault paths for one resolved account file. */
export function openCodeVaultPaths(accountFile) {
    const dir = join(dirname(accountFile), OPENCODE_VAULT_DIR_NAME);
    return {
        dir,
        modeFile: join(dir, 'opencode-mode.json'),
        rosterFile: join(dir, 'opencode-roster.json'),
        stateFile: join(dir, 'opencode-state.json'),
    };
}
/** Creates the vault directory readable by its owner only. */
async function ensureVaultDir(dir) {
    await mkdir(dir, { recursive: true, mode: 0o700 });
    await chmod(dir, 0o700);
}
const LOCAL_MODE = Object.freeze({
    version: 1,
    mode: 'local',
});
const CUSTODY_MODE = Object.freeze({
    version: 1,
    mode: 'custody',
});
function parseMode(raw) {
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw))
        return undefined;
    const keys = Object.keys(raw).sort();
    if (keys.length !== 2 || keys[0] !== 'mode' || keys[1] !== 'version')
        return undefined;
    if (!('version' in raw) || raw.version !== 1)
        return undefined;
    if (!('mode' in raw))
        return undefined;
    if (raw.mode === 'local')
        return LOCAL_MODE;
    if (raw.mode === 'custody')
        return CUSTODY_MODE;
    return undefined;
}
/**
 * Reads the mode file. A missing file is local mode. A file that exists but
 * cannot be read or understood is reported, never guessed: custody is then
 * refused, because the user's choice is unknown.
 */
export async function readOpenCodeVaultMode(modeFile) {
    let text;
    try {
        text = await readFile(modeFile, 'utf8');
    }
    catch (error) {
        if (typeof error === 'object' &&
            error !== null &&
            'code' in error &&
            error.code === 'ENOENT')
            return { ok: true, record: LOCAL_MODE };
        return { ok: false, reason: 'the vault mode file could not be read' };
    }
    let raw;
    try {
        raw = JSON.parse(text);
    }
    catch {
        return { ok: false, reason: 'the vault mode file is not valid JSON' };
    }
    const record = parseMode(raw);
    return record
        ? { ok: true, record }
        : { ok: false, reason: 'the vault mode file has an unknown shape' };
}
// ---------------------------------------------------------------------------
// Custody
// ---------------------------------------------------------------------------
/** A custody step refused before anything changed, with a message for the user. */
export class OpenCodeVaultCustodyError extends Error {
    constructor(message) {
        super(message);
        this.name = 'OpenCodeVaultCustodyError';
    }
}
export function createOpenCodeVaultCustody(options) {
    const paths = openCodeVaultPaths(options.accountFile);
    const loadClaustrum = options.loadClaustrum ?? loadCommonAuthClaustrum;
    const connectionFile = options.connectionFile ?? (() => resolveClaustrumConnectionPath());
    let source = null;
    let creating = null;
    const enrollmentPaths = async () => (await loadClaustrum()).hostEnrollmentPaths({
        stateDir: paths.dir,
        host: OPENCODE_VAULT_HOST,
    });
    const readEnrollment = async () => {
        const claustrum = await loadClaustrum();
        return claustrum
            .readClaustrumEnrollmentStatus(await enrollmentPaths(), OPENCODE_VAULT_ENROLLMENT_NAME)
            .catch(() => ({
            state: 'blocked',
            proposedName: OPENCODE_VAULT_ENROLLMENT_NAME,
            code: 'unreadable-state',
        }));
    };
    const requireCustodyMode = async () => {
        const mode = await custody.readMode();
        if (!mode.ok)
            throw new OpenCodeVaultCustodyError(`The vault mode is unclear (${mode.reason}). Choose a mode in the Vault section of the Antigravity menu.`);
        if (mode.record.mode !== 'custody')
            throw new OpenCodeVaultCustodyError('Antigravity accounts are not served from the vault.');
    };
    const closeSource = async () => {
        const pending = creating;
        creating = null;
        const current = source ?? (await pending?.catch(() => null)) ?? null;
        source = null;
        current?.close();
    };
    let observedAuthority;
    let observing = false;
    let closed = false;
    const ensureSource = async () => {
        if (closed)
            throw new OpenCodeVaultCustodyError('Vault custody is disposed');
        if (source)
            return source;
        creating ??= (async () => {
            const claustrum = await loadClaustrum();
            const { tokenPath } = await enrollmentPaths();
            const created = createAntigravityVaultAccountSource({
                claustrum,
                host: OPENCODE_VAULT_HOST,
                rosterPath: paths.rosterFile,
                tokenPath,
                connect: options.connect ??
                    (async () => claustrum.connectClaustrumScopedClient({
                        connectionFile: await connectionFile(),
                    })),
                isCustodyActive: async () => {
                    const mode = await custody.readMode();
                    const authority = !mode.ok
                        ? 'unreadable'
                        : mode.record.mode === 'custody'
                            ? 'vault'
                            : 'local';
                    if (authority !== observedAuthority) {
                        observedAuthority = authority;
                        options.onAuthorityChanged?.(authority);
                    }
                    if (authority !== 'vault')
                        return false;
                    return (await readEnrollment()).state === 'approved';
                },
                onRoster: () => options.onRosterChanged?.(),
                onError: () => options.onRosterChanged?.(),
                reporterSource: options.reporterSource,
                state: { path: paths.stateFile, fs: await loadCommonAuthFs() },
                ...(options.logger ? { logger: options.logger } : {}),
                ...(options.now ? { now: options.now } : {}),
            });
            source = created;
            created.start();
            return created;
        })();
        try {
            return await creating;
        }
        catch (error) {
            creating = null;
            throw error;
        }
    };
    const custody = {
        paths,
        async startObservation() {
            observing = true;
            await ensureSource();
        },
        async readMode() {
            const authority = await enrollmentAuthority(await enrollmentPaths(), OPENCODE_VAULT_ENROLLMENT_NAME, await loadClaustrum());
            if (authority === 'unreadable')
                return { ok: false, reason: VAULT_ACCOUNT_REMEDY };
            return {
                ok: true,
                record: authority === 'vault' ? CUSTODY_MODE : LOCAL_MODE,
            };
        },
        async custodySource() {
            await requireCustodyMode();
            return ensureSource();
        },
        async status() {
            const mode = await custody.readMode();
            const claustrum = await loadClaustrum();
            let hostSlot;
            try {
                hostSlot =
                    !mode.ok || mode.record.mode === 'custody'
                        ? 'not-used'
                        : claustrum.classifyHostSlot(await options.readHostSlot(), OPENCODE_VAULT_PROVIDER);
            }
            catch {
                hostSlot = 'unreadable';
            }
            return {
                ...(mode.ok
                    ? { mode: mode.record.mode }
                    : { mode: 'unreadable', modeProblem: mode.reason }),
                enrollment: await readEnrollment(),
                hostSlot,
            };
        },
        async requestAccess() {
            const claustrum = await loadClaustrum();
            await ensureVaultDir(paths.dir);
            const client = await (options.connectEnrollment
                ? options.connectEnrollment()
                : claustrum.connectClaustrumEnrollmentClient({
                    connectionFile: await connectionFile(),
                }));
            try {
                const manager = new claustrum.ClaustrumEnrollmentManager({
                    client,
                    paths: await enrollmentPaths(),
                    proposedName: OPENCODE_VAULT_ENROLLMENT_NAME,
                    ...(options.now ? { now: options.now } : {}),
                });
                const current = await manager.status();
                if (current.state === 'denied' || current.state === 'blocked')
                    await manager.resetTerminal();
                return await manager.reconcile();
            }
            finally {
                client.close();
            }
        },
        async useVault() {
            const enrollment = await readEnrollment();
            if (enrollment.state !== 'approved')
                throw new OpenCodeVaultCustodyError('OpenCode is not enrolled with the vault yet. Request access and wait for the operator to approve it first.');
            await ensureVaultDir(paths.dir);
            await writeJsonAtomic(paths.modeFile, CUSTODY_MODE);
        },
        async useLocal() {
            const claustrum = await loadClaustrum();
            const disconnected = await claustrum.disconnectClaustrumEnrollment(await enrollmentPaths(), OPENCODE_VAULT_ENROLLMENT_NAME);
            if (disconnected === 'busy')
                throw new OpenCodeVaultCustodyError('Vault enrollment is busy. Disconnect after the current enrollment operation finishes.');
            if (!observing)
                await closeSource();
            await ensureVaultDir(paths.dir);
            await writeJsonAtomic(paths.modeFile, LOCAL_MODE);
            if (observing)
                await source?.refresh();
        },
        menuSection() {
            return {
                id: 'vault',
                title: 'Vault',
                build: async () => {
                    const status = await custody.status();
                    const actions = [
                        {
                            id: 'request-access',
                            label: status.enrollment.state === 'pending'
                                ? 'Check vault approval'
                                : 'Request vault access',
                            run: async () => `Vault access: ${describeEnrollment(await custody.requestAccess())}`,
                        },
                    ];
                    if (status.mode !== 'custody')
                        actions.push({
                            id: 'use-vault',
                            label: 'Serve accounts from the vault',
                            run: async () => refusalOr(() => custody.useVault()),
                        });
                    if (status.mode !== 'local')
                        actions.push({
                            id: 'use-local',
                            label: 'Disconnect vault and restore local accounts',
                            run: async () => refusalOr(() => custody.useLocal()),
                        });
                    return { lines: statusLines(status), actions };
                },
            };
        },
        readState: () => readVaultProviderState(paths.stateFile),
        dispose: async () => {
            closed = true;
            await closeSource();
        },
    };
    return custody;
}
async function refusalOr(step) {
    try {
        await step();
    }
    catch (error) {
        if (error instanceof OpenCodeVaultCustodyError)
            return { ok: false, text: error.message, code: 'refused' };
        throw error;
    }
    return 'Done. Start a new request to use the change.';
}
function describeEnrollment(status) {
    switch (status.state) {
        case 'idle':
            return 'not requested';
        case 'pending':
            return status.retryCode
                ? `waiting for operator approval (retrying: ${status.retryCode})`
                : 'waiting for operator approval';
        case 'approved':
            return `approved as ${status.approvedName ?? status.proposedName}`;
        case 'denied':
            return 'denied by the operator';
        case 'blocked':
            return `blocked (${status.code})`;
        case 'unavailable':
            return `vault unavailable (${status.code})`;
        case 'busy':
            return 'another setup step is running';
    }
}
function describeHostSlot(slot) {
    switch (slot) {
        case 'login':
            return 'signed in with an OpenCode login';
        case 'placeholder':
            return 'holds the vault placeholder';
        case 'empty':
            return 'empty';
        case 'unreadable':
            return 'could not be read';
        case 'not-used':
            return 'not used in vault mode';
    }
}
/** Non-secret status lines: never a token, project or account address. */
export function statusLines(status) {
    return [
        `Mode: ${status.mode === 'custody'
            ? 'vault'
            : status.mode === 'local'
                ? 'this computer'
                : `unclear (${status.modeProblem ?? 'unknown'})`}`,
        `Vault access: ${describeEnrollment(status.enrollment)}`,
        ...(status.mode === 'local'
            ? [`OpenCode Google sign-in: ${describeHostSlot(status.hostSlot)}`]
            : []),
    ];
}
//# sourceMappingURL=vault-custody.js.map