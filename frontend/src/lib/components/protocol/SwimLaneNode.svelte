<script lang="ts">
    import { getContext } from "svelte";
    import { NodeResizer } from "@xyflow/svelte";
    import * as ContextMenu from "$lib/components/ui/context-menu";

    let { data, selected, id } = $props();

    const nodeActions: {
        deleteNode: (nodeId: string) => void;
    } = getContext("nodeActions");

    const laneInfo: { childCount(laneId: string): number } | undefined =
        getContext("laneInfo");

    const isVertical = $derived(data.orientation === "vertical");
    const isEmpty = $derived((laneInfo?.childCount(id) ?? 1) === 0);
</script>

<ContextMenu.Root>
    <ContextMenu.Trigger>
        <div
            class="swimlane-node"
            class:selected
            class:vertical={isVertical}
            style:--lane-color={data.color || "#94a3b8"}
        >
            <NodeResizer
                minWidth={isVertical ? 140 : 280}
                minHeight={isVertical ? 200 : 100}
                isVisible={selected}
                lineStyle="border-color: {data.color || '#94a3b8'}; border-width: 1px;"
                handleStyle="background: {data.color ||
                    '#94a3b8'}; width: 8px; height: 8px;"
            />

            <!-- Lane header -->
            <div class="lane-header" class:vertical-header={isVertical}>
                <div class="lane-color-dot" style:background={data.color}></div>
                <span class="lane-label">{data.label || "Untitled Role"}</span>
                {#if isEmpty}
                    <span
                        class="lane-empty-badge"
                        title="This role has no steps. Drag steps into this lane or remove the role."
                    >
                        ⚠ empty
                    </span>
                {/if}
            </div>
        </div>
    </ContextMenu.Trigger>

    <ContextMenu.Content>
        <ContextMenu.Item onclick={() => nodeActions.deleteNode(id)}>
            <span class="menu-item-icon menu-delete-icon">&#x1F5D1;</span>
            <span class="menu-item-label menu-delete-label">Delete</span>
        </ContextMenu.Item>
    </ContextMenu.Content>
</ContextMenu.Root>

<style>
    .swimlane-node {
        background: color-mix(in srgb, var(--lane-color) 4%, white);
        border: 1.5px dashed
            color-mix(in srgb, var(--lane-color) 30%, transparent);
        border-radius: 12px;
        width: 100%;
        height: 100%;
        min-height: 100px;
        position: relative;
    }

    /* The xyflow node wrapper applies the user's resized width/height as
       inline styles, but our content is wrapped in
       <ContextMenu.Trigger> → <div cursor-wrapper> → .swimlane-node.
       Neither wrapper has height set, so .swimlane-node's height: 100%
       collapses to content height — making vertical NodeResizer drags
       look like a no-op. Force the trigger chain to fill the xyflow
       wrapper so resize-driven height changes propagate down. */
    :global(.svelte-flow__node-swimLane > [data-slot="context-menu-trigger"]),
    :global(
            .svelte-flow__node-swimLane
                > [data-slot="context-menu-trigger"]
                > div
        ) {
        width: 100%;
        height: 100%;
    }

    .swimlane-node.selected {
        border-color: var(--lane-color);
        border-style: solid;
    }

    .lane-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        background: color-mix(in srgb, var(--lane-color) 8%, white);
        border-bottom: 1px solid
            color-mix(in srgb, var(--lane-color) 15%, transparent);
        border-radius: 12px 12px 0 0;
    }

    .lane-header.vertical-header {
        writing-mode: vertical-rl;
        text-orientation: mixed;
        border-bottom: none;
        border-right: 1px solid
            color-mix(in srgb, var(--lane-color) 15%, transparent);
        border-radius: 12px 0 0 12px;
        padding: 14px 10px;
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: auto;
    }

    .lane-color-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .lane-label {
        font-size: 12px;
        font-weight: 600;
        color: #475569;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        white-space: nowrap;
    }

    .lane-empty-badge {
        font-size: 10px;
        font-weight: 600;
        color: #b45309;
        background: #fef3c7;
        border: 1px solid #fde68a;
        border-radius: 4px;
        padding: 2px 6px;
        margin-left: 4px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        white-space: nowrap;
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
</style>
