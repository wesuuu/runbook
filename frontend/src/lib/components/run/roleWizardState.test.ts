import { describe, it, expect } from 'vitest';
import {
    stepProgressPercent,
    areStepFieldsLocked,
    barcodeScanApplies,
} from './roleWizardState';

describe('stepProgressPercent', () => {
    it('is 0 when nothing is completed', () => {
        expect(stepProgressPercent(0, 2)).toBe(0);
    });

    it('is 50 when half the steps are completed', () => {
        expect(stepProgressPercent(1, 2)).toBe(50);
    });

    it('is 100 when every step is completed (#24)', () => {
        // A two-step run with both steps done must show a full bar — it
        // previously sat at ~50% because it tracked the viewed step index.
        expect(stepProgressPercent(2, 2)).toBe(100);
    });

    it('returns 0 for a run with no steps', () => {
        expect(stepProgressPercent(0, 0)).toBe(0);
    });

    it('clamps to [0, 100] for out-of-range inputs', () => {
        expect(stepProgressPercent(-1, 2)).toBe(0);
        expect(stepProgressPercent(5, 2)).toBe(100);
    });
});

describe('areStepFieldsLocked', () => {
    it('locks the fields of a completed step (#23)', () => {
        expect(areStepFieldsLocked(false, 'completed')).toBe(true);
    });

    it('leaves an in-progress step editable', () => {
        expect(areStepFieldsLocked(false, 'in_progress')).toBe(false);
    });

    it('leaves a pending or undefined step editable', () => {
        expect(areStepFieldsLocked(false, 'pending')).toBe(false);
        expect(areStepFieldsLocked(false, undefined)).toBe(false);
    });

    it('locks every step when the wizard is read-only', () => {
        expect(areStepFieldsLocked(true, 'in_progress')).toBe(true);
        expect(areStepFieldsLocked(true, undefined)).toBe(true);
    });
});

describe('barcodeScanApplies', () => {
    it('is hidden for numeric process parameters (#26)', () => {
        // RPM / duration / temperature are numbers — a barcode scanner
        // next to them makes no sense.
        expect(barcodeScanApplies('number')).toBe(false);
        expect(barcodeScanApplies('integer')).toBe(false);
    });

    it('is offered for text fields', () => {
        expect(barcodeScanApplies('string')).toBe(true);
    });

    it('is offered when the field type is unknown', () => {
        expect(barcodeScanApplies(undefined)).toBe(true);
    });

    it('is offered for other non-numeric types', () => {
        expect(barcodeScanApplies('boolean')).toBe(true);
    });
});
