import { render, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({
    getToken: () => 'tok123',
    logout: () => {},
}));

// Mock the edra barrel so the component mounts without a real Tiptap instance.
vi.mock('$lib/components/edra/shadcn', () => ({
    EdraEditor: (() => {}) as unknown,
    EdraToolBar: (() => {}) as unknown,
}));

import RefinementEditor from './RefinementEditor.svelte';

describe('RefinementEditor', () => {
    it('renders a container and loads the edra module', async () => {
        const { container } = render(RefinementEditor, {
            props: {
                documentId: 'doc-1',
                initialMarkdown: '# Hello\n\n![f](images/1.png)',
            },
        });
        await waitFor(() =>
            expect(container.querySelector('.refinement-editor')).not.toBeNull(),
        );
    });
});
