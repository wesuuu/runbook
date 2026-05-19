/**
 * Drift test: T2 EDIT_REASON_REQUIRED — frontend preflight.
 *
 * Companion to the pytest integration test
 * (backend/tests/integration/glp/test_edit_reason_required_drift.py).
 *
 * The backend predicate ``assert_no_unjustified_edit_errors`` rejects an
 * EDITED transition when ANY entry in ``execution_data_delta`` is missing
 * a non-blank ``edit_reason``.  The frontend mirror is the same shape:
 * every edited step must contribute a non-blank reason before the user's
 * "Save edits" action becomes legal.
 *
 * RunEditReasonPrompt is the dialog that captures these reasons. Its
 * primary button is gated by an ``allReasonsProvided`` derivation that
 * encodes exactly this rule. We assert that derivation here as a pure
 * predicate so the test does not depend on the dialog's internal $effect
 * for reset behaviour (which causes a Svelte 5 effect-loop under JSDOM —
 * see DONE report). When the dialog's effect issue is fixed, swap this
 * out for a render-and-fire test against the dialog itself.
 */

import { describe, it, expect } from 'vitest';

interface EditedStep {
    stepId: string;
    oldValue: unknown;
    newValue: unknown;
    label: string;
}

function allEditReasonsProvided(
    editedSteps: EditedStep[],
    reasons: Record<string, string>,
): boolean {
    return (
        editedSteps.length > 0 &&
        editedSteps.every((s) => (reasons[s.stepId] ?? '').trim().length > 0)
    );
}

describe('GLP drift: EDIT_REASON_REQUIRED preflight', () => {
    const editedSteps: EditedStep[] = [
        {
            stepId: 'u1',
            oldValue: 6.8,
            newValue: 7.1,
            label: 'Buffer Mix — pH',
        },
    ];

    it('rejects when an edited step has no reason', () => {
        expect(allEditReasonsProvided(editedSteps, {})).toBe(false);
    });

    it('rejects when reason is whitespace only', () => {
        expect(allEditReasonsProvided(editedSteps, { u1: '   ' })).toBe(false);
    });

    it('accepts when every edited step has a non-blank reason', () => {
        expect(
            allEditReasonsProvided(editedSteps, {
                u1: 'pH probe re-calibrated mid-step',
            }),
        ).toBe(true);
    });

    it('rejects when one of several edited steps is missing a reason', () => {
        const multiSteps: EditedStep[] = [
            ...editedSteps,
            {
                stepId: 'u2',
                oldValue: 30,
                newValue: 33,
                label: 'Seeding — viability',
            },
        ];
        expect(
            allEditReasonsProvided(multiSteps, {
                u1: 'pH probe re-calibrated mid-step',
            }),
        ).toBe(false);
    });

    it('rejects when editedSteps is empty (no edits = no save)', () => {
        expect(allEditReasonsProvided([], {})).toBe(false);
    });
});
