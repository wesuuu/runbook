import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import RunCreatorReviewStep from './RunCreatorReviewStep.svelte';

describe('RunCreatorReviewStep', () => {
    it('renders the run name, protocol name, and version', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7',
            experimentName: null,
            protocolName: 'Mab-A',
            versionNumber: 3,
            isLatestVersion: true,
            edits: [],
            creating: false,
            error: null,
            onCreate: () => {},
        });
        expect(getByText('Run 7')).toBeTruthy();
        expect(getByText('Mab-A')).toBeTruthy();
        expect(getByText(/v3/)).toBeTruthy();
    });

    it('shows "uses protocol defaults" when no edits', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true, edits: [],
            creating: false, error: null, onCreate: () => {},
        });
        expect(getByText(/uses protocol defaults/i)).toBeTruthy();
    });

    it('lists edits when present', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true,
            edits: [
                { nodeId: 'n1', stepName: 'Buffer Mix', kind: 'VALUE', field: 'temperature', fieldLabel: 'Temperature', oldValue: 25, newValue: 30 },
            ],
            creating: false, error: null, onCreate: () => {},
        });
        expect(getByText(/Buffer Mix/)).toBeTruthy();
    });

    it('fires onCreate when Create button clicked', async () => {
        let called = false;
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true, edits: [],
            creating: false, error: null,
            onCreate: () => { called = true; },
        });
        await fireEvent.click(getByText(/Create run/i));
        expect(called).toBe(true);
    });

    it('disables Create button when creating=true', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true, edits: [],
            creating: true, error: null, onCreate: () => {},
        });
        const btn = getByText(/Creating/i).closest('button') as HTMLButtonElement;
        expect(btn.disabled).toBe(true);
    });

    it('renders error message when error is set', () => {
        const { getByText } = render(RunCreatorReviewStep, {
            runName: 'Run 7', experimentName: null, protocolName: 'Mab-A',
            versionNumber: 3, isLatestVersion: true, edits: [],
            creating: false, error: 'Backend exploded', onCreate: () => {},
        });
        expect(getByText('Backend exploded')).toBeTruthy();
    });
});
