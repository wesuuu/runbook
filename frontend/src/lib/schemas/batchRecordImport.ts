import { z } from 'zod';

// ── Extraction response schemas ─────────────────────────────────────

export const ExtractedParameterValueSchema = z.object({
    field_label: z.string(),
    value: z.union([z.string(), z.number()]),
    unit: z.string().nullable(),
    confidence: z.number(),
    source_page: z.number().nullable(),
}).passthrough();

export const ExtractedTimestampSchema = z.object({
    value: z.string(),
    label: z.string(),
    confidence: z.number(),
}).passthrough();

export const ExtractedSignatureSchema = z.object({
    initials_or_name: z.string(),
    role: z.string().nullable(),
    confidence: z.number(),
}).passthrough();

export const ExtractedDeviationSchema = z.object({
    description: z.string(),
    severity: z.string().nullable(),
    step_reference: z.string().nullable(),
    confidence: z.number(),
}).passthrough();

export const ExtractedStepSchema = z.object({
    step_name: z.string(),
    step_number: z.number().nullable(),
    description: z.string().default(''),
    parameters: z.array(ExtractedParameterValueSchema).default([]),
    timestamps: z.array(ExtractedTimestampSchema).default([]),
    signatures: z.array(ExtractedSignatureSchema).default([]),
    deviations: z.array(ExtractedDeviationSchema).default([]),
    notes: z.string().default(''),
    confidence: z.number(),
    source_page: z.number().nullable(),
}).passthrough();

export const ExtractionResponseSchema = z.object({
    document_title: z.string().default(''),
    batch_id: z.string().nullable(),
    product_name: z.string().nullable(),
    date: z.string().nullable(),
    steps: z.array(ExtractedStepSchema).default([]),
    general_notes: z.array(z.string()).default([]),
    overall_confidence: z.number(),
}).passthrough();

// ── Step mapping schemas ────────────────────────────────────────────

export const ParamMappingSchema = z.object({
    extracted_param_index: z.number(),
    extracted_label: z.string(),
    extracted_value: z.unknown(),
    extracted_unit: z.string().nullable(),
    schema_field_key: z.string(),
    schema_field_label: z.string(),
    confidence: z.number(),
}).passthrough();

export const StepMappingSchema = z.object({
    extracted_step_index: z.number(),
    extracted_step_name: z.string(),
    protocol_step_id: z.string(),
    protocol_step_name: z.string(),
    score: z.number(),
    param_mappings: z.array(ParamMappingSchema).default([]),
}).passthrough();

// ── Processing progress ─────────────────────────────────────────────

export const ProcessingProgressSchema = z.object({
    stage: z.string().default(''),
    stage_label: z.string().default(''),
    current: z.number().default(0),
    total: z.number().default(0),
    percent: z.number().default(0),
    status: z.string().default(''),
    error_message: z.string().nullable().default(null),
}).passthrough();

// ── Import response ─────────────────────────────────────────────────

export const BatchRecordImportResponseSchema = z.object({
    import_id: z.string().uuid(),
    status: z.string(),
    extraction: ExtractionResponseSchema.nullable().default(null),
    step_mappings: z.array(StepMappingSchema).default([]),
    progress: ProcessingProgressSchema.nullable().default(null),
    created_run_id: z.string().uuid().nullable().default(null),
    error_message: z.string().nullable().default(null),
    page_count: z.number().nullable().default(null),
    original_filename: z.string().default(''),
    protocol_id: z.string().uuid(),
    created_at: z.string(),
}).passthrough();

// ── Finalize response ───────────────────────────────────────────────

export const BatchRecordFinalizeResponseSchema = z.object({
    run_id: z.string().uuid(),
    run_name: z.string(),
    import_id: z.string().uuid(),
    status: z.string().default('FINALIZED'),
}).passthrough();

// ── Derived types ───────────────────────────────────────────────────

export type BatchRecordImportResponse = z.infer<typeof BatchRecordImportResponseSchema>;
export type ExtractionResponse = z.infer<typeof ExtractionResponseSchema>;
export type ExtractedStep = z.infer<typeof ExtractedStepSchema>;
export type ExtractedParameterValue = z.infer<typeof ExtractedParameterValueSchema>;
export type StepMapping = z.infer<typeof StepMappingSchema>;
export type ParamMapping = z.infer<typeof ParamMappingSchema>;
export type ProcessingProgress = z.infer<typeof ProcessingProgressSchema>;
export type BatchRecordFinalizeResponse = z.infer<typeof BatchRecordFinalizeResponseSchema>;

// ── Frontend-only types for review state ────────────────────────────

export type ValueAssignment = {
    paramKey: string;
    protocolStepId: string;
    schemaFieldKey: string;
    value: unknown;
    originalValue: unknown;
    extractedLabel: string;
    extractedUnit: string | null;
    confidence: number;
    accepted: boolean;
    edited: boolean;
    rejected: boolean;
};
