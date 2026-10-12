import { AccountRepositoryError, sameRowRef, } from '@cortexkit/antigravity-auth-core';
import { ANTIGRAVITY_DEFAULT_PROJECT_ID, ANTIGRAVITY_ENDPOINT_PROD, } from '../constants';
import { accessBlockOf, accessVerdictFromProbe, clearLegacyAccessBlocks, markLegacyIneligible, markLegacyVerificationRequired, } from './account-blocks';
import { buildAgyAgentRequestMetadata, createAgyRequestSessionContext, orderAgyRequestPayloadInPlace, } from './agy-request-metadata';
import { fetchWithAgyCliTransport } from './agy-transport';
import { formatRefreshParts, parseRefreshParts } from './auth';
import { buildFingerprintHeaders, getSessionFingerprint } from './fingerprint';
import { AntigravityTokenRefreshError, refreshAccessToken } from './token';
function decodeEscapedText(input) {
    return input
        .replace(/&amp;/g, '&')
        .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(Number.parseInt(hex, 16)));
}
export function normalizeGoogleVerificationUrl(rawUrl) {
    const normalized = decodeEscapedText(rawUrl).trim();
    if (!normalized)
        return undefined;
    try {
        const parsed = new URL(normalized);
        if (parsed.hostname !== 'accounts.google.com')
            return undefined;
        return parsed.toString();
    }
    catch {
        return undefined;
    }
}
export function selectBestVerificationUrl(urls) {
    const unique = Array.from(new Set(urls
        .map((url) => normalizeGoogleVerificationUrl(url))
        .filter(Boolean)));
    if (unique.length === 0)
        return undefined;
    const score = (value) => {
        let total = 0;
        if (value.includes('plt='))
            total += 4;
        if (value.includes('/signin/continue'))
            total += 3;
        if (value.includes('continue='))
            total += 2;
        if (value.includes('service=cloudcode'))
            total += 1;
        return total;
    };
    unique.sort((a, b) => score(b) - score(a));
    return unique[0];
}
export function extractAccountAccessErrorDetails(bodyText) {
    const decodedBody = decodeEscapedText(bodyText);
    const lowerBody = decodedBody.toLowerCase();
    let validationRequired = lowerBody.includes('validation_required');
    const ineligiblePattern = /(^|[^a-z0-9_])account_ineligible([^a-z0-9_]|$)/i;
    let accountIneligible = ineligiblePattern.test(decodedBody);
    let message;
    const verificationUrls = new Set();
    const collectUrlsFromText = (text) => {
        for (const match of text.matchAll(/https:\/\/accounts\.google\.com\/[^\s"'<>]+/gi)) {
            if (match[0])
                verificationUrls.add(match[0]);
        }
    };
    collectUrlsFromText(decodedBody);
    const payloads = [];
    const trimmed = decodedBody.trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
        try {
            payloads.push(JSON.parse(trimmed));
        }
        catch { }
    }
    for (const rawLine of decodedBody.split('\n')) {
        const line = rawLine.trim();
        if (!line.startsWith('data:'))
            continue;
        const payloadText = line.slice(5).trim();
        if (!payloadText || payloadText === '[DONE]')
            continue;
        try {
            payloads.push(JSON.parse(payloadText));
        }
        catch {
            collectUrlsFromText(payloadText);
        }
    }
    const visited = new Set();
    const walk = (value, key) => {
        if (typeof value === 'string') {
            const normalizedValue = decodeEscapedText(value);
            const lowerValue = normalizedValue.toLowerCase();
            const lowerKey = key?.toLowerCase() ?? '';
            if (lowerValue.includes('validation_required')) {
                validationRequired = true;
            }
            if (ineligiblePattern.test(normalizedValue)) {
                accountIneligible = true;
            }
            if (!message &&
                (lowerKey.includes('message') ||
                    lowerKey.includes('detail') ||
                    lowerKey.includes('description'))) {
                message = normalizedValue;
            }
            if (lowerKey.includes('validation_url') ||
                lowerKey.includes('verify_url') ||
                lowerKey.includes('verification_url') ||
                lowerKey === 'url') {
                verificationUrls.add(normalizedValue);
            }
            collectUrlsFromText(normalizedValue);
            return;
        }
        if (!value || typeof value !== 'object' || visited.has(value))
            return;
        visited.add(value);
        if (Array.isArray(value)) {
            for (const item of value)
                walk(item);
            return;
        }
        for (const [childKey, childValue] of Object.entries(value)) {
            walk(childValue, childKey);
        }
    };
    for (const payload of payloads)
        walk(payload);
    if (!validationRequired) {
        validationRequired =
            lowerBody.includes('verification required') ||
                lowerBody.includes('verify your account') ||
                lowerBody.includes('account verification');
    }
    if (!message) {
        message = decodedBody
            .split('\n')
            .map((line) => line.trim())
            .find((line) => line &&
            !line.startsWith('data:') &&
            /(verify|validation|required|ineligible)/i.test(line));
    }
    return {
        validationRequired,
        accountIneligible,
        message,
        verifyUrl: selectBestVerificationUrl([...verificationUrls]),
    };
}
export function buildAccountAccessProbeRequest(projectId) {
    const wireModel = 'gemini-3.5-flash-low';
    const request = {
        contents: [{ role: 'user', parts: [{ text: 'ping' }] }],
        generationConfig: { maxOutputTokens: 1, temperature: 0 },
    };
    const requestMetadata = buildAgyAgentRequestMetadata(createAgyRequestSessionContext(''), request, wireModel);
    request.labels = requestMetadata.labels;
    request.sessionId = requestMetadata.sessionId;
    orderAgyRequestPayloadInPlace(request);
    return {
        project: projectId,
        requestId: requestMetadata.requestId,
        request,
        model: wireModel,
        userAgent: 'antigravity',
        requestType: 'agent',
    };
}
export async function interpretAccountAccessProbeResponse(response) {
    if (response.ok) {
        await response.body?.cancel().catch(() => { });
        return { status: 'ok', message: 'Account verification check passed.' };
    }
    let responseBody = '';
    try {
        responseBody = await response.text();
    }
    catch { }
    const extracted = extractAccountAccessErrorDetails(responseBody);
    if (response.status === 403 && extracted.accountIneligible) {
        return {
            status: 'ineligible',
            message: extracted.message ??
                'Google marked this account as ineligible for Antigravity.',
        };
    }
    if (response.status === 403 && extracted.validationRequired) {
        return {
            status: 'verification-required',
            message: extracted.message ?? 'Google requires additional account verification.',
            verifyUrl: extracted.verifyUrl,
        };
    }
    return {
        status: 'error',
        message: extracted.message ??
            `Request failed (${response.status} ${response.statusText}).`,
    };
}
export function markStoredAccountVerificationRequired(account, reason, verifyUrl) {
    return markLegacyVerificationRequired(account, reason, verifyUrl, Date.now());
}
export function markStoredAccountIneligible(account, reason) {
    return markLegacyIneligible(account, reason, Date.now());
}
export function clearStoredAccountAccessBlocks(account, enableIfBlocked = false) {
    return clearLegacyAccessBlocks(account, enableIfBlocked, Date.now());
}
function findAccountIndex(storage, identity) {
    if (identity.refreshToken) {
        const tokenIndex = storage.accounts.findIndex((account) => account.refreshToken === identity.refreshToken);
        if (tokenIndex !== -1)
            return tokenIndex;
    }
    if (identity.email) {
        return storage.accounts.findIndex((account) => account.email === identity.email);
    }
    return -1;
}
/**
 * Sends one minimal generation request with `accessToken` for `projectId`
 * and classifies the answer. Network failures and timeouts become `error`
 * results, never an access verdict.
 */
async function probeAccountAccess(accessToken, projectId, transport) {
    const fingerprintHeaders = buildFingerprintHeaders(getSessionFingerprint());
    const headers = {
        'User-Agent': fingerprintHeaders['User-Agent'] ?? getSessionFingerprint().userAgent,
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        'Accept-Encoding': 'gzip',
    };
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 20_000);
    try {
        const response = await transport(`${ANTIGRAVITY_ENDPOINT_PROD}/v1internal:streamGenerateContent?alt=sse`, {
            method: 'POST',
            headers,
            body: JSON.stringify(buildAccountAccessProbeRequest(projectId)),
        }, { signal: controller.signal });
        return interpretAccountAccessProbeResponse(response);
    }
    catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
            return { status: 'error', message: 'Verification check timed out.' };
        }
        return {
            status: 'error',
            message: `Verification check failed: ${String(error)}`,
        };
    }
    finally {
        clearTimeout(timeoutId);
    }
}
export function createAccountAccessService({ client, providerId, store, openBrowser, prompt, dependencies, }) {
    const refresh = dependencies?.refreshAccessToken ?? refreshAccessToken;
    const transport = dependencies?.transport ?? fetchWithAgyCliTransport;
    const verifyAccount = async (account) => {
        // Once the account store serves the location, a refresh with a token
        // copied out of a listing would bypass the repository's attributed
        // refresh; store-mode verification goes through `repositoryAccess`.
        if (store.source && (await store.source()) !== 'pool-file') {
            return {
                status: 'error',
                message: 'Accounts live in the account store; verify them through the account store.',
            };
        }
        const parsed = parseRefreshParts(account.refreshToken);
        if (!parsed.refreshToken) {
            return {
                status: 'error',
                message: 'Missing refresh token for selected account.',
            };
        }
        const auth = {
            type: 'oauth',
            refresh: formatRefreshParts({
                refreshToken: parsed.refreshToken,
                projectId: parsed.projectId ?? account.projectId,
                managedProjectId: parsed.managedProjectId ?? account.managedProjectId,
            }),
            access: '',
            expires: 0,
        };
        let refreshedAuth;
        try {
            refreshedAuth = await refresh(auth, client, providerId);
        }
        catch (error) {
            if (error instanceof AntigravityTokenRefreshError) {
                return { status: 'error', message: error.message };
            }
            return {
                status: 'error',
                message: `Token refresh failed: ${String(error)}`,
            };
        }
        if (!refreshedAuth?.access) {
            return {
                status: 'error',
                message: 'Could not refresh access token for this account.',
            };
        }
        const projectId = parsed.managedProjectId ??
            parsed.projectId ??
            account.managedProjectId ??
            account.projectId ??
            ANTIGRAVITY_DEFAULT_PROJECT_ID;
        return probeAccountAccess(refreshedAuth.access, projectId, transport);
    };
    return {
        source: () => store.source ? store.source() : Promise.resolve('pool-file'),
        repositoryAccess: (repository) => createRepositoryAccountAccessService({
            repository,
            openBrowser,
            prompt,
            transport,
        }),
        loadAccounts: () => store.load(),
        mutateAccounts: (mutate) => store.mutate(mutate),
        clearAccounts: () => store.clear(),
        persistAccountPool: (results, replaceAll) => store.persistAccountPool(results, replaceAll),
        verifyAccount,
        async applyVerificationResult(identity, result) {
            if (result.status !== 'verification-required' &&
                result.status !== 'ineligible') {
                return;
            }
            await store.mutate((current) => {
                const index = findAccountIndex(current, identity);
                const account = current.accounts[index];
                if (!account)
                    return current;
                if (result.status === 'verification-required') {
                    markStoredAccountVerificationRequired(account, result.message, result.verifyUrl);
                }
                else {
                    markStoredAccountIneligible(account, result.message);
                }
                return current;
            });
        },
        async clearAccessBlocks(identity, enableIfBlocked = false) {
            let outcome = { changed: false, wasAccessBlocked: false };
            await store.mutate((current) => {
                const index = findAccountIndex(current, identity);
                const account = current.accounts[index];
                if (!account)
                    return current;
                outcome = clearStoredAccountAccessBlocks(account, enableIfBlocked);
                return current;
            });
            return outcome;
        },
        selectAccount: (accounts) => prompt.selectAccount(accounts),
        async openVerificationUrl(url) {
            if (!(await prompt.confirmOpenVerificationUrl()))
                return false;
            return openBrowser(url);
        },
    };
}
// ---------------------------------------------------------------------------
// Account-store access service
// ---------------------------------------------------------------------------
/** Exact text shown when a re-authentication lost its row. */
export const ACCOUNT_CHANGED_DURING_REAUTHORIZATION_MESSAGE = 'Account changed during reauthorization. Reopen the account dialog.';
/**
 * Thrown when a re-authentication cannot land on the row it was started
 * for: the row was removed, re-added or given another credential since the
 * dialog captured it, or the browser signed in to a different account than
 * the row holds. Nothing is written.
 */
