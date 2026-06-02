import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import RegistrationWaitlist from './RegistrationWaitlist.svelte';

describe('RegistrationWaitlist', () => {
    it('renders the cohort heading and a Calendly CTA in a new tab', () => {
        render(RegistrationWaitlist, {
            calendlyUrl: 'https://calendly.com/test/30min',
        });
        expect(screen.getByText('Join the first cohort')).toBeInTheDocument();
        const cta = screen.getByRole('link', { name: /request early access/i });
        expect(cta).toHaveAttribute('href', 'https://calendly.com/test/30min');
        expect(cta).toHaveAttribute('target', '_blank');
        expect(cta).toHaveAttribute('rel', 'noopener noreferrer');
    });

    it('always offers a back-to-sign-in escape', () => {
        render(RegistrationWaitlist, {
            calendlyUrl: 'https://calendly.com/test/30min',
        });
        const back = screen.getByRole('link', { name: /back to sign in/i });
        expect(back).toHaveAttribute('href', '/login');
    });
});
