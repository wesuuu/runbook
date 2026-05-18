import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import SignoffBlock from './SignoffBlock.svelte';

describe('SignoffBlock', () => {
    it('renders all required roles, signed and pending', async () => {
        render(SignoffBlock, {
            props: {
                entityType: 'run',
                entityId: 'r1',
                requiredRoles: ['OPERATOR', 'QAU'],
                signoffs: [
                    {
                        id: 's1',
                        run_id: 'r1',
                        protocol_id: null,
                        role: 'OPERATOR',
                        action: 'APPROVED',
                        signer_id: 'u1',
                        attestation: 'x',
                        signed_at: '2026-05-18T10:00:00Z',
                        signature_image_path: 'p.png',
                        signoff_request_id: null,
                        invalidated_at: null,
                        invalidated_reason: null,
                        invalidated_by_id: null,
                        created_at: '',
                        updated_at: '',
                    } as any,
                ],
                signers: {
                    u1: { id: 'u1', full_name: 'Wesley', email: 'w@x' },
                },
                currentUserId: 'u2',
                attestationDefaults: { OPERATOR: '', QAU: 'I attest.' },
                onSignClick: () => {},
            },
        });
        expect(screen.getByText('OPERATOR')).toBeInTheDocument();
        expect(screen.getByText('QAU')).toBeInTheDocument();
        // OPERATOR row shows signer name; QAU row shows "Sign as QAU"
        expect(screen.getByText('Wesley')).toBeInTheDocument();
        expect(
            screen.getByRole('button', { name: /sign as QAU/i }),
        ).toBeInTheDocument();
    });
});