export class AccountChangedDuringReauthorizationError extends Error {
    rowId;
    constructor(rowId, options) {
        super(ACCOUNT_CHANGED_DURING_REAUTHORIZATION_MESSAGE, options);
        this.name = 'AccountChangedDuringReauthorizationError';
        this.rowId = rowId;
    }
}
/**
 * Thrown when the account store cannot list accounts (pending migration or
 * management operation, unreadable file). Nothing falls back to the pool
 * file or to an empty list.
 */
export class AccountStoreUnavailableError extends Error {
    status;
    constructor(status, detail) {
        super(`The account store is not available (${status}): ${detail}`);
        this.name = 'AccountStoreUnavailableError';
        this.status = status;
    }
}
function textOf(value) {
    return typeof value === 'string' && value !== '' ? value : undefined;
}
function accessViewOf(row) {
    const metadata = row.metadata.status === 'present' ? row.metadata.metadata : undefined;
    const email = textOf(metadata?.email);
    const label = textOf(metadata?.label);
    const projectId = textOf(metadata?.projectId);
    const managedProjectId = textOf(metadata?.managedProjectId);
    return {
        ref: row.ref,
        index: row.index,
        enabled: row.enabled,
        block: accessBlockOf(metadata),
        ...(email !== undefined ? { email } : {}),
        ...(label !== undefined ? { label } : {}),
        ...(projectId !== undefined ? { projectId } : {}),
        ...(managedProjectId !== undefined ? { managedProjectId } : {}),
    };
}
/**
 * A pool-file shaped view of account-store rows, for menus and listings that
 * still render the pool-file record. Each view's position equals the row's
 * index in `rows`, so a caller that keeps `rows[i].ref` beside it acts on
 * the exact row the user picked. The view is for display; it is never
 * written back.
 */
