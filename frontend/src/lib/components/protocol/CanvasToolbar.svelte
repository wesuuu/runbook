<script lang="ts">
    import { Position, type Node } from "@xyflow/svelte";

    interface Props {
        interactionMode: "pan" | "select";
        layout: "horizontal" | "vertical";
        handleOrientation: "horizontal" | "vertical";
        timeEnabled: boolean;
        versionNumber: number;
        previewingVersion: number | null;
        previewLoading: boolean;
        nodes: Node[];
        canUndoAction: boolean;
        canRedoAction: boolean;
        onUndo: () => void;
        onRedo: () => void;
        onInteractionModeChange: (mode: "pan" | "select") => void;
        onToggleLayout: () => void;
        onHandleOrientationChange: (orientation: "horizontal" | "vertical", nodes: Node[]) => void;
        onToggleTime: () => void;
        onToggleVersionHistory: () => void;
        onBrowseVersion: (dir: "prev" | "next") => void;
    }

    let {
        interactionMode,
        layout,
        handleOrientation,
        timeEnabled,
        versionNumber,
        previewingVersion,
        previewLoading,
        nodes,
        canUndoAction,
        canRedoAction,
        onUndo,
        onRedo,
        onInteractionModeChange,
        onToggleLayout,
        onHandleOrientationChange,
        onToggleTime,
        onToggleVersionHistory,
        onBrowseVersion,
    }: Props = $props();

    function handleHandleOrientationToggle() {
        const newOrientation = handleOrientation === "horizontal" ? "vertical" : "horizontal";
        const src = newOrientation === "horizontal" ? Position.Right : Position.Bottom;
        const tgt = newOrientation === "horizontal" ? Position.Left : Position.Top;
        const updatedNodes = nodes.map((n) => {
            if (
                (n.type === "unitOp" || n.type === "processStart") &&
                !n.data.handleOrientation
            ) {
                return {
                    ...n,
                    sourcePosition: src,
                    targetPosition: tgt,
                };
            }
            return n;
        });
        onHandleOrientationChange(newOrientation, updatedNodes);
    }
</script>

<div class="canvas-toolbar">
    <div class="mode-toggle">
        <button
            class="mode-btn"
            class:active={interactionMode === "pan"}
            onclick={() => onInteractionModeChange("pan")}
            title="Pan mode (hold Shift to select)"
        >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v1"/><path d="M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v6"/><path d="M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>
        </button>
        <button
            class="mode-btn"
            class:active={interactionMode === "select"}
            onclick={() => onInteractionModeChange("select")}
            title="Select mode (drag to select nodes)"
        >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/><path d="M13 13l6 6"/></svg>
        </button>
    </div>

    <div class="toolbar-divider"></div>

    <div class="undo-redo-group">
        <button
            class="icon-toolbar-btn"
            onclick={onUndo}
            disabled={!canUndoAction}
            title="Undo (Ctrl+Z)"
        >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6.69 3L3 13"/></svg>
        </button>
        <button
            class="icon-toolbar-btn"
            onclick={onRedo}
            disabled={!canRedoAction}
            title="Redo (Ctrl+Shift+Z)"
        >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 7v6h-6"/><path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6.69 3L21 13"/></svg>
        </button>
    </div>

    <div class="toolbar-divider"></div>

    <button
        class="toolbar-btn"
        class:active={layout === "horizontal"}
        onclick={onToggleLayout}
        title="Toggle orientation"
    >
        {layout === "horizontal" ? "↔ Horizontal" : "↕ Vertical"}
    </button>

    <div class="toolbar-divider"></div>

    <button
        class="toolbar-btn"
        class:active={handleOrientation === "horizontal"}
        onclick={handleHandleOrientationToggle}
        title="Toggle handle orientation"
    >
        {handleOrientation === "horizontal"
            ? "→ Handles H"
            : "↓ Handles V"}
    </button>

    <div class="toolbar-divider"></div>

    <button
        class="toolbar-btn"
        class:active={timeEnabled}
        onclick={onToggleTime}
    >
        Time: {timeEnabled ? "ON" : "OFF"}
    </button>

    <div class="toolbar-divider"></div>

    <button
        class="toolbar-btn"
        onclick={onToggleVersionHistory}
    >
        History{versionNumber > 0 ? ` (v${versionNumber})` : ""}
    </button>

    {#if versionNumber > 0}
        <div class="version-nav">
            <button
                class="version-nav-btn"
                onclick={() => onBrowseVersion('prev')}
                disabled={previewLoading || (previewingVersion ?? versionNumber) <= 1}
                title="Previous version"
            >&#x2039;</button>
            <span class="version-nav-label">
                {#if previewingVersion !== null}
                    v{previewingVersion}
                {:else}
                    v{versionNumber}
                {/if}
            </span>
            <button
                class="version-nav-btn"
                onclick={() => onBrowseVersion('next')}
                disabled={previewLoading || previewingVersion === null}
                title="Next version"
            >&#x203A;</button>
        </div>
    {/if}
</div>

<style>
    .canvas-toolbar {
        position: absolute;
        top: 12px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 10;
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        background: white;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    }

    .mode-toggle {
        display: flex;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        overflow: hidden;
    }

    .mode-btn {
        padding: 5px 8px;
        border: none;
        background: white;
        color: #475569;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.15s;
    }

    .mode-btn:first-child {
        border-right: 1px solid hsl(240, 5.9%, 90%);
    }

    .mode-btn:hover {
        background: #f8fafc;
    }

    .mode-btn.active {
        background: hsl(173, 58%, 39%);
        color: white;
    }

    .toolbar-btn {
        padding: 5px 10px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        background: white;
        font-size: 11px;
        font-weight: 600;
        color: #475569;
        cursor: pointer;
        font-family: inherit;
        transition: all 0.15s;
        white-space: nowrap;
    }

    .toolbar-btn:hover {
        background: #f8fafc;
    }

    .toolbar-btn.active {
        background: hsl(173, 58%, 39%);
        color: white;
        border-color: hsl(173, 58%, 39%);
    }

    .undo-redo-group {
        display: flex;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        overflow: hidden;
    }

    .icon-toolbar-btn {
        padding: 5px 8px;
        border: none;
        background: white;
        color: #475569;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.15s;
    }

    .icon-toolbar-btn:first-child {
        border-right: 1px solid hsl(240, 5.9%, 90%);
    }

    .icon-toolbar-btn:hover:not(:disabled) {
        background: #f8fafc;
    }

    .icon-toolbar-btn:disabled {
        color: #cbd5e1;
        cursor: not-allowed;
    }

    .toolbar-divider {
        width: 1px;
        height: 20px;
        background: hsl(240, 5.9%, 90%);
    }

    .version-nav {
        display: flex;
        align-items: center;
        gap: 2px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        background: white;
        overflow: hidden;
    }

    .version-nav-btn {
        padding: 4px 8px;
        border: none;
        background: transparent;
        font-size: 16px;
        font-weight: 600;
        color: #475569;
        cursor: pointer;
        line-height: 1;
        transition: background 0.15s;
    }

    .version-nav-btn:hover:not(:disabled) {
        background: #f1f5f9;
    }

    .version-nav-btn:disabled {
        color: #cbd5e1;
        cursor: not-allowed;
    }

    .version-nav-label {
        font-size: 11px;
        font-weight: 700;
        color: #334155;
        min-width: 24px;
        text-align: center;
        font-family: monospace;
    }
</style>
