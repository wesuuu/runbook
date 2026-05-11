/**
 * Single source of truth for the backend URL used by Playwright helpers.
 *
 * Resolution order:
 *   1. `E2E_API_BASE` — full URL (e.g. `http://localhost:8010`)
 *   2. `E2E_API_PORT` — port only, paired with `localhost`
 *   3. fallback: `http://localhost:8000`
 *
 * Worktrees run on alternate ports (e.g. 8010, 8020) — set `E2E_API_PORT`
 * to match without restarting servers.
 */
function resolveApiBase(): string {
    const explicit = process.env.E2E_API_BASE;
    if (explicit && explicit.length > 0) return explicit.replace(/\/$/, '');
    const port = process.env.E2E_API_PORT || process.env.VITE_API_PORT;
    if (port && port.length > 0) return `http://localhost:${port}`;
    return 'http://localhost:8000';
}

export const API_BASE = resolveApiBase();
