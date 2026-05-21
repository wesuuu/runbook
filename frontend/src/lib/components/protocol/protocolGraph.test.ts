import { describe, it, expect } from "vitest";
import type { Edge, Node } from "@xyflow/svelte";
import {
    adoptOrphanUnitOpsToLanes,
    applyDragStopReparenting,
    buildStateSnapshot,
    findSwimLaneParent,
    parseGraphState,
    reparentNode,
    sortNodesForParenting,
    topologicalSortNodes,
} from "./protocolGraph";

function lane(id: string, x: number, y: number, w: number, h: number): Node {
    return {
        id,
        type: "swimLane",
        position: { x, y },
        measured: { width: w, height: h },
        data: { label: id },
    } as unknown as Node;
}

function step(
    id: string,
    parentId: string | undefined,
    position: { x: number; y: number },
    size: { w: number; h: number } = { w: 100, h: 60 },
): Node {
    return {
        id,
        type: "unitOp",
        parentId,
        position,
        measured: { width: size.w, height: size.h },
        data: { label: id },
    } as unknown as Node;
}

describe("reparentNode", () => {
    it("moves a node into a new swimlane and adjusts position relative to it", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            lane("lane-B", 0, 300, 600, 200),
            step("n1", "lane-A", { x: 50, y: 50 }),
        ];
        const updated = reparentNode(nodes, "n1", { x: 200, y: 350 });
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-B");
        expect(n1.position).toEqual({ x: 200, y: 50 });
    });

    it("clears parentId when dragged outside all swimlanes", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            step("n1", "lane-A", { x: 50, y: 50 }),
        ];
        const updated = reparentNode(nodes, "n1", { x: 800, y: 800 });
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBeUndefined();
        expect(n1.position).toEqual({ x: 800, y: 800 });
    });

    it("keeps parentId when dropped inside the same lane", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            step("n1", "lane-A", { x: 50, y: 50 }),
        ];
        const updated = reparentNode(nodes, "n1", { x: 100, y: 100 });
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-A");
    });

    it("returns nodes unchanged when nodeId not found", () => {
        const nodes = [lane("lane-A", 0, 0, 600, 200)];
        const updated = reparentNode(nodes, "missing", { x: 50, y: 50 });
        expect(updated).toBe(nodes);
    });

    it("uses node center, not top-left, for lane containment", () => {
        // Lane B starts at y=300. Drop a 100x60 step at top-left (200,270):
        // top-left is above the lane (270 < 300), but center is at (250, 300)
        // which sits on lane-B's edge. Center-based check should adopt to lane-B.
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            lane("lane-B", 0, 300, 600, 200),
            step("n1", "lane-A", { x: 0, y: 0 }, { w: 100, h: 60 }),
        ];
        const updated = reparentNode(
            nodes,
            "n1",
            { x: 200, y: 280 },
            { w: 100, h: 60 },
        );
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-B");
        // Top-left position relative to lane-B (0, 300) → (200, -20)
        expect(n1.position).toEqual({ x: 200, y: -20 });
    });
});

describe("adoptOrphanUnitOpsToLanes", () => {
    it("adopts orphan steps that fall inside a lane and adjusts their position", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            lane("lane-B", 0, 300, 600, 200),
            step("n1", undefined, { x: 100, y: 50 }),
            step("n2", undefined, { x: 100, y: 350 }),
            step("n3", undefined, { x: 800, y: 800 }),
        ];
        const updated = adoptOrphanUnitOpsToLanes(nodes);
        const n1 = updated.find((n) => n.id === "n1")!;
        const n2 = updated.find((n) => n.id === "n2")!;
        const n3 = updated.find((n) => n.id === "n3")!;
        expect(n1.parentId).toBe("lane-A");
        expect(n1.position).toEqual({ x: 100, y: 50 });
        expect(n2.parentId).toBe("lane-B");
        // Absolute (100,350) → relative to lane-B (0,300) → (100,50)
        expect(n2.position).toEqual({ x: 100, y: 50 });
        expect(n3.parentId).toBeUndefined();
    });

    it("does not touch steps that already have a parent", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            lane("lane-B", 0, 300, 600, 200),
            // already in lane-A; absolute pos would land inside lane-B but that
            // must not trigger a re-parent — the user assigned it deliberately.
            step("n1", "lane-A", { x: 100, y: 350 }),
        ];
        const updated = adoptOrphanUnitOpsToLanes(nodes);
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-A");
        expect(n1.position).toEqual({ x: 100, y: 350 });
    });

    it("returns the same array reference when nothing needs to change", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            step("n1", undefined, { x: 800, y: 800 }),
        ];
        const updated = adoptOrphanUnitOpsToLanes(nodes);
        expect(updated).toBe(nodes);
    });
});

