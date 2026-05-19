import { render, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import SitePicker from './SitePicker.svelte';

const sites = [
    { id: 'd', name: 'Default Site', archived_at: null },
    { id: 'a', name: 'Alpha', archived_at: null },
    { id: 'arch', name: 'Old', archived_at: '2026-01-01' },
];

describe('SitePicker', () => {
    it('renders only active sites by default', () => {
        const { getByText, queryByText } = render(SitePicker, {
            props: { sites, value: 'd', onChange: vi.fn() },
        });
        expect(getByText('Default Site')).toBeTruthy();
        expect(getByText('Alpha')).toBeTruthy();
        expect(queryByText('Old')).toBeNull();
    });

    it('emits onChange', async () => {
        const onChange = vi.fn();
        const { getByRole } = render(SitePicker, { props: { sites, value: 'd', onChange } });
        await fireEvent.change(getByRole('combobox'), { target: { value: 'a' } });
        expect(onChange).toHaveBeenCalledWith('a');
    });
});
