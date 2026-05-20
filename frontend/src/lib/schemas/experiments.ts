import { z } from 'zod';
import { RunSchema } from './runs';

export const ExperimentStatusEnum = z.enum([
    'DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED',
]);
export type ExperimentStatus = z.infer<typeof ExperimentStatusEnum>;

export const ExperimentNoteSchema = z.object({
    id: z.string().uuid(),
    content: z.string(),
    author_id: z.string().uuid(),
    author_name: z.string().default('Unknown'),
    created_at: z.string(),
    flags: z.array(z.string()).default([]),
}).passthrough();

export type ExperimentNote = z.infer<typeof ExperimentNoteSchema>;

export const ExperimentNoteListSchema = z.object({
    items: z.array(ExperimentNoteSchema).default([]),
}).passthrough();

export const ExperimentSchema = z.object({
    id: z.string().uuid(),
    project_id: z.string().uuid(),
    project_slug: z.string(),
    slug: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    content: z.record(z.string(), z.unknown()).default({}),
    status: ExperimentStatusEnum.default('DRAFT'),
    notes: z.array(ExperimentNoteSchema).default([]),
    runs: z.array(RunSchema).default([]),
    run_count: z.number().default(0),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Experiment = z.infer<typeof ExperimentSchema>;

export const ExperimentListSchema = z.array(ExperimentSchema);
export type ExperimentList = z.infer<typeof ExperimentListSchema>;
