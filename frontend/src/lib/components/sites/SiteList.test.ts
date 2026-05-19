import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SiteList from './SiteList.svelte';

const sites = [
    { id: 'd', name: 'Default Site', archived_at: null, equipment_count: 5 },
    { id: 'a', name: 'Alpha', archived_at: null, equipment_count: 2 },
];

describe('SiteList', () => {
    it('renders sites and highlights active', () => {
        const { getByText } = render(SiteList, {
            props: { sites, activeId: 'd', canEdit: false, onSelect: vi.fn(), onAdd: vi.fn() },
        });
        const active = getByText('Default Site').closest('.site-rail-item');
        expect(active?.classList.contains('active')).toBe(true);
    });

    it('hides + New button when canEdit=false', () => {
        const { queryByText } = render(SiteList, {
            props: { sites, activeId: 'd', canEdit: false, onSelect: vi.fn(), onAdd: vi.fn() },
        });
        expect(queryByText(/\+ New/i)).toBeNull();
    });
});
