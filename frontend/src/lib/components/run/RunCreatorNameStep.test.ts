import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorNameStep from './RunCreatorNameStep.svelte';

interface ChangePayload {
    name: string;
    experimentId: string | null;
    lotNumber: string;
    batchNumber: string;
}

const EXPERIMENTS = [
    { id: 'e1', name: 'Pilot', status: 'ACTIVE' },
    { id: 'e2', name: 'Archived', status: 'ARCHIVED' },
];

describe('RunCreatorNameStep', () => {
    it('shows error when name is empty and onValidate fires false', () => {
        let lastValid: boolean | null = null;
        render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
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
            lotNumber: '',
            batchNumber: '',
        };
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            onChange: (next: ChangePayload) => { captured = next; },
            onValidate: () => {},
        });
        const input = container.querySelector('input[type="text"]') as HTMLInputElement;
        await fireEvent.input(input, { target: { value: 'New' } });
        expect(captured.name).toBe('New');
    });

    it('renders lot number and batch number inputs', () => {
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            lotNumber: '',
            batchNumber: '',
            onChange: () => {},
            onValidate: () => {},
        });
        const lotInput = container.querySelector('#run-lot') as HTMLInputElement | null;
        const batchInput = container.querySelector('#run-batch') as HTMLInputElement | null;
        expect(lotInput).not.toBeNull();
        expect(batchInput).not.toBeNull();
    });

    it('emits onChange with lotNumber and batchNumber when those inputs are edited', async () => {
        let captured: ChangePayload = {
            name: 'Run X',
            experimentId: null,
            lotNumber: '',
            batchNumber: '',
        };
        const { container } = render(RunCreatorNameStep, {
            name: 'Run X',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            lotNumber: '',
            batchNumber: '',
            onChange: (next: ChangePayload) => { captured = next; },
            onValidate: () => {},
        });
        const lotInput = container.querySelector('#run-lot') as HTMLInputElement;
        await fireEvent.input(lotInput, { target: { value: 'LOT-001' } });
        expect(captured.lotNumber).toBe('LOT-001');
        expect(captured.batchNumber).toBe('');

        const batchInput = container.querySelector('#run-batch') as HTMLInputElement;
        await fireEvent.input(batchInput, { target: { value: 'BATCH-42' } });
        expect(captured.batchNumber).toBe('BATCH-42');
    });
});
