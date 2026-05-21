import { describe, it, expect } from 'vitest';
import {
    GlpRoleSchema,
    GlpSignoffActionSchema,
    ApprovalActorRefSchema,
    GlpSignoffResponseSchema,
    GlpSignoffCreateSchema,
    GlpSettingsSchema,
    AwaitingApprovalItemSchema,
    DEFAULT_OPERATOR_ATTESTATION,
    DEFAULT_STUDY_DIRECTOR_ATTESTATION,
    DEFAULT_QAU_ATTESTATION,
    DEFAULT_STEP_ATTESTATION,
} from './glpSignoff';

describe('GlpRoleSchema', () => {
    it('accepts the four role values', () => {
        expect(GlpRoleSchema.parse('SPONSOR')).toBe('SPONSOR');
        expect(GlpRoleSchema.parse('STUDY_DIRECTOR')).toBe('STUDY_DIRECTOR');
        expect(GlpRoleSchema.parse('QAU')).toBe('QAU');
        expect(GlpRoleSchema.parse('OPERATOR')).toBe('OPERATOR');
    });

    it('rejects unknown roles', () => {
        expect(() => GlpRoleSchema.parse('CREATOR')).toThrow();
    });
});

describe('GlpSignoffActionSchema', () => {
    it('accepts the three action values', () => {
        expect(GlpSignoffActionSchema.parse('APPROVED')).toBe('APPROVED');
        expect(GlpSignoffActionSchema.parse('REJECTED')).toBe('REJECTED');
        expect(GlpSignoffActionSchema.parse('REQUESTED_CHANGES')).toBe('REQUESTED_CHANGES');
    });

    it('rejects unknown actions', () => {
        expect(() => GlpSignoffActionSchema.parse('SUBMITTED')).toThrow();
        expect(() => GlpSignoffActionSchema.parse('REVERTED')).toThrow();
    });
});

describe('ApprovalActorRefSchema', () => {
    it('parses a complete actor', () => {
        const actor = ApprovalActorRefSchema.parse({
            id: '550e8400-e29b-41d4-a716-446655440000',
            name: 'Jane Doe',
            email: 'jane@example.com',
        });
        expect(actor.name).toBe('Jane Doe');
        expect(actor.email).toBe('jane@example.com');
    });

    it('accepts a null name (full_name may be null on the user)', () => {
        const actor = ApprovalActorRefSchema.parse({
            id: '550e8400-e29b-41d4-a716-446655440000',
            name: null,
            email: 'jane@example.com',
        });
        expect(actor.name).toBeNull();
    });
});

describe('GlpSignoffResponseSchema', () => {
    it('parses a happy-path APPROVED signoff', () => {
        const sig = GlpSignoffResponseSchema.parse({
            id: '770e8400-e29b-41d4-a716-446655440000',
            protocol_id: '660e8400-e29b-41d4-a716-446655440000',
            run_id: null,
            role: 'STUDY_DIRECTOR',
            action: 'APPROVED',
            signer_id: '550e8400-e29b-41d4-a716-446655440000',
            signer: {
                id: '550e8400-e29b-41d4-a716-446655440000',
                name: 'Quality Lead',
                email: 'ql@example.com',
            },
            attestation: 'I have reviewed and approve this protocol.',
            signed_at: '2026-05-10T13:00:00Z',
            signature_image_path: 'system/sigs/x.png',
            signoff_request_id: null,
            invalidated_at: null,
            invalidated_reason: null,
            invalidated_by_id: null,
            created_at: '2026-05-10T13:00:00Z',
            updated_at: '2026-05-10T13:00:00Z',
        });
        expect(sig.action).toBe('APPROVED');
        expect(sig.role).toBe('STUDY_DIRECTOR');
        expect(sig.signer?.email).toBe('ql@example.com');
    });

    it('rejects an unknown action', () => {
        expect(() =>
            GlpSignoffResponseSchema.parse({
                id: '770e8400-e29b-41d4-a716-446655440000',
                role: 'QAU',
                action: 'BOGUS',
                signer_id: '550e8400-e29b-41d4-a716-446655440000',
                signed_at: '2026-05-10T13:00:00Z',
                created_at: '2026-05-10T13:00:00Z',
                updated_at: '2026-05-10T13:00:00Z',
            }),
        ).toThrow();
    });
});

