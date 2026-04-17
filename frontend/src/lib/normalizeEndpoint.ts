/** Strip trailing slashes from the path portion of an endpoint to avoid 307 redirects from FastAPI. */
export function normalizeEndpoint(endpoint: string): string {
    const qIndex = endpoint.indexOf('?');
    if (qIndex === -1) return endpoint.replace(/\/+$/, '');
    const path = endpoint.slice(0, qIndex).replace(/\/+$/, '');
    return path + endpoint.slice(qIndex);
}
