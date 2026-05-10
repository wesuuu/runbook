import type { Node } from '@xyflow/svelte';

export interface SelectedEquipment {
    equipment_id: string;
    local_id?: string;
    shareable: boolean;
}

function readEquipment(node: Node): SelectedEquipment[] {
    if (node.type !== 'unitOp') return [];
    const data = node.data as { equipment?: SelectedEquipment[] } | undefined;
    return data?.equipment ?? [];
}

export function suggestNextLocalId(nodes: Node[]): string {
    let maxN = 0;
    for (const node of nodes) {
        for (const eq of readEquipment(node)) {
            const m = eq.local_id?.match(/^E-(\d+)$/);
            if (m) {
                const n = Number.parseInt(m[1], 10);
                if (n > maxN) maxN = n;
            }
        }
    }
    return `E-${String(maxN + 1).padStart(3, '0')}`;
}

export function findLocalIdConflicts(nodes: Node[]): Map<string, string[]> {
    const byId = new Map<string, string[]>();
    for (const node of nodes) {
        for (const eq of readEquipment(node)) {
            if (!eq.local_id) continue;
            const arr = byId.get(eq.local_id) ?? [];
            arr.push(node.id);
            byId.set(eq.local_id, arr);
        }
    }
    const conflicts = new Map<string, string[]>();
    for (const [id, nodeIds] of byId) {
        if (nodeIds.length > 1) conflicts.set(id, nodeIds);
    }
    return conflicts;
}
