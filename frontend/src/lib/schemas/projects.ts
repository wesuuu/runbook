import { z } from 'zod';

export const ProjectSchema = z.object({
    id: z.string(),
    slug: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    organization_id: z.string(),
    owner_type: z.string().nullable().optional(),
    owner_id: z.string().nullable().optional(),
    settings: z.record(z.string(), z.unknown()).default({}),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Project = z.infer<typeof ProjectSchema>;

export const ProjectListSchema = z.array(ProjectSchema);
export type ProjectList = z.infer<typeof ProjectListSchema>;
