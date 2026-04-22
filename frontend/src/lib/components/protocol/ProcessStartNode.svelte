<script lang="ts">
    import { getContext } from "svelte";
    import { Handle, NodeResizer, Position } from "@xyflow/svelte";
    import * as ContextMenu from "$lib/components/ui/context-menu";

    let { data, selected, id, width, height } = $props();

    const protocolOrientation: { value: "horizontal" | "vertical" } =
        getContext("protocolHandleOrientation");
    const nodeActions: {
        deleteNode: (nodeId: string) => void;
        onNodeResized: (nodeId: string, width: number, height: number) => void;
    } = getContext("nodeActions");

    const branchValidation: { invalidNodeIds: Set<string> } =
        getContext("branchValidation");
    const isInvalid = $derived(branchValidation.invalidNodeIds.has(id));

    // Source-only handle: process start is always the root
    const sourcePosition = $derived<Position>(
        protocolOrientation.value === "horizontal" ? Position.Right : Position.Bottom,
    );

    const sourceLabelSide = $derived(positionToSide(sourcePosition));

    function positionToSide(pos: Position): string {
        switch (pos) {
            case Position.Left: return "left";
            case Position.Right: return "right";
            case Position.Top: return "top";
            case Position.Bottom: return "bottom";
            default: return "right";
        }
    }
</script>

<NodeResizer
    minWidth={180}
    minHeight={60}
    isVisible={selected}
    lineStyle="border-color: #6366f1; border-width: 1px;"
    handleStyle="background: #6366f1; width: 8px; height: 8px;"
    onResizeEnd={(event, params) => {
        nodeActions.onNodeResized(id, params.width, params.height);
    }}
/>
<ContextMenu.Root>
    <ContextMenu.Trigger>
        {#snippet child({ props })}
            <div {...props} class="process-start-node" class:selected class:invalid={isInvalid}>
                <!-- Indigo color bar -->
                <div class="color-bar"></div>

                <!-- Header -->
                <div class="node-header">
                    <span class="node-icon">&#x25B6;</span>
                    <div class="node-title-group">
                        <span class="node-name">{data.label || "Process Start"}</span>
                        <span class="node-badge">PROCESS START</span>
                    </div>
                </div>

                <!-- Description -->
                {#if data.description}
                    <div class="node-description">
                        <span class="desc-text">{data.description}</span>
                    </div>
                {/if}

                <div class="handle-label source-label side-{sourceLabelSide}">Out</div>
                <Handle type="source" position={sourcePosition} />
            </div>
        {/snippet}
    </ContextMenu.Trigger>

    <ContextMenu.Content>
        <ContextMenu.Item onclick={() => nodeActions.deleteNode(id)}>
            <span class="menu-item-icon menu-delete-icon">&#x1F5D1;</span>
            <span class="menu-item-label menu-delete-label">Delete</span>
        </ContextMenu.Item>
    </ContextMenu.Content>
</ContextMenu.Root>

<style>
    .process-start-node {
        background: white;
        border: 1.5px solid #c7d2fe;
        border-radius: 10px;
        min-width: 180px;
        width: 100%;
        height: 100%;
        box-shadow:
            0 1px 3px rgba(0, 0, 0, 0.06),
            0 1px 2px rgba(0, 0, 0, 0.04);
        overflow: visible;
        transition:
            box-shadow 0.2s ease,
            border-color 0.2s ease;
        font-family: "Inter", system-ui, sans-serif;
        cursor: pointer;
        user-select: none;
    }

    .process-start-node.selected {
        border-color: #6366f1;
        box-shadow:
            0 0 0 2px rgba(99, 102, 241, 0.25),
            0 4px 12px rgba(0, 0, 0, 0.08);
    }

    .process-start-node.invalid {
        border-color: #f59e0b;
        box-shadow:
            0 0 0 2px rgba(245, 158, 11, 0.25),
            0 4px 12px rgba(245, 158, 11, 0.12);
    }

    .color-bar {
        height: 4px;
        width: 100%;
        border-radius: 10px 10px 0 0;
        background: linear-gradient(90deg, #6366f1, #818cf8);
    }

    .node-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 12px 6px;
        cursor: pointer;
    }

    .node-icon {
        font-size: 14px;
        color: #6366f1;
        line-height: 1;
    }

    .node-title-group {
        display: flex;
        flex-direction: column;
        min-width: 0;
    }

    .node-name {
        font-size: 13px;
        font-weight: 600;
        color: #1e293b;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        user-select: none;
    }

    .node-badge {
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.06em;
        color: #6366f1;
        text-transform: uppercase;
        user-select: none;
    }

    .node-description {
        padding: 4px 12px 8px;
        border-top: 1px solid #f1f5f9;
        margin-top: 2px;
    }

    .desc-text {
        font-size: 11px;
        color: #64748b;
        line-height: 1.4;
    }

    :global([data-slot="context-menu-item"]) {
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
    }

    .menu-item-icon {
        font-size: 13px;
        width: 16px;
        flex-shrink: 0;
        text-align: center;
        color: #64748b;
    }

    .menu-item-label {
        flex: 1;
        font-size: 13px;
        font-weight: 500;
        color: #1e293b;
    }

    .menu-delete-icon {
        color: #ef4444;
    }

    .menu-delete-label {
        color: #ef4444;
    }

    /* Handle labels */
    .handle-label {
        position: absolute;
        font-size: 8px;
        font-weight: 600;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        pointer-events: none;
        user-select: none;
        white-space: nowrap;
        z-index: 1000;
        background: white;
        padding: 1px 3px;
        border-radius: 3px;
        opacity: 0;
        transition: opacity 0.15s;
    }

    .process-start-node:hover .handle-label {
        opacity: 1;
    }

    .handle-label.side-left {
        left: 0;
        top: 50%;
        transform: translate(-100%, -50%);
        padding-right: 5px;
    }

    .handle-label.side-right {
        right: 0;
        top: 50%;
        transform: translate(100%, -50%);
        padding-left: 5px;
    }

    .handle-label.side-top {
        top: 0;
        left: 50%;
        transform: translate(-50%, -100%);
        padding-bottom: 5px;
    }

    .handle-label.side-bottom {
        bottom: 0;
        left: 50%;
        transform: translate(-50%, 100%);
        padding-top: 5px;
    }

    /* Handle styling */
    :global(.process-start-node .svelte-flow__handle) {
        width: 8px;
        height: 8px;
        background: #94a3b8;
        border: 2px solid white;
    }

    :global(.process-start-node.selected .svelte-flow__handle) {
        background: #6366f1;
    }
</style>
