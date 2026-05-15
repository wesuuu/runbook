import { z } from 'zod';

/** A single docling-emitted low-confidence region. Phase 1 always emits []. */
export const RefinementFlagSchema = z
    .object({
        id: z.string(),
        kind: z.string(),
        confidence: z.number().nullable().optional(),
        block_anchor: z.string().nullable().optional(),
        source_text: z.string().nullable().optional(),
        page: z.number().nullable().optional(),
        bbox: z.array(z.number()).nullable().optional(),
    })
    .passthrough();
export type RefinementFlag = z.infer<typeof RefinementFlagSchema>;

/** Mirrors backend DocumentResponse (schemas/library.py). */
export const DocumentResponseSchema = z
    .object({
        id: z.string(),
        org_id: z.string(),
        project_id: z.string().nullable().optional(),
        uploaded_by_id: z.string(),
        title: z.string(),
        original_filename: z.string(),
        mime_type: z.string(),
        file_size_bytes: z.number(),
        file_path: z.string(),
        status: z.string(),
        page_count: z.number().nullable().optional(),
        tags: z.array(z.unknown()).default([]),
        doc_metadata: z.record(z.string(), z.unknown()).default({}),
        error_message: z.string().nullable().optional(),
        source_url: z.string().nullable().optional(),
        processing_started_at: z.string().nullable().optional(),
        structure_metadata: z.record(z.string(), z.unknown()).nullable().optional(),
        created_at: z.string(),
        updated_at: z.string(),
        can_delete: z.boolean().default(false),
        source_format: z.string().nullable().optional(),
        refinement_status: z.string().nullable().optional(),
        refinement_flags: z.array(RefinementFlagSchema).nullable().optional(),
        refined_by_id: z.string().nullable().optional(),
        refined_at: z.string().nullable().optional(),
    })
    .passthrough();
export type DocumentResponse = z.infer<typeof DocumentResponseSchema>;

/** GET /library/documents/{id}/markdown */
export const MarkdownResponseSchema = z
    .object({
        markdown: z.string(),
    })
    .passthrough();
export type MarkdownResponse = z.infer<typeof MarkdownResponseSchema>;

/** POST /library/documents/{id}/refine/ai */
export const RefineAiResponseSchema = z
    .object({
        suggested_markdown: z.string(),
        model_used: z.string(),
    })
    .passthrough();
export type RefineAiResponse = z.infer<typeof RefineAiResponseSchema>;
