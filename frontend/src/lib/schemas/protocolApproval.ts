import { z } from 'zod';

export const ApprovalActionEnum = z.enum([
    'SUBMITTED',
    'APPROVED',
    'REJECTED',
    'REVERTED',
]);
export type ApprovalAction = z.infer<typeof ApprovalActionEnum>;

export const ApprovalActorRefSchema = z
    .object({
        id: z.string(),
        name: z.string().nullable(),
        email: z.string(),
    })
    .passthrough();
export type ApprovalActorRef = z.infer<typeof ApprovalActorRefSchema>;

export const ProtocolVersionRefSchema = z
    .object({
        id: z.string(),
        version_number: z.number().int(),
    })
    .passthrough();
export type ProtocolVersionRef = z.infer<typeof ProtocolVersionRefSchema>;

export const ProtocolApprovalEventSchema = z
    .object({
        id: z.string(),
        action: ApprovalActionEnum,
        comment: z.string().nullable().optional(),
        signature_statement: z.string().nullable().optional(),
        actor: ApprovalActorRefSchema.nullable().optional(),
        protocol_version: ProtocolVersionRefSchema.nullable().optional(),
        created_at: z.string(),
    })
    .passthrough();
export type ProtocolApprovalEvent = z.infer<typeof ProtocolApprovalEventSchema>;

export const ProtocolApprovalEventListSchema = z.array(ProtocolApprovalEventSchema);
export type ProtocolApprovalEventList = z.infer<typeof ProtocolApprovalEventListSchema>;

export const AwaitingApprovalItemSchema = z
    .object({
        protocol_id: z.string(),
        name: z.string(),
        project_id: z.string().nullable().optional(),
        project_name: z.string().nullable().optional(),
        // Backend currently types this as non-null UUID, but the Phase 3
        // review noted a latent mismatch (org-scoped protocols can have
        // null project_id and the org_id derivation may also be null).
        // Accept null for forward compatibility.
        organization_id: z.string().nullable().optional(),
        submitted_at: z.string().nullable().optional(),
        submitted_by: ApprovalActorRefSchema.nullable().optional(),
    })
    .passthrough();
export type AwaitingApprovalItem = z.infer<typeof AwaitingApprovalItemSchema>;

export const AwaitingApprovalListSchema = z.array(AwaitingApprovalItemSchema);
export type AwaitingApprovalList = z.infer<typeof AwaitingApprovalListSchema>;

// Request body schemas (used by the API client)
export const DesignateApprovalRequestSchema = z.object({
    requires_approval: z.boolean(),
});
export type DesignateApprovalRequest = z.infer<typeof DesignateApprovalRequestSchema>;

export const SubmitForApprovalRequestSchema = z.object({
    requested_user_ids: z.array(z.string()),
});
export type SubmitForApprovalRequest = z.infer<typeof SubmitForApprovalRequestSchema>;

export const ApproveProtocolRequestSchema = z.object({
    comment: z.string().optional(),
    signature_statement: z.string().optional(),
});
export type ApproveProtocolRequest = z.infer<typeof ApproveProtocolRequestSchema>;

export const RejectProtocolRequestSchema = z.object({
    comment: z.string().min(1),
    signature_statement: z.string().optional(),
});
export type RejectProtocolRequest = z.infer<typeof RejectProtocolRequestSchema>;
