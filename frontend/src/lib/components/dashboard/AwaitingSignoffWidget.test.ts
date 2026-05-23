import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import AwaitingSignoffWidget from './AwaitingSignoffWidget.svelte';

function item(name: string, kind: string) {
    return { kind, entity_id: name, name, project_name: null, detail: `detail ${name}` };
}

describe('AwaitingSignoffWidget', () => {
    it('shows the empty line when nothing is pending', () => {
        const { getByTestId } = render(AwaitingSignoffWidget, {
            props: { items: [], onSelect: vi.fn() },
        });
        expect(getByTestId('signoff-empty').textContent).toContain('Nothing awaiting your sign-off.');
    });

    it('renders a kind badge per item', () => {
        const { getByText } = render(AwaitingSignoffWidget, {
            props: { items: [item('Buffer SOP', 'protocol'), item('Run 7', 'run')], onSelect: vi.fn() },
        });
        expect(getByText('Buffer SOP')).toBeTruthy();
        expect(getByText('Run 7')).toBeTruthy();
    });

    it('caps the list and shows +N more', () => {
        const items = Array.from({ length: 8 }, (_, i) => item(`I${i}`, 'run'));
        const { getByTestId } = render(AwaitingSignoffWidget, {
            props: { items, cap: 5, onSelect: vi.fn() },
        });
        expect(getByTestId('signoff-more').textContent).toContain('+3 more');
    });

    it('invokes onSelect when an item is clicked', async () => {
        const onSelect = vi.fn();
        const it0 = item('Run 7', 'run');
        const { getByText } = render(AwaitingSignoffWidget, {
            props: { items: [it0], onSelect },
        });
        await fireEvent.click(getByText('Run 7'));
        expect(onSelect).toHaveBeenCalledWith(it0);
    });
});
