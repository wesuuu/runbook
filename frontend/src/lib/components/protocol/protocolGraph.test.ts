import { describe, it, expect } from "vitest";
import type { Node } from "@xyflow/svelte";
import { reparentNode } from "./protocolGraph";

function lane(id: string, x: number, y: number, w: number, h: number): Node {
    return {
        id,
        type: "swimLane",
        position: { x, y },
        measured: { width: w, height: h },
        data: { label: id },
    } as unknown as Node;
}

function step(id: string, parentId: string | undefined, position: { x: number; y: number }): Node {
    return {
        id,
        type: "unitOp",
        parentId,
        position,
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
});
