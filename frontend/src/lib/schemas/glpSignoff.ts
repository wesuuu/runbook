import { z } from 'zod';

export const GlpRoleSchema = z.enum([
    'SPONSOR',
    'STUDY_DIRECTOR',
    'QAU',
    'OPERATOR',
]);
export type GlpRole = z.infer<typeof GlpRoleSchema>;

export const GlpSignoffActionSchema = z.enum([
    'APPROVED',
    'REJECTED',
    'REQUESTED_CHANGES',
]);
export type GlpSignoffAction = z.infer<typeof GlpSignoffActionSchema>;

export const ApprovalActorRefSchema = z
    .object({
        id: z.string(),
        name: z.string().nullable(),
        email: z.string(),
    })
    .passthrough();
export type ApprovalActorRef = z.infer<typeof ApprovalActorRefSchema>;

export const GlpSignoffResponseSchema = z
    .object({
        id: z.string(),
        protocol_id: z.string().nullable().optional(),
        run_id: z.string().nullable().optional(),
        role: GlpRoleSchema,
        action: GlpSignoffActionSchema,
        signer_id: z.string(),
        signer: ApprovalActorRefSchema.nullable().optional(),
        attestation: z.string().nullable().optional(),
        signed_at: z.string(),
        signature_image_path: z.string().nullable().optional(),
        signoff_request_id: z.string().nullable().optional(),
        invalidated_at: z.string().nullable().optional(),
        invalidated_reason: z.string().nullable().optional(),
        invalidated_by_id: z.string().nullable().optional(),
        created_at: z.string(),
        updated_at: z.string(),
    })
    .passthrough();
export type GlpSignoffResponse = z.infer<typeof GlpSignoffResponseSchema>;

export const GlpSignoffResponseListSchema = z.array(GlpSignoffResponseSchema);
export type GlpSignoffResponseList = z.infer<typeof GlpSignoffResponseListSchema>;

export const GlpSignoffCreateSchema = z.object({
    role: GlpRoleSchema,
    action: GlpSignoffActionSchema,
    attestation: z.string().optional(),
    signature_image_path: z.string().optional(),
    signoff_request_id: z.string().optional(),
});
export type GlpSignoffCreate = z.infer<typeof GlpSignoffCreateSchema>;

export const GlpSettingsSchema = z.object({
    require_study_director: z.boolean().default(false),
    require_qau: z.boolean().default(true),
    operator_attestation_text: z.string().default(''),
    study_director_attestation_text: z.string().default(''),
    qau_attestation_text: z.string().default(''),
    step_attestation_text: z.string().default(''),
});
export type GlpSettings = z.infer<typeof GlpSettingsSchema>;

// Awaiting-approval list (used by /protocols/awaiting-my-approval).
export const AwaitingApprovalItemSchema = z
    .object({
        protocol_id: z.string(),
        name: z.string(),
        project_id: z.string().nullable().optional(),
        project_name: z.string().nullable().optional(),
        // Backend currently types this as non-null UUID, but org-scoped
        // protocols can have null project_id and the org_id derivation
        // may also be null. Accept null for forward compatibility.
        organization_id: z.string().nullable().optional(),
        submitted_at: z.string().nullable().optional(),
        submitted_by: ApprovalActorRefSchema.nullable().optional(),
    })
    .passthrough();
export type AwaitingApprovalItem = z.infer<typeof AwaitingApprovalItemSchema>;

export const AwaitingApprovalListSchema = z.array(AwaitingApprovalItemSchema);
export type AwaitingApprovalList = z.infer<typeof AwaitingApprovalListSchema>;

// Request body schemas (used by the API client).
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
