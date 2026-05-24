import { describe, it, expect } from 'vitest';
import fixture from '../../../tests/fixtures/conditions_parity.json';
import { computeConditions } from '$lib/experiments/conditions';

describe('computeConditions parity', () => {
    for (const scenario of fixture.scenarios) {
        it(scenario.name, () => {
            const actual = computeConditions(scenario.runs as any);
            const normalized = actual.map(row => ({
                nodeLabel: row.nodeLabel,
                paramKey: row.paramKey,
                varied: row.varied,
                ...(row.unitConflict ? { unitConflict: row.unitConflict } : {}),
                perRun: Object.fromEntries(row.perRun),
            }));
            expect(normalized).toEqual(scenario.expected);
        });
    }
});
