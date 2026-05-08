import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import SaveAsNewVersionDialog from './SaveAsNewVersionDialog.svelte';
import type { Edit } from '$lib/utils/runOverrides';

const sampleEdits: Edit[] = [
    { nodeId: 'n1', stepName: 'Buffer Mix', kind: 'VALUE', field: 'temperature', fieldLabel: 'Temperature', oldValue: 25, newValue: 30 },
    { nodeId: 'n2', stepName: 'Centrifugation', kind: 'SWAP', field: 'equipment', fieldLabel: 'Equipment' },
];

describe('SaveAsNewVersionDialog', () => {
    it('lists every edit with its kind tag', () => {
        const { getByText } = render(SaveAsNewVersionDialog, {
            open: true,
            edits: sampleEdits,
            nextVersionNumber: 4,
            onCancel: () => {},
            onJustThisRun: () => {},
            onSaveAsVersion: () => {},
        });
        expect(getByText(/Buffer Mix/)).toBeTruthy();
        expect(getByText(/Centrifugation/)).toBeTruthy();
        expect(getByText(/VALUE/i)).toBeTruthy();
        expect(getByText(/SWAP/i)).toBeTruthy();
    });

    it('shows v{N+1} in the save-as-version button', () => {
        const { getByText } = render(SaveAsNewVersionDialog, {
            open: true,
            edits: sampleEdits,
            nextVersionNumber: 4,
            onCancel: () => {},
            onJustThisRun: () => {},
            onSaveAsVersion: () => {},
        });
        expect(getByText(/Save as v4/)).toBeTruthy();
    });

    it('fires onJustThisRun when primary clicked', async () => {
        let called = false;
        const { getByText } = render(SaveAsNewVersionDialog, {
            open: true,
            edits: sampleEdits,
            nextVersionNumber: 4,
            onCancel: () => {},
            onJustThisRun: () => { called = true; },
            onSaveAsVersion: () => {},
        });
        await fireEvent.click(getByText(/Just for this run/));
        expect(called).toBe(true);
    });

    it('fires onSaveAsVersion with the description when secondary clicked', async () => {
        let captured: string | null = null;
        const { getByText } = render(SaveAsNewVersionDialog, {
            open: true,
            edits: sampleEdits,
            nextVersionNumber: 4,
            onCancel: () => {},
            onJustThisRun: () => {},
            onSaveAsVersion: (desc: string) => { captured = desc; },
        });
        const ta = document.querySelector('textarea#save-as-desc') as HTMLTextAreaElement;
        await fireEvent.input(ta, { target: { value: 'pH tweak' } });
        await fireEvent.click(getByText(/Save as v4/));
        expect(captured).toBe('pH tweak');
    });
});
