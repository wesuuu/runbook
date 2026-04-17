<script lang="ts">
    import { getContext } from "svelte";
    import { NodeResizer } from "@xyflow/svelte";
    import * as ContextMenu from "$lib/components/ui/context-menu";

    let { data, selected, id } = $props();

    const nodeActions: {
        deleteNode: (nodeId: string) => void;
    } = getContext("nodeActions");

    const isVertical = $derived(data.orientation === "vertical");
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
                minWidth={isVertical ? 220 : 600}
                minHeight={isVertical ? 400 : 150}
                isVisible={selected}
                lineStyle="border-color: {data.color || '#94a3b8'}; border-width: 1px;"
                handleStyle="background: {data.color ||
                    '#94a3b8'}; width: 8px; height: 8px;"
            />

            <!-- Lane header -->
            <div class="lane-header" class:vertical-header={isVertical}>
                <div class="lane-color-dot" style:background={data.color}></div>
                <span class="lane-label">{data.label || "Untitled Role"}</span>
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
        min-height: 150px;
        position: relative;
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
