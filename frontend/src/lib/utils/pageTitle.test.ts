import { describe, it, expect } from 'vitest';
import { routeName, routeTitle } from './pageTitle';

describe('routeName', () => {
    it('names static routes', () => {
        expect(routeName('/')).toBe('Dashboard');
        expect(routeName('/projects')).toBe('Projects');
        expect(routeName('/settings')).toBe('Settings');
        expect(routeName('/legal/accept')).toBe('Accept Terms');
    });

    it('names dynamic routes by prefix', () => {
        expect(routeName('/projects/abc123')).toBe('Project');
        expect(routeName('/runs/abc123')).toBe('Run');
        expect(routeName('/protocols/abc123')).toBe('Protocol Editor');
        expect(routeName('/acme/experiments')).toBe('Experiments');
        expect(routeName('/acme/projects/proj-1/experiments/exp-1')).toBe(
            'Experiment',
        );
    });

    it('distinguishes the document-refinement route from a library doc', () => {
        expect(routeName('/library/documents/abc/refine')).toBe(
            'Document Refinement',
        );
        expect(routeName('/library/abc123')).toBe('Library Document');
    });

    it('ignores a trailing slash', () => {
        expect(routeName('/projects/')).toBe('Projects');
    });

    it('returns an empty string for an unknown route', () => {
        expect(routeName('/nope')).toBe('');
    });
});

describe('routeTitle', () => {
    it('suffixes the page name with the app name', () => {
        expect(routeTitle('/projects')).toBe('Projects · Batchrite');
    });

    it('falls back to the bare app name for an unknown route (#2)', () => {
        // Navigating to a route with no title must not leave the tab stuck
        // on the previous page's title.
        expect(routeTitle('/nope')).toBe('Batchrite');
    });
});
