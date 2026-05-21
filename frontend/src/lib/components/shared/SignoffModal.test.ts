import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import SignoffModal from './SignoffModal.svelte';

describe('SignoffModal', () => {
    it('renders attestation defaulted to the role text', async () => {
        render(SignoffModal, {
            props: {
                open: true,
                role: 'QAU',
                entityType: 'run',
                entityId: 'run-1',
                defaultAttestation: 'I attest as QAU.',
                signerName: 'Wesley',
                signatureImageUrl: '/sig.png',
                onConfirm: () => {},
                onCancel: () => {},
            },
        });
        const ta = screen.getByLabelText(/attestation/i) as HTMLTextAreaElement;
        expect(ta.value).toBe('I attest as QAU.');
    });

    it('disables confirm when attestation empty', async () => {
        render(SignoffModal, {
            props: {
                open: true,
                role: 'QAU',
                entityType: 'run',
                entityId: 'run-1',
                defaultAttestation: '',
                signerName: 'Wesley',
                signatureImageUrl: '/sig.png',
                onConfirm: () => {},
                onCancel: () => {},
            },
        });
        const btn = screen.getByRole('button', { name: /confirm sign-off/i });
        expect(btn).toBeDisabled();
    });

    it('shows a generated default signature with a link when none on file', () => {
        render(SignoffModal, {
            props: {
                open: true,
                role: 'OPERATOR',
                entityType: 'run',
                entityId: 'run-1',
                defaultAttestation: 'I performed the operations as written.',
                signerName: 'Wesley',
                signatureImageUrl: null,
                onConfirm: () => {},
                onCancel: () => {},
            },
        });
        // The generated cursive image stands in for an uploaded signature.
        const img = screen.getByAltText(/auto-generated signature/i);
        expect(img).toBeTruthy();
        expect(img.getAttribute('src')).toContain('/auth/me/default-signature');
        // A link points the signer to where they can upload their own.
        const link = screen.getByRole('link', { name: /set your own/i });
        expect(link.getAttribute('href')).toBe('/settings?tab=profile');
    });

    it('shows the uploaded signature image when one is on file', () => {
        render(SignoffModal, {
            props: {
                open: true,
                role: 'OPERATOR',
                entityType: 'run',
                entityId: 'run-1',
                defaultAttestation: 'I performed the operations as written.',
                signerName: 'Wesley',
                signatureImageUrl: '/sig.png',
                onConfirm: () => {},
                onCancel: () => {},
            },
        });
        const img = screen.getByAltText(/^signature$/i) as HTMLImageElement;
        expect(img.getAttribute('src')).toBe('/sig.png');
        // No "set your own" prompt when a real signature exists.
        expect(screen.queryByRole('link', { name: /set your own/i })).toBeNull();
    });

    it('syncs attestation when opened after mount with a new default', async () => {
        // The modal is mounted once and reused — `open` and the role's
        // default attestation are set only when a sign-off is requested.
        const { rerender } = render(SignoffModal, {
            props: {
                open: false,
                role: 'OPERATOR',
                entityType: 'run',
                entityId: 'run-1',
                defaultAttestation: '',
                signerName: 'Wesley',
                signatureImageUrl: '/sig.png',
                onConfirm: () => {},
                onCancel: () => {},
            },
        });
        await rerender({
            open: true,
            role: 'OPERATOR',
            entityType: 'run',
            entityId: 'run-1',
            defaultAttestation: 'I performed the operations as written.',
            signerName: 'Wesley',
            signatureImageUrl: '/sig.png',
            onConfirm: () => {},
            onCancel: () => {},
        });
        const ta = screen.getByLabelText(/attestation/i) as HTMLTextAreaElement;
        expect(ta.value).toBe('I performed the operations as written.');
    });
});
