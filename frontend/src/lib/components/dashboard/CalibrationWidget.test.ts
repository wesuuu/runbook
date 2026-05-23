import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import CalibrationWidget from './CalibrationWidget.svelte';

function item(name: string, state: string) {
    return { equipment_id: name, name, site_name: null, next_calibration_date: null, state };
}

describe('CalibrationWidget', () => {
    it('shows the empty line when nothing is due', () => {
        const { getByTestId } = render(CalibrationWidget, {
            props: { calibration: { overdue: [], due_soon: [] }, onViewAll: vi.fn() },
        });
        expect(getByTestId('calibration-empty').textContent).toContain('No calibrations due.');
    });

    it('renders overdue and due-soon items', () => {
        const { getByText } = render(CalibrationWidget, {
            props: {
                calibration: { overdue: [item('Centrifuge', 'overdue')], due_soon: [item('pH Meter', 'due_soon')] },
                onViewAll: vi.fn(),
            },
        });
        expect(getByText('Centrifuge')).toBeTruthy();
        expect(getByText('pH Meter')).toBeTruthy();
    });

    it('caps the list and shows a +N more link, overdue filling the cap first', () => {
        const overdue = Array.from({ length: 6 }, (_, i) => item(`O${i}`, 'overdue'));
        const { getByTestId, queryByText } = render(CalibrationWidget, {
            props: {
                calibration: { overdue, due_soon: [item('DS', 'due_soon')] },
                cap: 5,
                onViewAll: vi.fn(),
            },
        });
        // 6 overdue + 1 due-soon = 7, cap 5 → 2 hidden
        expect(getByTestId('calibration-more').textContent).toContain('+2 more');
        // due-soon item is truncated in favour of overdue
        expect(queryByText('DS')).toBeNull();
    });
});
