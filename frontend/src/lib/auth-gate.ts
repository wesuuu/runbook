export interface GateState {
    initialized: boolean;
    authenticated: boolean;
    emailVerified: boolean;
    tosCurrent: boolean;
    pathname: string;
}

export type GateRedirect =
    | { kind: 'login' }
    | { kind: 'accept-tos' }
    | { kind: 'home' }
    | { kind: 'none' };

const PUBLIC_ROUTES = ['/login', '/register', '/check-email', '/legal/terms', '/legal/privacy'];

export function decideRedirect(state: GateState): GateRedirect {
    if (!state.initialized) return { kind: 'none' };
    const isPublic = PUBLIC_ROUTES.includes(state.pathname);

    if (!state.authenticated) {
        if (isPublic) return { kind: 'none' };
        return { kind: 'login' };
    }
    if (!state.tosCurrent) {
        if (state.pathname === '/legal/accept') return { kind: 'none' };
        if (isPublic) return { kind: 'none' };
        return { kind: 'accept-tos' };
    }
    if (isPublic) return { kind: 'home' };
    return { kind: 'none' };
}

/**
 * Validate a post-login `next` redirect target. Returns the path only when
 * it is a same-origin absolute path (`/foo`); rejects open-redirect payloads
 * such as `//evil.com`, `/\evil.com`, or absolute URLs. Falls back to `/`.
 */
export function sanitizeNextPath(next: string | null | undefined): string {
    if (!next || !next.startsWith('/')) return '/';
    if (next.startsWith('//') || next.startsWith('/\\')) return '/';
    return next;
}

export { PUBLIC_ROUTES };