describe("sortNodesForParenting", () => {
    it("hoists swimlanes to the front when a child appears before a lane", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            step("n1", "lane-A", { x: 50, y: 50 }),
            lane("lane-B", 0, 300, 600, 200),
        ];
        const sorted = sortNodesForParenting(nodes);
        expect(sorted.map((n) => n.id)).toEqual(["lane-A", "lane-B", "n1"]);
    });

    it("returns the same reference when lanes already lead", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            lane("lane-B", 0, 300, 600, 200),
            step("n1", "lane-A", { x: 50, y: 50 }),
        ];
        const sorted = sortNodesForParenting(nodes);
        expect(sorted).toBe(nodes);
    });

    it("after reparenting, lanes still lead the array", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            step("n1", undefined, { x: 100, y: 100 }, { w: 100, h: 60 }),
            lane("lane-B", 0, 300, 600, 200),
        ];
        const updated = reparentNode(
            nodes,
            "n1",
            { x: 100, y: 320 },
            { w: 100, h: 60 },
        );
        expect(updated[0].type).toBe("swimLane");
        expect(updated[1].type).toBe("swimLane");
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-B");
    });
});

describe("parseGraphState", () => {
    // Regression guard: saved protocols sometimes have lanes after their
    // children in the nodes array (e.g. when a lane was added after the
    // steps it parents). xyflow drops the parentId silently in that case
    // unless we sort lanes to the front on load. parseGraphState MUST run
    // sortNodesForParenting on the incoming payload — every loaded protocol
    // depends on this for parent-child rendering to work.
    it("hoists swimlanes to the front of nodes on load", () => {
        const payload = {
            nodes: [
                { id: "n1", type: "unitOp", parentId: "lane-A", position: { x: 50, y: 50 }, data: {} },
                { id: "lane-A", type: "swimLane", position: { x: 0, y: 0 }, data: {} },
                { id: "n2", type: "unitOp", parentId: "lane-B", position: { x: 50, y: 50 }, data: {} },
                { id: "lane-B", type: "swimLane", position: { x: 0, y: 300 }, data: {} },
            ],
            edges: [],
        };
        const state = parseGraphState(payload);
        expect(state.nodes[0].type).toBe("swimLane");
        expect(state.nodes[1].type).toBe("swimLane");
        expect(state.nodes.map((n) => n.id)).toEqual([
            "lane-A",
            "lane-B",
            "n1",
            "n2",
        ]);
    });

    it("preserves lane order when payload is already correctly sorted", () => {
        const payload = {
            nodes: [
                { id: "lane-A", type: "swimLane", position: { x: 0, y: 0 }, data: {} },
                { id: "lane-B", type: "swimLane", position: { x: 0, y: 300 }, data: {} },
                { id: "n1", type: "unitOp", parentId: "lane-A", position: { x: 50, y: 50 }, data: {} },
            ],
            edges: [],
        };
        const state = parseGraphState(payload);
        expect(state.nodes.map((n) => n.id)).toEqual(["lane-A", "lane-B", "n1"]);
    });

    it("tolerates missing/empty graph payload", () => {
        const state = parseGraphState({});
        expect(state.nodes).toEqual([]);
        expect(state.edges).toEqual([]);
        expect(state.layout).toBe("horizontal");
    });
});

describe("adoptOrphanUnitOpsToLanes — sort-on-output", () => {
    // Regression guard: adopting an orphan into a lane sets parentId, so the
    // returned array must satisfy xyflow's parent-before-child invariant or
    // the new parentage is silently dropped.
    it("returns lanes-first ordering after adopting an orphan", () => {
        const nodes = [
            step("n1", undefined, { x: 100, y: 50 }, { w: 100, h: 60 }),
            lane("lane-A", 0, 0, 600, 200),
        ];
        const updated = adoptOrphanUnitOpsToLanes(nodes);
        expect(updated[0].type).toBe("swimLane");
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-A");
    });
});

