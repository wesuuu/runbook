import { z } from 'zod';
import { RunSchema } from './runs';
import { uuidString } from './common';

export const ExperimentStatusEnum = z.enum([
    'DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED',
]);
export type ExperimentStatus = z.infer<typeof ExperimentStatusEnum>;

export const LifecycleStatusEnum = z.enum([
    'DRAFT', 'IN_PROGRESS', 'COMPLETE', 'ARCHIVED',
]);
export type LifecycleStatus = z.infer<typeof LifecycleStatusEnum>;

export const ExperimentNoteSchema = z.object({
    id: uuidString(),
    content: z.string(),
    author_id: uuidString(),
    author_name: z.string().default('Unknown'),
    created_at: z.string(),
    flags: z.array(z.string()).default([]),
}).passthrough();

export type ExperimentNote = z.infer<typeof ExperimentNoteSchema>;

export const ExperimentNoteListSchema = z.object({
    items: z.array(ExperimentNoteSchema).default([]),
}).passthrough();

export const ExperimentSchema = z.object({
    id: uuidString(),
    project_id: uuidString(),
    project_slug: z.string(),
    project_name: z.string().optional(),
    slug: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    objective: z.string().nullable().optional(),
    success_criteria: z.array(z.string()).default([]),
    content: z.record(z.string(), z.unknown()).default({}),
    status: ExperimentStatusEnum.default('DRAFT'),
    lifecycle_status: LifecycleStatusEnum.optional(),
    notes: z.array(ExperimentNoteSchema).default([]),
    runs: z.array(RunSchema).default([]),
    run_count: z.number().default(0),
    run_summaries: z.array(z.unknown()).default([]),
    owner: z.unknown().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Experiment = z.infer<typeof ExperimentSchema>;

export const ExperimentListSchema = z.array(ExperimentSchema);
export type ExperimentList = z.infer<typeof ExperimentListSchema>;
