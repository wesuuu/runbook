import { describe, it, expect } from 'vitest';
import {
    BatchRecordImportResponseSchema,
    ExtractionResponseSchema,
    ExtractedStepSchema,
    ExtractedParameterValueSchema,
    StepMappingSchema,
    ParamMappingSchema,
    ProcessingProgressSchema,
    BatchRecordFinalizeResponseSchema,
} from './batchRecordImport';

describe('ExtractedParameterValueSchema', () => {
    it('validates a complete parameter value', () => {
        const result = ExtractedParameterValueSchema.parse({
            field_label: 'pH',
            value: 7.2,
            unit: null,
            confidence: 0.95,
            source_page: 1,
        });
        expect(result.field_label).toBe('pH');
        expect(result.value).toBe(7.2);
        expect(result.confidence).toBe(0.95);
    });

    it('accepts string values', () => {
        const result = ExtractedParameterValueSchema.parse({
            field_label: 'Color',
            value: 'amber',
            unit: null,
            confidence: 0.8,
            source_page: null,
        });
        expect(result.value).toBe('amber');
    });

    it('allows unknown fields with passthrough', () => {
        const result = ExtractedParameterValueSchema.parse({
            field_label: 'pH',
            value: 7.0,
            unit: null,
            confidence: 0.9,
            source_page: 1,
            extra_field: 'should pass',
        });
        expect((result as any).extra_field).toBe('should pass');
    });

    it('rejects missing required fields', () => {
        expect(() =>
            ExtractedParameterValueSchema.parse({ field_label: 'pH' })
        ).toThrow();
    });
});

describe('ExtractedStepSchema', () => {
    it('validates a step with all fields', () => {
        const result = ExtractedStepSchema.parse({
            step_name: 'Buffer Prep',
            step_number: 1,
            description: 'Prepare buffer',
            parameters: [
                { field_label: 'pH', value: 7.2, unit: null, confidence: 0.95, source_page: 1 },
            ],
            timestamps: [
                { value: '08:30', label: 'Start', confidence: 0.9 },
            ],
            signatures: [
                { initials_or_name: 'JKL', role: 'Operator', confidence: 0.88 },
            ],
            deviations: [
                { description: 'Foam', severity: 'minor', step_reference: null, confidence: 0.7 },
            ],
            notes: 'Clear solution',
            confidence: 0.93,
            source_page: 1,
        });
        expect(result.step_name).toBe('Buffer Prep');
        expect(result.parameters).toHaveLength(1);
        expect(result.timestamps).toHaveLength(1);
        expect(result.signatures).toHaveLength(1);
        expect(result.deviations).toHaveLength(1);
    });

    it('defaults empty arrays for optional lists', () => {
        const result = ExtractedStepSchema.parse({
            step_name: 'Simple Step',
            step_number: null,
            confidence: 0.5,
            source_page: null,
        });
        expect(result.parameters).toEqual([]);
        expect(result.timestamps).toEqual([]);
        expect(result.signatures).toEqual([]);
        expect(result.deviations).toEqual([]);
        expect(result.notes).toBe('');
    });
});

describe('ExtractionResponseSchema', () => {
    it('validates a full extraction', () => {
        const result = ExtractionResponseSchema.parse({
            document_title: 'Batch Record LOT-042',
            batch_id: 'LOT-042',
            product_name: 'mAb-X',
            date: '2026-01-15',
            steps: [
                {
                    step_name: 'Step 1',
                    step_number: 1,
                    confidence: 0.9,
                    source_page: 1,
                },
            ],
            overall_confidence: 0.92,
        });
        expect(result.steps).toHaveLength(1);
        expect(result.batch_id).toBe('LOT-042');
    });

    it('handles empty extraction', () => {
        const result = ExtractionResponseSchema.parse({
            overall_confidence: 0.0,
            batch_id: null,
            product_name: null,
            date: null,
        });
        expect(result.steps).toEqual([]);
        expect(result.document_title).toBe('');
    });
});