describe("findSwimLaneParent", () => {
    // Center-vs-top-left contract: callers pass the dragged node's CENTER as
    // `probe` (so the lane "claims" the node when most of it is over the lane)
    // and the TOP-LEFT as `topLeft` (so the parent-relative position math
    // stays correct). reparentNode and adoptOrphanUnitOpsToLanes both rely on
    // this distinction; if findSwimLaneParent ever conflates the two, drag
    // adoption breaks at lane edges.
    it("uses probe (not topLeft) for containment", () => {
        const nodes = [lane("lane-A", 0, 0, 600, 200)];
        // topLeft is outside the lane (y=-30) but probe (center) is inside.
        const result = findSwimLaneParent(
            nodes,
            { x: 100, y: 30 },
            { x: 100, y: -30 },
        );
        expect(result.parentId).toBe("lane-A");
    });

    it("uses topLeft (not probe) for the adjusted position", () => {
        const nodes = [lane("lane-A", 0, 100, 600, 200)];
        const result = findSwimLaneParent(
            nodes,
            { x: 100, y: 200 },
            { x: 100, y: 170 },
        );
        // Adjusted position is topLeft minus lane origin: (100, 170) - (0, 100).
        expect(result.parentId).toBe("lane-A");
        expect(result.adjustedPosition).toEqual({ x: 100, y: 70 });
    });

    it("falls back to probe when topLeft is omitted", () => {
        const nodes = [lane("lane-A", 0, 100, 600, 200)];
        const result = findSwimLaneParent(nodes, { x: 100, y: 200 });
        expect(result.parentId).toBe("lane-A");
        expect(result.adjustedPosition).toEqual({ x: 100, y: 100 });
    });

    it("returns no parent when probe is outside every lane", () => {
        const nodes = [lane("lane-A", 0, 0, 600, 200)];
        const result = findSwimLaneParent(nodes, { x: 800, y: 800 });
        expect(result.parentId).toBeUndefined();
        expect(result.adjustedPosition).toEqual({ x: 800, y: 800 });
    });
});

describe("applyDragStopReparenting", () => {
    // The xyflow drag-stop callback hands us a `targetNode` snapshot that
    // can be stale (its position/parentId reflects pre-drag state for some
    // operations). The handler MUST look the node up by id in the live
    // `nodes` array — using the snapshot caused the "regrab teleports to
    // top-left" bug. This helper encodes the lookup so the contract is
    // testable.
    it("reads the live position from nodes, not from a stale snapshot", () => {
        // The "live" nodes have n1 inside lane-B at position (10, 10). A
        // refactor that read position from a passed-in snapshot would be
        // tempted to use whatever the caller passes; this test pins the
        // helper to the array.
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            lane("lane-B", 0, 300, 600, 200),
            step("n1", "lane-B", { x: 10, y: 10 }, { w: 100, h: 60 }),
        ];
        const updated = applyDragStopReparenting(nodes, "n1");
        const n1 = updated.find((n) => n.id === "n1")!;
        // Absolute is (10, 310) → still inside lane-B → parent stays.
        expect(n1.parentId).toBe("lane-B");
        expect(n1.position).toEqual({ x: 10, y: 10 });
    });

    it("reparents a unitOp when its absolute position falls into a different lane", () => {
        const nodes = [
            lane("lane-A", 0, 0, 600, 200),
            lane("lane-B", 0, 300, 600, 200),
            // Live position is parent-relative (50, 350) inside lane-A,
            // which puts the absolute center down inside lane-B.
            step("n1", "lane-A", { x: 50, y: 350 }, { w: 100, h: 60 }),
        ];
        const updated = applyDragStopReparenting(nodes, "n1");
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-B");
        // Absolute (50, 350) → relative to lane-B (0, 300) → (50, 50).
        expect(n1.position).toEqual({ x: 50, y: 50 });
    });

    it("triggers orphan adoption when a swimlane is the dragged node", () => {
        // Drop a lane on top of an orphan step — the step should be adopted.
        const nodes = [
            step("n1", undefined, { x: 100, y: 50 }, { w: 100, h: 60 }),
            lane("lane-A", 0, 0, 600, 200),
        ];
        const updated = applyDragStopReparenting(nodes, "lane-A");
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-A");
    });

    it("returns the same array when the node id isn't found", () => {
        const nodes = [lane("lane-A", 0, 0, 600, 200)];
        expect(applyDragStopReparenting(nodes, "missing")).toBe(nodes);
    });

    it("ignores nodes that are neither swimLane, unitOp, nor processStart", () => {
        const other = {
            id: "other",
            type: "annotation",
            position: { x: 100, y: 100 },
            data: {},
        } as unknown as Node;
        const nodes = [lane("lane-A", 0, 0, 600, 200), other];
        expect(applyDragStopReparenting(nodes, "other")).toBe(nodes);
    });

    it("falls back to a default size when the live node has no measured/declared dimensions", () => {
        // A freshly-dropped step may not have measured set yet. The helper
        // should still pick a center for containment rather than treating
        // the node as a 0×0 point (which would make lane edges flaky).
        const stepNoSize = {
            id: "n1",
            type: "unitOp",
            parentId: undefined,
            position: { x: 100, y: 100 },
            data: {},
        } as unknown as Node;
        const nodes = [lane("lane-A", 0, 0, 600, 200), stepNoSize];
        const updated = applyDragStopReparenting(nodes, "n1");
        const n1 = updated.find((n) => n.id === "n1")!;
        expect(n1.parentId).toBe("lane-A");
    });
});

