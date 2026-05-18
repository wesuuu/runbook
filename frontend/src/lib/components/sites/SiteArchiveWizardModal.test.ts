import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SiteArchiveWizardModal from './SiteArchiveWizardModal.svelte';

const site = { id: 'src', name: 'Old Lab', archived_at: null };
const otherSites = [
    { id: 'dst-a', name: 'Lab A', archived_at: null },
    { id: 'dst-b', name: 'Lab B', archived_at: null },
];
const equipment = [
    { id: 'e1', name: 'Bioreactor', site_id: 'src', room: 'Lab A' },
    { id: 'e2', name: 'Cytometer', site_id: 'src', room: 'Lab A' },
];

describe('SiteArchiveWizardModal', () => {
    it('starts on step 1; next is disabled until destination is picked', async () => {
        const { getByText } = render(SiteArchiveWizardModal, {
            props: {
                open: true, site, otherSites, equipment,
                onClose: vi.fn(), onSubmit: vi.fn(),
            },
        });
        expect(getByText(/Step 1/i)).toBeTruthy();
    });

    it('submits payload with reason and per-item overrides', async () => {
        const onSubmit = vi.fn().mockResolvedValue(undefined);
        const { getByText, getByPlaceholderText } = render(SiteArchiveWizardModal, {
            props: {
                open: true, site, otherSites, equipment,
                onClose: vi.fn(), onSubmit,
            },
        });
        await fireEvent.click(getByText(/Next: Review/i));
        await fireEvent.click(getByText(/Next: Confirm/i));
        await fireEvent.input(getByPlaceholderText(/Hayward lease|reason/i),
            { target: { value: 'consolidate' } });
        await fireEvent.click(getByText(/Archive site/i));
        expect(onSubmit).toHaveBeenCalled();
        const payload = onSubmit.mock.calls[0][0];
        expect(payload.reason).toBe('consolidate');
        expect(payload.default_move_to).toBe('dst-a');
    });
});
