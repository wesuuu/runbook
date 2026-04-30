// frontend/src/lib/utils/runOverrides.ts
//
// Pure helpers for computing and packing run-level param overrides.
// No DOM, no API calls — safe to unit-test and import anywhere.

export type EditKind =
    | 'VALUE'
    | 'SWAP'
    | 'ADDED'
    | 'REMOVED'
    | 'INSTRUCTION'
    | 'SCHEMA';

export interface Edit {
    nodeId: string;
    stepName: string;
    kind: EditKind;
    field?: string;
    fieldLabel?: string;
    oldValue?: unknown;
    newValue?: unknown;
}

interface NodeOverridesPayload {
    params?: Record<string, unknown>;
    equipment?: Array<{ equipment_id: string; shareable: boolean }>;
    paramSchema?: Record<string, unknown>;
    description?: string;
}

export interface RunOverridesPayload {
    nodes: Record<string, NodeOverridesPayload>;
}

function deriveLabel(props: Record<string, any> | undefined, key: string): string {
    const prop = props?.[key];
    if (prop && typeof prop === 'object' && typeof prop.title === 'string' && prop.title) {
        return prop.title;
    }
    return key
        .replace(/([a-z])([A-Z])/g, '$1 $2')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
}

function isUnitOp(node: any): boolean {
    return node && typeof node === 'object' && node.type === 'unitOp';
}

function deepEqual(a: unknown, b: unknown): boolean {
    return JSON.stringify(a) === JSON.stringify(b);
}

export function computeEdits(originalGraph: any, currentGraph: any): Edit[] {
    const edits: Edit[] = [];
    const origById = new Map<string, any>();
    for (const n of originalGraph?.nodes ?? []) {
        if (isUnitOp(n)) origById.set(n.id, n);
    }
    for (const node of currentGraph?.nodes ?? []) {
        if (!isUnitOp(node)) continue;
        const orig = origById.get(node.id);
        if (!orig) continue;
        const stepName = node.data?.label || node.id;
        const origData = orig.data || {};
        const currData = node.data || {};

        const origProps = (origData.paramSchema?.properties ?? {}) as Record<string, any>;
        const currProps = (currData.paramSchema?.properties ?? {}) as Record<string, any>;
        const origParams = (origData.params ?? {}) as Record<string, unknown>;
        const currParams = (currData.params ?? {}) as Record<string, unknown>;

        const allKeys = new Set([
            ...Object.keys(origProps),
            ...Object.keys(currProps),
        ]);
        for (const key of allKeys) {
            const inOrig = key in origProps;
            const inCurr = key in currProps;
            if (inOrig && !inCurr) {
                edits.push({
                    nodeId: node.id,
                    stepName,
                    kind: 'REMOVED',
                    field: key,
                    fieldLabel: deriveLabel(origProps, key),
                    oldValue: origParams[key],
                });
            } else if (!inOrig && inCurr) {
                edits.push({
                    nodeId: node.id,
                    stepName,
                    kind: 'ADDED',
                    field: key,
                    fieldLabel: deriveLabel(currProps, key),
                    newValue: currParams[key],
                });
            } else if (inOrig && inCurr) {
                if (!deepEqual(origParams[key], currParams[key])) {
                    edits.push({
                        nodeId: node.id,
                        stepName,
                        kind: 'VALUE',
                        field: key,
                        fieldLabel: deriveLabel(currProps, key),
                        oldValue: origParams[key],
                        newValue: currParams[key],
                    });
                }
            }
        }

        if (!deepEqual(origData.equipment ?? [], currData.equipment ?? [])) {
            edits.push({
                nodeId: node.id,
                stepName,
                kind: 'SWAP',
                field: 'equipment',
                fieldLabel: 'Equipment',
                oldValue: origData.equipment ?? [],
                newValue: currData.equipment ?? [],
            });
        }

        if ((origData.description ?? '') !== (currData.description ?? '')) {
            edits.push({
                nodeId: node.id,
                stepName,
                kind: 'INSTRUCTION',
                field: 'description',
                fieldLabel: 'Instructions',
                oldValue: origData.description ?? '',
                newValue: currData.description ?? '',
            });
        }
    }
    return edits;
}

