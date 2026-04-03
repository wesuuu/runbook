import { z } from 'zod';

export const StepProposalSchema = z.object({
    name: z.string(),
    description: z.string(),
    category: z.string(),
    duration_min: z.number(),
    params: z.record(z.string(), z.unknown()),
    param_schema: z.record(z.string(), z.unknown()),
    role: z.string().nullable(),
    matched_unit_op_id: z.string().nullable(),
    matched_unit_op_name: z.string().nullable(),
    is_new: z.boolean(),
}).passthrough();

export type StepProposal = z.infer<typeof StepProposalSchema>;

export const ProtocolImportProposalSchema = z.object({
    protocol_name: z.string(),
    protocol_description: z.string(),
    steps: z.array(StepProposalSchema),
    matched_count: z.number(),
    unmatched_count: z.number(),
    source_filename: z.string(),
    source_text_preview: z.string(),
}).passthrough();

export type ProtocolImportProposal = z.infer<typeof ProtocolImportProposalSchema>;
