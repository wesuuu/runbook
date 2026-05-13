import { describe, it, expect } from 'vitest';
import { computeDeviations } from './approval-diff';

describe('computeDeviations', () => {
    it('returns no deviations when the edited list matches the original', () => {
        const orig = [{ text: 'Step 1' }, { text: 'Step 2' }];
        expect(computeDeviations(orig, [...orig])).toEqual([]);
    });

    it('emits "Removed step" for a step the user deleted', () => {
        const orig = [{ text: 'Step 1' }, { text: 'Step 2' }, { text: 'Step 3' }];
        const edited = [{ text: 'Step 1' }, { text: 'Step 3' }];
        expect(computeDeviations(orig, edited)).toEqual(['Removed step: Step 2']);
    });

    it('emits "Added step" for a step the user inserted', () => {
        const orig = [{ text: 'Step 1' }, { text: 'Step 2' }];
        const edited = [
            { text: 'Step 1' },
            { text: 'Step 1.5 new' },
            { text: 'Step 2' },
        ];
        expect(computeDeviations(orig, edited)).toEqual([
            'Added step: Step 1.5 new',
        ]);
    });

    it('emits "Edited step" with strikethrough for in-place text edits', () => {
        const orig = [{ text: 'Heat at 60s' }];
        const edited = [{ text: 'Heat at 30s' }];
        expect(computeDeviations(orig, edited)).toEqual([
            'Edited step: ~~Heat at 60s~~ Heat at 30s',
        ]);
    });

    it('handles a mix of add + remove + edit', () => {
        const orig = [
            { text: 'Mix buffer' },
            { text: 'Spin 5 min' },
            { text: 'Plate cells' },
        ];
        const edited = [
            { text: 'Mix sterile buffer' }, // edit
            // remove "Spin 5 min"
            { text: 'Plate cells' },
            { text: 'Incubate 30 min' }, // add
        ];
        expect(computeDeviations(orig, edited)).toEqual([
            'Edited step: ~~Mix buffer~~ Mix sterile buffer',
            'Removed step: Spin 5 min',
            'Added step: Incubate 30 min',
        ]);
    });

    it('trims surrounding whitespace before comparing', () => {
        const orig = [{ text: 'Step 1' }];
        const edited = [{ text: '   Step 1\n' }];
        expect(computeDeviations(orig, edited)).toEqual([]);
    });
});
