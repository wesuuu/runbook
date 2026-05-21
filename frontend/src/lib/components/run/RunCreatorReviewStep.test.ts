import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorReviewStep from './RunCreatorReviewStep.svelte';

const baseProps = {
    runName: 'Run 7',
    experimentName: null,
    protocolName: 'Mab-A',
    versionNumber: 3,
    isLatestVersion: true,
    edits: [],
    assignees: [] as Array<{ role: string; name: string }>,
    creating: false,
    error: null,
    onCreate: () => {},
};

describe('RunCreatorReviewStep', () => {
    it('renders the run name, protocol name, and version', () => {
        const { getByText } = render(RunCreatorReviewStep, { ...baseProps });
        expect(getByText('Run 7')).toBeTruthy();
        expect(getByText('Mab-A')).toBeTruthy();
        expect(getByText(/v3/)).toBeTruthy();
    });

    it('heading reflects step 5, matching the stepper', () => {
        const { getByText } = render(RunCreatorReviewStep, { ...baseProps });
        expect(getByText(/Step 5 ·/)).toBeTruthy();
    });

    it('shows "uses protocol defaults" when no edits', () => {
        const { getByText } = render(RunCreatorReviewStep, { ...baseProps });
        expect(getByText(/uses protocol defaults/i)).toBeTruthy();
    });

    it('lists edits when present', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            ...baseProps,
            edits: [
                { nodeId: 'n1', stepName: 'Buffer Mix', kind: 'VALUE', field: 'temperature', fieldLabel: 'Temperature', oldValue: 25, newValue: 30 },
            ],
        });
        expect(getByText(/Buffer Mix/)).toBeTruthy();
    });

    it('shows the assigned operator in the summary', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            ...baseProps,
            assignees: [{ role: 'Operator', name: 'Wesley Soo' }],
        });
        expect(getByText(/Operator: Wesley Soo/)).toBeTruthy();
    });

    it('notes when no assignee was picked', () => {
        const { getByText } = render(RunCreatorReviewStep, { ...baseProps });
        expect(getByText(/Not assigned/i)).toBeTruthy();
    });

    it('fires onCreate when Create button clicked', async () => {
        let called = false;
        const { getByText } = render(RunCreatorReviewStep, {
            ...baseProps,
            onCreate: () => { called = true; },
        });
        await fireEvent.click(getByText(/Create run/i));
        expect(called).toBe(true);
    });

    it('disables Create button when creating=true', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            ...baseProps,
            creating: true,
        });
        const btn = getByText(/Creating/i).closest('button') as HTMLButtonElement;
        expect(btn.disabled).toBe(true);
    });

    it('renders error message when error is set', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            ...baseProps,
            error: 'Backend exploded',
        });
        expect(getByText('Backend exploded')).toBeTruthy();
    });
});
