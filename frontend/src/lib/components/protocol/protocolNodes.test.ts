import { describe, it, expect } from 'vitest';
import { formatNodeParams } from './protocolNodes';

describe('formatNodeParams', () => {
    const schema = {
        properties: {
            speed_rpm: { title: 'Speed', type: 'number' },
            duration_min: { title: 'Duration', type: 'number' },
            temperature_C: { title: 'Temperature', type: 'number' },
            buffer: { title: 'Buffer', type: 'string' },
        },
    };

    it('returns an empty list when params or schema are missing', () => {
        expect(formatNodeParams(null, schema)).toEqual([]);
        expect(formatNodeParams({ speed_rpm: 300 }, null)).toEqual([]);
        expect(formatNodeParams({ speed_rpm: 300 }, {})).toEqual([]);
    });

    it('orders rows by schema property order, not params key order (#12)', () => {
        // params keys deliberately in a different order than the schema —
        // mimics JSONB reordering the object across a reload.
        const reloaded = formatNodeParams(
            { temperature_C: 37, buffer: 'PBS', speed_rpm: 300, duration_min: 10 },
            schema,
        );
        const labels = reloaded.map((r) => r.label);
        expect(labels).toEqual(['Speed', 'Duration', 'Temperature', 'Buffer']);
    });

    it('produces an identical summary regardless of params key order (#12)', () => {
        const orderA = formatNodeParams(
            { speed_rpm: 300, duration_min: 10, buffer: 'PBS' },
            schema,
        );
        const orderB = formatNodeParams(
            { buffer: 'PBS', duration_min: 10, speed_rpm: 300 },
            schema,
        );
        expect(orderA).toEqual(orderB);
    });

    it('caps the summary at 4 rows', () => {
        const big = {
            properties: {
                a: { type: 'string' },
                b: { type: 'string' },
                c: { type: 'string' },
                d: { type: 'string' },
                e: { type: 'string' },
            },
        };
        const rows = formatNodeParams(
            { a: '1', b: '2', c: '3', d: '4', e: '5' },
            big,
        );
        expect(rows).toHaveLength(4);
        expect(rows.map((r) => r.value)).toEqual(['1', '2', '3', '4']);
    });

    it('skips schema properties with no matching params value', () => {
        const rows = formatNodeParams({ speed_rpm: 300 }, schema);
        expect(rows).toEqual([{ label: 'Speed', value: '300' }]);
    });

    it('skips params keys absent from the schema', () => {
        const rows = formatNodeParams(
            { speed_rpm: 300, mystery_field: 'x' },
            schema,
        );
        expect(rows.map((r) => r.label)).toEqual(['Speed']);
    });

    it('skips reference-typed properties in the inline view', () => {
        const refSchema = {
            properties: {
                reagent: { title: 'Reagent', 'x-ref-type': 'material' },
                speed_rpm: { title: 'Speed', type: 'number' },
            },
        };
        const rows = formatNodeParams(
            { reagent: 'mat-1', speed_rpm: 300 },
            refSchema,
        );
        expect(rows.map((r) => r.label)).toEqual(['Speed']);
    });

    it('formats integers with thousands separators and floats to one decimal', () => {
        const rows = formatNodeParams(
            { speed_rpm: 12000, duration_min: 7.25 },
            schema,
        );
        expect(rows[0]).toEqual({ label: 'Speed', value: '12,000' });
        expect(rows[1]).toEqual({ label: 'Duration', value: '7.3' });
    });

    it('falls back to the param key when the schema omits a title', () => {
        const rows = formatNodeParams(
            { speed_rpm: 300 },
            { properties: { speed_rpm: { type: 'number' } } },
        );
        expect(rows[0].label).toBe('speed_rpm');
    });
});
