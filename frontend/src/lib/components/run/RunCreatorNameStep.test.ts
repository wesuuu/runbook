import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorNameStep from './RunCreatorNameStep.svelte';

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
        let captured: { name: string; experimentId: string | null } | null = null;
        const { container } = render(RunCreatorNameStep, {
            name: '',
            experimentId: null,
            experiments: EXPERIMENTS,
            lockedExperiment: null,
            onChange: (next: { name: string; experimentId: string | null }) => { captured = next; },
            onValidate: () => {},
        });
        const input = container.querySelector('input[type="text"]') as HTMLInputElement;
        await fireEvent.input(input, { target: { value: 'New' } });
        expect(captured?.name).toBe('New');
    });
});
