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
        nodes: sortNodesForParenting(graph?.nodes || []),
        edges: graph?.edges || [],
        layout: (graph?.layout || "horizontal") as "horizontal" | "vertical",
        handleOrientation: (graph?.handleOrientation || "vertical") as "horizontal" | "vertical",
        timeEnabled: graph?.timeEnabled || false,
        pixelsPerHour: graph?.pixelsPerHour || 200,
    };
}

/**
 * Serialize current nodes/edges/layout state into a graph payload for the API.
 * `glpSettings` is an optional protocol-level extension (F-0087) and is
 * persisted under `graph.glpSettings` when provided.
 */
export function serializeGraphData(
    nodes: Node[],
    edges: Edge[],
    layout: string,
    handleOrientation: string,
    timeEnabled: boolean,
    pixelsPerHour: number,
    glpSettings?: Record<string, unknown>,
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
        ...(glpSettings !== undefined ? { glpSettings } : {}),
    };
}

/**
 * Build a JSON snapshot string for change tracking. Includes
 * `glpSettings` when provided so changes to protocol-level GLP config
 * mark the protocol dirty alongside graph edits.
 *
 * Snapshots the SAME normalized shape that `serializeGraphData` persists to
 * the API — not the raw SvelteFlow nodes. Raw nodes carry transient UI
 * fields (`selected`, `dragging`, `measured`) that mutate on mere selection;
 * including them here made simply clicking a node flag the protocol as
 * having unsaved changes (#9).
 */
