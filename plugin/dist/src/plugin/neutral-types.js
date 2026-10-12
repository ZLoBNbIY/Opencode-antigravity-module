/**
 * Host-SDK-free types shared by both host adapters.
 *
 * Modules that a server location reaches (configuration, logging, debug,
 * dump, signature cache, operator settings and the request services that use
 * them) must not depend on the OpenCode plugin SDK, not even through
 * `import type`. `./types` re-exports SDK shapes, so code that only needs
 * credential records or the capability shapes below imports them from here.
 * The `@cortexkit/antigravity-auth-core` package is an external boundary and
 * may be referenced directly.
 */
//# sourceMappingURL=neutral-types.js.map