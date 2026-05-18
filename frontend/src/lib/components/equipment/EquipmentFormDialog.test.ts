import { render } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import EquipmentFormDialog from './EquipmentFormDialog.svelte';

const sites = [{ id: 'd', name: 'Default', archived_at: null }];

describe('EquipmentFormDialog', () => {
    it('disables restricted fields when canManage=false', () => {
        const { getByLabelText } = render(EquipmentFormDialog, {
            props: {
                open: true, initial: null, sites, canManage: false,
                tags: [], onClose: vi.fn(), onSubmit: vi.fn(),
            },
        });
        const cal = getByLabelText(/Last calibration/i) as HTMLInputElement;
        expect(cal.disabled).toBe(true);
    });

    it('enables restricted fields when canManage=true', () => {
        const { getByLabelText } = render(EquipmentFormDialog, {
            props: {
                open: true, initial: null, sites, canManage: true,
                tags: [], onClose: vi.fn(), onSubmit: vi.fn(),
            },
        });
        const cal = getByLabelText(/Last calibration/i) as HTMLInputElement;
        expect(cal.disabled).toBe(false);
    });
});
