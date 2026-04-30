import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorStepper from './RunCreatorStepper.svelte';

describe('RunCreatorStepper', () => {
    it('renders 4 step pills with labels', () => {
        const { getByText } = render(RunCreatorStepper, {
            currentStep: 1,
            highestVisited: 1,
            onJump: () => {},
        });
        expect(getByText(/Name/)).toBeTruthy();
        expect(getByText(/Protocol/)).toBeTruthy();
        expect(getByText(/Parameters/)).toBeTruthy();
        expect(getByText(/Review/)).toBeTruthy();
    });

    it('marks current step active', () => {
        const { container } = render(RunCreatorStepper, {
            currentStep: 2,
            highestVisited: 2,
            onJump: () => {},
        });
        const active = container.querySelector('[data-step-active="true"]');
        expect(active?.textContent).toMatch(/2/);
    });

    it('allows jumping to a previously-visited step', async () => {
        let jumped: number | null = null;
        const { container } = render(RunCreatorStepper, {
            currentStep: 3,
            highestVisited: 3,
            onJump: (n: number) => { jumped = n; },
        });
        const step1 = container.querySelector('[data-step="1"]') as HTMLButtonElement;
        await fireEvent.click(step1);
        expect(jumped).toBe(1);
    });

    it('disables steps beyond highestVisited', async () => {
        let jumped: number | null = null;
        const { container } = render(RunCreatorStepper, {
            currentStep: 1,
            highestVisited: 1,
            onJump: (n: number) => { jumped = n; },
        });
        const step3 = container.querySelector('[data-step="3"]') as HTMLButtonElement;
        expect(step3.disabled).toBe(true);
        await fireEvent.click(step3);
        expect(jumped).toBeNull();
    });
});
