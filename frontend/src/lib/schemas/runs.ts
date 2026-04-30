import { z } from 'zod';

export const RunStatusEnum = z.enum(['PLANNED', 'ACTIVE', 'COMPLETED', 'EDITED', 'ARCHIVED']);
export type RunStatus = z.infer<typeof RunStatusEnum>;

export const RunNoteSchema = z.object({
    id: z.string().uuid(),
    content: z.string(),
    author_id: z.string().uuid(),
    author_name: z.string().default('Unknown'),
    created_at: z.string(),
    run_status: z.string(),
    flags: z.array(z.string()).default([]),
}).passthrough();

export type RunNote = z.infer<typeof RunNoteSchema>;

export const RunNoteListSchema = z.object({
    items: z.array(RunNoteSchema).default([]),
}).passthrough();

export const RunAttachmentSchema = z.object({
    id: z.string().uuid(),
    file_path: z.string(),
    filename: z.string(),
    content_type: z.string(),
    size_bytes: z.number(),
    uploaded_by_id: z.string().uuid(),
    uploaded_at: z.string(),
    step_id: z.string().nullable().optional(),
    run_status: z.string(),
    deleted: z.boolean().default(false),
}).passthrough();

export type RunAttachment = z.infer<typeof RunAttachmentSchema>;

export const RunAttachmentListSchema = z.object({
    items: z.array(RunAttachmentSchema).default([]),
}).passthrough();

export const RunSchema = z.object({
    id: z.string().uuid(),
    project_id: z.string().uuid(),
    protocol_id: z.string().uuid().nullable().optional(),
    name: z.string(),
    status: RunStatusEnum.default('PLANNED'),
    graph: z.record(z.string(), z.unknown()).default({}),
    execution_data: z.record(z.string(), z.unknown()).default({}),
    experiment_id: z.string().uuid().nullable().optional(),
    started_by_id: z.string().uuid().nullable().optional(),
    notes: z.array(RunNoteSchema).default([]),
    attachments: z.array(RunAttachmentSchema).default([]),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Run = z.infer<typeof RunSchema>;

export const RunListSchema = z.array(RunSchema);
export type RunList = z.infer<typeof RunListSchema>;

export const RunRoleAssignmentSchema = z.object({
    id: z.string(),
    run_id: z.string(),
    lane_node_id: z.string(),
    role_name: z.string(),
    user_id: z.string(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type RunRoleAssignment = z.infer<typeof RunRoleAssignmentSchema>;

export const RunRoleAssignmentListSchema = z.object({
    items: z.array(RunRoleAssignmentSchema).default([]),
}).passthrough();

export type RunRoleAssignmentList = z.infer<typeof RunRoleAssignmentListSchema>;

export const NodeOverridesSchema = z.object({
    params: z.record(z.string(), z.unknown()).optional(),
    equipment: z.array(z.object({
        equipment_id: z.string(),
        shareable: z.boolean(),
    })).optional(),
    paramSchema: z.record(z.string(), z.unknown()).optional(),
    description: z.string().optional(),
});

export type NodeOverrides = z.infer<typeof NodeOverridesSchema>;

export const RunOverridesSchema = z.object({
    nodes: z.record(z.string(), NodeOverridesSchema),
});

export type RunOverrides = z.infer<typeof RunOverridesSchema>;

export const RunCreatePayloadSchema = z.object({
    name: z.string().min(1),
    project_id: z.string().uuid(),
    protocol_id: z.string().uuid(),
    protocol_version_number: z.number().int().positive().optional(),
    experiment_id: z.string().uuid().optional(),
    overrides: RunOverridesSchema.optional(),
});

export type RunCreatePayload = z.infer<typeof RunCreatePayloadSchema>;