export function buildStateSnapshot(
    nodes: Node[],
    edges: Edge[],
    layout: string,
    handleOrientation: string,
    timeEnabled: boolean,
    pixelsPerHour: number,
    glpSettings?: Record<string, unknown>,
): string {
    return JSON.stringify(
        serializeGraphData(
            nodes,
            edges,
            layout,
            handleOrientation,
            timeEnabled,
            pixelsPerHour,
            glpSettings,
        ),
    );
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
 * Order nodes by graph execution order: a topological sort that follows
 * edges (source → target). Nodes with no incoming edge come first; among
 * nodes that are ready at the same time, the one further left/up wins so
 * the result stays deterministic and matches the canvas reading order.
 *
 * A protocol's step sequence is defined by its edges, not by where the
 * boxes happen to sit on the canvas — sorting purely by `position.x`
 * reordered the run step list whenever a node was nudged (#19). When the
 * graph has no edges this degrades gracefully to the old position order.
 * Any nodes left over from a cycle are appended in position order.
 */
export function topologicalSortNodes(nodes: Node[], edges: Edge[]): Node[] {
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const inDegree = new Map<string, number>();
    const adjacency = new Map<string, string[]>();
    for (const n of nodes) {
        inDegree.set(n.id, 0);
        adjacency.set(n.id, []);
    }
    for (const e of edges) {
        // Ignore edges that dangle to a node not in this set.
        if (!nodeById.has(e.source) || !nodeById.has(e.target)) continue;
        adjacency.get(e.source)!.push(e.target);
        inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
    }

    const byPosition = (aId: string, bId: string): number => {
        const a = nodeById.get(aId)!;
        const b = nodeById.get(bId)!;
        const dx = (a.position?.x ?? 0) - (b.position?.x ?? 0);
        if (dx !== 0) return dx;
        const dy = (a.position?.y ?? 0) - (b.position?.y ?? 0);
        if (dy !== 0) return dy;
        return aId < bId ? -1 : aId > bId ? 1 : 0;
    };

    const ready = nodes
        .filter((n) => (inDegree.get(n.id) ?? 0) === 0)
        .map((n) => n.id)
        .sort(byPosition);
    const ordered: Node[] = [];
    const visited = new Set<string>();
    while (ready.length) {
        const id = ready.shift()!;
        if (visited.has(id)) continue;
        visited.add(id);
        ordered.push(nodeById.get(id)!);
        for (const target of adjacency.get(id) ?? []) {
            if (visited.has(target)) continue;
            const remaining = (inDegree.get(target) ?? 0) - 1;
            inDegree.set(target, remaining);
            if (remaining <= 0) ready.push(target);
        }
        ready.sort(byPosition);
    }

    if (ordered.length < nodes.length) {
        const leftover = nodes
            .filter((n) => !visited.has(n.id))
            .sort((a, b) => byPosition(a.id, b.id));
        ordered.push(...leftover);
    }
    return ordered;
}

/**
 * SvelteFlow requires parent nodes to appear before their children in the
 * nodes array — otherwise its `adoptUserNodes` pass logs
 * "Parent node X not found" and silently drops the parentId. Sort all
 * swimLane nodes to the front while preserving the relative order within
 * each group. Cheap to call after any structural change.
 */
export function sortNodesForParenting(nodes: Node[]): Node[] {
    let needsSort = false;
    let seenChild = false;
    for (const n of nodes) {
        if (n.type === "swimLane") {
            if (seenChild) {
                needsSort = true;
                break;
            }
        } else {
            seenChild = true;
        }
    }
    if (!needsSort) return nodes;
    const lanes: Node[] = [];
    const others: Node[] = [];
    for (const n of nodes) {
        if (n.type === "swimLane") lanes.push(n);
        else others.push(n);
    }
    return [...lanes, ...others];
}

function nodeSize(n: Node): { w: number; h: number } {
    return {
        w: (n.measured?.width || n.width || 0) as number,
        h: (n.measured?.height || n.height || 0) as number,
    };
}

/**
 * Find the swimlane node that contains a given probe point, if any.
 * Returns the parent node ID and adjusted top-left position relative to the
 * parent. The probe point is what's tested against lane bounds; the
 * topLeft argument is what the returned adjustedPosition is computed from.
 *
 * For drag/drop, callers should pass the dragged node's CENTER as `probe`
 * (so the lane "claims" the node when most of it is over the lane, matching
 * user intuition) and the node's TOP-LEFT corner as `topLeft` (so the
 * SvelteFlow-relative position stays correct).
 */
export function findSwimLaneParent(
    nodes: Node[],
    probe: { x: number; y: number },
    topLeft?: { x: number; y: number },
): { parentId: string | undefined; adjustedPosition: { x: number; y: number } } {
    const tl = topLeft ?? probe;
    for (const n of nodes) {
        if (n.type === "swimLane") {
            const laneX = n.position.x;
            const laneY = n.position.y;
            const laneW = (n.measured?.width || n.width || 600) as number;
            const laneH = (n.measured?.height || n.height || 200) as number;
            if (
                probe.x >= laneX &&
                probe.x <= laneX + laneW &&
                probe.y >= laneY &&
                probe.y <= laneY + laneH
            ) {
                return {
                    parentId: n.id,
                    adjustedPosition: {
                        x: tl.x - laneX,
                        y: tl.y - laneY,
                    },
                };
            }
        }
    }
    return { parentId: undefined, adjustedPosition: tl };
}

/**
 * Move a node to a new absolute top-left position. If the node's CENTER
 * falls inside a swimlane, set parentId to that lane and adjust the node's
 * top-left to be relative to the lane. Otherwise clear parentId and use the
 * absolute top-left.
 *
 * Caller must pass the absolute top-left (not the SvelteFlow node-relative
 * position). Convert by adding the current parent's position before calling.
 * Pass the node's measured size so containment uses the visual center.
 */
export function reparentNode(
    nodes: Node[],
    nodeId: string,
    absoluteTopLeft: { x: number; y: number },
    size?: { w: number; h: number },
): Node[] {
    const idx = nodes.findIndex((n) => n.id === nodeId);
    if (idx < 0) return nodes;
    const s = size ?? nodeSize(nodes[idx]);
    const center = {
        x: absoluteTopLeft.x + s.w / 2,
        y: absoluteTopLeft.y + s.h / 2,
    };
    const { parentId, adjustedPosition } = findSwimLaneParent(
        nodes,
        center,
        absoluteTopLeft,
    );
    const next = nodes.map((n, i) =>
        i === idx
            ? { ...n, parentId, position: adjustedPosition }
            : n,
    );
    return sortNodesForParenting(next);
}

const DEFAULT_DRAG_STOP_SIZE = { w: 180, h: 60 };

/**
 * React to a drag-stop on `nodeId`. Looks the node up in the live `nodes`
 * array (NOT a snapshot from the caller — xyflow's drag callback hands us a
 * node that can lag behind state for some operations, which used to teleport
 * regrabbed nodes to the top-left). Behavior:
 *
 * - swimLane → run an orphan adoption sweep (the lane may have moved over
 *   parent-less steps).
 * - unitOp / processStart → compute the absolute top-left from the
 *   parent-relative position, then reparent based on the visual center.
 * - anything else (or unknown id) → return the array unchanged.
 *
 * Falls back to a sensible default size when the live node hasn't been
 * measured yet, so freshly-dropped nodes still get a meaningful center.
 */
export function applyDragStopReparenting(
    nodes: Node[],
    nodeId: string,
): Node[] {
    const live = nodes.find((n) => n.id === nodeId);
    if (!live) return nodes;
    if (live.type === "swimLane") {
        return adoptOrphanUnitOpsToLanes(nodes);
    }
    if (live.type !== "unitOp" && live.type !== "processStart") return nodes;
    let absX = live.position.x;
    let absY = live.position.y;
    if (live.parentId) {
        const parent = nodes.find((n) => n.id === live.parentId);
        if (parent) {
            absX += parent.position.x;
            absY += parent.position.y;
        }
    }
    const measured = nodeSize(live);
    const size = {
        w: measured.w || DEFAULT_DRAG_STOP_SIZE.w,
        h: measured.h || DEFAULT_DRAG_STOP_SIZE.h,
    };
    return reparentNode(nodes, nodeId, { x: absX, y: absY }, size);
}

/**
 * Adopt orphan (parentId-less) unit-op / processStart nodes whose CENTER
 * falls inside any swimlane's bounds. Already-parented steps are left
 * untouched, so this is safe to call after a user explicitly drops a new
 * swimlane onto the canvas — orphans visible inside it become children, and
 * steps already assigned to other lanes don't get yanked around.
 */
export function adoptOrphanUnitOpsToLanes(nodes: Node[]): Node[] {
    let changed = false;
    const next = nodes.map((n) => {
        if (n.type !== "unitOp" && n.type !== "processStart") return n;
        if (n.parentId) return n;
        const s = nodeSize(n);
        const center = {
            x: n.position.x + s.w / 2,
            y: n.position.y + s.h / 2,
        };
        const { parentId, adjustedPosition } = findSwimLaneParent(
            nodes,
            center,
            n.position,
        );
        if (!parentId) return n;
        changed = true;
        return { ...n, parentId, position: adjustedPosition };
    });
    return sortNodesForParenting(changed ? next : nodes);
}
