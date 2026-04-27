<script lang="ts">
    import { getContext } from "svelte";
    import { Handle, NodeResizer, Position } from "@xyflow/svelte";
    import { getCategoryColor, getCategoryIcon } from "$lib/categoryColors";
    import * as ContextMenu from "$lib/components/ui/context-menu";

    let { data, selected, id, width, height } = $props();

    const protocolOrientation: { value: "horizontal" | "vertical" } =
        getContext("protocolHandleOrientation");
    const nodeActions: {
        setNodeHandleOrientation: (
            nodeId: string,
            orientation: "horizontal" | "vertical" | null,
        ) => void;
        setNodeHandlePosition: (
            nodeId: string,
            handleType: "source" | "target",
            position: Position,
        ) => void;
        deleteNode: (nodeId: string) => void;
        onNodeResized: (nodeId: string, width: number, height: number) => void;
    } = getContext("nodeActions");

    const timelineConfig: {
        enabled: boolean;
        pixelsPerHour: number;
        layout: "horizontal" | "vertical";
        snapMinutes: number;
    } = getContext("timelineConfig");

    const branchValidation: { invalidNodeIds: Set<string> } =
        getContext("branchValidation");
    const isInvalid = $derived(branchValidation.invalidNodeIds.has(id));

    const color = $derived(getCategoryColor(data.category || "General"));
    const icon = $derived(getCategoryIcon(data.category || "General"));

    // Determine effective orientation (per-node override or protocol default)
    const effectiveOrientation = $derived(
        data.handleOrientation || protocolOrientation.value,
    );

    // Compute handle positions: per-handle overrides > orientation preset > protocol default
    const sourcePosition = $derived<Position>(
        data.sourcePosition ||
        (effectiveOrientation === "horizontal" ? Position.Right : Position.Bottom),
    );
    const targetPosition = $derived<Position>(
        data.targetPosition ||
        (effectiveOrientation === "horizontal" ? Position.Left : Position.Top),
    );

    // Helper to map Position to a CSS class for label placement
    const sourceLabelSide = $derived(positionToSide(sourcePosition));
    const targetLabelSide = $derived(positionToSide(targetPosition));

    function positionToSide(pos: Position): string {
        switch (pos) {
            case Position.Left: return "left";
            case Position.Right: return "right";
            case Position.Top: return "top";
            case Position.Bottom: return "bottom";
            default: return "left";
        }
    }

    // Whether node has any per-handle customization
    const hasPerHandleOverride = $derived(!!data.sourcePosition || !!data.targetPosition);

    // Format param values for inline display
    function formatParams(
        params: Record<string, any>,
        schema: Record<string, any>,
    ): Array<{ label: string; value: string }> {
        if (!params || !schema?.properties) return [];
        const entries: Array<{ label: string; value: string }> = [];
        for (const [key, val] of Object.entries(params)) {
            const prop = schema.properties[key];
            if (!prop || prop["x-ref-type"]) continue; // skip refs in inline view
            const label = prop.title || key;
            let display = String(val);
            if (prop.type === "number" && typeof val === "number") {
                display = val % 1 === 0 ? val.toLocaleString() : val.toFixed(1);
            }
            entries.push({ label, value: display });
        }
        return entries.slice(0, 4); // show max 4 params inline
    }

    const displayParams = $derived(formatParams(data.params, data.paramSchema));
    const shortId = $derived(id.slice(0, 8).toUpperCase());
    const hasOverride = $derived(!!data.handleOrientation || hasPerHandleOverride);

    // Resize direction: constrain along time axis when timeline is on
    const minWidth = $derived(timelineConfig.enabled && timelineConfig.layout === "horizontal" ? 60 : 120);
    const minHeight = $derived(timelineConfig.enabled && timelineConfig.layout === "vertical" ? 60 : 60);
</script>

<NodeResizer
    {minWidth}
    {minHeight}
    isVisible={selected}
    lineStyle="border-color: {color}; border-width: 1px;"
    handleStyle="background: {color}; width: 8px; height: 8px;"
    onResizeEnd={(event, params) => {
        nodeActions.onNodeResized(id, params.width, params.height);
    }}
