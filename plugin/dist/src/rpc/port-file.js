import { discoverPortFile as discoverPublicPortFile } from '../common-auth-embedded/rpc/client.js';
// Discovery reads directory modes without changing them. Only the server writer
// changes directory permissions; clients discover only the expected PID.
export function discoverPortFile(dir, expectedPid) {
    return discoverPublicPortFile(dir, expectedPid, { exactPid: true });
}
//# sourceMappingURL=port-file.js.map