describe("buildStateSnapshot", () => {
    function unitOp(id: string, selected: boolean): Node {
        return {
            id,
            type: "unitOp",
            position: { x: 10, y: 20 },
            data: { label: id, params: {} },
            // Transient SvelteFlow UI fields that change on selection / drag.
            selected,
            dragging: selected,
            measured: { width: 120, height: 60 },
        } as unknown as Node;
    }

    it("ignores transient UI fields so selecting a node is not a change", () => {
        const unselected = [unitOp("n1", false)];
        const selected = [unitOp("n1", true)];
        const a = buildStateSnapshot(unselected, [], "horizontal", "vertical", false, 200);
        const b = buildStateSnapshot(selected, [], "horizontal", "vertical", false, 200);
        expect(a).toBe(b);
    });

    it("still reflects a real edit (node moved)", () => {
        const before = [unitOp("n1", false)];
        const moved = [
            { ...unitOp("n1", false), position: { x: 999, y: 20 } } as Node,
        ];
        const a = buildStateSnapshot(before, [], "horizontal", "vertical", false, 200);
        const b = buildStateSnapshot(moved, [], "horizontal", "vertical", false, 200);
        expect(a).not.toBe(b);
    });

    it("reflects a glpSettings change", () => {
        const nodes = [unitOp("n1", false)];
        const a = buildStateSnapshot(nodes, [], "horizontal", "vertical", false, 200, {
            requireOperator: false,
        });
        const b = buildStateSnapshot(nodes, [], "horizontal", "vertical", false, 200, {
            requireOperator: true,
        });
        expect(a).not.toBe(b);
    });
});

describe("topologicalSortNodes", () => {
    function node(id: string, x: number, y = 0): Node {
        return {
            id,
            type: "unitOp",
            position: { x, y },
            data: { label: id },
        } as unknown as Node;
    }
    function edge(source: string, target: string): Edge {
        return { id: `${source}-${target}`, source, target } as Edge;
    }

    it("orders nodes by edge direction, not canvas position (#19)", () => {
        // Canvas x-positions run backwards relative to the edge chain.
        const nodes = [node("a", 300), node("b", 200), node("c", 100)];
        const edges = [edge("a", "b"), edge("b", "c")];
        const sorted = topologicalSortNodes(nodes, edges).map((n) => n.id);
        expect(sorted).toEqual(["a", "b", "c"]);
    });

    it("is stable when nodes are nudged but edges are unchanged (#19)", () => {
        const edges = [edge("a", "b"), edge("b", "c")];
        const order1 = topologicalSortNodes(
            [node("a", 0), node("b", 100), node("c", 200)],
            edges,
        ).map((n) => n.id);
        const order2 = topologicalSortNodes(
            [node("a", 999), node("b", 5), node("c", 42)],
            edges,
        ).map((n) => n.id);
        expect(order1).toEqual(order2);
    });

    it("falls back to position order when there are no edges", () => {
        const nodes = [node("c", 300), node("a", 100), node("b", 200)];
        const sorted = topologicalSortNodes(nodes, []).map((n) => n.id);
        expect(sorted).toEqual(["a", "b", "c"]);
    });

    it("breaks ties between ready nodes by position", () => {
        // Two independent chains; left chain should interleave first.
        const nodes = [
            node("a", 0),
            node("b", 100),
            node("x", 50),
            node("y", 150),
        ];
        const edges = [edge("a", "b"), edge("x", "y")];
        const sorted = topologicalSortNodes(nodes, edges).map((n) => n.id);
        expect(sorted).toEqual(["a", "x", "b", "y"]);
    });

    it("respects a join where a node has two upstream parents", () => {
        const nodes = [node("a", 0), node("b", 10), node("c", 100)];
        const edges = [edge("a", "c"), edge("b", "c")];
        const sorted = topologicalSortNodes(nodes, edges).map((n) => n.id);
        expect(sorted[2]).toBe("c");
        expect(sorted.slice(0, 2).sort()).toEqual(["a", "b"]);
    });

    it("appends cycle members in position order without looping forever", () => {
        const nodes = [node("a", 0), node("b", 100), node("c", 200)];
        const edges = [edge("a", "b"), edge("b", "c"), edge("c", "b")];
        const sorted = topologicalSortNodes(nodes, edges).map((n) => n.id);
        expect(sorted[0]).toBe("a");
        expect(sorted.slice(1).sort()).toEqual(["b", "c"]);
        expect(sorted).toHaveLength(3);
    });

    it("ignores edges that dangle to an unknown node", () => {
        const nodes = [node("a", 0), node("b", 100)];
        const edges = [edge("a", "b"), edge("b", "ghost")];
        const sorted = topologicalSortNodes(nodes, edges).map((n) => n.id);
        expect(sorted).toEqual(["a", "b"]);
    });
});
