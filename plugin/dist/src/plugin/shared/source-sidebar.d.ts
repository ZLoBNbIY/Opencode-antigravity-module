import { type EnrollmentAuthority } from '@cortexkit/antigravity-auth-core';
import type { SidebarMachineState } from '../../sidebar-state';
export interface SourceSidebarOptions {
    readonly readAuthority: () => Promise<EnrollmentAuthority>;
    readonly local: () => Promise<SidebarMachineState>;
    readonly vault: () => Promise<SidebarMachineState>;
    readonly write: (state: SidebarMachineState, accountIds: readonly string[]) => Promise<void>;
    readonly now?: () => number;
}
/** Choose local or vault sidebar rows before reading accounts; finish queued snapshot writes on shutdown. */
export declare function createSourceSidebarPublisher(options: SourceSidebarOptions): {
    publish(): Promise<void>;
    dispose(): Promise<void>;
};
//# sourceMappingURL=source-sidebar.d.ts.map