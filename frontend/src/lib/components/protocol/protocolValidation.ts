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

export interface BranchTimeContext {
    timeEnabled: boolean;
    pixelsPerHour: number;
    layout: "horizontal" | "vertical";
}

/**
 * Detect branches whose immediate targets share or lack distinct role
 * assignments. When time mode is enabled, suppress errors where every pair
 * of target intervals is disjoint.
 */
export function computeBranchValidationErrors(
    nodes: Node[],
    edges: Edge[],
    timeContext: BranchTimeContext,
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

    const nodeMap = new Map(nodes.map((n) => [n.id, n]));

    const intervalFor = (n: Node): [number, number] => {
        const pos = n.position ?? { x: 0, y: 0 };
        const axis = timeContext.layout === "horizontal" ? pos.x : pos.y;
        const start = (axis / timeContext.pixelsPerHour) * 60;
        const duration = ((n.data as any)?.duration_min as number) ?? 30;
        return [start, start + duration];
    };

    const intervalsPairwiseDisjoint = (targets: Node[]): boolean => {
        const ints = targets.map(intervalFor);
        for (let i = 0; i < ints.length; i++) {
            for (let j = i + 1; j < ints.length; j++) {
                const a = ints[i], b = ints[j];
                if (!(a[1] <= b[0] || b[1] <= a[0])) return false;
            }
        }
        return true;
    };

    for (const [sourceId, targetIds] of outgoingMap) {
        if (targetIds.length < 2) continue;
        const src = nodeMap.get(sourceId);
        if (!src || src.type !== "unitOp") continue;

        const targets: Node[] = [];
        for (const tid of targetIds) {
            const t = nodeMap.get(tid);
            if (t && t.type === "unitOp") targets.push(t);
        }
        if (targets.length < 2) continue;

        const parentIds = targets.map((t) => t.parentId ?? null);
        const hasDuplicate = new Set(parentIds).size !== parentIds.length;
        const hasNull = parentIds.some((p) => p === null);
        if (!hasDuplicate && !hasNull) continue;

        if (timeContext.timeEnabled && intervalsPairwiseDisjoint(targets)) continue;

        // Determine duplicateLane for the message: the parentId shared by 2+
        // targets, or null if the conflict is "any null parentId".
        const counts = new Map<string | null, number>();
        for (const p of parentIds) counts.set(p, (counts.get(p) ?? 0) + 1);
        let duplicateLane: string | null = null;
        for (const [p, c] of counts) {
            if (c >= 2) { duplicateLane = p; break; }
        }
        // If only conflict is null parentId(s), duplicateLane stays null already.

        errors.push({
            sourceNodeId: sourceId,
            sourceNodeLabel: ((src.data as any).label || "Unnamed") as string,
            duplicateLane,
            targetNodeLabels: targets.map(
                (t) => ((t.data as any)?.label || "Unnamed") as string,
            ),
        });
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

/**
 * Block GLP approval submission until the protocol has at least one
 * Process Start node connected to at least one unit op, and no branch
 * or process-start validation errors. Returns null when ready, else a
 * short reason suitable for a toast / disabled-button tooltip.
 */
export function computeGlpApprovalBlockReason(
    nodes: Node[],
    edges: Edge[],
    timeContext: BranchTimeContext,
): string | null {
    const unitOps = nodes.filter((n) => n.type === "unitOp");
    if (unitOps.length === 0) {
        return "Add a Process Start and at least one unit operation before submitting for approval.";
    }
    const processStarts = nodes.filter((n) => n.type === "processStart");
    if (processStarts.length === 0) {
        return "Add a Process Start node and connect it to a unit operation before submitting for approval.";
    }

    // Ensure at least one Process Start shares a connected component with a unit op.
    const psIds = new Set(processStarts.map((n) => n.id));
    const opIds = new Set(unitOps.map((n) => n.id));
    const adj = new Map<string, Set<string>>();
    for (const n of nodes) adj.set(n.id, new Set());
    for (const e of edges) {
        adj.get(e.source)?.add(e.target);
        adj.get(e.target)?.add(e.source);
    }
    let connected = false;
    for (const startId of psIds) {
        const visited = new Set<string>();
        const queue = [startId];
        while (queue.length) {
            const curr = queue.shift()!;
            if (visited.has(curr)) continue;
            visited.add(curr);
            if (opIds.has(curr)) { connected = true; break; }
            for (const nb of adj.get(curr) ?? []) {
                if (!visited.has(nb)) queue.push(nb);
            }
        }
        if (connected) break;
    }
    if (!connected) {
        return "Connect the Process Start node to at least one unit operation before submitting for approval.";
    }

    const branchErrs = computeBranchValidationErrors(nodes, edges, timeContext);
    if (branchErrs.length > 0) {
        return `Resolve ${branchErrs.length} branching ${branchErrs.length === 1 ? "warning" : "warnings"} before submitting for approval.`;
    }
    const psErrs = computeProcessStartValidationErrors(nodes, edges);
    if (psErrs.length > 0) {
        return `Resolve ${psErrs.length} Process Start ${psErrs.length === 1 ? "warning" : "warnings"} before submitting for approval.`;
    }
    return null;
}
