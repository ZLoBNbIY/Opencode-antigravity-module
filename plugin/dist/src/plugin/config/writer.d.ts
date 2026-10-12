/**
 * Lock-held config writer for operator-controlled settings.
 *
 * The /antigravity-quota, /antigravity-account, /antigravity-routing,
 * /antigravity-killswitch, /antigravity-dump, and /antigravity-logging
 * slash commands all mutate a small slice of the persisted
 * `antigravity.json`. This writer:
 *
 *   1. Selects the existing project config (if present) — never the
 *      user one — so a multi-workspace OpenCode install gets per-project
 *      overrides. When no project config exists, the user config is the
 *      fallback.
 *   2. Holds the same fenced file lock Task 7's core uses for the
 *      account pool so two slash commands fired in quick succession
 *      cannot race.
 *   3. Serializes through `writeJsonAtomic` — staged tmp + rename —
 *      so a crash mid-write leaves the previous file intact.
 *   4. Preserves every other top-level field the user may have set
 *      (the operator slice is one slot in the schema, not the whole
 *      file).
 *
 * No raw OAuth refresh tokens ever pass through this writer — the
 * killswitch accounts map is keyed by sha256(refreshToken).slice(0,12)
 * and `OperatorSettings` carries only that hash.
 */
import type { OperatorSettings } from './operator-settings-schema';
export type { OperatorSettings } from './operator-settings-schema';
export interface WriteOperatorConfigOptions {
    projectConfigPath: string;
    userConfigPath: string;
    operator: OperatorSettings;
}
export declare function writeOperatorConfig(options: WriteOperatorConfigOptions): Promise<void>;
/**
 * Replace the operator block of one explicit config file under the same
 * fenced lock and atomic rename, keeping every other top-level field. A
 * process-shared settings controller owns exactly one file and writes it
 * through this, so it never re-derives the target from file existence.
 */
export declare function writeOperatorConfigAt(target: string, settings: OperatorSettings): Promise<void>;
//# sourceMappingURL=writer.d.ts.map