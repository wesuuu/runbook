import { z } from 'zod';

export const CurrentLegalVersionSchema = z
    .object({
        version: z.string(),
        effective_date: z.string(),
    })
    .passthrough();

export type CurrentLegalVersion = z.infer<typeof CurrentLegalVersionSchema>;

export const LegalDocumentSchema = z
    .object({
        version: z.string(),
        effective_date: z.string(),
        markdown: z.string(),
    })
    .passthrough();

export type LegalDocument = z.infer<typeof LegalDocumentSchema>;

export type LegalDocType = 'terms' | 'privacy';
