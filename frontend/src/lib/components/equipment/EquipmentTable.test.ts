import { render } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import EquipmentTable from './EquipmentTable.svelte';

const rows = [
    { id: '1', name: 'HPLC-1', status: 'ACTIVE', next_calibration_due: '2026-08-12',
      room: 'QC Bay', location: 'Bench 2', tags: ['qc'], equipment_type: 'HPLC' },
];

describe('EquipmentTable', () => {
    it('renders rows', () => {
        const { getByText } = render(EquipmentTable, {
            props: { rows, canManage: false, onEdit: vi.fn(), onArchive: vi.fn() },
        });
        expect(getByText('HPLC-1')).toBeTruthy();
    });

    it('hides archive button when canManage is false', () => {
        const { queryByText } = render(EquipmentTable, {
            props: { rows, canManage: false, onEdit: vi.fn(), onArchive: vi.fn() },
        });
        expect(queryByText(/archive/i)).toBeNull();
    });
});
