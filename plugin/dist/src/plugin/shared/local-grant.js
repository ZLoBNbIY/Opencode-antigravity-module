/** A prepared local request no longer matches the row's current bearer. */
export class LocalGrantSupersededError extends Error {
    constructor() {
        super('The selected local grant has been superseded');
        this.name = 'LocalGrantSupersededError';
    }
}
/** The original selected credential is unavailable for local serving. */
export class StaleLocalGrantError extends Error {
    constructor() {
        super('The selected local grant is unavailable');
        this.name = 'StaleLocalGrantError';
    }
}
export function isLocalGrantError(error) {
    return (error instanceof LocalGrantSupersededError ||
        error instanceof StaleLocalGrantError);
}
//# sourceMappingURL=local-grant.js.map