describe('GlpSignoffCreateSchema', () => {
    it('parses a minimal create payload', () => {
        const payload = GlpSignoffCreateSchema.parse({
            role: 'OPERATOR',
            action: 'APPROVED',
        });
        expect(payload.role).toBe('OPERATOR');
        expect(payload.action).toBe('APPROVED');
    });

    it('parses a full create payload with optional fields', () => {
        const payload = GlpSignoffCreateSchema.parse({
            role: 'QAU',
            action: 'APPROVED',
            attestation: 'I have reviewed this.',
            signature_image_path: 'system/sigs/x.png',
            signoff_request_id: '770e8400-e29b-41d4-a716-446655440000',
        });
        expect(payload.attestation).toBe('I have reviewed this.');
        expect(payload.signoff_request_id).toBe(
            '770e8400-e29b-41d4-a716-446655440000',
        );
    });

    it('rejects an unknown role on create', () => {
        expect(() =>
            GlpSignoffCreateSchema.parse({
                role: 'CREATOR',
                action: 'APPROVED',
            }),
        ).toThrow();
    });
});

describe('GlpSettingsSchema', () => {
    it('applies defaults when fields are omitted', () => {
        const settings = GlpSettingsSchema.parse({});
        expect(settings.require_study_director).toBe(false);
        expect(settings.require_qau).toBe(false);
        expect(settings.operator_attestation_text).toBe(
            DEFAULT_OPERATOR_ATTESTATION,
        );
        expect(settings.study_director_attestation_text).toBe(
            DEFAULT_STUDY_DIRECTOR_ATTESTATION,
        );
        expect(settings.qau_attestation_text).toBe(DEFAULT_QAU_ATTESTATION);
        expect(settings.step_attestation_text).toBe(DEFAULT_STEP_ATTESTATION);
    });

    it('parses a fully specified settings payload', () => {
        const settings = GlpSettingsSchema.parse({
            require_study_director: true,
            require_qau: false,
            operator_attestation_text: 'Operator attestation.',
            study_director_attestation_text: 'SD attestation.',
            qau_attestation_text: 'QAU attestation.',
            step_attestation_text: 'Step attestation.',
        });
        expect(settings.require_study_director).toBe(true);
        expect(settings.require_qau).toBe(false);
        expect(settings.operator_attestation_text).toBe('Operator attestation.');
    });

    it('rejects non-boolean require_qau', () => {
        expect(() =>
            GlpSettingsSchema.parse({ require_qau: 'yes' }),
        ).toThrow();
    });
});

describe('AwaitingApprovalItemSchema', () => {
    it('parses a project-scoped item', () => {
        const item = AwaitingApprovalItemSchema.parse({
            protocol_id: '880e8400-e29b-41d4-a716-446655440000',
            name: 'Buffer Prep v2',
            project_id: '990e8400-e29b-41d4-a716-446655440000',
            project_name: 'Project Alpha',
            organization_id: 'aa0e8400-e29b-41d4-a716-446655440000',
            submitted_at: '2026-05-09T08:00:00Z',
            submitted_by: {
                id: '550e8400-e29b-41d4-a716-446655440000',
                name: 'Jane Doe',
                email: 'jane@example.com',
            },
        });
        expect(item.name).toBe('Buffer Prep v2');
        expect(item.project_name).toBe('Project Alpha');
    });

    it('parses an item with null organization_id (forward-compat)', () => {
        const item = AwaitingApprovalItemSchema.parse({
            protocol_id: '880e8400-e29b-41d4-a716-446655440000',
            name: 'Org Protocol',
            project_id: null,
            project_name: null,
            organization_id: null,
            submitted_at: null,
            submitted_by: null,
        });
        expect(item.organization_id).toBeNull();
        expect(item.project_id).toBeNull();
        expect(item.submitted_by).toBeNull();
    });
});
