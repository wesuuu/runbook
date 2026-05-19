import { render, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SiteManagersPanel from './SiteManagersPanel.svelte';

vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn().mockResolvedValue([
            { id: 'g1', user_id: 'u1', site_id: 's1', granted_by_id: 'admin',
              created_at: '2026-05-01T00:00:00Z',
              user: { id: 'u1', name: 'Alice Chen', email: 'alice@trellis.bio' } },
        ]),
        post: vi.fn(),
        delete: vi.fn(),
    },
}));

describe('SiteManagersPanel', () => {
    it('renders the grants returned by the API', async () => {
        const { findByText } = render(SiteManagersPanel, { props: { siteId: 's1' } });
        expect(await findByText('Alice Chen')).toBeTruthy();
    });

    it('shows empty state when no grants', async () => {
        const { api } = await import('$lib/api');
        (api.get as any).mockResolvedValueOnce([]);
        const { findByText } = render(SiteManagersPanel, { props: { siteId: 's1' } });
        expect(await findByText(/no site managers/i)).toBeTruthy();
    });
});
