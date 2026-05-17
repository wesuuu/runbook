import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({
    getToken: () => 'tok123',
    logout: () => {},
}));

import RefinementSidebar from './RefinementSidebar.svelte';

const BASE_PROPS = {
    documentId: 'doc-1',
    mimeType: 'application/pdf',
    pageCount: 3,
    status: 'AWAITING_REFINEMENT',
    sourceFormat: 'PDF',
    ocrEngine: 'easyocr',
};

describe('RefinementSidebar', () => {
    it('renders the source-page thumbnail for a PDF', () => {
        const { container } = render(RefinementSidebar, { props: BASE_PROPS });
        const img = container.querySelector('img');
        expect(img?.getAttribute('src')).toContain(
            '/library/documents/doc-1/source-page/1.png',
        );
    });

    it('advances the page when Next is clicked', async () => {
        const { container } = render(RefinementSidebar, { props: BASE_PROPS });
        await fireEvent.click(screen.getByRole('button', { name: /next page/i }));
        expect(container.querySelector('img')?.getAttribute('src')).toContain(
            '/source-page/2.png',
        );
    });

    it('does not render a thumbnail for a non-PDF source', () => {
        const { container } = render(RefinementSidebar, {
            props: { ...BASE_PROPS, mimeType: 'image/png', sourceFormat: 'IMAGE' },
        });
        expect(container.querySelector('img')).toBeNull();
    });

    it('marks the current pipeline step active from the status', () => {
        render(RefinementSidebar, { props: BASE_PROPS });
        const active = screen.getByText('Awaiting refinement').closest('li');
        expect(active?.getAttribute('data-active')).toBe('true');
    });
});
