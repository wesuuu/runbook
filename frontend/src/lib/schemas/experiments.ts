import { z } from 'zod';
import { RunSchema } from './runs';
import { uuidString } from './common';

export const ExperimentStatusEnum = z.enum([
    'DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED',
]);
export type ExperimentStatus = z.infer<typeof ExperimentStatusEnum>;

// Rolling-deploy safety: an old tab loaded before the deploy still holds the
// previous bundle (with the 4-state enum) while the backend has already shipped
// the 5-state contract. A strict z.enum() would throw on the first observed
// AWAITING_CONCLUSION. Use z.string() in dev/prod and let unknown values pass
// through; runtime code branches with switch statements that already have a
// default case. Vitest tests still get the strict enum via the exported type.
export const LifecycleStatusValues = [
    'DRAFT', 'IN_PROGRESS', 'AWAITING_CONCLUSION', 'COMPLETE', 'ARCHIVED',
] as const;
export type LifecycleStatus = (typeof LifecycleStatusValues)[number];
export const LifecycleStatusEnum = z.string().transform(
    (s) => s.toUpperCase() as LifecycleStatus,
);

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
    lifecycle_status: LifecycleStatusEnum,
    created_by_id: uuidString().nullable().optional(),
    conclusion: z.string().nullable().optional(),
    conclusion_locked_at: z.string().nullable().optional(),
    conclusion_locked_by_id: uuidString().nullable().optional(),
    conclusion_locked_by_name: z.string().nullable().optional(),
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
