import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import LabStatusRail from './LabStatusRail.svelte';

describe('LabStatusRail', () => {
    it('composes the three widgets with empty data', () => {
        const { getByText } = render(LabStatusRail, {
            props: {
                calibration: { overdue: [], due_soon: [] },
                awaitingSignoff: [],
                activity: [],
                onCalibrationViewAll: vi.fn(),
                onSignoffSelect: vi.fn(),
            },
        });
        expect(getByText('Equipment Calibration')).toBeTruthy();
        expect(getByText('Awaiting Sign-off')).toBeTruthy();
        expect(getByText('Recent Activity')).toBeTruthy();
    });
});
