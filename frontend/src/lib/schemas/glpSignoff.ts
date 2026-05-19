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
        signature_image_url: z.string().nullable().optional(),
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

// 21 CFR Part 58 default attestation language. Sites may override per
// protocol, but the defaults are GLP-appropriate so a new protocol is
// compliant out of the box.
export const DEFAULT_OPERATOR_ATTESTATION =
    'I performed the operations described above in accordance with the ' +
    'approved Standard Operating Procedure and recorded the results ' +
    'contemporaneously, accurately, and completely (21 CFR §58.130).';

export const DEFAULT_STUDY_DIRECTOR_ATTESTATION =
    'As Study Director, I have reviewed this protocol and attest that ' +
    'the study has been conducted in accordance with 21 CFR Part 58 and ' +
    'that the reported results accurately reflect the raw data ' +
    '(21 CFR §58.33).';

export const DEFAULT_QAU_ATTESTATION =
    'As Quality Assurance, I have inspected this study, reviewed the ' +
    'final report, and confirm that it accurately describes the methods ' +
    'and standard operating procedures and reflects the raw data of the ' +
    'study (21 CFR §58.35).';

export const DEFAULT_STEP_ATTESTATION =
    'I performed this step as written and the recorded values are true ' +
    'and complete.';

export const QauModeSchema = z.enum(['ANY_ORG_QAU', 'SPECIFIC_USER']);
export type QauMode = z.infer<typeof QauModeSchema>;

export const GlpSettingsSchema = z.object({
    require_study_director: z.boolean().default(false),
    require_qau: z.boolean().default(false),
    // Designated approvers. Set when the matching require_* toggle is on.
    // study_director_user_id: must be a specific user (no "any of role" mode
    // because §58.33 SD is a single named individual).
    // qau_mode: ANY_ORG_QAU lets any org member with the QAU role sign;
    // SPECIFIC_USER pins it to qau_user_id. Defaults preserve legacy
    // protocols where no approver was designated.
    study_director_user_id: z.string().nullable().default(null),
    qau_mode: QauModeSchema.default('ANY_ORG_QAU'),
    qau_user_id: z.string().nullable().default(null),
    operator_attestation_text: z
        .string()
        .default(DEFAULT_OPERATOR_ATTESTATION),
    study_director_attestation_text: z
        .string()
        .default(DEFAULT_STUDY_DIRECTOR_ATTESTATION),
    qau_attestation_text: z.string().default(DEFAULT_QAU_ATTESTATION),
    step_attestation_text: z.string().default(DEFAULT_STEP_ATTESTATION),
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