describe('StepMappingSchema', () => {
    it('validates a mapping with param mappings', () => {
        const result = StepMappingSchema.parse({
            extracted_step_index: 0,
            extracted_step_name: 'Buffer Prep',
            protocol_step_id: 'node-buf',
            protocol_step_name: 'Buffer Preparation',
            score: 0.92,
            param_mappings: [
                {
                    extracted_param_index: 0,
                    extracted_label: 'pH',
                    extracted_value: 7.2,
                    extracted_unit: null,
                    schema_field_key: 'ph_value',
                    schema_field_label: 'pH Value',
                    confidence: 0.95,
                },
            ],
        });
        expect(result.score).toBe(0.92);
        expect(result.param_mappings).toHaveLength(1);
    });

    it('defaults empty param_mappings', () => {
        const result = StepMappingSchema.parse({
            extracted_step_index: 0,
            extracted_step_name: 'Step',
            protocol_step_id: 'node-1',
            protocol_step_name: 'Step One',
            score: 0.5,
        });
        expect(result.param_mappings).toEqual([]);
    });
});

describe('ProcessingProgressSchema', () => {
    it('validates progress data', () => {
        const result = ProcessingProgressSchema.parse({
            stage: 'extracting',
            stage_label: 'Extracting page 3 of 12',
            current: 3,
            total: 12,
            percent: 25,
            status: 'RUNNING',
            error_message: null,
        });
        expect(result.stage).toBe('extracting');
        expect(result.percent).toBe(25);
    });

    it('defaults all fields', () => {
        const result = ProcessingProgressSchema.parse({});
        expect(result.stage).toBe('');
        expect(result.current).toBe(0);
        expect(result.total).toBe(0);
        expect(result.percent).toBe(0);
        expect(result.error_message).toBeNull();
    });
});

describe('BatchRecordImportResponseSchema', () => {
    it('validates an EXTRACTING response', () => {
        const result = BatchRecordImportResponseSchema.parse({
            import_id: '550e8400-e29b-41d4-a716-446655440000',
            status: 'EXTRACTING',
            protocol_id: '660e8400-e29b-41d4-a716-446655440000',
            created_at: '2026-01-15T08:30:00Z',
        });
        expect(result.status).toBe('EXTRACTING');
        expect(result.extraction).toBeNull();
        expect(result.step_mappings).toEqual([]);
        expect(result.progress).toBeNull();
    });

    it('validates a REVIEW response with extraction', () => {
        const result = BatchRecordImportResponseSchema.parse({
            import_id: '550e8400-e29b-41d4-a716-446655440000',
            status: 'REVIEW',
            protocol_id: '660e8400-e29b-41d4-a716-446655440000',
            created_at: '2026-01-15T08:30:00Z',
            extraction: {
                document_title: 'Test',
                batch_id: null,
                product_name: null,
                date: null,
                steps: [{ step_name: 'Step 1', step_number: 1, confidence: 0.9, source_page: 1 }],
                overall_confidence: 0.9,
            },
            step_mappings: [
                {
                    extracted_step_index: 0,
                    extracted_step_name: 'Step 1',
                    protocol_step_id: 'node-1',
                    protocol_step_name: 'Step One',
                    score: 0.85,
                },
            ],
            page_count: 2,
            original_filename: 'batch.pdf',
        });
        expect(result.extraction).not.toBeNull();
        expect(result.extraction!.steps).toHaveLength(1);
        expect(result.step_mappings).toHaveLength(1);
    });

    it('validates a FAILED response', () => {
        const result = BatchRecordImportResponseSchema.parse({
            import_id: '550e8400-e29b-41d4-a716-446655440000',
            status: 'FAILED',
            protocol_id: '660e8400-e29b-41d4-a716-446655440000',
            created_at: '2026-01-15T08:30:00Z',
            error_message: 'Vision model timeout',
        });
        expect(result.error_message).toBe('Vision model timeout');
    });
});

describe('BatchRecordFinalizeResponseSchema', () => {
    it('validates a finalize response', () => {
        const result = BatchRecordFinalizeResponseSchema.parse({
            run_id: '770e8400-e29b-41d4-a716-446655440000',
            run_slug: 'imported-run-lot-042',
            run_name: 'Imported Run LOT-042',
            project_slug: 'project-alpha',
            import_id: '550e8400-e29b-41d4-a716-446655440000',
            status: 'FINALIZED',
        });
        expect(result.run_id).toBe('770e8400-e29b-41d4-a716-446655440000');
        expect(result.run_name).toBe('Imported Run LOT-042');
    });
});
