import { describe, it, expect } from 'vitest';
import {
    ApprovalActionEnum,
    ApprovalActorRefSchema,
    ProtocolVersionRefSchema,
    ProtocolApprovalEventSchema,
    AwaitingApprovalItemSchema,
} from './protocolApproval';

describe('ApprovalActionEnum', () => {
    it('accepts the four action values', () => {
        expect(ApprovalActionEnum.parse('SUBMITTED')).toBe('SUBMITTED');
        expect(ApprovalActionEnum.parse('APPROVED')).toBe('APPROVED');
        expect(ApprovalActionEnum.parse('REJECTED')).toBe('REJECTED');
        expect(ApprovalActionEnum.parse('REVERTED')).toBe('REVERTED');
    });

    it('rejects unknown actions', () => {
        expect(() => ApprovalActionEnum.parse('PENDING')).toThrow();
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

describe('ProtocolVersionRefSchema', () => {
    it('parses a version ref', () => {
        const ref = ProtocolVersionRefSchema.parse({
            id: '660e8400-e29b-41d4-a716-446655440000',
            version_number: 3,
        });
        expect(ref.version_number).toBe(3);
    });
});

describe('ProtocolApprovalEventSchema', () => {
    it('parses a happy-path SUBMITTED event', () => {
        const event = ProtocolApprovalEventSchema.parse({
            id: '770e8400-e29b-41d4-a716-446655440000',
            action: 'SUBMITTED',
            comment: null,
            signature_statement: null,
            actor: {
                id: '550e8400-e29b-41d4-a716-446655440000',
                name: 'Jane Doe',
                email: 'jane@example.com',
            },
            protocol_version: {
                id: '660e8400-e29b-41d4-a716-446655440000',
                version_number: 1,
            },
            created_at: '2026-05-10T12:00:00Z',
        });
        expect(event.action).toBe('SUBMITTED');
        expect(event.actor?.email).toBe('jane@example.com');
        expect(event.protocol_version?.version_number).toBe(1);
    });

    it('parses an APPROVED event with a comment and signature statement', () => {
        const event = ProtocolApprovalEventSchema.parse({
            id: '770e8400-e29b-41d4-a716-446655440000',
            action: 'APPROVED',
            comment: 'Looks good',
            signature_statement: 'I have reviewed and approve this protocol.',
            actor: {
                id: '550e8400-e29b-41d4-a716-446655440000',
                name: 'Quality Lead',
                email: 'ql@example.com',
            },
            protocol_version: null,
            created_at: '2026-05-10T13:00:00Z',
        });
        expect(event.comment).toBe('Looks good');
        expect(event.protocol_version).toBeNull();
    });

    it('rejects an unknown action', () => {
        expect(() =>
            ProtocolApprovalEventSchema.parse({
                id: '770e8400-e29b-41d4-a716-446655440000',
                action: 'BOGUS',
                created_at: '2026-05-10T13:00:00Z',
            }),
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
