import type { Node, Edge } from "@xyflow/svelte";

export const MAX_STACK_DEPTH = 50;

export interface UndoRedoState {
    undoStack: string[];
    redoStack: string[];
}

export function createUndoRedoState(): UndoRedoState {
    return { undoStack: [], redoStack: [] };
}

/**
 * Build a graph snapshot string from current nodes and edges.
 */
export function buildGraphSnapshot(nodes: Node[], edges: Edge[]): string {
    return JSON.stringify({ nodes, edges });
}

/**
 * Push a snapshot onto the undo stack, clearing the redo stack.
 * Enforces MAX_STACK_DEPTH.
 */
export function pushSnapshot(
    state: UndoRedoState,
    snapshot: string,
): UndoRedoState {
    const undoStack = [...state.undoStack, snapshot];
    if (undoStack.length > MAX_STACK_DEPTH) {
        undoStack.shift();
    }
    return { undoStack, redoStack: [] };
}

/**
 * Undo: pop from undo stack, push current state to redo stack.
 * Returns null if nothing to undo.
 */
export function undo(
    state: UndoRedoState,
    currentSnapshot: string,
): { state: UndoRedoState; snapshot: string } | null {
    if (state.undoStack.length === 0) return null;
    const snapshot = state.undoStack[state.undoStack.length - 1];
    return {
        state: {
            undoStack: state.undoStack.slice(0, -1),
            redoStack: [...state.redoStack, currentSnapshot],
        },
        snapshot,
    };
}

/**
 * Redo: pop from redo stack, push current state to undo stack.
 * Returns null if nothing to redo.
 */
export function redo(
    state: UndoRedoState,
    currentSnapshot: string,
): { state: UndoRedoState; snapshot: string } | null {
    if (state.redoStack.length === 0) return null;
    const snapshot = state.redoStack[state.redoStack.length - 1];
    return {
        state: {
            undoStack: [...state.undoStack, currentSnapshot],
            redoStack: state.redoStack.slice(0, -1),
        },
        snapshot,
    };
}

export function canUndo(state: UndoRedoState): boolean {
    return state.undoStack.length > 0;
}

export function canRedo(state: UndoRedoState): boolean {
    return state.redoStack.length > 0;
}
