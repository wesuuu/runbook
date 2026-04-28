import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import AcceptForm from './AcceptForm.svelte';

describe('AcceptForm', () => {
    it('disables the Accept button until both checkboxes are checked', async () => {
        render(AcceptForm, { props: { onAccept: vi.fn() } });
        const button = screen.getByRole('button', { name: /accept/i });
        expect(button).toBeDisabled();

        await fireEvent.click(screen.getByLabelText(/Terms of Service/i));
        expect(button).toBeDisabled();

        await fireEvent.click(screen.getByLabelText(/Privacy Policy/i));
        expect(button).toBeEnabled();
    });

    it('calls onAccept when both boxes are checked and button is clicked', async () => {
        const onAccept = vi.fn().mockResolvedValueOnce(undefined);
        render(AcceptForm, { props: { onAccept } });

        await fireEvent.click(screen.getByLabelText(/Terms of Service/i));
        await fireEvent.click(screen.getByLabelText(/Privacy Policy/i));
        await fireEvent.click(screen.getByRole('button', { name: /accept/i }));

        expect(onAccept).toHaveBeenCalledOnce();
    });

    it('shows an error message when onAccept rejects', async () => {
        const onAccept = vi.fn().mockRejectedValueOnce(new Error('boom'));
        render(AcceptForm, { props: { onAccept } });

        await fireEvent.click(screen.getByLabelText(/Terms of Service/i));
        await fireEvent.click(screen.getByLabelText(/Privacy Policy/i));
        await fireEvent.click(screen.getByRole('button', { name: /accept/i }));

        await screen.findByText(/boom/);
    });
});
