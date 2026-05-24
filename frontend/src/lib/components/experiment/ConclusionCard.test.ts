import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ConclusionCard from '$lib/components/experiment/ConclusionCard.svelte';

const baseProps: any = {
    experiment: { id: 'e1', conclusion: '', conclusion_locked_at: null,
                  conclusion_locked_by_name: null, slug: 'e1' },
    hasOpenRuns: false,
    canAdmin: false,
    onSave: () => {},
    onLock: () => {},
    onUnlock: (_reason: string) => {},
};

describe('ConclusionCard', () => {
    it('disables Lock when body empty', () => {
        const { getByRole } = render(ConclusionCard, { props: baseProps });
        const btn = getByRole('button', { name: /lock conclusion/i });
        expect(btn.hasAttribute('disabled')).toBe(true);
    });

    it('disables Lock when runs are open', () => {
        const { getByRole } = render(ConclusionCard, {
            props: { ...baseProps,
                     experiment: { ...baseProps.experiment, conclusion: 'done' },
                     hasOpenRuns: true },
        });
        const btn = getByRole('button', { name: /lock conclusion/i });
        expect(btn.hasAttribute('disabled')).toBe(true);
    });

    it('hides admin unlock when canAdmin is false', () => {
        const { queryByRole } = render(ConclusionCard, {
            props: {
                ...baseProps,
                experiment: { ...baseProps.experiment, conclusion: 'x',
                              conclusion_locked_at: '2026-05-22T00:00:00Z',
                              conclusion_locked_by_name: 'Alice' },
                canAdmin: false,
            },
        });
        expect(queryByRole('button', { name: /unlock/i })).toBeNull();
    });

    it('blocks unlock submit until reason >= 8 chars', async () => {
        const { getByRole, getByLabelText } = render(ConclusionCard, {
            props: {
                ...baseProps,
                experiment: { ...baseProps.experiment, conclusion: 'x',
                              conclusion_locked_at: '2026-05-22T00:00:00Z',
                              conclusion_locked_by_name: 'Alice' },
                canAdmin: true,
            },
        });
        await fireEvent.click(getByRole('button', { name: /unlock and edit/i }));
        const submit = getByRole('button', { name: /submit unlock/i });
        expect(submit.hasAttribute('disabled')).toBe(true);
        const ta = getByLabelText(/reason/i);
        await fireEvent.input(ta, { target: { value: 'short' } });
        expect(submit.hasAttribute('disabled')).toBe(true);
        await fireEvent.input(ta, { target: { value: 'long enough reason' } });
        expect(submit.hasAttribute('disabled')).toBe(false);
    });
});
