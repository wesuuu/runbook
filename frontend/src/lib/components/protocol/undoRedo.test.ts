import { describe, it, expect } from "vitest";
import {
    createUndoRedoState,
    pushSnapshot,
    undo,
    redo,
    canUndo,
    canRedo,
    buildGraphSnapshot,
    MAX_STACK_DEPTH,
} from "./undoRedo";

describe("undoRedo", () => {
    const snap = (label: string) => JSON.stringify({ nodes: [{ id: label }], edges: [] });

    describe("createUndoRedoState", () => {
        it("returns empty stacks", () => {
            const state = createUndoRedoState();
            expect(state.undoStack).toEqual([]);
            expect(state.redoStack).toEqual([]);
        });
    });

    describe("buildGraphSnapshot", () => {
        it("serializes nodes and edges to JSON", () => {
            const nodes = [{ id: "n1", position: { x: 0, y: 0 }, data: {} }] as any;
            const edges = [{ id: "e1", source: "n1", target: "n2" }] as any;
            const result = buildGraphSnapshot(nodes, edges);
            const parsed = JSON.parse(result);
            expect(parsed.nodes).toHaveLength(1);
            expect(parsed.edges).toHaveLength(1);
            expect(parsed.nodes[0].id).toBe("n1");
        });
    });

    describe("pushSnapshot", () => {
        it("adds snapshot to undo stack", () => {
            let state = createUndoRedoState();
            state = pushSnapshot(state, snap("a"));
            expect(state.undoStack).toHaveLength(1);
            expect(state.redoStack).toHaveLength(0);
        });

        it("clears redo stack on new action", () => {
            let state = createUndoRedoState();
            state = pushSnapshot(state, snap("a"));
            state = pushSnapshot(state, snap("b"));
            // Undo to get something on redo stack
            const result = undo(state, snap("c"));
            expect(result).not.toBeNull();
            state = result!.state;
            expect(state.redoStack).toHaveLength(1);
            // Push new action — redo should be cleared
            state = pushSnapshot(state, snap("d"));
            expect(state.redoStack).toHaveLength(0);
        });

        it("enforces MAX_STACK_DEPTH", () => {
            let state = createUndoRedoState();
            for (let i = 0; i < MAX_STACK_DEPTH + 10; i++) {
                state = pushSnapshot(state, snap(`item-${i}`));
            }
            expect(state.undoStack).toHaveLength(MAX_STACK_DEPTH);
            // Oldest items should have been dropped
            const oldest = JSON.parse(state.undoStack[0]);
            expect(oldest.nodes[0].id).toBe("item-10");
        });
    });

    describe("undo", () => {
        it("returns null when undo stack is empty", () => {
            const state = createUndoRedoState();
            expect(undo(state, snap("current"))).toBeNull();
        });

        it("pops from undo and pushes current to redo", () => {
            let state = createUndoRedoState();
            state = pushSnapshot(state, snap("before"));
            const result = undo(state, snap("current"));
            expect(result).not.toBeNull();
            expect(result!.state.undoStack).toHaveLength(0);
            expect(result!.state.redoStack).toHaveLength(1);
            // The snapshot returned is the "before" state
            const restored = JSON.parse(result!.snapshot);
            expect(restored.nodes[0].id).toBe("before");
            // The redo stack contains the "current" state
            const redoSnap = JSON.parse(result!.state.redoStack[0]);
            expect(redoSnap.nodes[0].id).toBe("current");
        });

        it("supports multiple undos", () => {
            let state = createUndoRedoState();
            state = pushSnapshot(state, snap("a"));
            state = pushSnapshot(state, snap("b"));
            state = pushSnapshot(state, snap("c"));

            // Undo from state "d" (current)
            let result = undo(state, snap("d"));
            expect(result).not.toBeNull();
            state = result!.state;
            expect(JSON.parse(result!.snapshot).nodes[0].id).toBe("c");

            result = undo(state, snap("c"));
            expect(result).not.toBeNull();
            state = result!.state;
            expect(JSON.parse(result!.snapshot).nodes[0].id).toBe("b");

            result = undo(state, snap("b"));
            expect(result).not.toBeNull();
            state = result!.state;
            expect(JSON.parse(result!.snapshot).nodes[0].id).toBe("a");

            // No more undos
            expect(undo(state, snap("a"))).toBeNull();
        });
    });

    describe("redo", () => {
        it("returns null when redo stack is empty", () => {
            const state = createUndoRedoState();
            expect(redo(state, snap("current"))).toBeNull();
        });

        it("pops from redo and pushes current to undo", () => {
            let state = createUndoRedoState();
            state = pushSnapshot(state, snap("before"));
            // Undo
            let result = undo(state, snap("current"));
            state = result!.state;
            // Now redo
            result = redo(state, snap("before"));
            expect(result).not.toBeNull();
            expect(result!.state.redoStack).toHaveLength(0);
            expect(result!.state.undoStack).toHaveLength(1);
            const restored = JSON.parse(result!.snapshot);
            expect(restored.nodes[0].id).toBe("current");
        });
    });

    describe("undo/redo round-trip", () => {
        it("undo then redo restores original state", () => {
            let state = createUndoRedoState();
            state = pushSnapshot(state, snap("initial"));
            const currentSnap = snap("modified");

            // Undo
            let result = undo(state, currentSnap);
            state = result!.state;
            const afterUndo = result!.snapshot;

            // Redo
            result = redo(state, afterUndo);
            state = result!.state;
            const afterRedo = result!.snapshot;

            // Should restore the "modified" state
            expect(JSON.parse(afterRedo).nodes[0].id).toBe("modified");
        });

        it("new action after undo clears redo stack", () => {
            let state = createUndoRedoState();
            state = pushSnapshot(state, snap("a"));
            state = pushSnapshot(state, snap("b"));

            // Undo
            const result = undo(state, snap("c"));
            state = result!.state;
            expect(canRedo(state)).toBe(true);

            // New action
            state = pushSnapshot(state, snap("d"));
            expect(canRedo(state)).toBe(false);
        });
    });

    describe("canUndo / canRedo", () => {
        it("reports correctly for empty state", () => {
            const state = createUndoRedoState();
            expect(canUndo(state)).toBe(false);
            expect(canRedo(state)).toBe(false);
        });

        it("canUndo is true after push", () => {
            let state = createUndoRedoState();
            state = pushSnapshot(state, snap("a"));
            expect(canUndo(state)).toBe(true);
            expect(canRedo(state)).toBe(false);
        });

        it("canRedo is true after undo", () => {
            let state = createUndoRedoState();
            state = pushSnapshot(state, snap("a"));
            const result = undo(state, snap("b"));
            state = result!.state;
            expect(canUndo(state)).toBe(false);
            expect(canRedo(state)).toBe(true);
        });
    });

    describe("batch operations", () => {
        it("single pushSnapshot before batch delete is one undo entry", () => {
            let state = createUndoRedoState();
            // Simulate: user has 3 nodes, selects 2, deletes them
            const beforeDelete = snap("3-nodes");
            state = pushSnapshot(state, beforeDelete);
            // After the batch delete, current state has 1 node
            const afterDelete = snap("1-node");

            // One undo should restore all 3 nodes
            const result = undo(state, afterDelete);
            expect(result).not.toBeNull();
            expect(JSON.parse(result!.snapshot).nodes[0].id).toBe("3-nodes");
            expect(result!.state.undoStack).toHaveLength(0);
        });
    });
});
