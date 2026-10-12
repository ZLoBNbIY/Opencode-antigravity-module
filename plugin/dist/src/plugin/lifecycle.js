const NOOP_DRAIN = async () => { };
export function createPluginLifecycle(options) {
    let accountManager = null;
    let refreshQueue = null;
    let accountRequests = null;
    // Replaced account runtimes still being wound down. Each record owns the
    // replaced manager until both its refresh queue has finished any refresh
    // already under way and its request runtime (when it has one) has finished
    // admitted requests; only then is the manager disposed. Records stay here
    // for that whole time so final disposal can abort and await them.
    const retiring = new Set();
    let disposal = null;
    let closing = false;
    const producers = [];
    const consumers = [];
    const drainSidebarWrites = options.drainSidebarWrites ?? NOOP_DRAIN;
    /**
     * Starts winding down a replaced runtime. The queue's timers stop at once;
     * `queueDrained` settles once its refresh in progress has finished, `done`
     * once the manager has been disposed after both drains.
     */
    const retire = (manager, queue, requests) => {
        const queueDrained = Promise.resolve(queue?.dispose());
        const record = {
            requests,
            done: (async () => {
                const drained = await Promise.allSettled([
                    queueDrained,
                    requests?.retire(),
                ]);
                await manager.dispose();
                const failed = drained.find((outcome) => outcome.status === 'rejected');
                if (failed)
                    throw failed.reason;
            })(),
        };
        retiring.add(record);
        // A finished record is forgotten. A failed one stays for final disposal
        // to report, unless no request runtime kept it running in the background:
        // then the replacement awaited it and has already reported the failure.
        record.done.then(() => retiring.delete(record), () => {
            if (!requests)
                retiring.delete(record);
        });
        void queueDrained.catch(() => { });
        return { queueDrained, done: record.done };
    };
    const disposeAccountRuntime = async () => {
        const oldQueue = refreshQueue;
        const oldManager = accountManager;
        const oldRequests = accountRequests;
        refreshQueue = null;
        accountManager = null;
        accountRequests = null;
        // Abort the physical I/O of the live runtime and of every retired one,
        // and stop the live refresh queue at the same moment so it starts no
        // new refresh while that I/O drains. Every manager is disposed only
        // after the runtimes and queues using it have finished.
        const retired = [...retiring];
        retiring.clear();
        const aborted = Promise.all([
            oldRequests?.dispose(),
            ...retired.map((record) => record.requests?.dispose()),
        ]);
        const liveQueueDrained = Promise.resolve(oldQueue?.dispose());
        void liveQueueDrained.catch(() => { });
        await aborted;
        const retirements = await Promise.allSettled(retired.map((record) => record.done));
        await liveQueueDrained;
        await oldManager?.dispose();
        const failed = retirements.find((outcome) => outcome.status === 'rejected');
        if (failed)
            throw failed.reason;
    };
    const register = (disposable, phase = 'consumer') => {
        if (closing) {
            void disposable.dispose();
            return;
        }
        if (phase === 'producer') {
            producers.push(disposable);
        }
        else {
            consumers.push(disposable);
        }
    };
    return {
        getAccountManager: () => accountManager,
        isClosing: () => closing,
        async replaceAccountRuntime(manager, queue, requests = null) {
            if (!closing) {
                const oldQueue = refreshQueue;
                const oldManager = accountManager;
                const oldRequests = accountRequests;
                refreshQueue = null;
                accountManager = null;
                accountRequests = null;
                if (oldManager) {
                    const retirement = retire(oldManager, oldQueue, oldRequests);
                    // Without a request runtime nothing is left running for the old
                    // manager, so it is disposed before the replacement is published.
                    await (oldRequests ? retirement.queueDrained : retirement.done);
                }
                else {
                    await oldQueue?.dispose();
                }
            }
            if (closing) {
                await requests?.dispose();
                await queue?.dispose();
                await manager.dispose();
                return false;
            }
            accountManager = manager;
            refreshQueue = queue;
            accountRequests = requests;
            return true;
        },
        register,
        dispose() {
            if (!disposal) {
                // Hooks can synchronously reenter admission or disposal. Publish both
                // closing and the shared completion promise before invoking any hook.
                closing = true;
                let finishDisposal = () => { };
                let failDisposal = () => { };
                disposal = new Promise((resolve, reject) => {
                    finishDisposal = resolve;
                    failDisposal = reject;
                });
                void (async () => {
                    await disposeAccountRuntime();
                    await options.shutdownDiskSignatureCache();
                    options.sessionRegistry.clear();
                    options.clearFetchState();
                    // 1. Stop and await all producers (e.g. fetch interceptor).
                    //    This prevents NEW sidebar writes from being enqueued
                    //    while the drain is in flight.
                    for (const disposable of producers) {
                        await disposable.dispose();
                    }
                    producers.length = 0;
                    // 2. Drain sidebar writes. Every write enqueued by a now-stopped
                    //    producer lands here before the consumers (RPC server, file
                    //    logger) are torn down.
                    await drainSidebarWrites();
                    // 3. Stop consumers. The TUI's last frame can still observe a
                    //    fully landed snapshot because the file logger is still alive
                    //    during the drain.
                    for (const disposable of consumers) {
                        await disposable.dispose();
                    }
                    consumers.length = 0;
                })().then(finishDisposal, failDisposal);
            }
            return disposal;
        },
    };
}
//# sourceMappingURL=lifecycle.js.map