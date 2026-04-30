// frontend/src/lib/utils/runOverrides.test.ts
import { describe, it, expect } from 'vitest';
import {
    computeEdits,
    buildOverridesPayload,
    hasStructuralChanges,
    resolveNodeRoleId,
    groupUnitOpsByRole,
    groupEditsByRole,
    type Edit,
} from './runOverrides';

const sampleGraph = (mut?: (g: any) => void) => {
    const g = {
        nodes: [
            {
                id: 'n1',
                type: 'unitOp',
                data: {
                    label: 'Buffer Mix',
                    params: { temperature: 25, ph: 7.0 },
                    equipment: [{ equipment_id: 'eq-1', shareable: false }],
                    paramSchema: {
                        type: 'object',
                        properties: {
                            temperature: { type: 'number', title: 'Temperature' },
                            ph: { type: 'number', title: 'pH' },
                        },
                    },
                    description: 'Mix at {{temperature}}°C, pH {{ph}}',
                    protocol_params: { temperature: 25, ph: 7.0 },
                    protocol_equipment: [{ equipment_id: 'eq-1', shareable: false }],
                    protocol_paramSchema: {
                        type: 'object',
                        properties: {
                            temperature: { type: 'number', title: 'Temperature' },
                            ph: { type: 'number', title: 'pH' },
                        },
                    },
                    protocol_description: 'Mix at {{temperature}}°C, pH {{ph}}',
                },
            },
            { id: 'lane', type: 'swimLane', data: { label: 'Operator' } },
        ],
        edges: [],
    };
    if (mut) mut(g);
    return g;
};

describe('computeEdits', () => {
    it('returns empty when current matches original', () => {
        const orig = sampleGraph();
        const curr = sampleGraph();
        expect(computeEdits(orig, curr)).toEqual([]);
    });

    it('detects a single param value override', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => { g.nodes[0].data.params.temperature = 30; });
        const edits = computeEdits(orig, curr);
        expect(edits).toHaveLength(1);
        expect(edits[0]).toMatchObject({
            nodeId: 'n1',
            stepName: 'Buffer Mix',
            kind: 'VALUE',
            field: 'temperature',
            fieldLabel: 'Temperature',
            oldValue: 25,
            newValue: 30,
        });
    });

    it('detects equipment swap', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => {
            g.nodes[0].data.equipment = [{ equipment_id: 'eq-2', shareable: false }];
        });
        const edits = computeEdits(orig, curr);
        expect(edits).toHaveLength(1);
        expect(edits[0].kind).toBe('SWAP');
    });

    it('detects added param (schema property added + value set)', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => {
            g.nodes[0].data.paramSchema.properties.duration = { type: 'number', title: 'Duration' };
            g.nodes[0].data.params.duration = 60;
        });
        const edits = computeEdits(orig, curr);
        const added = edits.find((e) => e.kind === 'ADDED');
        expect(added).toBeDefined();
        expect(added?.field).toBe('duration');
    });

    it('detects removed param (schema property removed)', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => {
            delete g.nodes[0].data.paramSchema.properties.ph;
            delete g.nodes[0].data.params.ph;
        });
        const edits = computeEdits(orig, curr);
        const removed = edits.find((e) => e.kind === 'REMOVED');
        expect(removed?.field).toBe('ph');
    });

    it('detects instruction edit', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => { g.nodes[0].data.description = 'New instructions'; });
        const edits = computeEdits(orig, curr);
        expect(edits).toHaveLength(1);
        expect(edits[0].kind).toBe('INSTRUCTION');
    });

    it('ignores non-unitOp nodes (swimlanes etc.)', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => { g.nodes[1].data.label = 'Different Lane'; });
        expect(computeEdits(orig, curr)).toEqual([]);
    });

    it('uses key as fallback fieldLabel when paramSchema has no title', () => {
        const orig = sampleGraph((g) => { delete g.nodes[0].data.paramSchema.properties.temperature.title; });
        const curr = sampleGraph((g) => {
            delete g.nodes[0].data.paramSchema.properties.temperature.title;
            g.nodes[0].data.params.temperature = 30;
        });
        const edits = computeEdits(orig, curr);
        expect(edits[0].fieldLabel).toBe('Temperature');  // title-cased fallback
    });
});

describe('hasStructuralChanges', () => {
    it('returns false for value-only and swap edits', () => {
        const edits: Edit[] = [
            { nodeId: 'n1', stepName: 'X', kind: 'VALUE' },
            { nodeId: 'n1', stepName: 'X', kind: 'SWAP' },
        ];
        expect(hasStructuralChanges(edits)).toBe(false);
    });

    it('returns true if any edit is ADDED, REMOVED, INSTRUCTION, or SCHEMA', () => {
        expect(hasStructuralChanges([{ nodeId: 'n1', stepName: 'X', kind: 'ADDED' }])).toBe(true);
        expect(hasStructuralChanges([{ nodeId: 'n1', stepName: 'X', kind: 'REMOVED' }])).toBe(true);
        expect(hasStructuralChanges([{ nodeId: 'n1', stepName: 'X', kind: 'INSTRUCTION' }])).toBe(true);
    });
});

