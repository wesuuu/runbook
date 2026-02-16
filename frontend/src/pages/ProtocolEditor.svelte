<script lang="ts">
    import { onMount } from "svelte";
    import {
        SvelteFlow,
        Background,
        Controls,
        MiniMap,
        type Node,
        type Edge,
        type Viewport,
    } from "@xyflow/svelte";
    import "@xyflow/svelte/dist/style.css";

    import { api } from "../lib/api";
    import Link from "../lib/Link.svelte";
    import { getCategoryColor, getCategoryIcon } from "$lib/categoryColors";
    import UnitOpNode from "$lib/components/UnitOpNode.svelte";
    import SwimLaneNode from "$lib/components/SwimLaneNode.svelte";
    import Inspector from "$lib/components/Inspector.svelte";
    import TimeAxis from "$lib/components/TimeAxis.svelte";
    import CreateUnitOpModal from "$lib/components/CreateUnitOpModal.svelte";

    let { params } = $props();

    // --- Node Types ---
    const nodeTypes = { unitOp: UnitOpNode, swimLane: SwimLaneNode };

    // --- State ---
    let protocol = $state<any>(null);
    let unitOps = $state<any[]>([]);
    let roles = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let saving = $state(false);
    let saveMessage = $state<string | null>(null);

    // Flow state
    let nodes = $state<Node[]>([]);
    let edges = $state<Edge[]>([]);
    let viewport = $state<Viewport>({ x: 0, y: 0, zoom: 1 });
    let flowContainer: HTMLDivElement;

    // Layout / time settings
    let layout = $state<"horizontal" | "vertical">("horizontal");
    let timeEnabled = $state(false);
    let startTime = $state("08:00");
    let pixelsPerHour = $state(200);

    // Inline name editing
    let editingName = $state(false);
    let nameInput = $state("");

    // Inspector — watch for node selection changes via SvelteFlow's built-in selection
    let selectedNodeId = $state<string | null>(null);

    $effect(() => {
        const sel = nodes.find((n) => n.type === "unitOp" && n.selected);
        selectedNodeId = sel ? sel.id : null;
    });

    const selectedNode = $derived(
        selectedNodeId
            ? nodes.find((n) => n.id === selectedNodeId) || null
            : null,
    );

    // Search
    let searchQuery = $state("");

    // Category accordion state
    let collapsedCategories = $state<Set<string>>(new Set());

    // Create Unit Op modal
    let showCreateModal = $state(false);
    let createModalCategory = $state("");

    // Add Role
    let newRoleName = $state("");
    let showRoleInput = $state(false);

    // --- Derived ---
    const filteredOps = $derived(() => {
        if (!searchQuery.trim()) return unitOps;
        const q = searchQuery.toLowerCase();
        return unitOps.filter(
            (op) =>
                op.name.toLowerCase().includes(q) ||
                op.category.toLowerCase().includes(q),
        );
    });

    const categories = $derived(() => {
        const map = new Map<string, any[]>();
        for (const op of filteredOps()) {
            const cat = op.category || "General";
            if (!map.has(cat)) map.set(cat, []);
            map.get(cat)!.push(op);
        }
        return map;
    });

    // --- Data Loading ---
    async function loadData() {
        try {
            unitOps = await api.get("/science/unit-ops");

            if (params.id && params.id !== "new") {
                protocol = await api.get(`/science/protocols/${params.id}`);
                roles = protocol.roles || [];

                if (protocol.graph && protocol.graph.nodes) {
                    nodes = protocol.graph.nodes;
                    edges = protocol.graph.edges || [];
                    layout = protocol.graph.layout || "horizontal";
                    timeEnabled = protocol.graph.timeEnabled || false;
                    startTime = protocol.graph.startTime || "08:00";
                    pixelsPerHour = protocol.graph.pixelsPerHour || 200;
                }
            }
        } catch (e: any) {
            error = e.message;
        } finally {
            loading = false;
        }
    }

    // --- Name Editing ---
    async function saveName() {
        if (!protocol || !nameInput.trim()) {
            editingName = false;
            return;
        }
        try {
            await api.put(`/science/protocols/${protocol.id}`, {
                name: nameInput.trim(),
            });
            protocol.name = nameInput.trim();
        } catch (e) {
            // silent
        }
        editingName = false;
    }

    function startEditingName() {
        nameInput = protocol?.name || "";
        editingName = true;
    }

    function handleNameKeydown(e: KeyboardEvent) {
        if (e.key === "Enter") saveName();
        else if (e.key === "Escape") editingName = false;
    }

    // --- Save Protocol ---
    async function save() {
        if (!protocol) return;
        saving = true;
        saveMessage = null;

        try {
            const graphData = {
                nodes: nodes.map((n) => ({
                    id: n.id,
                    type: n.type,
                    position: n.position,
                    parentId: n.parentId,
                    data: n.data,
                    width: n.measured?.width,
                    height: n.measured?.height,
                    style: n.style,
                })),
                edges: edges.map((e) => ({
                    id: e.id,
                    source: e.source,
                    target: e.target,
                })),
                layout,
                timeEnabled,
                startTime,
                pixelsPerHour,
            };

            await api.put(`/science/protocols/${protocol.id}`, {
                graph: graphData,
            });
            saveMessage = "Saved!";
            setTimeout(() => (saveMessage = null), 2000);
        } catch (e: any) {
            saveMessage = `Failed: ${e.message}`;
        } finally {
            saving = false;
        }
    }

    // --- Drag & Drop ---
    function onDragStart(event: DragEvent, op: any) {
        if (!event.dataTransfer) return;
        event.dataTransfer.setData(
            "application/svelteflow",
            JSON.stringify(op),
        );
        event.dataTransfer.effectAllowed = "move";
    }

    function onDragOver(event: DragEvent) {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    }

    function onDrop(event: DragEvent) {
        event.preventDefault();
        if (!event.dataTransfer) return;

        const opData = event.dataTransfer.getData("application/svelteflow");
        if (!opData) return;

        const op = JSON.parse(opData);

        // Convert screen coordinates to flow coordinates
        const bounds = flowContainer.getBoundingClientRect();
        const position = {
            x: (event.clientX - bounds.left - viewport.x) / viewport.zoom,
            y: (event.clientY - bounds.top - viewport.y) / viewport.zoom,
        };

        // Set default params from param_schema
        const defaultParams: Record<string, any> = {};
        if (op.param_schema?.properties) {
            for (const [key, prop] of Object.entries(
                op.param_schema.properties as Record<string, any>,
            )) {
                if (prop.default !== undefined) {
                    defaultParams[key] = prop.default;
                } else if (prop.enum) {
                    defaultParams[key] = prop.enum[0];
                }
            }
        }

        // Check if dropped inside a swimlane
        let parentId: string | undefined;
        for (const n of nodes) {
            if (n.type === "swimLane") {
                const laneX = n.position.x;
                const laneY = n.position.y;
                const laneW = (n.measured?.width || n.width || 600) as number;
                const laneH = (n.measured?.height || n.height || 200) as number;
                if (
                    position.x >= laneX &&
                    position.x <= laneX + laneW &&
                    position.y >= laneY &&
                    position.y <= laneY + laneH
                ) {
                    parentId = n.id;
                    // Adjust position to be relative to parent
                    position.x -= laneX;
                    position.y -= laneY;
                    break;
                }
            }
        }

        const newNode: Node = {
            id: crypto.randomUUID(),
            type: "unitOp",
            position,
            parentId,
            data: {
                label: op.name,
                unitOpId: op.id,
                category: op.category,
                duration_min: 30,
                params: defaultParams,
                paramSchema: op.param_schema || {},
            },
        };

        nodes = [...nodes, newNode];
    }

    // --- Inspector Apply ---
    function handleInspectorApply(
        nodeId: string,
        params: Record<string, any>,
        duration: number,
    ) {
        nodes = nodes.map((n) => {
            if (n.id === nodeId) {
                return {
                    ...n,
                    data: {
                        ...n.data,
                        params,
                        duration_min: duration,
                    },
                };
            }
            return n;
        });
        selectedNodeId = null;
    }

    // --- Roles ---
    async function addRole() {
        if (!protocol || !newRoleName.trim()) return;
        try {
            const role = await api.post(
                `/science/protocols/${protocol.id}/roles`,
                {
                    name: newRoleName.trim(),
                    color: getNextRoleColor(),
                    sort_order: roles.length,
                },
            );

            roles = [...roles, role];
            newRoleName = "";
            showRoleInput = false;

            // Create swimlane node on canvas
            const laneY = roles.length === 1 ? 0 : (roles.length - 1) * 220;
            const laneX = 0;
            const laneNode: Node = {
                id: `lane-${(role as any).id}`,
                type: "swimLane",
                position:
                    layout === "horizontal"
                        ? { x: laneX, y: laneY }
                        : { x: laneY, y: laneX },
                data: {
                    label: (role as any).name,
                    color: (role as any).color,
                    roleId: (role as any).id,
                    orientation: layout,
                },
                style:
                    layout === "horizontal"
                        ? "width: 800px; height: 200px;"
                        : "width: 220px; height: 500px;",
            };

            nodes = [...nodes, laneNode];
        } catch (e: any) {
            console.error("Failed to add role:", e);
        }
    }

    async function deleteRole(roleId: string) {
        if (!protocol) return;
        try {
            await api.delete(
                `/science/protocols/${protocol.id}/roles/${roleId}`,
            );
            roles = roles.filter((r) => r.id !== roleId);
            // Remove the lane node
            const laneNodeId = `lane-${roleId}`;
            // Unparent any children
            nodes = nodes
                .filter((n) => n.id !== laneNodeId)
                .map((n) => {
                    if (n.parentId === laneNodeId) {
                        return { ...n, parentId: undefined };
                    }
                    return n;
                });
        } catch (e: any) {
            console.error("Failed to delete role:", e);
        }
    }

    function getNextRoleColor(): string {
        const colors = [
            "#3b82f6",
            "#10b981",
            "#f97316",
            "#8b5cf6",
            "#ec4899",
            "#06b6d4",
            "#f59e0b",
        ];
        return colors[roles.length % colors.length];
    }

    // --- Category Accordion ---
    function toggleCategory(cat: string) {
        const s = new Set(collapsedCategories);
        if (s.has(cat)) s.delete(cat);
        else s.add(cat);
        collapsedCategories = s;
    }

    // --- Orientation Toggle ---
    function toggleLayout() {
        layout = layout === "horizontal" ? "vertical" : "horizontal";
        // Update swimlane node orientations
        nodes = nodes.map((n) => {
            if (n.type === "swimLane") {
                return {
                    ...n,
                    data: { ...n.data, orientation: layout },
                    style:
                        layout === "horizontal"
                            ? "width: 800px; height: 200px;"
                            : "width: 220px; height: 500px;",
                };
            }
            return n;
        });
    }

    // --- Custom Unit Op ---
    async function handleCreateUnitOp(opData: any) {
        try {
            const created = await api.post("/science/unit-ops", opData);
            unitOps = [...unitOps, created];
            showCreateModal = false;
        } catch (e: any) {
            console.error("Failed to create unit op:", e);
        }
    }

    function openCreateModal(category: string) {
        createModalCategory = category;
        showCreateModal = true;
    }

    onMount(() => {
        loadData();
    });
