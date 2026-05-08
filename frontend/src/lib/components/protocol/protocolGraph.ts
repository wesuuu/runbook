import type { Node, Edge } from "@xyflow/svelte";

export interface GraphState {
    nodes: Node[];
    edges: Edge[];
    layout: "horizontal" | "vertical";
    handleOrientation: "horizontal" | "vertical";
    timeEnabled: boolean;
    pixelsPerHour: number;
}

/**
 * Parse a graph payload from the API into typed state fields.
 * Used for loading, reverting, and previewing versions.
 */
export function parseGraphState(graph: any): GraphState {
    return {
        nodes: graph?.nodes || [],
        edges: graph?.edges || [],
        layout: (graph?.layout || "horizontal") as "horizontal" | "vertical",
        handleOrientation: (graph?.handleOrientation || "vertical") as "horizontal" | "vertical",
        timeEnabled: graph?.timeEnabled || false,
        pixelsPerHour: graph?.pixelsPerHour || 200,
    };
}

/**
 * Serialize current nodes/edges/layout state into a graph payload for the API.
 */
export function serializeGraphData(
    nodes: Node[],
    edges: Edge[],
    layout: string,
    handleOrientation: string,
    timeEnabled: boolean,
    pixelsPerHour: number,
) {
    return {
        nodes: nodes.map((n) => ({
            id: n.id,
            type: n.type,
            position: n.position,
            parentId: n.parentId,
            zIndex: n.zIndex,
            data: n.data,
            width: n.width ?? n.measured?.width,
            height: n.height ?? n.measured?.height,
            style: n.style,
        })),
        edges: edges.map((e) => ({
            id: e.id,
            source: e.source,
            target: e.target,
        })),
        layout,
        handleOrientation,
        timeEnabled,
        pixelsPerHour,
    };
}

/**
 * Build a JSON snapshot string for change tracking.
 */
export function buildStateSnapshot(
    nodes: Node[],
    edges: Edge[],
    layout: string,
    handleOrientation: string,
    timeEnabled: boolean,
    pixelsPerHour: number,
): string {
    return JSON.stringify({
        nodes,
        edges,
        layout,
        handleOrientation,
        timeEnabled,
        pixelsPerHour,
    });
}

/**
 * Apply timeline sizing to nodes based on their duration_min.
 */
export function applyTimelineSizing(
    nodes: Node[],
    layout: "horizontal" | "vertical",
    pixelsPerHour: number,
): Node[] {
    return nodes.map((n) => {
        if (n.type !== "unitOp") return n;
        const dur = (n.data.duration_min as number) || 30;
        const sizePx = (dur / 60) * pixelsPerHour;
        return {
            ...n,
            width: layout === "horizontal" ? sizePx : n.width,
            height: layout === "vertical" ? sizePx : n.height,
        };
    });
}

/**
 * Clear timeline sizing constraints from nodes.
 */
export function clearTimelineSizing(nodes: Node[]): Node[] {
    return nodes.map((n) => {
        if (n.type !== "unitOp") return n;
        return { ...n, width: undefined, height: undefined };
    });
}

/**
 * Detect equipment conflicts between concurrent (non-sequenced) nodes.
 * Returns a Map of nodeId -> conflicting equipment IDs.
 */
export function detectEquipmentConflicts(
    nodes: Node[],
    edges: Edge[],
): Map<string, string[]> {
    const adjacency = new Map<string, Set<string>>();
    for (const e of edges) {
        if (!adjacency.has(e.source)) adjacency.set(e.source, new Set());
        adjacency.get(e.source)!.add(e.target);
    }

    function reachable(start: string): Set<string> {
        const visited = new Set<string>();
        const queue = [start];
        while (queue.length) {
            const cur = queue.shift()!;
            for (const next of adjacency.get(cur) ?? []) {
                if (!visited.has(next)) {
                    visited.add(next);
                    queue.push(next);
                }
            }
        }
        return visited;
    }

    const unitOpNodes = nodes.filter((n) => n.type === "unitOp");
    const conflicts = new Map<string, string[]>();

    for (let i = 0; i < unitOpNodes.length; i++) {
        for (let j = i + 1; j < unitOpNodes.length; j++) {
            const a = unitOpNodes[i];
            const b = unitOpNodes[j];
            const aReach = reachable(a.id);
            const bReach = reachable(b.id);
            const concurrent = !aReach.has(b.id) && !bReach.has(a.id);
            if (!concurrent) continue;

            const aEq = (a.data?.equipment as any[]) ?? [];
            const bEq = (b.data?.equipment as any[]) ?? [];
            for (const ae of aEq) {
                if (ae.shareable) continue;
                const match = bEq.find(
                    (be: any) =>
                        be.equipment_id === ae.equipment_id && !be.shareable,
                );
                if (match) {
                    if (!conflicts.has(a.id)) conflicts.set(a.id, []);
                    if (!conflicts.has(b.id)) conflicts.set(b.id, []);
                    conflicts.get(a.id)!.push(ae.equipment_id);
                    conflicts.get(b.id)!.push(ae.equipment_id);
                }
            }
        }
    }
    return conflicts;
}

/**
 * Find the swimlane node that contains a given position, if any.
 * Returns the parent node ID and adjusted position relative to the parent.
 */
export function findSwimLaneParent(
    nodes: Node[],
    position: { x: number; y: number },
): { parentId: string | undefined; adjustedPosition: { x: number; y: number } } {
    for (const n of nodes) {
        if (n.type === "swimLane") {
            const laneX = n.position.x;
            const laneY = n.position.y;
            const laneW = (n.measured?.width || n.width || 600) as number;
            const laneH = (n.measured?.height || n.height || 200) as number;
            if (
                position.x >= laneX &&
                position.x <= laneX + laneW &&
                position.y >= laneY &&
                position.y <= laneY + laneH
            ) {
                return {
                    parentId: n.id,
                    adjustedPosition: {
                        x: position.x - laneX,
                        y: position.y - laneY,
                    },
                };
            }
        }
    }
    return { parentId: undefined, adjustedPosition: position };
}

/**
 * Move a node to a new absolute position. If the new position falls inside a
 * swimlane, set parentId to that lane and adjust the node's position to be
 * relative to the lane. Otherwise clear parentId and use the absolute position.
 *
 * Caller must pass the absolute position (not the SvelteFlow node-relative
 * position). Convert by adding the current parent's position before calling.
 */
export function reparentNode(
    nodes: Node[],
    nodeId: string,
    absolutePosition: { x: number; y: number },
): Node[] {
    const idx = nodes.findIndex((n) => n.id === nodeId);
    if (idx < 0) return nodes;
    const { parentId, adjustedPosition } = findSwimLaneParent(nodes, absolutePosition);
    return nodes.map((n, i) =>
        i === idx
            ? { ...n, parentId, position: adjustedPosition }
            : n,
    );
}
