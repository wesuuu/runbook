import { z } from 'zod';

export const RunImageSchema = z.object({
    id: z.string().uuid(),
    run_id: z.string().uuid(),
    node_id: z.string().nullable().optional(),
    original_filename: z.string(),
    file_path: z.string(),
    tags: z.record(z.string(), z.unknown()).default({}),
    ai_values: z.record(z.string(), z.unknown()).nullable().optional(),
    manual_values: z.record(z.string(), z.unknown()).nullable().optional(),
    status: z.string().default('pending'),
    created_at: z.string(),
}).passthrough();

export type RunImage = z.infer<typeof RunImageSchema>;

export const PendingImagesSchema = z.object({
    items: z.array(RunImageSchema).default([]),
}).passthrough();

export type PendingImages = z.infer<typeof PendingImagesSchema>;

export const AnalyzePendingResultSchema = z.object({
    total: z.number(),
    succeeded: z.number(),
    failed: z.number(),
}).passthrough();

export type AnalyzePendingResult = z.infer<typeof AnalyzePendingResultSchema>;

// --- AI Settings ---

export const AiProviderConfigSchema = z.object({
    id: z.string().uuid(),
    capability: z.string(),
    provider: z.string(),
    model_name: z.string(),
    credentials_set: z.boolean(),
    is_enabled: z.boolean(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type AiProviderConfig = z.infer<typeof AiProviderConfigSchema>;

export const AiSettingsListSchema = z.object({
    items: z.array(AiProviderConfigSchema),
    subscription_tier: z.string(),
}).passthrough();

export type AiSettingsList = z.infer<typeof AiSettingsListSchema>;

export const AiTestConnectionSchema = z.object({
    success: z.boolean(),
    message: z.string(),
}).passthrough();

export type AiTestConnection = z.infer<typeof AiTestConnectionSchema>;
