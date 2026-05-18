<script lang="ts">
    import { Position, type Node } from "@xyflow/svelte";
    import { Button } from "$lib/components/ui/button";

    interface Props {
        interactionMode: "pan" | "select";
        layout: "horizontal" | "vertical";
        handleOrientation: "horizontal" | "vertical";
        timeEnabled: boolean;
        versionNumber: number;
        previewingVersion: number | null;
        previewLoading: boolean;
        latestDraftVersion: number | null;
        nodes: Node[];
        canUndoAction: boolean;
        canRedoAction: boolean;
        glpPanelOpen: boolean;
        glpSettingsDirty: boolean;
        onUndo: () => void;
        onRedo: () => void;
        onInteractionModeChange: (mode: "pan" | "select") => void;
        onToggleLayout: () => void;
        onHandleOrientationChange: (orientation: "horizontal" | "vertical", nodes: Node[]) => void;
        onToggleTime: () => void;
        onToggleVersionHistory: () => void;
        onBrowseVersion: (dir: "prev" | "next") => void;
        onToggleGlpPanel: () => void;
    }

    let {
        interactionMode,
        layout,
        handleOrientation,
        timeEnabled,
        versionNumber,
        previewingVersion,
        previewLoading,
        latestDraftVersion,
        nodes,
        canUndoAction,
        canRedoAction,
        glpPanelOpen,
        glpSettingsDirty,
        onUndo,
        onRedo,
        onInteractionModeChange,
        onToggleLayout,
        onHandleOrientationChange,
        onToggleTime,
        onToggleVersionHistory,
        onBrowseVersion,
        onToggleGlpPanel,
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
        <Button
            variant="ghost"
            size="icon-sm"
            class="mode-btn rounded-none"
            data-active={interactionMode === "pan"}
            onclick={() => onInteractionModeChange("pan")}
            title="Pan mode (hold Shift to select)"
        >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v1"/><path d="M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v6"/><path d="M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>
        </Button>
        <Button
            variant="ghost"
            size="icon-sm"
            class="mode-btn rounded-none"
            data-active={interactionMode === "select"}
            onclick={() => onInteractionModeChange("select")}
            title="Select mode (drag to select nodes)"
        >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/><path d="M13 13l6 6"/></svg>
        </Button>
    </div>

    <div class="toolbar-divider"></div>

    <div class="undo-redo-group">
        <Button
            variant="ghost"
            size="icon-sm"
            class="rounded-none"
            onclick={onUndo}
            disabled={!canUndoAction}
            title="Undo (Ctrl+Z)"
        >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6.69 3L3 13"/></svg>
        </Button>
        <Button
            variant="ghost"
            size="icon-sm"
            class="rounded-none"
            onclick={onRedo}
            disabled={!canRedoAction}
            title="Redo (Ctrl+Shift+Z)"
        >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 7v6h-6"/><path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6.69 3L21 13"/></svg>
        </Button>
    </div>

    <div class="toolbar-divider"></div>

    <Button
        variant="outline"
        size="sm"
        class="toolbar-btn"
        data-active={layout === "horizontal"}
        onclick={onToggleLayout}
        title="Toggle orientation"
    >
        {layout === "horizontal" ? "↔ Horizontal" : "↕ Vertical"}
    </Button>

    <div class="toolbar-divider"></div>

    <Button
        variant="outline"
        size="sm"
        class="toolbar-btn"
        data-active={handleOrientation === "horizontal"}
        onclick={handleHandleOrientationToggle}
        title="Toggle handle orientation"
    >
        {handleOrientation === "horizontal"
            ? "→ Handles H"
            : "↓ Handles V"}
    </Button>

    <div class="toolbar-divider"></div>

    <Button
        variant="outline"
        size="sm"
        class="toolbar-btn"
        data-active={timeEnabled}
        onclick={onToggleTime}
    >
        Time: {timeEnabled ? "ON" : "OFF"}
    </Button>

    <div class="toolbar-divider"></div>

    <button
        type="button"
        class="glp-btn"
        class:active={glpPanelOpen}
        onclick={onToggleGlpPanel}
        aria-pressed={glpPanelOpen}
        aria-label="Toggle GLP settings panel"
        title="GLP settings"
    >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 3v18"/><path d="M5 21h14"/><path d="M5 8h14"/>
            <path d="m5 8 3 6h-6z"/><path d="m19 8 3 6h-6z"/>
        </svg>
        <span>GLP</span>
        {#if glpSettingsDirty}
            <span class="glp-dirty-dot" aria-label="unsaved changes"></span>
        {/if}
    </button>

    <div class="toolbar-divider"></div>

    <Button
        variant="outline"
        size="sm"
        class="toolbar-btn"
        onclick={onToggleVersionHistory}
    >
        History{versionNumber > 0 ? ` (v${versionNumber})` : ""}
    </Button>

    {#if versionNumber > 0}
        <div class="version-nav">
            <Button
                variant="ghost"
                size="icon-sm"
                class="version-nav-btn rounded-none"
                onclick={() => onBrowseVersion('prev')}
                disabled={previewLoading || (previewingVersion ?? versionNumber) <= 1}
                title="Previous version"
            >&#x2039;</Button>
            <span class="version-nav-label">
                {#if previewingVersion !== null}
                    v{previewingVersion}{#if latestDraftVersion !== null && previewingVersion === latestDraftVersion}
                        <span class="version-nav-draft-tag">draft</span>
                    {/if}
                {:else}
                    v{versionNumber}
                {/if}
            </span>
            <Button
                variant="ghost"
                size="icon-sm"
                class="version-nav-btn rounded-none"
                onclick={() => onBrowseVersion('next')}
                disabled={previewLoading || (
                    previewingVersion === null
                        ? latestDraftVersion === null
                        : previewingVersion >= (latestDraftVersion ?? versionNumber)
                )}
                title={latestDraftVersion !== null && previewingVersion === null
                    ? `Next version (draft v${latestDraftVersion})`
                    : "Next version"}
            >&#x203A;</Button>
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

    :global(.mode-btn[data-active="true"]) {
        background: hsl(173, 58%, 39%);
        color: white;
    }

    :global(.mode-btn[data-active="true"]:hover) {
        background: hsl(173, 58%, 34%);
        color: white;
    }

    :global(.toolbar-btn[data-active="true"]) {
        background: hsl(173, 58%, 39%);
        color: white;
        border-color: hsl(173, 58%, 39%);
    }

    :global(.toolbar-btn[data-active="true"]:hover) {
        background: hsl(173, 58%, 34%);
        color: white;
    }

    .undo-redo-group {
        display: flex;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        overflow: hidden;
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

    .version-nav-label {
        font-size: 11px;
        font-weight: 700;
        color: #334155;
        min-width: 24px;
        text-align: center;
        font-family: monospace;
    }

    .version-nav-draft-tag {
        margin-left: 4px;
        padding: 1px 5px;
        font-size: 9px;
        font-weight: 700;
        color: rgb(180, 83, 9);
        background: rgb(254, 243, 199);
        border-radius: 4px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .glp-btn {
        position: relative;
        display: inline-flex;
        align-items: center;
        gap: 4px;
        height: 28px;
        padding: 0 10px;
        font-size: 12px;
        font-weight: 500;
        background: white;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        color: hsl(240, 5.9%, 10%);
        cursor: pointer;
        transition: background-color 0.12s ease, color 0.12s ease, border-color 0.12s ease;
    }

    .glp-btn:hover {
        background: hsl(240, 4.8%, 95.9%);
    }

    .glp-btn.active {
        background: hsl(173, 58%, 39%);
        color: white;
        border-color: hsl(173, 58%, 39%);
    }

    .glp-btn.active:hover {
        background: hsl(173, 58%, 34%);
    }

    .glp-dirty-dot {
        position: absolute;
        top: -2px;
        right: -2px;
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: hsl(24, 95%, 53%);
    }
</style>
