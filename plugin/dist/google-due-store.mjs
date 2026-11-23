// Private protocol for the 3.1.13 Hub adapter (also implemented inline in
// the 3.0.0 recovery bundle, which must work without sibling files).
export class DueRefreshError extends Error {
  constructor(status, retryAfterSeconds = 0) {
    super("Background Google OAuth exchange failed");
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export function readRetryAfter(header, now = Date.now()) {
  const value = header?.trim() ?? "";
  const seconds = /^\d+$/.test(value) ? Number(value) : Math.ceil((Date.parse(value) - now) / 1000);
  return Number.isSafeInteger(seconds) ? Math.max(0, seconds) : 0;
}

export function isDueRefreshId(value) {
  return typeof value === "string" && /^[a-z0-9_][a-z0-9_.-]{0,255}$/i.test(value);
}

export function parseDueRefreshArgs(args) {
  if (args.length === 1 && args[0] === "--list") return { account: undefined };
  const [option, generation, id, epoch, expires] = args;
  const positiveInteger = (n) => /^\d+$/.test(n) && Number.isSafeInteger(Number(n)) && Number(n) > 0;
  if (args.length === 5 && option === "--account" && [generation, id].every(isDueRefreshId) &&
      positiveInteger(epoch) && positiveInteger(expires))
    return { account: { generation, id, epoch: Number(epoch), expires: Number(expires) } };
  return null;
}

function googleRowDue(row, now) {
  const credential = row.credential;
  const meta = row.metadata?.status === "present" ? row.metadata.metadata : undefined;
  return row.enabled && !row.invalid && !row.torn && !row.unbound && row.stamp === "bound" &&
    meta?.accountIneligible !== true && meta?.verificationRequired !== true &&
    Boolean(credential?.refreshToken && credential?.accessToken) &&
    Number.isSafeInteger(credential.expiresAt) && credential.expiresAt > now &&
    credential.expiresAt <= now + 1800e3;
}

export async function refreshDueStore(account, { open, exchange, now = Date.now }) {
  const binding = await open();
  if (!binding) return { status: "unavailable" };
  const { generation, authorized = () => true, stillActive = () => true } = binding;
  if (!isDueRefreshId(generation) || account && account.generation !== generation)
    return { status: "skipped" };
  let exchangeFailure;
  const repository = binding.createRepository(async ({ refreshToken }) => {
    try {
      if (!await authorized()) throw new DueRefreshError("unavailable");
      const result = await exchange(refreshToken);
      if (typeof result.access !== "string" || !result.access.trim() ||
          typeof result.refresh !== "string" || !result.refresh.trim() ||
          !Number.isSafeInteger(result.expires) || result.expires <= now())
        throw new DueRefreshError("failed");
      return { accessToken: result.access, refreshToken: result.refresh, expiresAt: result.expires };
    } catch (error) {
      if (error instanceof DueRefreshError) exchangeFailure = error;
      throw error;
    }
  });
  try {
    const read = await repository.read();
    if (read.status !== "ready" || !await authorized() || !await stillActive())
      return { status: "unavailable" };
    const checkedAt = now();
    const due = read.rows.filter((row) => isDueRefreshId(row.ref.id) && googleRowDue(row, checkedAt));
    if (!account) {
      due.sort((a, b) => a.credential.expiresAt - b.credential.expiresAt);
      return {
        status: "ready",
        generation,
        accounts: due.map(({ ref, credential }) => ({
          id: ref.id, epoch: ref.credentialEpoch, expires: credential.expiresAt
        }))
      };
    }
    const row = due.find(({ ref, credential }) => ref.id === account.id &&
      ref.credentialEpoch === account.epoch && credential.expiresAt === account.expires);
    if (!row) return { status: "skipped" };
    const result = await repository.refresh(row.ref, {
      // The repository checks again at commit; crossing the old expiry
      // during the exchange must not lose the successor credential.
      refuse: (current) => googleRowDue(current, checkedAt) && current.credential.expiresAt === account.expires ?
        undefined : "no-longer-due"
    });
    return { status: result.status === "rotated" ? "refreshed" : "skipped" };
  } catch {
    if (exchangeFailure?.status === "rate_limited")
      return { status: "rate_limited", retryAfterSeconds: exchangeFailure.retryAfterSeconds };
    return { status: exchangeFailure?.status ?? "failed" };
  } finally {
    await repository.dispose();
  }
}
