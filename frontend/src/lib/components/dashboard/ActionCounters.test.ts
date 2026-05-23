import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ActionCounters from './ActionCounters.svelte';

const COUNTERS = {
    runs_blocked: 3,
    calibrations_due: 0,
    signoffs_pending: 2,
    active_runs: 5,
};

describe('ActionCounters', () => {
    it('renders all four counters as buttons', () => {
        const { getByTestId } = render(ActionCounters, {
            props: { counters: COUNTERS, onActivate: vi.fn() },
        });
        for (const key of ['runs_blocked', 'calibrations_due', 'signoffs_pending', 'active_runs']) {
            expect(getByTestId(`counter-${key}`).tagName).toBe('BUTTON');
        }
    });

    it('applies danger styling to runs_blocked only when non-zero', () => {
        const { getByTestId } = render(ActionCounters, {
            props: { counters: COUNTERS, onActivate: vi.fn() },
        });
        const blocked = getByTestId('counter-runs_blocked').querySelector('[data-testid="counter-value"]');
        expect(blocked?.className).toContain('text-red-600');
    });

    it('keeps a zero alarm counter muted', () => {
        const { getByTestId } = render(ActionCounters, {
            props: { counters: COUNTERS, onActivate: vi.fn() },
        });
        const cal = getByTestId('counter-calibrations_due').querySelector('[data-testid="counter-value"]');
        expect(cal?.className).toContain('text-muted-foreground');
    });

    it('never alarm-styles the neutral counters', () => {
        const { getByTestId } = render(ActionCounters, {
            props: { counters: COUNTERS, onActivate: vi.fn() },
        });
        const active = getByTestId('counter-active_runs').querySelector('[data-testid="counter-value"]');
        expect(active?.className).not.toContain('text-red-600');
        expect(active?.className).not.toContain('text-amber-600');
    });

    it('alarm-styles a non-zero warn counter amber', () => {
        const { getByTestId } = render(ActionCounters, {
            props: {
                counters: { ...COUNTERS, calibrations_due: 4 },
                onActivate: vi.fn(),
            },
        });
        const cal = getByTestId('counter-calibrations_due').querySelector('[data-testid="counter-value"]');
        expect(cal?.className).toContain('text-amber-600');
    });

    it('invokes onActivate with the counter key on click', async () => {
        const onActivate = vi.fn();
        const { getByTestId } = render(ActionCounters, {
            props: { counters: COUNTERS, onActivate },
        });
        await fireEvent.click(getByTestId('counter-signoffs_pending'));
        expect(onActivate).toHaveBeenCalledWith('signoffs_pending');
    });
});
