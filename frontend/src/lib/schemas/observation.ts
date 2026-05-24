import { z } from 'zod';
import { uuidString } from './common';

export const ObservationFlagEnum = z.enum(['observation', 'anomaly']);
export type ObservationFlag = z.infer<typeof ObservationFlagEnum>;

export const ObservationItemSchema = z.object({
    id: z.string(),
    source: z.enum(['experiment', 'run']),
    source_id: uuidString(),
    run_label: z.string().nullable().optional(),
    run_slug: z.string().nullable().optional(),
    run_project_slug: z.string().nullable().optional(),
    flag: ObservationFlagEnum,
    body: z.string(),
    author_name: z.string(),
    created_at: z.string(),
}).passthrough();

export type ObservationItem = z.infer<typeof ObservationItemSchema>;

export const ObservationsResponseSchema = z.object({
    items: z.array(ObservationItemSchema).default([]),
    truncated: z.boolean().default(false),
}).passthrough();

export type ObservationsResponse = z.infer<typeof ObservationsResponseSchema>;