export function hasStructuralChanges(edits: Edit[]): boolean {
    return edits.some((e) =>
        e.kind === 'ADDED' ||
        e.kind === 'REMOVED' ||
        e.kind === 'INSTRUCTION' ||
        e.kind === 'SCHEMA',
    );
}

export function buildOverridesPayload(
    edits: Edit[],
    currentGraph: any,
): RunOverridesPayload | undefined {
    if (edits.length === 0) return undefined;
    const byNode = new Map<string, Set<EditKind>>();
    for (const e of edits) {
        if (!byNode.has(e.nodeId)) byNode.set(e.nodeId, new Set());
        byNode.get(e.nodeId)!.add(e.kind);
    }

    const result: RunOverridesPayload = { nodes: {} };
    for (const [nodeId, kinds] of byNode) {
        const node = (currentGraph?.nodes ?? []).find((n: any) => n.id === nodeId);
        if (!node) continue;
        const data = node.data ?? {};
        const entry: NodeOverridesPayload = {};

        const valueOrStructural =
            kinds.has('VALUE') || kinds.has('ADDED') || kinds.has('REMOVED');
        if (valueOrStructural) {
            const valueEdits = edits.filter(
                (e) => e.nodeId === nodeId && (e.kind === 'VALUE' || e.kind === 'ADDED'),
            );
            const sparse: Record<string, unknown> = {};
            for (const ve of valueEdits) {
                if (ve.field) sparse[ve.field] = ve.newValue;
            }
            if (Object.keys(sparse).length > 0) entry.params = sparse;
        }

        if (kinds.has('SWAP')) {
            entry.equipment = data.equipment ?? [];
        }

        if (kinds.has('ADDED') || kinds.has('REMOVED') || kinds.has('SCHEMA')) {
            entry.paramSchema = data.paramSchema ?? {};
        }

        if (kinds.has('INSTRUCTION')) {
            entry.description = data.description ?? '';
        }

        result.nodes[nodeId] = entry;
    }
    return result;
}

// ─── Role resolution ───
//
// Roles are encoded in the graph via swimlane nodes (type === 'swimLane'). A
// unit-op node belongs to a role when its parentId references a swimlane that
// references that role. The role id is stored at swimlane.data.roleId
// (camelCase) — see protocolNodes.ts for where the protocol editor writes
// this.

const SWIMLANE_ROLE_KEYS = ['roleId'] as const;

function readSwimlaneRoleId(swimlaneNode: any): string | null {
    const data = swimlaneNode?.data ?? {};
    for (const k of SWIMLANE_ROLE_KEYS) {
        const v = data[k];
        if (typeof v === 'string' && v.length > 0) return v;
    }
    return null;
}

export function resolveNodeRoleId(
    nodeId: string,
    graph: any,
): string | null {
    const nodes = (graph?.nodes ?? []) as any[];
    const byId = new Map<string, any>();
    for (const n of nodes) byId.set(n.id, n);
    const node = byId.get(nodeId);
    if (!node) return null;
    if (node.type === 'swimLane') return readSwimlaneRoleId(node);
    const parent = node.parentId ? byId.get(node.parentId) : null;
    if (parent && parent.type === 'swimLane') return readSwimlaneRoleId(parent);
    return null;
}

export function groupUnitOpsByRole(
    graph: any,
): Map<string | null, any[]> {
    const out = new Map<string | null, any[]>();
    for (const node of (graph?.nodes ?? []) as any[]) {
        if (node.type !== 'unitOp') continue;
        const roleId = resolveNodeRoleId(node.id, graph);
        if (!out.has(roleId)) out.set(roleId, []);
        out.get(roleId)!.push(node);
    }
    return out;
}

export function groupEditsByRole(
    edits: Edit[],
    graph: any,
): Map<string | null, Edit[]> {
    const out = new Map<string | null, Edit[]>();
    for (const edit of edits) {
        const roleId = resolveNodeRoleId(edit.nodeId, graph);
        if (!out.has(roleId)) out.set(roleId, []);
        out.get(roleId)!.push(edit);
    }
    return out;
}