</script>

<div class="editor-wrapper">
    <!-- ============= SIDEBAR ============= -->
    <aside class="sidebar">
        <!-- Header -->
        <div class="sidebar-header">
            {#if editingName}
                <input
                    type="text"
                    bind:value={nameInput}
                    onblur={saveName}
                    onkeydown={handleNameKeydown}
                    class="name-input"
                    autofocus
                />
            {:else if protocol}
                <button class="name-display" onclick={startEditingName}>
                    {protocol.name}
                    <span class="edit-hint">✏️</span>
                </button>
            {:else}
                <span class="name-placeholder">Loading...</span>
            {/if}

            {#if protocol}
                <Link href="/projects/{protocol.project_id}" class="back-link">
                    ← Back to Project
                </Link>
            {/if}
        </div>

        <!-- Roles Section -->
        <div class="sidebar-section">
            <div class="section-header-row">
                <span class="section-title">ROLES</span>
                <button
                    class="icon-btn"
                    onclick={() => (showRoleInput = !showRoleInput)}>+</button
                >
            </div>

            {#if showRoleInput}
                <div class="role-input-row">
                    <input
                        type="text"
                        bind:value={newRoleName}
                        placeholder="Role name..."
                        class="role-input"
                        onkeydown={(e) => {
                            if (e.key === "Enter") addRole();
                        }}
                    />
                    <button class="role-add-btn" onclick={addRole}>Add</button>
                </div>
            {/if}

            <div class="roles-list">
                {#each roles as role}
                    <div class="role-item">
                        <div
                            class="role-dot"
                            style:background={role.color}
                        ></div>
                        <span class="role-name">{role.name}</span>
                        <button
                            class="role-delete-btn"
                            onclick={() => deleteRole(role.id)}>✕</button
                        >
                    </div>
                {/each}
            </div>
        </div>

        <!-- Search -->
        <div class="sidebar-section search-section">
            <input
                type="text"
                bind:value={searchQuery}
                placeholder="Search ops..."
                class="search-input"
            />
        </div>

        <!-- Unit Operations -->
        <div class="ops-list">
            <div class="section-header-row">
                <span class="section-title">UNIT OPERATIONS</span>
            </div>

            {#if unitOps.length === 0}
                <p class="loading-text">Loading...</p>
            {:else}
                {#each [...categories().entries()] as [category, ops]}
                    <div class="category-group">
                        <button
                            class="category-header"
                            onclick={() => toggleCategory(category)}
                        >
                            <span
                                class="cat-dot"
                                style:background={getCategoryColor(category)}
                            ></span>
                            <span class="cat-name">{category}</span>
                            <span
                                class="cat-chevron"
                                class:collapsed={collapsedCategories.has(
                                    category,
                                )}>▾</span
                            >
                            <span
                                class="cat-add-btn"
                                role="button"
                                tabindex="0"
                                onclick={(e) => {
                                    e.stopPropagation();
                                    openCreateModal(category);
                                }}
                                onkeydown={(e) => {
                                    if (e.key === "Enter") {
                                        e.stopPropagation();
                                        openCreateModal(category);
                                    }
                                }}
                                title="Add unit op to {category}">+</span
                            >
                        </button>

                        {#if !collapsedCategories.has(category)}
                            <div class="cat-ops">
                                {#each ops as op}
                                    <div
                                        role="button"
                                        tabindex="0"
                                        class="op-item"
                                        draggable="true"
                                        ondragstart={(e) => onDragStart(e, op)}
                                    >
                                        <span class="op-icon"
                                            >{getCategoryIcon(
                                                op.category,
                                            )}</span
                                        >
                                        <div class="op-info">
                                            <span class="op-name"
                                                >{op.name}</span
                                            >
                                            {#if op.description}
                                                <span class="op-desc"
                                                    >{op.description}</span
                                                >
                                            {/if}
                                        </div>
                                    </div>
                                {/each}
                            </div>
                        {/if}
                    </div>
                {/each}
            {/if}
        </div>

        <!-- Drag hint -->
        <div class="drag-hint">
            <span>⬆ Drag nodes to canvas to add</span>
        </div>

        <!-- Save Button -->
        <div class="sidebar-footer">
            {#if saveMessage}
                <p
                    class="save-msg"
                    class:error={saveMessage.startsWith("Failed")}
                >
                    {saveMessage}
                </p>
            {/if}
            <button
                class="save-btn"
                onclick={save}
                disabled={saving || !protocol}
            >
                {saving ? "Saving..." : "Save Protocol"}
            </button>
        </div>
    </aside>

    <!-- ============= CANVAS ============= -->
    <div
        class="canvas-wrapper"
        ondrop={onDrop}
        ondragover={onDragOver}
        bind:this={flowContainer}
    >
        <!-- Toolbar -->
        <div class="canvas-toolbar">
            <button
                class="toolbar-btn"
                class:active={layout === "horizontal"}
                onclick={toggleLayout}
                title="Toggle orientation"
            >
                {layout === "horizontal" ? "↔ Horizontal" : "↕ Vertical"}
            </button>

            <div class="toolbar-divider"></div>

            <button
                class="toolbar-btn"
                class:active={timeEnabled}
                onclick={() => (timeEnabled = !timeEnabled)}
            >
                🕐 Time: {timeEnabled ? "ON" : "OFF"}
            </button>

            {#if timeEnabled}
                <div class="toolbar-divider"></div>
                <label class="toolbar-label">
                    Start
                    <input
                        type="time"
                        bind:value={startTime}
                        class="toolbar-time-input"
                    />
                </label>
            {/if}
        </div>

        <!-- Time axis overlay -->
        {#if timeEnabled}
            <TimeAxis
                {layout}
                {startTime}
                {pixelsPerHour}
                viewportTransform={viewport}
            />
        {/if}

        {#if loading}
            <div class="canvas-loading">
                <div class="spinner"></div>
                <p>Loading protocol...</p>
            </div>
        {:else}
            <SvelteFlow bind:nodes bind:edges bind:viewport {nodeTypes} fitView>
                <Background />
                <Controls />
                <MiniMap />
            </SvelteFlow>
        {/if}
    </div>

    <!-- ============= INSPECTOR ============= -->
    {#if selectedNode}
        <Inspector
            node={selectedNode}
            allNodes={nodes}
            onApply={handleInspectorApply}
            onClose={() => (selectedNodeId = null)}
        />
    {/if}

    <!-- ============= CREATE MODAL ============= -->
    <CreateUnitOpModal
        open={showCreateModal}
        defaultCategory={createModalCategory}
        onClose={() => (showCreateModal = false)}
        onCreate={handleCreateUnitOp}
    />
</div>

<style>
    /* ── Layout ── */
    .editor-wrapper {
        height: calc(100vh - 57px);
        display: flex;
        font-family: "Inter", system-ui, sans-serif;
    }

    /* ── Sidebar ── */
    .sidebar {
        width: 280px;
        background: white;
        border-right: 1px solid hsl(240, 5.9%, 90%);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        flex-shrink: 0;
    }

    .sidebar-header {
        padding: 16px;
        border-bottom: 1px solid hsl(240, 5.9%, 90%);
    }

    .name-input {
        width: 100%;
        font-size: 16px;
        font-weight: 700;
        padding: 6px 8px;
        border: 1.5px solid hsl(173, 58%, 39%);
        border-radius: 6px;
        outline: none;
        color: #0f172a;
        box-sizing: border-box;
    }

    .name-display {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 16px;
        font-weight: 700;
        color: #0f172a;
        background: transparent;
        border: none;
        cursor: pointer;
        padding: 0;
        text-align: left;
        width: 100%;
    }

    .name-display:hover {
        color: hsl(173, 58%, 39%);
    }

    .edit-hint {
        font-size: 12px;
        opacity: 0;
        transition: opacity 0.15s;
    }

    .name-display:hover .edit-hint {
        opacity: 1;
    }

    .name-placeholder {
        font-size: 16px;
        font-weight: 700;
        color: #94a3b8;
    }

    :global(.back-link) {
        display: block;
        font-size: 12px;
        color: #94a3b8 !important;
        margin-top: 6px;
        text-decoration: none;
    }

    :global(.back-link:hover) {
        color: hsl(173, 58%, 39%) !important;
    }

    /* ── Sidebar Sections ── */
    .sidebar-section {
        padding: 12px 16px;
        border-bottom: 1px solid #f1f5f9;
    }

    .section-header-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
    }

    .section-title {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: #94a3b8;
        text-transform: uppercase;
    }

    .icon-btn {
        width: 22px;
        height: 22px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 4px;
        background: white;
        color: hsl(173, 58%, 39%);
        cursor: pointer;
        font-size: 14px;
        font-weight: 700;
        display: flex;
        align-items: center;
        justify-content: center;
        line-height: 1;
    }

    .icon-btn:hover {
        background: #f8fafc;
    }

    /* Roles */
    .role-input-row {
        display: flex;
        gap: 6px;
        margin-bottom: 8px;
    }

    .role-input {
        flex: 1;
        padding: 5px 8px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 4px;
        font-size: 12px;
        font-family: inherit;
    }

    .role-input:focus {
        outline: none;
        border-color: hsl(173, 58%, 39%);
    }

    .role-add-btn {
        padding: 5px 10px;
        background: hsl(173, 58%, 39%);
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        cursor: pointer;
    }

    .roles-list {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .role-item {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 6px;
        border-radius: 4px;
    }

    .role-item:hover {
        background: #f8fafc;
    }

    .role-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .role-name {
        flex: 1;
        font-size: 12px;
        color: #334155;
        font-weight: 500;
    }

    .role-delete-btn {
        width: 18px;
        height: 18px;
        border: none;
        background: transparent;
        color: transparent;
        cursor: pointer;
        border-radius: 4px;
        font-size: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .role-item:hover .role-delete-btn {
        color: #94a3b8;
    }

    .role-delete-btn:hover {
        background: #fee2e2;
        color: #ef4444 !important;
    }

    /* Search */
    .search-section {
        padding: 8px 16px;
    }

    .search-input {
        width: 100%;
        padding: 7px 10px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        font-size: 12px;
        font-family: inherit;
        color: #334155;
        box-sizing: border-box;
    }

    .search-input::placeholder {
        color: #94a3b8;
    }

    .search-input:focus {
        outline: none;
        border-color: hsl(173, 58%, 39%);
        box-shadow: 0 0 0 2px hsla(173, 58%, 39%, 0.1);
    }

    /* Ops List */
    .ops-list {
        flex: 1;
        overflow-y: auto;
        padding: 12px 16px;
    }

    .loading-text {
        font-size: 12px;
        color: #94a3b8;
        font-style: italic;
    }

    .category-group {
        margin-bottom: 8px;
    }

    .category-header {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        padding: 6px 4px;
        background: transparent;
        border: none;
        cursor: pointer;
        font-family: inherit;
        border-radius: 4px;
    }

    .category-header:hover {
        background: #f8fafc;
    }

    .cat-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .cat-name {
        flex: 1;
        font-size: 12px;
        font-weight: 600;
        color: #334155;
        text-align: left;
    }

    .cat-chevron {
        font-size: 10px;
        color: #94a3b8;
        transition: transform 0.15s;
    }

    .cat-chevron.collapsed {
        transform: rotate(-90deg);
    }

    .cat-add-btn {
        width: 18px;
        height: 18px;
        border: none;
        background: transparent;
        color: #94a3b8;
        cursor: pointer;
        font-size: 14px;
        font-weight: 700;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        transition: opacity 0.15s;
    }

    .category-header:hover .cat-add-btn {
        opacity: 1;
    }

    .cat-add-btn:hover {
        color: hsl(173, 58%, 39%);
        background: #f1f5f9;
    }

    .cat-ops {
        padding-left: 20px;
        margin-top: 2px;
    }

    .op-item {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        padding: 6px 8px;
        border-radius: 6px;
        cursor: grab;
        transition: background 0.15s;
        margin-bottom: 2px;
    }

    .op-item:hover {
        background: #f8fafc;
    }

    .op-item:active {
        cursor: grabbing;
        background: #f1f5f9;
    }

    .op-icon {
        font-size: 14px;
        line-height: 1.3;
        flex-shrink: 0;
    }

    .op-info {
        display: flex;
        flex-direction: column;
        min-width: 0;
    }

    .op-name {
        font-size: 12px;
        font-weight: 600;
        color: #1e293b;
    }

    .op-desc {
        font-size: 10px;
        color: #94a3b8;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 180px;
    }

    /* Drag hint */
    .drag-hint {
        padding: 8px 16px;
        text-align: center;
    }

    .drag-hint span {
        font-size: 10px;
        color: #cbd5e1;
        font-weight: 500;
    }

    /* Footer */
    .sidebar-footer {
        padding: 12px 16px;
        border-top: 1px solid hsl(240, 5.9%, 90%);
    }

    .save-msg {
        font-size: 11px;
        text-align: center;
        margin-bottom: 6px;
        color: hsl(173, 58%, 39%);
        font-weight: 500;
    }

    .save-msg.error {
        color: hsl(0, 84.2%, 60.2%);
    }

    .save-btn {
        width: 100%;
        padding: 10px 16px;
        background: hsl(173, 58%, 39%);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s;
    }

    .save-btn:hover:not(:disabled) {
        background: hsl(173, 58%, 34%);
    }

    .save-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    /* ── Canvas ── */
    .canvas-wrapper {
        flex: 1;
        position: relative;
        background: hsl(240, 4.8%, 95.9%);
    }

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

    .toolbar-divider {
        width: 1px;
        height: 20px;
        background: hsl(240, 5.9%, 90%);
    }

    .toolbar-label {
        font-size: 11px;
        color: #475569;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .toolbar-time-input {
        padding: 3px 6px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 4px;
        font-size: 11px;
        font-family: "JetBrains Mono", monospace;
        width: 80px;
    }

    .canvas-loading {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
        gap: 12px;
        color: #94a3b8;
    }

    .spinner {
        width: 28px;
        height: 28px;
        border: 3px solid #e2e8f0;
        border-top-color: hsl(173, 58%, 39%);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
</style>
