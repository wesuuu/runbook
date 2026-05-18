import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorNameStep from './RunCreatorNameStep.svelte';

interface ChangePayload {
    name: string;
    experimentId: string | null;
    producesLot: boolean;
    lotNumber: string;
    batchNumber: string;
}

const EXPERIMENTS = [
    { id: 'e1', name: 'Pilot', status: 'ACTIVE' },
    { id: 'e2', name: 'Archived', status: 'ARCHIVED' },
];

vi.mock('$lib/api', () => ({
    api: {
        get: vi.fn(),
        post: vi.fn(),
    },
}));

import { api } from '$lib/api';

describe('RunCreatorNameStep', () => {
    it('shows error when name is empty and onValidate fires false', () => {
        let lastValid: boolean | null = null;
        render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            projectId: 'p1',
            onChange: () => {},
            onValidate: (v: boolean) => { lastValid = v; },
        });
        expect(lastValid).toBe(false);
    });

    it('marks valid when name is non-empty', () => {
        let lastValid: boolean | null = null;
        render(RunCreatorNameStep, {
            name: 'My Run',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            projectId: 'p1',
            onChange: () => {},
            onValidate: (v: boolean) => { lastValid = v; },
        });
        expect(lastValid).toBe(true);
    });

    it('hides archived experiments from the dropdown', () => {
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            projectId: 'p1',
            onChange: () => {},
            onValidate: () => {},
        });
        const opts = container.querySelectorAll('option');
        const labels = Array.from(opts).map((o) => o.textContent);
        expect(labels.some((l) => l?.includes('Archived'))).toBe(false);
    });

    it('locks experiment field when lockedExperiment is set', () => {
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: 'e1',
            experiments: EXPERIMENTS,
            lockedExperiment: { id: 'e1', name: 'Pilot' },
            projectId: 'p1',
            onChange: () => {},
            onValidate: () => {},
        });
        const sel = container.querySelector('select');
        expect(sel?.disabled).toBe(true);
    });

    it('emits onChange when user types name', async () => {
        let captured: ChangePayload = {
            name: '',
            experimentId: null,
            producesLot: false,
            lotNumber: '',
            batchNumber: '',
        };
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            projectId: 'p1',
            onChange: (next: ChangePayload) => { captured = next; },
            onValidate: () => {},
        });
        const input = container.querySelector('input[type="text"]') as HTMLInputElement;
        await fireEvent.input(input, { target: { value: 'New' } });
        expect(captured.name).toBe('New');
    });

    it('renders batch number input', () => {
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: false,
            lotNumber: '',
            batchNumber: '',
            projectId: 'p1',
            onChange: () => {},
            onValidate: () => {},
        });
        const batchInput = container.querySelector('#run-batch') as HTMLInputElement | null;
        expect(batchInput).not.toBeNull();
    });

    it('emits onChange with batchNumber when batch input is edited', async () => {
        let captured: ChangePayload = {
            name: 'Run X',
            experimentId: null,
            producesLot: false,
            lotNumber: '',
            batchNumber: '',
        };
        const { container } = render(RunCreatorNameStep, {
            name: 'Run X',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: false,
            lotNumber: '',
            batchNumber: '',
            projectId: 'p1',
            onChange: (next: ChangePayload) => { captured = next; },
            onValidate: () => {},
        });
        const batchInput = container.querySelector('#run-batch') as HTMLInputElement;
        await fireEvent.input(batchInput, { target: { value: 'BATCH-42' } });
        expect(captured.batchNumber).toBe('BATCH-42');
    });
});

describe('RunCreatorNameStep · produces_lot', () => {
    it('hides lot input when toggle is off', () => {
        const { queryByLabelText } = render(RunCreatorNameStep, {
            name: 'r',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: false,
            lotNumber: '',
            batchNumber: '',
            projectId: 'p1',
            onChange: () => {},
            onValidate: () => {},
        });
        expect(queryByLabelText(/Lot number/)).toBeNull();
    });

    it('shows lot input when producesLot is true', () => {
        const { getByLabelText } = render(RunCreatorNameStep, {
            name: 'r',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: true,
            lotNumber: '',
            batchNumber: '',
            projectId: 'p1',
            onChange: () => {},
            onValidate: () => {},
        });
        expect(getByLabelText(/Lot number/)).toBeTruthy();
    });

    it('clicking Auto-generate populates the lot input via onChange', async () => {
        (api.post as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ lot_number: 'LOT-000042' });
        let latest: ChangePayload | null = null as ChangePayload | null;
        const { getByText } = render(RunCreatorNameStep, {
            name: 'r',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: true,
            lotNumber: '',
            batchNumber: '',
            projectId: 'p1',
            onChange: (next: ChangePayload) => { latest = next; },
            onValidate: () => {},
        });
        await fireEvent.click(getByText('Auto-generate'));
        expect(api.post).toHaveBeenCalledWith(
            '/science/runs/suggest-lot-number',
            { project_id: 'p1' },
        );
        expect(latest?.lotNumber).toBe('LOT-000042');
    });

    it('renders duplicate warning when check-lot-number returns exists=true', async () => {
        (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ exists: true, count: 2 });
        const { getByLabelText, findByTestId } = render(RunCreatorNameStep, {
            name: 'r',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            producesLot: true,
            lotNumber: 'DUP-1',
            batchNumber: '',
            projectId: 'p1',
            onChange: () => {},
            onValidate: () => {},
        });
        const input = getByLabelText(/Lot number/) as HTMLInputElement;
        await fireEvent.blur(input);
        const warning = await findByTestId('lot-duplicate-warning');
        expect(warning.textContent).toMatch(/already exists/);
    });
});