export function storageViewOfRows(rows) {
    return {
        version: 4,
        activeIndex: 0,
        accounts: rows.map((row) => {
            const meta = row.metadata.status === 'present' ? row.metadata.metadata : undefined;
            const quota = row.quota.status === 'present' ? row.quota.quota : undefined;
            const view = {
                refreshToken: row.credential?.refreshToken ?? '',
                addedAt: meta?.addedAt ?? row.storeAddedAt ?? 0,
                lastUsed: meta?.lastUsed ?? 0,
                enabled: row.enabled,
            };
            const email = textOf(meta?.email);
            if (email !== undefined)
                view.email = email;
            const label = textOf(meta?.label);
            if (label !== undefined)
                view.label = label;
            for (const key of [
                'verificationRequired',
                'accountIneligible',
            ]) {
                if (meta?.[key] != null)
                    view[key] = meta[key];
            }
            for (const key of [
                'verificationRequiredAt',
                'accountIneligibleAt',
                'coolingDownUntil',
            ]) {
                if (meta?.[key] != null)
                    view[key] = meta[key];
            }
            for (const key of [
                'verificationRequiredReason',
                'verificationUrl',
                'accountIneligibleReason',
            ]) {
                const value = textOf(meta?.[key]);
                if (value !== undefined)
                    view[key] = value;
            }
            if (meta?.cooldownReason != null)
                view.cooldownReason = meta.cooldownReason;
            if (quota?.cachedQuotaUpdatedAt != null) {
                view.cachedQuotaUpdatedAt = quota.cachedQuotaUpdatedAt;
            }
            return view;
        }),
    };
}
/** A repository refusal meaning the ref no longer names the row's credential. */
function isStaleRefFailure(error) {
    return (error instanceof AccountRepositoryError &&
        (error.failure.kind === 'attribution' ||
            error.failure.kind === 'unknown-row'));
}
/**
 * The access service over the account repository. Every operation names its
 * row by the `RowRef` captured when the account list was read:
 * - verification refreshes the bearer through `AccountRepository.refresh`
 *   on that ref (the stored credential, fenced by the store), never with a
 *   token copied out of an earlier read;
 * - the verdict is recorded with `recordAccessVerdict` on the ref the
 *   refresh confirmed, timestamped when the answer arrived, so a late
 *   verdict cannot undo newer evidence and a verdict about a replaced or
 *   re-added credential is refused;
 * - re-authentication replaces the credential of exactly that ref
 *   (`replaceCredential`), keeping a user's disabled choice.
 */