describe('buildOverridesPayload', () => {
    it('returns undefined when no edits', () => {
        const orig = sampleGraph();
        const curr = sampleGraph();
        const edits = computeEdits(orig, curr);
        expect(buildOverridesPayload(edits, curr)).toBeUndefined();
    });

    it('packs sparse params, full equipment/schema/description', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => {
            g.nodes[0].data.params.temperature = 30;
            g.nodes[0].data.equipment = [{ equipment_id: 'eq-2', shareable: true }];
            g.nodes[0].data.description = 'New';
        });
        const edits = computeEdits(orig, curr);
        const payload = buildOverridesPayload(edits, curr);
        expect(payload).toEqual({
            nodes: {
                n1: {
                    params: { temperature: 30 },
                    equipment: [{ equipment_id: 'eq-2', shareable: true }],
                    description: 'New',
                },
            },
        });
    });

    it('only emits paramSchema when schema actually changed', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => { g.nodes[0].data.params.temperature = 30; });
        const edits = computeEdits(orig, curr);
        const payload = buildOverridesPayload(edits, curr);
        expect(payload?.nodes.n1.paramSchema).toBeUndefined();
    });

    it('emits paramSchema but no params entry on removed-only schema change', () => {
        const orig = sampleGraph();
        const curr = sampleGraph((g) => {
            delete g.nodes[0].data.paramSchema.properties.ph;
            delete g.nodes[0].data.params.ph;
        });
        const edits = computeEdits(orig, curr);
        const payload = buildOverridesPayload(edits, curr);
        expect(payload?.nodes.n1.paramSchema).toBeDefined();
        expect(payload?.nodes.n1.params).toBeUndefined();
    });
});

const multiRoleGraph = () => ({
    nodes: [
        { id: 'lane-op',  type: 'swimLane', data: { label: 'Operator',        roleId: 'role-1' } },
        { id: 'lane-sup', type: 'swimLane', data: { label: 'Senior Operator', roleId: 'role-2' } },
        { id: 'n1', type: 'unitOp', parentId: 'lane-op',  data: { label: 'Buffer Mix',     params: {}, paramSchema: { properties: {} }, equipment: [], description: '' } },
        { id: 'n2', type: 'unitOp', parentId: 'lane-op',  data: { label: 'Cell Seeding',   params: {}, paramSchema: { properties: {} }, equipment: [], description: '' } },
        { id: 'n3', type: 'unitOp', parentId: 'lane-sup', data: { label: 'Centrifugation', params: {}, paramSchema: { properties: {} }, equipment: [], description: '' } },
    ],
    edges: [],
});

describe('resolveNodeRoleId', () => {
    it('returns the swimlane role id for a parented unit op', () => {
        expect(resolveNodeRoleId('n1', multiRoleGraph())).toBe('role-1');
        expect(resolveNodeRoleId('n3', multiRoleGraph())).toBe('role-2');
    });

    it('returns null for an orphan unit op (no parentId)', () => {
        const g = multiRoleGraph();
        g.nodes[2].parentId = undefined;
        expect(resolveNodeRoleId('n1', g)).toBeNull();
    });

    it('returns null for an unknown node id', () => {
        expect(resolveNodeRoleId('does-not-exist', multiRoleGraph())).toBeNull();
    });
});

describe('groupUnitOpsByRole', () => {
    it('buckets unit ops under their role id', () => {
        const grouped = groupUnitOpsByRole(multiRoleGraph());
        expect(grouped.get('role-1')?.map((n) => n.id)).toEqual(['n1', 'n2']);
        expect(grouped.get('role-2')?.map((n) => n.id)).toEqual(['n3']);
    });

    it('puts orphan unit ops under null', () => {
        const g = multiRoleGraph();
        g.nodes[2].parentId = undefined;
        const grouped = groupUnitOpsByRole(g);
        expect(grouped.get(null)?.map((n) => n.id)).toEqual(['n1']);
        expect(grouped.get('role-1')?.map((n) => n.id)).toEqual(['n2']);
    });
});

describe('groupEditsByRole', () => {
    it('buckets edits under each unit op\'s role', () => {
        const edits: Edit[] = [
            { nodeId: 'n1', stepName: 'Buffer Mix',     kind: 'VALUE' },
            { nodeId: 'n2', stepName: 'Cell Seeding',   kind: 'SWAP' },
            { nodeId: 'n3', stepName: 'Centrifugation', kind: 'VALUE' },
        ];
        const grouped = groupEditsByRole(edits, multiRoleGraph());
        expect(grouped.get('role-1')).toHaveLength(2);
        expect(grouped.get('role-2')).toHaveLength(1);
    });
});