/>
<ContextMenu.Root>
    <ContextMenu.Trigger>
        {#snippet child({ props })}
            <div {...props} class="unit-op-node" class:selected class:invalid={isInvalid} style:--cat-color={color}>
                <!-- Category color bar -->
                <div class="color-bar" style:background={color}></div>

                <!-- Header -->
                <div class="node-header">
                    <span class="node-icon">{icon}</span>
                    <div class="node-title-group">
                        <span class="node-name">{data.label}</span>
                        <span class="node-id">ID: {shortId}</span>
                    </div>
                </div>

                <!-- Inline params -->
                {#if displayParams.length > 0}
                    <div class="node-params">
                        {#each displayParams as param}
                            <div class="param-row">
                                <span class="param-label">{param.label}</span>
                                <span class="param-value">{param.value}</span>
                            </div>
                        {/each}
                    </div>
                {/if}

                {#if data.duration_min}
                    <div class="node-duration">
                        <span class="duration-icon">&#x23F1;</span>
                        <span class="duration-text">{data.duration_min} min</span>
                    </div>
                {/if}

                <div class="handle-label target-label side-{targetLabelSide}">In</div>
                <Handle type="target" position={targetPosition} />
                <div class="handle-label source-label side-{sourceLabelSide}">Out</div>
                <Handle type="source" position={sourcePosition} />
            </div>
        {/snippet}
    </ContextMenu.Trigger>

    <ContextMenu.Content>
        <ContextMenu.Item
            onclick={() => nodeActions.setNodeHandleOrientation(id, "horizontal")}
        >
            <span class="menu-item-icon">↔</span>
            <span class="menu-item-label">Horizontal Handles</span>
            {#if !hasPerHandleOverride && effectiveOrientation === "horizontal"}
                <span class="menu-check">✓</span>
            {/if}
        </ContextMenu.Item>
        <ContextMenu.Item
            onclick={() => nodeActions.setNodeHandleOrientation(id, "vertical")}
        >
            <span class="menu-item-icon">↕</span>
            <span class="menu-item-label">Vertical Handles</span>
            {#if !hasPerHandleOverride && effectiveOrientation === "vertical"}
                <span class="menu-check">✓</span>
            {/if}
        </ContextMenu.Item>

        <ContextMenu.Separator />

        <!-- In (target) handle submenu -->
        <ContextMenu.Sub>
            <ContextMenu.SubTrigger>
                <span class="menu-item-icon">&#x2B95;</span>
                <span class="menu-item-label">In Handle</span>
                <span class="menu-item-hint">{targetLabelSide}</span>
                <span class="submenu-arrow">&#x25B8;</span>
            </ContextMenu.SubTrigger>
            <ContextMenu.SubContent>
                {#each [
                    { pos: Position.Left, label: "Left", icon: "←" },
                    { pos: Position.Right, label: "Right", icon: "→" },
                    { pos: Position.Top, label: "Top", icon: "↑" },
                    { pos: Position.Bottom, label: "Bottom", icon: "↓" },
                ] as opt}
                    <ContextMenu.Item
                        onclick={() => nodeActions.setNodeHandlePosition(id, "target", opt.pos)}
                    >
                        <span class="menu-item-icon">{opt.icon}</span>
                        <span class="menu-item-label">{opt.label}</span>
                        {#if targetPosition === opt.pos}
                            <span class="menu-check">✓</span>
                        {/if}
                    </ContextMenu.Item>
                {/each}
            </ContextMenu.SubContent>
        </ContextMenu.Sub>

        <!-- Out (source) handle submenu -->
        <ContextMenu.Sub>
            <ContextMenu.SubTrigger>
                <span class="menu-item-icon">&#x2B95;</span>
                <span class="menu-item-label">Out Handle</span>
                <span class="menu-item-hint">{sourceLabelSide}</span>
                <span class="submenu-arrow">&#x25B8;</span>
            </ContextMenu.SubTrigger>
            <ContextMenu.SubContent>
                {#each [
                    { pos: Position.Left, label: "Left", icon: "←" },
                    { pos: Position.Right, label: "Right", icon: "→" },
                    { pos: Position.Top, label: "Top", icon: "↑" },
                    { pos: Position.Bottom, label: "Bottom", icon: "↓" },
                ] as opt}
                    <ContextMenu.Item
                        onclick={() => nodeActions.setNodeHandlePosition(id, "source", opt.pos)}
                    >
                        <span class="menu-item-icon">{opt.icon}</span>
                        <span class="menu-item-label">{opt.label}</span>
                        {#if sourcePosition === opt.pos}
                            <span class="menu-check">✓</span>
                        {/if}
                    </ContextMenu.Item>
                {/each}
            </ContextMenu.SubContent>
        </ContextMenu.Sub>

        {#if hasOverride}
            <ContextMenu.Separator />
            <ContextMenu.Item
                onclick={() => nodeActions.setNodeHandleOrientation(id, null)}
            >
                <span class="menu-item-label">Use Default</span>
                <span class="menu-item-hint">({protocolOrientation.value})</span>
            </ContextMenu.Item>
        {/if}

        <ContextMenu.Separator />
        <ContextMenu.Item onclick={() => nodeActions.deleteNode(id)}>
            <span class="menu-item-icon menu-delete-icon">&#x1F5D1;</span>
            <span class="menu-item-label menu-delete-label">Delete</span>
        </ContextMenu.Item>
    </ContextMenu.Content>
</ContextMenu.Root>

<style>
    .unit-op-node {
        background: white;
        border: 1.5px solid #e2e8f0;
        border-radius: 10px;
        min-width: 120px;
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

    .unit-op-node.selected {
        border-color: var(--cat-color, #3b82f6);
        box-shadow:
            0 0 0 2px
                color-mix(in srgb, var(--cat-color, #3b82f6) 25%, transparent),
            0 4px 12px rgba(0, 0, 0, 0.08);
    }

    .unit-op-node.invalid {
        border-color: #f59e0b;
        box-shadow:
            0 0 0 2px rgba(245, 158, 11, 0.25),
            0 4px 12px rgba(245, 158, 11, 0.12);
    }

    .color-bar {
        height: 4px;
        width: 100%;
        border-radius: 10px 10px 0 0;
    }

    .node-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 12px 6px;
        cursor: pointer;
    }

    .node-icon {
        font-size: 16px;
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

    .node-id {
        font-size: 10px;
        color: #94a3b8;
        font-family: "JetBrains Mono", monospace;
        user-select: none;
    }

    .node-params {
        padding: 4px 12px 8px;
        border-top: 1px solid #f1f5f9;
        margin-top: 2px;
    }

    .param-row {
        display: flex;
        align-items: flex-start;
        gap: 16px;
        padding: 2px 0;
    }

    .param-label {
        font-size: 11px;
        color: #64748b;
        flex-shrink: 0;
    }

    .param-value {
        font-size: 11px;
        font-weight: 600;
        color: #334155;
        font-family: "JetBrains Mono", monospace;
        margin-left: auto;
        text-align: right;
        word-break: break-word;
        min-width: 0;
    }

    .node-duration {
        padding: 4px 12px 8px;
        display: flex;
        align-items: center;
        gap: 4px;
        border-top: 1px solid #f1f5f9;
    }

    .duration-icon {
        font-size: 11px;
    }

    .duration-text {
        font-size: 10px;
        color: #94a3b8;
        font-weight: 500;
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

    .menu-item-hint {
        font-size: 12px;
        color: #94a3b8;
        font-weight: 400;
        flex-shrink: 0;
    }

    .menu-check {
        color: hsl(173, 58%, 39%);
        font-weight: 700;
        font-size: 13px;
        width: 16px;
        flex-shrink: 0;
        text-align: center;
    }

    .submenu-arrow {
        font-size: 10px;
        color: #94a3b8;
        margin-left: auto;
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

    .unit-op-node:hover .handle-label {
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
    :global(.unit-op-node .svelte-flow__handle) {
        width: 8px;
        height: 8px;
        background: #94a3b8;
        border: 2px solid white;
    }

    :global(.unit-op-node.selected .svelte-flow__handle) {
        background: var(--cat-color, #3b82f6);
    }

</style>
