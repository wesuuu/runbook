import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({
    getToken: () => 'tok123',
    logout: () => {},
}));

import RefinementAiPanel from './RefinementAiPanel.svelte';
import * as documentsApi from '$lib/api/documents';

const SELECTION = {
    scope: 'selection' as const,
    markdown: 'NaHzPO4119.98',
    context: 'Add NaHzPO4119.98 to the buffer',
};

describe('RefinementAiPanel', () => {
    afterEach(() => vi.restoreAllMocks());

    it('shows a hint when there is no selection', () => {
        render(RefinementAiPanel, {
            props: {
                documentId: 'doc-1',
                selection: null,
                onAccept: vi.fn(),
                onCancel: vi.fn(),
            },
        });
        expect(screen.getByText(/select text/i)).toBeTruthy();
    });

    it('submits the instruction and renders the suggested diff', async () => {
        const spy = vi
            .spyOn(documentsApi, 'refineDocumentWithAi')
            .mockResolvedValue({
                suggested_markdown: 'NaH2PO4 119.98',
                model_used: 'claude-sonnet-4-6',
            });
        render(RefinementAiPanel, {
            props: {
                documentId: 'doc-1',
                selection: SELECTION,
                onAccept: vi.fn(),
                onCancel: vi.fn(),
            },
        });
        await fireEvent.input(screen.getByPlaceholderText(/how should/i), {
            target: { value: 'fix the formula spacing' },
        });
        await fireEvent.click(screen.getByRole('button', { name: /ask ai/i }));

        await waitFor(() => expect(screen.getByText('NaH2PO4 119.98')).toBeTruthy());
        expect(spy).toHaveBeenCalledWith('doc-1', {
            scope: 'selection',
            selectionMarkdown: 'NaHzPO4119.98',
            instruction: 'fix the formula spacing',
            surroundingContextMarkdown: 'Add NaHzPO4119.98 to the buffer',
        });
    });

    it('calls onAccept with the suggestion when Accept is clicked', async () => {
        vi.spyOn(documentsApi, 'refineDocumentWithAi').mockResolvedValue({
            suggested_markdown: 'NaH2PO4 119.98',
            model_used: 'claude-sonnet-4-6',
        });
        const onAccept = vi.fn();
        render(RefinementAiPanel, {
            props: { documentId: 'doc-1', selection: SELECTION, onAccept, onCancel: vi.fn() },
        });
        await fireEvent.input(screen.getByPlaceholderText(/how should/i), {
            target: { value: 'fix it' },
        });
        await fireEvent.click(screen.getByRole('button', { name: /ask ai/i }));
        await waitFor(() => screen.getByText('NaH2PO4 119.98'));
        await fireEvent.click(screen.getByRole('button', { name: /accept/i }));
        expect(onAccept).toHaveBeenCalledWith('NaH2PO4 119.98');
    });

    it('surfaces an error when the AI call fails', async () => {
        vi.spyOn(documentsApi, 'refineDocumentWithAi').mockRejectedValue(
            new Error('model unavailable'),
        );
        render(RefinementAiPanel, {
            props: {
                documentId: 'doc-1',
                selection: SELECTION,
                onAccept: vi.fn(),
                onCancel: vi.fn(),
            },
        });
        await fireEvent.input(screen.getByPlaceholderText(/how should/i), {
            target: { value: 'fix it' },
        });
        await fireEvent.click(screen.getByRole('button', { name: /ask ai/i }));
        await waitFor(() => expect(screen.getByText(/model unavailable/i)).toBeTruthy());
    });
});
