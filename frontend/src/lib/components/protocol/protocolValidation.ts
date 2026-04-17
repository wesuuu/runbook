import type { Node, Edge } from "@xyflow/svelte";

export interface BranchValidationError {
    sourceNodeId: string;
    sourceNodeLabel: string;
    duplicateLane: string | null;
    targetNodeLabels: string[];
}

export interface ProcessStartValidationError {
    componentFirstNodeLabel: string;
    processStartCount: number;
}

/**
 * Detect branches where multiple targets land in the same swimlane.
 */
export function computeBranchValidationErrors(
    nodes: Node[],
    edges: Edge[],
): BranchValidationError[] {
    const errors: BranchValidationError[] = [];

    // Build outgoing edge map: sourceId -> [targetId, ...]
    const outgoingMap = new Map<string, string[]>();
    for (const edge of edges) {
        if (!outgoingMap.has(edge.source)) outgoingMap.set(edge.source, []);
        outgoingMap.get(edge.source)!.push(edge.target);
    }

    // Exception: no swimlanes + purely linear -> skip
    const hasSwimlanes = nodes.some((n) => n.type === "swimLane");
    const hasBranching = [...outgoingMap.values()].some((t) => t.length >= 2);
    if (!hasSwimlanes && !hasBranching) return errors;

    // Node lookup map
    const nodeMap = new Map(nodes.map((n) => [n.id, n]));

    // For each branching node, group targets by parentId
    for (const [sourceId, targetIds] of outgoingMap) {
        if (targetIds.length < 2) continue;
        const src = nodeMap.get(sourceId);
        if (!src || src.type !== "unitOp") continue;

        const laneGroups = new Map<string | null, string[]>();
        for (const tid of targetIds) {
            const t = nodeMap.get(tid);
            if (!t || t.type !== "unitOp") continue;
            const lane = t.parentId ?? null;
            if (!laneGroups.has(lane)) laneGroups.set(lane, []);
            laneGroups.get(lane)!.push(tid);
        }

        for (const [lane, group] of laneGroups) {
            if (group.length >= 2) {
                errors.push({
                    sourceNodeId: sourceId,
                    sourceNodeLabel:
                        (src.data as any).label || "Unnamed",
                    duplicateLane: lane,
                    targetNodeLabels: group.map(
                        (id) =>
                            (nodeMap.get(id)?.data as any)?.label ||
                            "Unnamed",
                    ),
                });
            }
        }
    }
    return errors;
}

/**
 * Validate that each connected component has exactly one ProcessStart node.
 */
export function computeProcessStartValidationErrors(
    nodes: Node[],
    edges: Edge[],
): ProcessStartValidationError[] {
    const errors: ProcessStartValidationError[] = [];

    // Build undirected adjacency for component discovery (unitOps + processStarts)
    const relevantNodes = nodes.filter(
        (n) => n.type === "unitOp" || n.type === "processStart",
    );
    if (relevantNodes.length === 0) return errors;

    const nodeMap = new Map(relevantNodes.map((n) => [n.id, n]));
    const nodeIds = new Set(nodeMap.keys());
    const adj: Map<string, Set<string>> = new Map();
    for (const nid of nodeIds) adj.set(nid, new Set());
    for (const e of edges) {
        if (nodeIds.has(e.source) && nodeIds.has(e.target)) {
            adj.get(e.source)!.add(e.target);
            adj.get(e.target)!.add(e.source);
        }
    }

    // BFS to find connected components
    const visited = new Set<string>();
    const components: Array<Set<string>> = [];
    for (const nid of nodeIds) {
        if (visited.has(nid)) continue;
        const comp = new Set<string>();
        const queue = [nid];
        while (queue.length) {
            const curr = queue.shift()!;
            if (visited.has(curr)) continue;
            visited.add(curr);
            comp.add(curr);
            for (const neighbor of adj.get(curr) ?? []) {
                if (!visited.has(neighbor)) queue.push(neighbor);
            }
        }
        components.push(comp);
    }

    for (const comp of components) {
        const compNodes = [...comp].map((id) => nodeMap.get(id)!);
        const unitOpsInComp = compNodes.filter((n) => n.type === "unitOp");
        const processStartsInComp = compNodes.filter(
            (n) => n.type === "processStart",
        );

        // Skip components with no unit ops (orphaned processStart)
        if (unitOpsInComp.length === 0) continue;

        if (processStartsInComp.length !== 1) {
            const first = unitOpsInComp[0];
            errors.push({
                componentFirstNodeLabel:
                    (first.data as any).label || "Unnamed",
                processStartCount: processStartsInComp.length,
            });
        }
    }
    return errors;
}
