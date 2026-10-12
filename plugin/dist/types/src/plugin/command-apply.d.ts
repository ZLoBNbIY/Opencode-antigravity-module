/**
 * The `/antigravity` menu sections both OpenCode hosts build the same way
 * from a location's own collaborators: the Routing and Limits settings
 * source over the live operator-settings controller, and the Diagnostics
 * section (request dump switch and log level). The module imports no host
 * SDK and no process-wide state; every collaborator is passed in.
 */
import { type AccountRepository, type AntigravityAccountLimitSource, type AntigravityMenuSettingsSource, type CommonAuthCommandsModule } from '@cortexkit/antigravity-auth-core';
import { type OperatorSettings, type OperatorSettingsController } from './operator-settings.js';
type CommonAuthMenuOptions = Parameters<CommonAuthCommandsModule['createCommandMenu']>[0];
type MenuPluginSection = NonNullable<CommonAuthMenuOptions['cache']>;
/**
 * The location's operator settings as the shared menu's Routing and Limits
 * sections read and write them. Reads go to the live controller every
 * time; only the two update methods write.
 */
export declare function operatorMenuSettings(settings: Pick<OperatorSettingsController, 'get' | 'update'>): AntigravityMenuSettingsSource;
/**
 * The Diagnostics section: the Gemini request dump switch and the log
 * level. `applyLogLevel` applies a changed level to the running logger.
 */
export declare function diagnosticsMenuSection(options: {
    readonly settings: Pick<OperatorSettingsController, 'get' | 'update'>;
    readonly dump: {
        isEnabled(): boolean;
        setEnabled(enabled: boolean): void;
    };
    readonly applyLogLevel: (level: OperatorSettings['log_level']) => void;
}): MenuPluginSection;
/**
 * Per-account quota floors for a location whose accounts are in its local
 * account store, kept where the killswitch already reads them: the operator
 * settings' `killswitch.accounts` map, keyed by `accountKeyForRefreshToken`
 * of the account's stored refresh token. The key is computed here, in
 * process, and never leaves this adapter.
 *
 * A write runs inside the repository's fenced metadata update for the exact
 * captured reference, which holds the row's lock and checks its credential
 * epoch and recorded identity before the callback runs: the key comes from
 * the locked row, and a replaced, re-identified or removed credential is
 * refused (`stale`) before any setting is written. The callback keeps the
 * row's metadata unchanged. A concurrent replacement of the row waits for
 * the row lock, so it lands after the floor was written for the credential
 * the floor belongs to.
 *
 * Limit: the store renews the row lease while the callback runs and asserts
 * it when a lock is taken or a change is committed, but not after a callback
 * that changes nothing. A lease lost during the settings write (its renewal
 * stalled past the lease lifetime) is therefore not detected here, and the
 * write is reported as applied. The floor still sits under the key of the
 * credential it was written for.
 */
export declare function createStoreAccountLimits(input: {
    readonly repository: Pick<AccountRepository, 'read' | 'updateMetadata'>;
    readonly settings: Pick<OperatorSettingsController, 'get' | 'update'>;
}): AntigravityAccountLimitSource;
export {};
//# sourceMappingURL=command-apply.d.ts.map