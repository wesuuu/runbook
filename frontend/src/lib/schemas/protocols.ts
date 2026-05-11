import { z } from 'zod';

export const ProtocolRoleSchema = z.object({
    id: z.string(),
    protocol_id: z.string(),
    name: z.string(),
    color: z.string().default('#94a3b8'),
    sort_order: z.number().default(0),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type ProtocolRole = z.infer<typeof ProtocolRoleSchema>;

export const ProtocolSchema = z.object({
    id: z.string(),
    project_id: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    status: z.string().default('DRAFT'),
    version_number: z.number().default(0),
    graph: z.record(z.string(), z.unknown()).default({}),
    roles: z.array(ProtocolRoleSchema).default([]),
    is_tour_sample: z.boolean().default(false),
    requires_approval: z.boolean().default(false),
    created_by_id: z.string().nullable().optional(),
    approved_by_id: z.string().nullable().optional(),
    approved_at: z.string().nullable().optional(),
    latest_signature_statement: z.string().nullable().optional(),
    latest_approval_comment: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Protocol = z.infer<typeof ProtocolSchema>;

export const ProtocolListSchema = z.array(ProtocolSchema);
export type ProtocolList = z.infer<typeof ProtocolListSchema>;

export const ProtocolVersionSchema = z.object({
    id: z.string(),
    protocol_id: z.string(),
    version_number: z.number(),
    name: z.string(),
    description: z.string().nullable().optional(),
    graph: z.record(z.string(), z.unknown()).default({}),
    change_summary: z.string().nullable().optional(),
    created_by_id: z.string().nullable().optional(),
    created_by_name: z.string().nullable().optional(),
    created_at: z.string(),
    is_draft: z.boolean().default(false),
}).passthrough();

export type ProtocolVersion = z.infer<typeof ProtocolVersionSchema>;
