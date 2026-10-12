/**
 * Schema for runtime operator-controlled settings.
 *
 * These are the fields the /antigravity-* slash commands mutate at runtime.
 * They live under `config.operator.*` and persist via
 * `config/writer.ts` (fenced lock + atomic rename).
 */
import { z } from 'zod';
export declare const OperatorSettingsSchema: z.ZodObject<{
    routing: z.ZodObject<{
        cli_first: z.ZodBoolean;
        quota_style_fallback: z.ZodBoolean;
    }, z.core.$strip>;
    killswitch: z.ZodObject<{
        enabled: z.ZodBoolean;
        minimum_remaining_percent: z.ZodNumber;
        accounts: z.ZodOptional<z.ZodRecord<z.ZodString, z.ZodNumber>>;
    }, z.core.$strip>;
    log_level: z.ZodEnum<{
        info: "info";
        error: "error";
        warn: "warn";
        debug: "debug";
        trace: "trace";
    }>;
}, z.core.$strip>;
export type OperatorSettings = z.infer<typeof OperatorSettingsSchema>;
export declare function emptyOperatorSettings(): OperatorSettings;
//# sourceMappingURL=operator-settings-schema.d.ts.map