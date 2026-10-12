import { VAULT_ACCOUNT_REMEDY, } from '@cortexkit/antigravity-auth-core';
/** Choose local or vault sidebar rows before reading accounts; finish queued snapshot writes on shutdown. */
export function createSourceSidebarPublisher(options) {
    let tail = Promise.resolve();
    let disposed = false;
    const unavailable = () => ({
        checkedAt: (options.now ?? Date.now)(),
        accounts: [],
        lastError: VAULT_ACCOUNT_REMEDY,
    });
    return {
        publish() {
            if (disposed)
                return Promise.resolve();
            const next = tail.then(async () => {
                const authority = await options.readAuthority();
                let projection;
                if (authority === 'local')
                    projection = await options.local();
                else if (authority === 'vault') {
                    try {
                        projection = await options.vault();
                    }
                    catch {
                        projection = unavailable();
                    }
                }
                else
                    projection = unavailable();
                await options.write(projection, projection.accounts.map((account) => account.id));
            });
            tail = next.catch(() => { });
            return next;
        },
        async dispose() {
            disposed = true;
            await tail;
        },
    };
}
//# sourceMappingURL=source-sidebar.js.map