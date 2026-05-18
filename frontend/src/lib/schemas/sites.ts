import { z } from 'zod';

export const SiteSchema = z.object({
    id: z.string(),
    organization_id: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    archived_at: z.string().nullable().optional(),
    archived_by_id: z.string().nullable().optional(),
    archive_reason: z.string().nullable().optional(),
    created_by_id: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();
export type Site = z.infer<typeof SiteSchema>;

export const SiteListSchema = z.array(SiteSchema);

export const SiteCreateSchema = z.object({
    name: z.string().min(1).max(120),
    description: z.string().max(500).optional(),
});
export type SiteCreate = z.infer<typeof SiteCreateSchema>;

export const SiteUpdateSchema = SiteCreateSchema.partial();
export type SiteUpdate = z.infer<typeof SiteUpdateSchema>;

export const SiteArchiveRequestSchema = z.object({
    default_move_to: z.string(),
    overrides: z.record(z.string(), z.string()).default({}),
    reason: z.string().min(1).max(1000),
});
export type SiteArchiveRequest = z.infer<typeof SiteArchiveRequestSchema>;
