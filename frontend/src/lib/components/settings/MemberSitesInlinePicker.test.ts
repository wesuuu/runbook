import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import MemberSitesInlinePicker from './MemberSitesInlinePicker.svelte';

const sites = [
    { id: 's1', organization_id: 'o', name: 'San Diego HQ', is_default: true, archived_at: null, created_at: '', updated_at: '' },
    { id: 's2', organization_id: 'o', name: 'Boston Lab', is_default: false, archived_at: null, created_at: '', updated_at: '' },
    { id: 's3', organization_id: 'o', name: 'Old Site', is_default: false, archived_at: '2026-01-01', created_at: '', updated_at: '' },
];

describe('MemberSitesInlinePicker', () => {
    it('renders selected sites as removable chips', () => {
        const { getByText } = render(MemberSitesInlinePicker, {
            props: { allSites: sites, selectedSiteIds: ['s1'], onChange: vi.fn() },
        });
        expect(getByText('San Diego HQ')).toBeTruthy();
    });

    it('flags 0-site state as invalid when SITE_MANAGER is on', () => {
        const { getByText } = render(MemberSitesInlinePicker, {
            props: { allSites: sites, selectedSiteIds: [], onChange: vi.fn(), hasSiteManagerRole: true },
        });
        expect(getByText(/select at least one site/i)).toBeTruthy();
    });

    it('excludes archived sites from picker options', async () => {
        const { getByText, queryByText } = render(MemberSitesInlinePicker, {
            props: { allSites: sites, selectedSiteIds: [], onChange: vi.fn() },
        });
        await fireEvent.click(getByText(/add site/i));
        expect(queryByText('Old Site')).toBeNull();
    });

    it('emits onChange with new selection when chip removed', async () => {
        const onChange = vi.fn();
        const { container } = render(MemberSitesInlinePicker, {
            props: { allSites: sites, selectedSiteIds: ['s1', 's2'], onChange },
        });
        const removeBtn = container.querySelector('button[aria-label="Remove San Diego HQ"]');
        await fireEvent.click(removeBtn!);
        expect(onChange).toHaveBeenCalledWith(['s2']);
    });
});
