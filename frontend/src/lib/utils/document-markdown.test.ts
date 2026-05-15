import { describe, expect, it } from 'vitest';

import { toDisplayMarkdown, toStoredMarkdown } from './document-markdown';

const DOC_ID = 'doc-abc';
const BASE = 'http://localhost:8000';

describe('document-markdown rewrite util', () => {
    it('rewrites relative image refs to absolute token-bearing URLs', () => {
        const stored = 'Intro\n\n![Figure 1](images/3.png)\n\nMore text.';
        const display = toDisplayMarkdown(stored, DOC_ID, 'tok123');
        expect(display).toContain(
            `![Figure 1](${BASE}/library/documents/${DOC_ID}/images/3.png?token=tok123)`,
        );
    });

    it('omits the token query when no token is given', () => {
        const display = toDisplayMarkdown('![x](images/1.png)', DOC_ID, null);
        expect(display).toBe(`![x](${BASE}/library/documents/${DOC_ID}/images/1.png)`);
    });

    it('rewrites absolute image URLs back to relative on save', () => {
        const display = `![Figure 1](${BASE}/library/documents/${DOC_ID}/images/3.png?token=tok123)`;
        expect(toStoredMarkdown(display, DOC_ID)).toBe('![Figure 1](images/3.png)');
    });

    it('round-trips losslessly', () => {
        const stored = '# Doc\n\n![a](images/0.png)\n\ntext\n\n![b](images/12.png)\n';
        const back = toStoredMarkdown(toDisplayMarkdown(stored, DOC_ID, 'tok'), DOC_ID);
        expect(back).toBe(stored);
    });

    it('leaves non-image-asset URLs untouched', () => {
        const md = '![ext](https://example.com/pic.png)\n\n[link](images/3.png)';
        expect(toDisplayMarkdown(md, DOC_ID, 'tok')).toBe(md);
    });
});
