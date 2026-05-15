import { render } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({
    getToken: () => null,
    logout: () => {},
}));

import MarkdownDocument from './MarkdownDocument.svelte';

describe('MarkdownDocument', () => {
    it('renders markdown headings and paragraphs as HTML', () => {
        const { container } = render(MarkdownDocument, {
            props: { markdown: '# Batch Record\n\nProduct: mAb-X', documentId: 'doc-1' },
        });
        expect(container.querySelector('h1')?.textContent).toBe('Batch Record');
        expect(container.querySelector('p')?.textContent).toContain('mAb-X');
    });

    it('rewrites relative image refs to absolute API URLs', () => {
        const { container } = render(MarkdownDocument, {
            props: { markdown: '![Fig 1](images/2.png)', documentId: 'doc-1' },
        });
        const img = container.querySelector('img');
        expect(img?.getAttribute('src')).toContain(
            '/library/documents/doc-1/images/2.png',
        );
    });

    it('renders a table from GFM markdown', () => {
        const md = '| A | B |\n| --- | --- |\n| 1 | 2 |';
        const { container } = render(MarkdownDocument, {
            props: { markdown: md, documentId: 'doc-1' },
        });
        expect(container.querySelector('table')).not.toBeNull();
        expect(container.querySelectorAll('td')).toHaveLength(2);
    });
});
