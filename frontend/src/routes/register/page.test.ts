import { render, screen } from '@testing-library/svelte';
import { describe, it, expect, beforeEach, vi } from 'vitest';

const flag = vi.hoisted(() => ({ value: true }));
vi.mock('$lib/feature-flags', () => ({
    get REGISTRATION_ENABLED() {
        return flag.value;
    },
}));

import Page from './+page.svelte';

function setUrl(search: string) {
    window.history.replaceState({}, '', `/register${search}`);
}

describe('register page gating', () => {
    beforeEach(() => {
        flag.value = true;
        setUrl('');
    });

    it('shows the sign-up form when the flag is on', () => {
        render(Page);
        expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
        expect(screen.queryByText('Join the first cohort')).not.toBeInTheDocument();
    });

    it('shows the waitlist when the flag is off and no invite', () => {
        flag.value = false;
        render(Page);
        expect(screen.getByText('Join the first cohort')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /create account/i })).not.toBeInTheDocument();
    });

    it('shows the form when the flag is off but an invite is present', () => {
        flag.value = false;
        setUrl('?invite=tok-1');
        render(Page);
        expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
        expect(screen.queryByText('Join the first cohort')).not.toBeInTheDocument();
    });
});
