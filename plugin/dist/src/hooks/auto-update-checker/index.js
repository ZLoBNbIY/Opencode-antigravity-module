// Background checks do not modify the OpenCode cache.
import { findPluginEntry, getCachedVersion, getLatestVersion, getLocalDevVersion, } from './checker';
// Plugin selection is handled by the checker.
import { logAutoUpdate } from './logging';
export function createAutoUpdateCheckerHook(client, directory, options = {}) {
    const { showStartupToast = true, autoUpdate = false } = options;
    let hasChecked = false;
    return {
        event: ({ event }) => {
            if (event.type !== 'session.created')
                return;
            if (hasChecked)
                return;
            const props = event.properties;
            if (props?.info?.parentID)
                return;
            hasChecked = true;
            setTimeout(() => {
                const localDevVersion = getLocalDevVersion(directory);
                if (localDevVersion) {
                    if (showStartupToast) {
                        showLocalDevToast(client, localDevVersion).catch(() => { });
                    }
                    logAutoUpdate('Local development mode');
                    return;
                }
                if (!autoUpdate) return;
                runBackgroundUpdateCheck(client, directory).catch((err) => {
                    logAutoUpdate(`Background update check failed: ${err}`);
                });
            }, 0);
        },
    };
}
async function runBackgroundUpdateCheck(client, directory) {
    const pluginInfo = findPluginEntry(directory);
    if (!pluginInfo) {
        logAutoUpdate('Plugin not found in config');
        return;
    }
    if (pluginInfo.isPinned) return;
    const currentVersion = getCachedVersion();
    if (!currentVersion) {
        logAutoUpdate('No installed version found');
        return;
    }
    if (currentVersion.includes('-')) {
        logAutoUpdate(`Prerelease version (${currentVersion}), skipping auto-update`);
        return;
    }
    const latestVersion = await getLatestVersion();
    if (!latestVersion) {
        logAutoUpdate('Failed to fetch latest version');
        return;
    }
    if (currentVersion === latestVersion) {
        logAutoUpdate('Already on latest version');
        return;
    }
    logAutoUpdate(`Update available: ${currentVersion} → ${latestVersion}`);
    await showUpdateAvailableToast(client, latestVersion);
}
async function showUpdateAvailableToast(client, latestVersion) {
    await client.tui
        .showToast({
        body: {
            title: `Antigravity Auth Update`,
            message: `v${latestVersion} available. Review it with the OpenCode plugin manager.`,
            variant: 'info',
            duration: 8000,
        },
    })
        .catch(() => { });
    logAutoUpdate(`Update available toast shown: v${latestVersion}`);
}
// Updates are installed explicitly through OpenCode.
async function showLocalDevToast(client, version) {
    await client.tui
        .showToast({
        body: {
            title: `Antigravity Auth ${version} (dev)`,
            message: 'Running in local development mode.',
            variant: 'warning',
            duration: 5000,
        },
    })
        .catch(() => { });
    logAutoUpdate(`Local dev toast shown: v${version}`);
}
export { invalidateCache, invalidatePackage } from './cache';
export { checkForUpdate, getCachedVersion, getLatestVersion } from './checker';
//# sourceMappingURL=index.js.map