import { describe, expect, it } from 'vitest';
import type { Node } from '@xyflow/svelte';
import {
    findLocalIdConflicts,
    suggestNextLocalId,
} from './equipmentIds';

function makeNode(
    id: string,
    equipment: Array<{ equipment_id: string; local_id?: string; shareable: boolean }> = [],
): Node {
    return {
        id,
        type: 'unitOp',
        position: { x: 0, y: 0 },
        data: { equipment },
    } as unknown as Node;
}

describe('suggestNextLocalId', () => {
    it('returns E-001 when no equipment exists', () => {
        expect(suggestNextLocalId([])).toBe('E-001');
    });

    it('returns E-001 when no node has an E-NNN local_id', () => {
        const nodes = [
            makeNode('n1', [{ equipment_id: 'uuid-1', local_id: 'pump_a', shareable: false }]),
        ];
        expect(suggestNextLocalId(nodes)).toBe('E-001');
    });

    it('increments past the highest existing E-NNN', () => {
        const nodes = [
            makeNode('n1', [
                { equipment_id: 'uuid-1', local_id: 'E-001', shareable: false },
                { equipment_id: 'uuid-2', local_id: 'E-007', shareable: false },
            ]),
            makeNode('n2', [{ equipment_id: 'uuid-3', local_id: 'E-003', shareable: false }]),
        ];
        expect(suggestNextLocalId(nodes)).toBe('E-008');
    });

    it('ignores non-unitOp nodes and missing local_id entries', () => {
        const nodes = [
            { id: 's1', type: 'swimLane', data: {}, position: { x: 0, y: 0 } } as unknown as Node,
            makeNode('n1', [{ equipment_id: 'uuid-1', shareable: false }]),
        ];
        expect(suggestNextLocalId(nodes)).toBe('E-001');
    });
});

describe('findLocalIdConflicts', () => {
    it('returns empty map when all local_ids are unique', () => {
        const nodes = [
            makeNode('n1', [{ equipment_id: 'u1', local_id: 'E-001', shareable: false }]),
            makeNode('n2', [{ equipment_id: 'u2', local_id: 'E-002', shareable: false }]),
        ];
        expect(findLocalIdConflicts(nodes).size).toBe(0);
    });

    it('returns the offending node ids for each duplicated local_id', () => {
        const nodes = [
            makeNode('n1', [{ equipment_id: 'u1', local_id: 'E-001', shareable: false }]),
            makeNode('n2', [{ equipment_id: 'u2', local_id: 'E-001', shareable: false }]),
        ];
        const conflicts = findLocalIdConflicts(nodes);
        expect(conflicts.get('E-001')).toEqual(['n1', 'n2']);
    });

    it('skips empty / undefined local_ids', () => {
        const nodes = [
            makeNode('n1', [{ equipment_id: 'u1', shareable: false }]),
            makeNode('n2', [{ equipment_id: 'u2', local_id: '', shareable: false }]),
        ];
        expect(findLocalIdConflicts(nodes).size).toBe(0);
    });
});
