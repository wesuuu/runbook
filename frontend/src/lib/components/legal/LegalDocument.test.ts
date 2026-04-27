import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import LegalDocument from './LegalDocument.svelte';

describe('LegalDocument', () => {
    it('renders the title', () => {
        render(LegalDocument, {
            props: {
                title: 'Terms of Service',
                markdown: '# Hello',
                version: '2026-04-27',
                effectiveDate: '2026-04-27',
            },
        });
        expect(screen.getByText('Terms of Service')).toBeInTheDocument();
    });

    it('renders the version and effective date', () => {
        render(LegalDocument, {
            props: {
                title: 'Privacy Policy',
                markdown: '# Hi',
                version: '2026-04-27',
                effectiveDate: '2026-04-27',
            },
        });
        expect(screen.getByText(/2026-04-27/)).toBeInTheDocument();
    });

    it('renders the markdown content', () => {
        render(LegalDocument, {
            props: {
                title: 'Terms',
                markdown: '# Section',
                version: '2026-04-27',
                effectiveDate: '2026-04-27',
            },
        });
        // Use a substring match because MarkdownRenderer wraps output in DOM elements
        expect(screen.getByText(/Section/)).toBeInTheDocument();
    });
});
