import { describe, expect, it } from 'vitest';

import {
    DocumentResponseSchema,
    MarkdownResponseSchema,
    RefineAiResponseSchema,
    RefinementFlagSchema,
} from './documents';

describe('documents schemas', () => {
    it('parses a minimal DocumentResponse with null docling fields', () => {
        const raw = {
            id: 'doc-1',
            org_id: 'org-1',
            uploaded_by_id: 'user-1',
            title: 'SOP 12',
            original_filename: 'sop12.pdf',
            mime_type: 'application/pdf',
            file_size_bytes: 1024,
            file_path: 'org-1/documents/doc-1.pdf',
            status: 'AWAITING_REFINEMENT',
            created_at: '2026-05-14T00:00:00Z',
            updated_at: '2026-05-14T00:00:00Z',
        };
        const parsed = DocumentResponseSchema.parse(raw);
        expect(parsed.status).toBe('AWAITING_REFINEMENT');
        expect(parsed.tags).toEqual([]);
        expect(parsed.refinement_flags).toBeUndefined();
        expect(parsed.can_delete).toBe(false);
    });

    it('parses a DocumentResponse carrying refinement flags', () => {
        const raw = {
            id: 'doc-2',
            org_id: 'org-1',
            uploaded_by_id: 'user-1',
            title: 'SOP 13',
            original_filename: 'sop13.pdf',
            mime_type: 'application/pdf',
            file_size_bytes: 2048,
            file_path: 'org-1/documents/doc-2.pdf',
            status: 'AWAITING_REFINEMENT',
            created_at: '2026-05-14T00:00:00Z',
            updated_at: '2026-05-14T00:00:00Z',
            source_format: 'PDF',
            refinement_status: 'PENDING',
            refinement_flags: [
                {
                    id: 'flag-001',
                    kind: 'low_confidence_ocr',
                    confidence: 0.31,
                    block_anchor: 'table-1.row-1.col-2',
                    source_text: 'NaHzPO4119.98',
                    page: 1,
                    bbox: [0.42, 0.31, 0.58, 0.34],
                },
            ],
        };
        const parsed = DocumentResponseSchema.parse(raw);
        expect(parsed.refinement_flags).toHaveLength(1);
        expect(parsed.refinement_flags?.[0].source_text).toBe('NaHzPO4119.98');
    });

    it('parses the markdown and AI response shapes', () => {
        expect(MarkdownResponseSchema.parse({ markdown: '# Title' }).markdown).toBe('# Title');
        const ai = RefineAiResponseSchema.parse({
            suggested_markdown: 'NaH2PO4 119.98',
            model_used: 'claude-sonnet-4-6',
        });
        expect(ai.model_used).toBe('claude-sonnet-4-6');
    });

    it('rejects a flag missing its id', () => {
        expect(() => RefinementFlagSchema.parse({ kind: 'low_confidence_ocr' })).toThrow();
    });
});
