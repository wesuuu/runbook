import { z } from 'zod';

export const DocumentTemplateSchema = z
    .object({
        id: z.string(),
        org_id: z.string().nullable(),
        project_id: z.string().nullable(),
        uploaded_by_id: z.string().nullable(),
        name: z.string(),
        description: z.string().nullable(),
        template_type: z.string(),
        original_filename: z.string(),
        mime_type: z.string(),
        file_size_bytes: z.number(),
        variables: z.record(z.string(), z.any()).optional(),
        is_system: z.boolean(),
        is_default: z.boolean(),
        is_current_default: z.boolean(),
        status: z.string(),
        archived_at: z.string().nullable(),
        archived_by_id: z.string().nullable(),
        created_at: z.string(),
        updated_at: z.string(),
    })
    .passthrough();

export type DocumentTemplate = z.infer<typeof DocumentTemplateSchema>;
export const DocumentTemplateListSchema = z.array(DocumentTemplateSchema);

const TemplateVariableEntrySchema = z
    .object({
        name: z.string(),
        description: z.string(),
        example: z.any().optional(),
        type: z.string().optional(),
        syntax: z.string().optional(),
    })
    .passthrough();

export type TemplateVariableEntry = z.infer<typeof TemplateVariableEntrySchema>;

export const TemplateVariablesSchema = z.record(
    z.string(),
    z.array(TemplateVariableEntrySchema),
);
export type TemplateVariables = z.infer<typeof TemplateVariablesSchema>;
