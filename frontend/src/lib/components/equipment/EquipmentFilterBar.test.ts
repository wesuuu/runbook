import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import EquipmentFilterBar from './EquipmentFilterBar.svelte';

describe('EquipmentFilterBar', () => {
    it('emits filter changes', async () => {
        const onChange = vi.fn();
        const { getByPlaceholderText, getByLabelText } = render(EquipmentFilterBar, {
            props: { value: { q: '', status: null, tag: null, includeArchived: false }, onChange, tags: ['glp', 'qc'] },
        });
        await fireEvent.input(getByPlaceholderText(/search/i), { target: { value: 'pH' } });
        expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'pH' }));
    });
});
