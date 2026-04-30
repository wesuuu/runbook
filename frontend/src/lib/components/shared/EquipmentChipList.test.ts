import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import EquipmentChipList from './EquipmentChipList.svelte';

const ORG = [
    { id: 'eq-1', name: 'Bioreactor A' },
    { id: 'eq-2', name: 'Bioreactor B' },
];

describe('EquipmentChipList', () => {
    it('renders an empty state when no equipment', () => {
        const { getByText } = render(EquipmentChipList, {
            equipment: [],
            orgEquipment: ORG,
            conflictingIds: new Set(),
        });
        expect(getByText(/no equipment/i)).toBeTruthy();
    });

    it('renders one chip per equipment_id with org name', () => {
        const { getByText } = render(EquipmentChipList, {
            equipment: [{ equipment_id: 'eq-1', shareable: false }],
            orgEquipment: ORG,
            conflictingIds: new Set(),
        });
        expect(getByText('Bioreactor A')).toBeTruthy();
    });

    it('marks chip as conflicting when id is in conflictingIds and not shareable', () => {
        const { container } = render(EquipmentChipList, {
            equipment: [{ equipment_id: 'eq-1', shareable: false }],
            orgEquipment: ORG,
            conflictingIds: new Set(['eq-1']),
        });
        expect(container.querySelector('.equipment-chip.conflict')).toBeTruthy();
    });

    it('does NOT mark conflict when shareable', () => {
        const { container } = render(EquipmentChipList, {
            equipment: [{ equipment_id: 'eq-1', shareable: true }],
            orgEquipment: ORG,
            conflictingIds: new Set(['eq-1']),
        });
        expect(container.querySelector('.equipment-chip.conflict')).toBeFalsy();
    });

    it('falls back to "Unknown" when equipment_id is not in orgEquipment', () => {
        const { getByText } = render(EquipmentChipList, {
            equipment: [{ equipment_id: 'missing', shareable: false }],
            orgEquipment: ORG,
            conflictingIds: new Set(),
        });
        expect(getByText(/Unknown/)).toBeTruthy();
    });
});
