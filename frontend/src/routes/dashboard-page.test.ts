import { describe, it, expect, vi } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

// The dashboard page pulls in app-wide singletons; stub them so the page can
// be mounted in isolation. getCurrentOrg returns null to exercise the
// no-organization path (a failed /iam/organizations fetch during init, or an
// account with no org membership).
vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn(() => Promise.resolve({})),
        post: vi.fn(() => Promise.resolve({})),
    },
}));
vi.mock('$lib/auth.svelte', () => ({
    getCurrentOrg: vi.fn(() => null),
    getUser: vi.fn(() => ({ full_name: 'Sam Scientist' })),
}));
vi.mock('$lib/offline-db', () => ({
    getOrphanedActions: vi.fn(() => Promise.resolve(new Map())),
}));
vi.mock('$lib/sync-manager', () => ({
    syncNow: vi.fn(() => Promise.resolve()),
}));
vi.mock('$lib/onboarding/tourStore.svelte', () => ({
    isWelcomeEmpty: vi.fn(() => false),
    isHydrated: vi.fn(() => false),
    markAllDismissed: vi.fn(() => Promise.resolve()),
}));

import Page from './+page.svelte';
import { api } from '$lib/api';

describe('dashboard page', () => {
    it('settles into a terminal error, not an endless skeleton, when no org is available', async () => {
        const { container, getByText } = render(Page);

        await waitFor(() => {
            expect(getByText(/no organization/i)).toBeTruthy();
        });
        // The loading skeleton must have been torn down.
        expect(container.querySelector('.animate-pulse')).toBeNull();
        // The dashboard endpoint must not be queried without an org.
        expect(api.get).not.toHaveBeenCalled();
    });
});
