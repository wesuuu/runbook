import { render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/auth.svelte', () => ({
    isAuthenticated: () => true,
    isEmailVerified: () => true,
    isTosCurrent: () => false,
    acceptTos: vi.fn().mockResolvedValue(undefined),
}));

import AcceptPage from './+page.svelte';

describe('/legal/accept', () => {
    const data = {
        terms: { markdown: '# T', version: '2026-04-27', effective_date: '2026-04-27' },
        privacy: { markdown: '# P', version: '2026-04-27', effective_date: '2026-04-27' },
    };

    it('renders both documents and the accept form', () => {
        render(AcceptPage, { props: { data } });
        expect(screen.getByText('Terms of Service')).toBeInTheDocument();
        expect(screen.getByText('Privacy Policy')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
    });

    it('shows the at-a-glance callout with the three material terms', () => {
        render(AcceptPage, { props: { data } });
        expect(screen.getByText(/At a glance/i)).toBeInTheDocument();
        expect(screen.getByText(/research use only/i)).toBeInTheDocument();
        expect(screen.getByText(/Protected Health Information/i)).toBeInTheDocument();
        expect(screen.getByText(/train AI models/i)).toBeInTheDocument();
    });
});
