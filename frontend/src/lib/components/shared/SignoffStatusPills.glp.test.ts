/**
 * Drift test: T3 sign-off status pills.
 *
 * Per the GLP rule validation tiers table, sign-off status pills render
 * on the Run header sourced from ``GlpSignoffRequest`` rows (a.k.a.
 * ``GlpSignoff`` rows in the current schema). The closest mountable
 * surface today is ``SignoffBlock.svelte`` which renders one row per
 * required role with either a "Signed" pill (when an active signoff
 * exists for the role) or a "Sign as ${role}" button (when missing).
 *
 * Asserting the visible pill text per role is exactly the drift signal
 * we want — the pill copy is what users see and what downstream golden
 * paths key off.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import SignoffBlock from './SignoffBlock.svelte';

const ROLES = ['OPERATOR', 'STUDY_DIRECTOR', 'QAU'] as const;

function signoff(role: (typeof ROLES)[number], signerId: string) {
    return {
        id: `sig-${role}`,
        protocol_id: null,
        run_id: 'run-1',
        role,
        action: 'APPROVED' as const,
        signer_id: signerId,
        attestation: 'I attest.',
        signed_at: '2026-05-18T10:00:00Z',
        signature_image_path: '/sig.png',
        signoff_request_id: null,
        invalidated_at: null,
        invalidated_reason: null,
        invalidated_by_id: null,
        created_at: '',
        updated_at: '',
    };
}

describe('GLP drift: SignoffBlock pills on Run header', () => {
    it('renders a Signed pill for each role with an active signoff', () => {
        render(SignoffBlock, {
            props: {
                entityType: 'run',
                entityId: 'run-1',
                requiredRoles: [...ROLES],
                signoffs: [
                    signoff('OPERATOR', 'u-op'),
                    signoff('STUDY_DIRECTOR', 'u-sd'),
                    signoff('QAU', 'u-qau'),
                ],
                signers: {
                    'u-op': { id: 'u-op', full_name: 'Oscar', email: 'op@x' },
                    'u-sd': { id: 'u-sd', full_name: 'Dana', email: 'sd@x' },
                    'u-qau': {
                        id: 'u-qau',
                        full_name: 'Quinn',
                        email: 'qau@x',
                    },
                },
                currentUserId: 'u-op',
                attestationDefaults: {
                    OPERATOR: '',
                    STUDY_DIRECTOR: '',
                    QAU: '',
                },
                onSignClick: () => {},
            },
        });
        const signedPills = screen.getAllByText(/^signed$/i);
        expect(signedPills.length).toBe(3);
    });

    it('renders a Sign-as button for roles missing an active signoff', () => {
        render(SignoffBlock, {
            props: {
                entityType: 'run',
                entityId: 'run-1',
                requiredRoles: [...ROLES],
                signoffs: [signoff('OPERATOR', 'u-op')],
                signers: {
                    'u-op': { id: 'u-op', full_name: 'Oscar', email: 'op@x' },
                },
                currentUserId: 'u-op',
                attestationDefaults: {
                    OPERATOR: '',
                    STUDY_DIRECTOR: 'I attest as SD.',
                    QAU: 'I audit.',
                },
                onSignClick: () => {},
            },
        });
        expect(screen.getAllByText(/^signed$/i).length).toBe(1);
        expect(
            screen.getByRole('button', { name: /sign as study_director/i }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole('button', { name: /sign as qau/i }),
        ).toBeInTheDocument();
    });

    it('ignores invalidated signoffs (still treated as missing)', () => {
        const invalidatedOperator = {
            ...signoff('OPERATOR', 'u-op'),
            invalidated_at: '2026-05-18T11:00:00Z',
        };
        render(SignoffBlock, {
            props: {
                entityType: 'run',
                entityId: 'run-1',
                requiredRoles: ['OPERATOR'] as const,
                signoffs: [invalidatedOperator],
                signers: {
                    'u-op': { id: 'u-op', full_name: 'Oscar', email: 'op@x' },
                },
                currentUserId: 'u-op',
                attestationDefaults: { OPERATOR: '' },
                onSignClick: () => {},
            },
        });
        expect(screen.queryAllByText(/^signed$/i).length).toBe(0);
        expect(
            screen.getByRole('button', { name: /sign as operator/i }),
        ).toBeInTheDocument();
    });
});
