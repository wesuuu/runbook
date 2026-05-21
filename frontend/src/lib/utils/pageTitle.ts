/**
 * Browser-tab title resolution. Centralised in the root layout so every
 * route gets a correct, reactive `<title>` — the tab title is never left
 * "stuck" on a previous page after navigation (QA issue #2).
 */

const APP_NAME = 'Batchrite';

/**
 * The human-readable name for a route, or '' for an unknown route.
 *
 * Dynamic routes (`/projects/[id]`, `/runs/[id]`, …) resolve by prefix —
 * the per-record name is filled in by the page itself once data loads.
 */
export function routeName(pathname: string): string {
    const p = pathname.replace(/\/+$/, '') || '/';
    switch (p) {
        case '/':
            return 'Dashboard';
        case '/login':
            return 'Sign In';
        case '/register':
            return 'Sign Up';
        case '/check-email':
            return 'Check Your Email';
        case '/auth/callback':
            return 'Signing In';
        case '/legal/accept':
            return 'Accept Terms';
        case '/legal/terms':
            return 'Terms of Service';
        case '/legal/privacy':
            return 'Privacy Policy';
        case '/chat':
            return 'AI Chat';
        case '/export':
            return 'Export';
        case '/field':
            return 'Field Mode';
        case '/settings':
            return 'Settings';
        case '/organization/sites':
            return 'Sites & Equipment';
        case '/projects':
            return 'Projects';
        case '/library':
            return 'Library';
    }
    if (p.startsWith('/library/documents/')) return 'Document Refinement';
    if (p.startsWith('/library/')) return 'Library Document';
    if (/^\/[^/]+\/experiments\/?$/.test(p)) return 'Experiments';
    if (p.startsWith('/projects/')) return 'Project';
    if (p.startsWith('/protocols/')) return 'Protocol Editor';
    if (p.startsWith('/runs/')) return 'Run';
    if (/^\/[^/]+\/projects\/[^/]+\/experiments\/[^/]+/.test(p)) return 'Experiment';
    return '';
}

/**
 * The full `<title>` text for a route — `"<page> · Batchrite"`, or just
 * `"Batchrite"` for an unknown route.
 */
export function routeTitle(pathname: string): string {
    const name = routeName(pathname);
    return name ? `${name} · ${APP_NAME}` : APP_NAME;
}