export function createRepositoryAccountAccessService({ repository, openBrowser, prompt, now = () => Date.now(), transport = fetchWithAgyCliTransport, }) {
    const readRows = async () => {
        const read = await repository.read();
        switch (read.status) {
            case 'ready':
                return read.rows;
            case 'pending-migration':
                throw new AccountStoreUnavailableError(read.status, 'run `antigravity-auth migrate --offline`');
            case 'management-pending':
                throw new AccountStoreUnavailableError(read.status, `an account ${read.management.kind} operation must be resumed first`);
            case 'error':
                throw new AccountStoreUnavailableError(read.status, `${read.file}: ${read.reason}`);
        }
    };
    return {
        async listAccounts() {
            return (await readRows()).map(accessViewOf);
        },
        async verifyAccount({ ref }) {
            const rows = await readRows();
            const row = rows.find((candidate) => sameRowRef(candidate.ref, ref));
            if (row === undefined) {
                return {
                    status: 'not-probed',
                    ref,
                    result: {
                        status: 'error',
                        message: 'This account changed since the list was opened. Reopen the account list.',
                    },
                };
            }
            const view = accessViewOf(row);
            let outcome;
            try {
                outcome = await repository.refresh(ref);
            }
            catch (error) {
                const message = isStaleRefFailure(error)
                    ? 'This account changed since the list was opened. Reopen the account list.'
                    : error instanceof AntigravityTokenRefreshError
                        ? error.message
                        : `Token refresh failed: ${error instanceof Error ? error.message : String(error)}`;
                return {
                    status: 'not-probed',
                    ref,
                    result: { status: 'error', message },
                };
            }
            if (outcome.status !== 'rotated') {
                // A refused or identity-contradicted refresh never yields a bearer.
                return {
                    status: 'not-probed',
                    ref,
                    result: {
                        status: 'error',
                        message: outcome.status === 'refused'
                            ? `Token refresh was refused: ${outcome.reason}`
                            : 'Google answered for a different account; re-authenticate this account.',
                    },
                };
            }
            const projectId = view.managedProjectId ??
                view.projectId ??
                ANTIGRAVITY_DEFAULT_PROJECT_ID;
            const result = await probeAccountAccess(outcome.accessToken, projectId, transport);
            return { status: 'probed', ref: outcome.ref, result, observedAt: now() };
        },
        async applyVerificationResult(outcome, options = {}) {
            if (outcome.status !== 'probed')
                return { status: 'no-verdict' };
            const verdict = accessVerdictFromProbe(outcome.result, outcome.observedAt, options.enableIfBlocked ?? false);
            if (verdict === undefined)
                return { status: 'no-verdict' };
            try {
                const applied = await repository.recordAccessVerdict(outcome.ref, verdict);
                return {
                    status: 'applied',
                    ref: applied.ref,
                    declined: applied.declined === true,
                };
            }
            catch (error) {
                if (isStaleRefFailure(error)) {
                    return { status: 'stale', rowId: outcome.ref.id };
                }
                throw error;
            }
        },
        async reauthorizeAccount(expected, result) {
            const parts = parseRefreshParts(result.refresh);
            if (!parts.refreshToken) {
                throw new Error('The sign-in returned no refresh token');
            }
            const row = (await readRows()).find((candidate) => sameRowRef(candidate.ref, expected));
            if (row === undefined) {
                throw new AccountChangedDuringReauthorizationError(expected.id);
            }
            const stored = row.metadata.status === 'present' ? row.metadata.metadata : undefined;
            const storedEmail = textOf(stored?.email);
            // A sign-in to a different Google account is not a re-authentication
            // of this row, whatever the row's position or token.
            if (storedEmail !== undefined &&
                result.email !== undefined &&
                result.email !== storedEmail) {
                throw new AccountChangedDuringReauthorizationError(expected.id);
            }
            const at = now();
            try {
                return await repository.replaceCredential(expected, {
                    refreshToken: parts.refreshToken,
                    metadata: {
                        addedAt: at,
                        lastUsed: at,
                        ...(result.email !== undefined ? { email: result.email } : {}),
                        ...(result.label !== undefined ? { label: result.label } : {}),
                        ...(parts.projectId !== undefined
                            ? { projectId: parts.projectId }
                            : {}),
                        ...(parts.managedProjectId !== undefined
                            ? { managedProjectId: parts.managedProjectId }
                            : {}),
                    },
                    // OpenCode 1.x keeps a disabled account disabled.
                    disabled: 'keep',
                });
            }
            catch (error) {
                if (isStaleRefFailure(error)) {
                    throw new AccountChangedDuringReauthorizationError(expected.id, {
                        cause: error,
                    });
                }
                throw error;
            }
        },
        selectAccount: (accounts) => prompt.selectAccount(accounts),
        async openVerificationUrl(url) {
            if (!(await prompt.confirmOpenVerificationUrl()))
                return false;
            return openBrowser(url);
        },
    };
}
export async function promptAccountIndexForVerification(accounts) {
    const { createInterface } = await import('node:readline/promises');
    const { stdin, stdout } = await import('node:process');
    const rl = createInterface({ input: stdin, output: stdout });
    try {
        console.log('\nSelect an account to verify:');
        for (const account of accounts) {
            const label = account.email || `Account ${account.index + 1}`;
            console.log(`  ${account.index + 1}. ${label}`);
        }
        console.log('');
        while (true) {
            const answer = (await rl.question('Account number (leave blank to cancel): ')).trim();
            if (!answer)
                return undefined;
            const parsedIndex = Number(answer);
            if (!Number.isInteger(parsedIndex)) {
                console.log('Please enter a valid account number.');
                continue;
            }
            const normalizedIndex = parsedIndex - 1;
            const selected = accounts.find((account) => account.index === normalizedIndex);
            if (!selected) {
                console.log('Please enter a number from the list above.');
                continue;
            }
            return selected.index;
        }
    }
    finally {
        rl.close();
    }
}
export async function promptOpenVerificationUrl() {
    const { createInterface } = await import('node:readline/promises');
    const { stdin, stdout } = await import('node:process');
    const rl = createInterface({ input: stdin, output: stdout });
    try {
        const answer = (await rl.question('Open verification URL in your browser now? [Y/n]: '))
            .trim()
            .toLowerCase();
        return answer === '' || answer === 'y' || answer === 'yes';
    }
    finally {
        rl.close();
    }
}
//# sourceMappingURL=account-access.js.map