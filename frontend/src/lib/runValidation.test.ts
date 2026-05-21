import { describe, it, expect } from 'vitest';
import { resolveRequiredRoles, validateCanCloseRun } from './runValidation';
import { validateQauIndependent } from './signoffValidation';
import type { GlpSettings, GlpSignoffResponse } from '$lib/schemas/glpSignoff';
import type { Run } from '$lib/schemas/runs';

const minimalRun = { id: 'r1' } as unknown as Run;

function settings(overrides: Partial<GlpSettings> = {}): GlpSettings {
    return {
        require_study_director: false,
        require_qau: false,
        operator_attestation_text: '',
        study_director_attestation_text: '',
        qau_attestation_text: '',
        step_attestation_text: '',
        ...overrides,
    };
}

function signoff(
    role: GlpSignoffResponse['role'],
    signerId = 'u-default',
): GlpSignoffResponse {
    return {
        id: `sig-${role}-${signerId}`,
        protocol_id: null,
        run_id: 'r1',
        role,
        action: 'APPROVED',
        signer_id: signerId,
        signed_at: '2026-05-18T12:00:00Z',
        created_at: '2026-05-18T12:00:00Z',
        updated_at: '2026-05-18T12:00:00Z',
    } as unknown as GlpSignoffResponse;
}

describe('resolveRequiredRoles', () => {
    it('returns no roles for a basic run (no reviewer role enabled)', () => {
        expect(resolveRequiredRoles(settings())).toEqual([]);
    });

    it('requires OPERATOR + STUDY_DIRECTOR when SD is enabled', () => {
        expect(
            resolveRequiredRoles(settings({ require_study_director: true })),
        ).toEqual(['OPERATOR', 'STUDY_DIRECTOR']);
    });

    it('requires OPERATOR + QAU when QAU is enabled', () => {
        expect(resolveRequiredRoles(settings({ require_qau: true }))).toEqual([
            'OPERATOR',
            'QAU',
        ]);
    });

    it('requires all three when both reviewer roles are enabled', () => {
        expect(
            resolveRequiredRoles(
                settings({ require_study_director: true, require_qau: true }),
            ),
        ).toEqual(['OPERATOR', 'STUDY_DIRECTOR', 'QAU']);
    });
});

describe('validateCanCloseRun', () => {
    it('passes a basic run with no signoffs (no reviewer role required) (#18)', () => {
        const result = validateCanCloseRun(minimalRun, settings(), []);
        expect(result.ok).toBe(true);
        expect(result.missing).toEqual([]);
    });

    it('requires OPERATOR on a GLP run', () => {
        const result = validateCanCloseRun(
            minimalRun,
            settings({ require_study_director: true }),
            [],
        );
        expect(result.ok).toBe(false);
        expect(result.missing).toEqual(['OPERATOR', 'STUDY_DIRECTOR']);
    });

    it('flags missing QAU when required', () => {
        const result = validateCanCloseRun(
            minimalRun,
            settings({ require_qau: true }),
            [signoff('OPERATOR')],
        );
        expect(result.ok).toBe(false);
        expect(result.missing).toEqual(['QAU']);
    });

    it('flags missing STUDY_DIRECTOR when required', () => {
        const result = validateCanCloseRun(
            minimalRun,
            settings({ require_study_director: true }),
            [signoff('OPERATOR')],
        );
        expect(result.ok).toBe(false);
        expect(result.missing).toEqual(['STUDY_DIRECTOR']);
    });

    it('passes when all required roles have signed', () => {
        const result = validateCanCloseRun(
            minimalRun,
            settings({ require_qau: true, require_study_director: true }),
            [
                signoff('OPERATOR', 'u-op'),
                signoff('STUDY_DIRECTOR', 'u-sd'),
                signoff('QAU', 'u-qau'),
            ],
        );
        expect(result.ok).toBe(true);
        expect(result.missing).toEqual([]);
    });
});

describe('validateQauIndependent', () => {
    it('flags when proposed QAU signer is the OPERATOR signer', () => {
        const result = validateQauIndependent([], 'u-shared', 'u-shared');
        expect(result.ok).toBe(false);
        expect(result.conflictRole).toBe('OPERATOR');
    });

    it('flags when proposed QAU signer is the active STUDY_DIRECTOR signer', () => {
        const result = validateQauIndependent(
            [signoff('STUDY_DIRECTOR', 'u-sd')],
            'u-sd',
            'u-op',
        );
        expect(result.ok).toBe(false);
        expect(result.conflictRole).toBe('STUDY_DIRECTOR');
    });

    it('passes when proposed QAU signer is independent', () => {
        const result = validateQauIndependent(
            [signoff('STUDY_DIRECTOR', 'u-sd')],
            'u-qau',
            'u-op',
        );
        expect(result.ok).toBe(true);
        expect(result.conflictRole).toBeUndefined();
    });

    it('passes when there is no operator and no SD signoff', () => {
        const result = validateQauIndependent([], 'u-qau', null);
        expect(result.ok).toBe(true);
    });
});
