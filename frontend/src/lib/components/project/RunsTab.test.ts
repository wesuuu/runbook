import { describe, it, expect } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import RunsTab from './RunsTab.svelte';

const RUNS = [
    { id: 'r1', name: 'producer-1', status: 'COMPLETED', produces_lot: true, lot_number: 'LOT-000001', experiment_id: null, protocol_id: null, updated_at: '', created_at: '' },
    { id: 'r2', name: 'non-prod', status: 'COMPLETED', produces_lot: false, lot_number: null, experiment_id: null, protocol_id: null, updated_at: '', created_at: '' },
];

describe('RunsTab · produces_lot filter', () => {
    it('filter chip hides non-producing runs when active', async () => {
        // RunsTab renders runs in both a desktop table and a mobile card list,
        // so each run name appears multiple times in jsdom. Use getAllByText.
        const { getByTestId, queryAllByText, getAllByText } = render(RunsTab, {
            runs: RUNS,
            protocols: [],
            experiments: [],
        });
        expect(getAllByText('producer-1').length).toBeGreaterThan(0);
        expect(getAllByText('non-prod').length).toBeGreaterThan(0);
        await fireEvent.click(getByTestId('lot-producer-filter'));
        await waitFor(() => {
            expect(queryAllByText('non-prod').length).toBe(0);
        });
        expect(getAllByText('producer-1').length).toBeGreaterThan(0);
    });

    it('Lot # column appears only when filter is active', async () => {
        const { getByTestId, queryByText } = render(RunsTab, {
            runs: RUNS,
            protocols: [],
            experiments: [],
        });
        expect(queryByText('Lot #')).toBeNull();
        await fireEvent.click(getByTestId('lot-producer-filter'));
        expect(queryByText('Lot #')).toBeTruthy();
    });
});
