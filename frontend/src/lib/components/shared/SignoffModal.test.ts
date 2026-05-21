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

    it('disables confirm when no signature is on file', async () => {
        render(SignoffModal, {
            props: {
                open: true,
                role: 'OPERATOR',
                entityType: 'run',
                entityId: 'run-1',
                defaultAttestation: 'I attest as OPERATOR.',
                signerName: 'Wesley',
                signatureImageUrl: null,
                onConfirm: () => {},
                onCancel: () => {},
            },
        });
        // Attestation is filled, but a saved signature is required for an
        // APPROVED sign-off — confirm must stay disabled (issue #35).
        const btn = screen.getByRole('button', { name: /confirm sign-off/i });
        expect(btn).toBeDisabled();
    });

    it('enables confirm when both attestation and signature are present', async () => {
        render(SignoffModal, {
            props: {
                open: true,
                role: 'OPERATOR',
                entityType: 'run',
                entityId: 'run-1',
                defaultAttestation: 'I attest as OPERATOR.',
                signerName: 'Wesley',
                signatureImageUrl: '/sig.png',
                onConfirm: () => {},
                onCancel: () => {},
            },
        });
        const btn = screen.getByRole('button', { name: /confirm sign-off/i });
        expect(btn).not.toBeDisabled();
    });
});
