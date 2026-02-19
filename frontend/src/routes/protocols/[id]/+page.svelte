<script lang="ts">
    import { onMount, setContext } from "svelte";
    import { page } from '$app/stores';
    import {
        SvelteFlow,
        Background,
        Controls,
        MiniMap,
        Position,
        SelectionMode,
        type Node,
        type Edge,
        type Viewport,
    } from "@xyflow/svelte";
    import "@xyflow/svelte/dist/style.css";

    import { api } from "$lib/api";
    import { getCategoryColor, getCategoryIcon } from "$lib/categoryColors";
    import { getCurrentOrg } from "$lib/auth.svelte";
    import UnitOpNode from "$lib/components/UnitOpNode.svelte";
    import SwimLaneNode from "$lib/components/SwimLaneNode.svelte";
    import Inspector from "$lib/components/Inspector.svelte";
    import TimeAxis from "$lib/components/TimeAxis.svelte";
    import CreateUnitOpModal from "$lib/components/CreateUnitOpModal.svelte";

    const id = $derived($page.params.id);

    // --- Node Types ---
    const nodeTypes = { unitOp: UnitOpNode, swimLane: SwimLaneNode };

    // --- State ---
    let protocol = $state<any>(null);
    let unitOps = $state<any[]>([]);
    let roles = $state<any[]>([]);
    let orgEquipment = $state<any[]>([]);
    let equipmentConflicts = $state<Map<string, string[]>>(new Map());
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
    let handleOrientation = $state<"horizontal" | "vertical">("horizontal");
    let timeEnabled = $state(false);
    let pixelsPerHour = $state(200);

    // Interaction mode: pan (default) vs select
    let interactionMode = $state<"pan" | "select">("pan");

    // Track unsaved changes
    let hasUnsavedChanges = $state(false);
    let lastSavedState = $state<string>("");

    // Compute current state as JSON for comparison
    const currentState = $derived(() => {
        return JSON.stringify({
            nodes,
            edges,
            layout,
            handleOrientation,
            timeEnabled,
            pixelsPerHour,
        });
    });

    // Track changes
    $effect(() => {
        if (lastSavedState && currentState() !== lastSavedState) {
            hasUnsavedChanges = true;
        }
    });

    // Detect equipment conflicts when edges or nodes change
    $effect(() => {
        if (nodes.length > 0 && edges.length > 0) {
            detectEquipmentConflicts();
        }
    });

    // Provide handle orientation and node actions to child node components via context
    setContext("protocolHandleOrientation", {
        get value() {
            return handleOrientation;
        },
    });

    setContext("branchValidation", {
        get invalidNodeIds() {
            return branchInvalidNodeIds();
        },
    });

    setContext("nodeActions", {
        setNodeHandleOrientation(
            nodeId: string,
            orientation: "horizontal" | "vertical" | null,
        ) {
            const effective = orientation ?? handleOrientation;
            nodes = nodes.map((n) => {
                if (n.id === nodeId && n.type === "unitOp") {
                    const newData = { ...n.data };
                    if (orientation === null) {
                        delete newData.handleOrientation;
                        delete newData.sourcePosition;
                        delete newData.targetPosition;
                    } else {
                        newData.handleOrientation = orientation;
                        delete newData.sourcePosition;
                        delete newData.targetPosition;
                    }
                    return {
                        ...n,
                        data: newData,
                        sourcePosition:
                            effective === "horizontal"
                                ? Position.Right
                                : Position.Bottom,
                        targetPosition:
                            effective === "horizontal"
                                ? Position.Left
                                : Position.Top,
                    };
                }
                return n;
            });
        },
        setNodeHandlePosition(
            nodeId: string,
            handleType: "source" | "target",
            position: Position,
        ) {
            nodes = nodes.map((n) => {
                if (n.id === nodeId && n.type === "unitOp") {
                    const newData = { ...n.data };
                    // Store per-handle positions and clear the preset orientation
                    delete newData.handleOrientation;
                    if (handleType === "source") {
                        newData.sourcePosition = position;
                        // Keep existing target or derive from protocol default
                        if (!newData.targetPosition) {
                            newData.targetPosition =
                                handleOrientation === "horizontal"
                                    ? Position.Left
                                    : Position.Top;
                        }
                    } else {
                        newData.targetPosition = position;
                        // Keep existing source or derive from protocol default
                        if (!newData.sourcePosition) {
                            newData.sourcePosition =
                                handleOrientation === "horizontal"
                                    ? Position.Right
                                    : Position.Bottom;
                        }
                    }
                    return {
                        ...n,
                        data: newData,
                        sourcePosition: newData.sourcePosition as Position,
                        targetPosition: newData.targetPosition as Position,
                    };
                }
                return n;
            });
        },
        onNodeResized(nodeId: string, width: number, height: number) {
            if (!timeEnabled) return; // free-form resize, no duration sync
            const sizePx = layout === "horizontal" ? width : height;
            let minutes = (sizePx / pixelsPerHour) * 60;
            minutes = Math.round(minutes / 5) * 5; // snap to 5-min
            minutes = Math.max(5, minutes);         // minimum 5 min
            // Re-snap the visual size
            const snappedPx = (minutes / 60) * pixelsPerHour;
            nodes = nodes.map(n => {
                if (n.id !== nodeId) return n;
                return {
                    ...n,
                    data: { ...n.data, duration_min: minutes },
                    width: layout === "horizontal" ? snappedPx : n.width,
                    height: layout === "vertical" ? snappedPx : n.height,
                };
            });
        },
        deleteNode(nodeId: string) {
            const node = nodes.find((n) => n.id === nodeId);
            if (!node) return;
            const label = (node.data.label as string) || "this item";
            const kind = node.type === "swimLane" ? "role lane" : "unit operation";
            if (!confirm(`Delete ${kind} "${label}"? This cannot be undone.`)) return;

            // Unparent children before removing the node
            const parent = nodes.find((n) => n.id === nodeId);
            nodes = nodes
                .map((n) => {
                    if (n.parentId === nodeId) {
                        return {
                            ...n,
                            parentId: undefined,
                            position: {
                                x: n.position.x + (parent?.position.x || 0),
                                y: n.position.y + (parent?.position.y || 0),
                            },
                        };
                    }
                    return n;
                })
                .filter((n) => n.id !== nodeId);

            edges = edges.filter(
                (e) => e.source !== nodeId && e.target !== nodeId,
            );

            // Clear inspector if the deleted node was selected
            if (selectedNodeId === nodeId) {
                selectedNodeId = null;
            }
        },
    });

    setContext("timelineConfig", {
        get enabled() { return timeEnabled; },
        get pixelsPerHour() { return pixelsPerHour; },
        get layout() { return layout; },
        get snapMinutes() { return 5; },
    });

    // Inline name editing
    let editingName = $state(false);
    let nameInput = $state("");

    // Inline description editing
    let editingDescription = $state(false);
    let descriptionInput = $state("");

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

    const hasUnitOpNodes = $derived(nodes.some((n) => n.type === "unitOp"));

    async function previewSop() {
        if (!protocol) return;
        await save();
        const name = protocol.name.replace(/\s+/g, '_');
        api.downloadBlob(
            `/science/protocols/${protocol.id}/pdf/sop`,
            `SOP_Preview_${name}.pdf`
        );
    }

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

    // --- Branch-to-swimlane validation ---
    const branchValidationErrors = $derived(() => {
        const errors: Array<{
            sourceNodeId: string;
            sourceNodeLabel: string;
            duplicateLane: string | null;
            targetNodeLabels: string[];
        }> = [];

        // Build outgoing edge map: sourceId -> [targetId, ...]
        const outgoingMap = new Map<string, string[]>();
        for (const edge of edges) {
            if (!outgoingMap.has(edge.source)) outgoingMap.set(edge.source, []);
            outgoingMap.get(edge.source)!.push(edge.target);
        }

        // Exception: no swimlanes + purely linear → skip
        const hasSwimlanes = nodes.some((n) => n.type === "swimLane");
        const hasBranching = [...outgoingMap.values()].some((t) => t.length >= 2);
        if (!hasSwimlanes && !hasBranching) return errors;

        // Node lookup map
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));

        // For each branching node, group targets by parentId
        for (const [sourceId, targetIds] of outgoingMap) {
            if (targetIds.length < 2) continue;
            const src = nodeMap.get(sourceId);
            if (!src || src.type !== "unitOp") continue;

            const laneGroups = new Map<string | null, string[]>();
            for (const tid of targetIds) {
                const t = nodeMap.get(tid);
                if (!t || t.type !== "unitOp") continue;
                const lane = t.parentId ?? null;
                if (!laneGroups.has(lane)) laneGroups.set(lane, []);
                laneGroups.get(lane)!.push(tid);
            }

            for (const [lane, group] of laneGroups) {
                if (group.length >= 2) {
                    errors.push({
                        sourceNodeId: sourceId,
                        sourceNodeLabel: (src.data as any).label || "Unnamed",
                        duplicateLane: lane,
                        targetNodeLabels: group.map(
                            (id) => (nodeMap.get(id)?.data as any)?.label || "Unnamed",
                        ),
                    });
                }
            }
        }
        return errors;
    });

    const branchInvalidNodeIds = $derived(() => {
        const ids = new Set<string>();
        for (const err of branchValidationErrors()) {
            ids.add(err.sourceNodeId);
        }
        return ids;
    });

    // --- Timeline helpers ---
    const totalHours = $derived(() => {
        if (!timeEnabled) return 8;
        let maxEnd = 0;
        for (const n of nodes) {
            if (n.type !== "unitOp") continue;
            const pos = layout === "horizontal" ? n.position.x : n.position.y;
            const dur = (n.data.duration_min as number) || 30;
            const sizePx = (dur / 60) * pixelsPerHour;
            maxEnd = Math.max(maxEnd, pos + sizePx);
        }
        return Math.max(8, Math.ceil(maxEnd / pixelsPerHour) + 1);
    });

    const snapGridPx = $derived((5 / 60) * pixelsPerHour);

    function applyTimelineSizing() {
        nodes = nodes.map(n => {
            if (n.type !== "unitOp") return n;
            const dur = (n.data.duration_min as number) || 30;
            const sizePx = (dur / 60) * pixelsPerHour;
            return {
                ...n,
                width: layout === "horizontal" ? sizePx : n.width,
                height: layout === "vertical" ? sizePx : n.height,
            };
        });
    }

    function clearTimelineSizing() {
        nodes = nodes.map(n => {
            if (n.type !== "unitOp") return n;
            return { ...n, width: undefined, height: undefined };
        });
    }

    // --- Data Loading ---
    async function loadData() {
        try {
            unitOps = await api.get("/science/unit-ops");

            // Load organization equipment
            const org = getCurrentOrg();
            if (org?.id) {
                orgEquipment = await api.get(`/iam/organizations/${org.id}/equipment`);
            }

            if (id && id !== "new") {
                protocol = await api.get(`/science/protocols/${id}`);
                roles = protocol.roles || [];

                if (protocol.graph && protocol.graph.nodes) {
                    nodes = protocol.graph.nodes;
                    edges = protocol.graph.edges || [];
                    layout = protocol.graph.layout || "horizontal";
                    handleOrientation =
                        protocol.graph.handleOrientation || "horizontal";
                    timeEnabled = protocol.graph.timeEnabled || false;
                    pixelsPerHour = protocol.graph.pixelsPerHour || 200;
                    detectEquipmentConflicts();
                }
            }
            // Apply timeline sizing if loaded with timeline enabled
            if (timeEnabled) {
                applyTimelineSizing();
            }

            // Initialize saved state for change tracking
            lastSavedState = JSON.stringify({
                nodes,
                edges,
                layout,
                handleOrientation,
                timeEnabled,
                pixelsPerHour,
            });
            hasUnsavedChanges = false;
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

    // --- Description Editing ---
    async function saveDescription() {
        if (!protocol) {
            editingDescription = false;
            return;
        }
        try {
            await api.put(`/science/protocols/${protocol.id}`, {
                description: descriptionInput.trim(),
            });
            protocol.description = descriptionInput.trim();
        } catch (e) {
            // silent
        }
        editingDescription = false;
    }

    function startEditingDescription() {
        descriptionInput = protocol?.description || "";
        editingDescription = true;
    }

    function handleDescriptionKeydown(e: KeyboardEvent) {
        if (e.key === "Escape") editingDescription = false;
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
                    zIndex: n.zIndex,
                    data: n.data,
                    width: n.width ?? n.measured?.width,
                    height: n.height ?? n.measured?.height,
                    style: n.style,
                })),
                edges: edges.map((e) => ({
                    id: e.id,
                    source: e.source,
                    target: e.target,
                })),
                layout,
                handleOrientation,
                timeEnabled,
                pixelsPerHour,
            };

            await api.put(`/science/protocols/${protocol.id}`, {
                graph: graphData,
            });
            saveMessage = "Saved!";
            setTimeout(() => (saveMessage = null), 2000);
            // Mark as saved
            lastSavedState = JSON.stringify({
                nodes,
                edges,
                layout,
                handleOrientation,
                timeEnabled,
                pixelsPerHour,
            });
            hasUnsavedChanges = false;
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

        // Compute dimensions for timeline sizing
        let nodeWidth: number | undefined;
        let nodeHeight: number | undefined;
        if (timeEnabled) {
            const sizePx = (30 / 60) * pixelsPerHour; // default 30min
            if (layout === "horizontal") nodeWidth = sizePx;
            else nodeHeight = sizePx;
        }

        const newNode: Node = {
            id: crypto.randomUUID(),
            type: "unitOp",
            zIndex: 1,
            position,
            parentId,
            width: nodeWidth,
            height: nodeHeight,
            data: {
                label: op.name,
                unitOpId: op.id,
                category: op.category,
                description: op.description || "",
                duration_min: 30,
                params: defaultParams,
                paramSchema: op.param_schema || {},
            },
        };

        nodes = [...nodes, newNode];
    }

    // --- Equipment Management ---
    async function handleCreateEquipment(data: { name: string; description: string; equipment_type: string; location: string }): Promise<any> {
        const org = getCurrentOrg();
        if (!org?.id) throw new Error("No organization");

        const newEquipment: any = await api.post(
            `/iam/organizations/${org.id}/equipment`,
            {
                name: data.name,
                description: data.description,
                equipment_type: data.equipment_type,
                location: data.location,
            }
        );

        orgEquipment = [...orgEquipment, newEquipment];
        return newEquipment;
    }

    // --- Equipment Conflict Detection ---
    function detectEquipmentConflicts() {
        const adjacency = new Map<string, Set<string>>();
        for (const e of edges) {
            if (!adjacency.has(e.source)) adjacency.set(e.source, new Set());
            adjacency.get(e.source)!.add(e.target);
        }

        function reachable(start: string): Set<string> {
            const visited = new Set<string>();
            const queue = [start];
            while (queue.length) {
                const cur = queue.shift()!;
                for (const next of adjacency.get(cur) ?? []) {
                    if (!visited.has(next)) { visited.add(next); queue.push(next); }
                }
            }
            return visited;
        }

        const unitOpNodes = nodes.filter(n => n.type === "unitOp");
        const conflicts = new Map<string, string[]>();

        for (let i = 0; i < unitOpNodes.length; i++) {
            for (let j = i + 1; j < unitOpNodes.length; j++) {
                const a = unitOpNodes[i], b = unitOpNodes[j];
                const aReach = reachable(a.id), bReach = reachable(b.id);
                const concurrent = !aReach.has(b.id) && !bReach.has(a.id);
                if (!concurrent) continue;

                const aEq = (a.data?.equipment as any[] ?? []);
                const bEq = (b.data?.equipment as any[] ?? []);
                for (const ae of aEq) {
                    if (ae.shareable) continue;
                    const match = bEq.find((be: any) => be.equipment_id === ae.equipment_id && !be.shareable);
                    if (match) {
                        if (!conflicts.has(a.id)) conflicts.set(a.id, []);
                        if (!conflicts.has(b.id)) conflicts.set(b.id, []);
                        conflicts.get(a.id)!.push(ae.equipment_id);
                        conflicts.get(b.id)!.push(ae.equipment_id);
                    }
                }
            }
        }
        equipmentConflicts = conflicts;
    }

    // --- Inspector Apply ---
    function handleInspectorApply(
        nodeId: string,
        params: Record<string, any>,
        duration: number,
        description: string,
        equipment: any[] = [],
        paramSchema: Record<string, any> = {},
        position?: { x: number; y: number },
    ): void {
        nodes = nodes.map((n) => {
            if (n.id === nodeId) {
                let width = n.width;
                let height = n.height;
                if (timeEnabled) {
                    const sizePx = (duration / 60) * pixelsPerHour;
                    if (layout === "horizontal") width = sizePx;
                    else height = sizePx;
                }
                return {
                    ...n,
                    width,
                    height,
                    position: position ?? n.position,
                    data: {
                        ...n.data,
                        params,
                        duration_min: duration,
                        description,
                        equipment,
                        paramSchema,
                    },
                };
            }
            return n;
        });
        detectEquipmentConflicts();
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
                zIndex: -1,
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

    // --- Save as New Unit Op (from Inspector) ---
    async function handleSaveAsNew(
        name: string,
        paramSchema: Record<string, any>,
        category: string,
    ): Promise<void> {
        const created = await api.post('/science/unit-ops', {
            name,
            category: category || 'General',
            description: '',
            param_schema: paramSchema,
        });
        unitOps = [...unitOps, created];
    }

    function openCreateModal(category: string) {
        createModalCategory = category;
        showCreateModal = true;
    }

    onMount(() => {
        loadData();

        // Warn user if they try to leave with unsaved changes
        const handleBeforeUnload = (e: BeforeUnloadEvent) => {
            if (hasUnsavedChanges) {
                e.preventDefault();
                e.returnValue = "";
                return "";
            }
        };

        window.addEventListener("beforeunload", handleBeforeUnload);

        return () => {
            window.removeEventListener("beforeunload", handleBeforeUnload);
        };
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
                    <span class="edit-hint">&#9998;</span>
                </button>
            {:else}
                <span class="name-placeholder">Loading...</span>
            {/if}

            {#if protocol}
                {#if editingDescription}
                    <textarea
                        bind:value={descriptionInput}
                        onblur={saveDescription}
                        onkeydown={handleDescriptionKeydown}
                        class="description-input"
                        rows="2"
                        placeholder="Add a description..."
                        autofocus
                    ></textarea>
                {:else}
                    <button class="description-display" onclick={startEditingDescription}>
                        {protocol.description || "Add description..."}
                    </button>
                {/if}

                <a href="/projects/{protocol.project_id}" class="back-link">
                    &#8592; Back to Project
                </a>
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
                            onclick={() => deleteRole(role.id)}>&#10005;</button
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
                                )}>&#9662;</span
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
            <span>Drag nodes to canvas to add</span>
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
            {#if hasUnitOpNodes}
                <button
                    class="preview-sop-btn"
                    onclick={previewSop}
                    disabled={!protocol}
                >
                    Preview SOP
                </button>
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
            <div class="mode-toggle">
                <button
                    class="mode-btn"
                    class:active={interactionMode === "pan"}
                    onclick={() => (interactionMode = "pan")}
                    title="Pan mode (hold Shift to select)"
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v1"/><path d="M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v6"/><path d="M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>
                </button>
                <button
                    class="mode-btn"
                    class:active={interactionMode === "select"}
                    onclick={() => (interactionMode = "select")}
                    title="Select mode (drag to select nodes)"
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/><path d="M13 13l6 6"/></svg>
                </button>
            </div>

            <div class="toolbar-divider"></div>

            <button
                class="toolbar-btn"
                class:active={layout === "horizontal"}
                onclick={toggleLayout}
                title="Toggle orientation"
            >
                {layout === "horizontal" ? "&#8596; Horizontal" : "&#8597; Vertical"}
            </button>

            <div class="toolbar-divider"></div>

            <button
                class="toolbar-btn"
                class:active={handleOrientation === "horizontal"}
                onclick={() => {
                    handleOrientation =
                        handleOrientation === "horizontal"
                            ? "vertical"
                            : "horizontal";
                    // Update node-level sourcePosition/targetPosition so
                    // NodeWrapper recalculates handle bounds for edge routing
                    const src =
                        handleOrientation === "horizontal"
                            ? Position.Right
                            : Position.Bottom;
                    const tgt =
                        handleOrientation === "horizontal"
                            ? Position.Left
                            : Position.Top;
                    nodes = nodes.map((n) => {
                        if (
                            n.type === "unitOp" &&
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
                }}
                title="Toggle handle orientation"
            >
                {handleOrientation === "horizontal"
                    ? "&#8594; Handles H"
                    : "&#8595; Handles V"}
            </button>

            <div class="toolbar-divider"></div>

            <button
                class="toolbar-btn"
                class:active={timeEnabled}
                onclick={() => {
                    timeEnabled = !timeEnabled;
                    if (timeEnabled) {
                        applyTimelineSizing();
                    } else {
                        clearTimelineSizing();
                    }
                }}
            >
                Time: {timeEnabled ? "ON" : "OFF"}
            </button>
        </div>

        <!-- Branch validation banner -->
        {#if branchValidationErrors().length > 0}
            <div class="validation-banner">
                <span class="validation-icon">&#x26A0;</span>
                <div class="validation-content">
                    {#each branchValidationErrors() as err}
                        <div class="validation-item">
                            <strong>{err.sourceNodeLabel}</strong> branches to
                            {err.targetNodeLabels.join(" & ")} in
                            {#if err.duplicateLane === null}
                                <em>no swimlane</em>
                            {:else}
                                the <em>same swimlane</em>
                            {/if}
                            — move each branch target to a different role.
                        </div>
                    {/each}
                </div>
            </div>
        {/if}

        <!-- Time axis overlay -->
        {#if timeEnabled}
            <TimeAxis
                {layout}
                totalHours={totalHours()}
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
            <SvelteFlow
                bind:nodes
                bind:edges
                bind:viewport
                {nodeTypes}
                fitView
                elevateNodesOnSelect={false}
                selectionMode={SelectionMode.Partial}
                selectionOnDrag={interactionMode === "select"}
                panOnDrag={interactionMode === "pan"}
                snapToGrid={timeEnabled}
                snapGrid={timeEnabled ? [snapGridPx, snapGridPx] : [1, 1]}
            >
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
            {orgEquipment}
            {equipmentConflicts}
            onApply={handleInspectorApply}
            onSaveAsNew={handleSaveAsNew}
            onCreateEquipment={handleCreateEquipment}
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

    .description-input {
        width: 100%;
        font-size: 12px;
        padding: 6px 8px;
        border: 1.5px solid hsl(173, 58%, 39%);
        border-radius: 6px;
        outline: none;
        color: #334155;
        box-sizing: border-box;
        font-family: inherit;
        resize: vertical;
        margin-top: 6px;
    }

    .description-display {
        display: block;
        font-size: 12px;
        color: #94a3b8;
        background: transparent;
        border: none;
        cursor: pointer;
        padding: 0;
        text-align: left;
        width: 100%;
        margin-top: 6px;
        line-height: 1.4;
        word-break: break-word;
    }

    .description-display:hover {
        color: hsl(173, 58%, 39%);
    }

    .back-link {
        display: block;
        font-size: 12px;
        color: #94a3b8;
        margin-top: 6px;
        text-decoration: none;
    }

    .back-link:hover {
        color: hsl(173, 58%, 39%);
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

    .preview-sop-btn {
        width: 100%;
        padding: 9px 16px;
        background: white;
        color: hsl(173, 58%, 39%);
        border: 1px solid hsl(173, 58%, 39%);
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s;
        margin-bottom: 8px;
    }

    .preview-sop-btn:hover:not(:disabled) {
        background: hsl(173, 58%, 96%);
    }

    .preview-sop-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
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

    .toolbar-divider {
        width: 1px;
        height: 20px;
        background: hsl(240, 5.9%, 90%);
    }

    .validation-banner {
        position: absolute;
        top: 56px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 10;
        display: flex;
        align-items: flex-start;
        gap: 8px;
        padding: 8px 14px;
        background: #fffbeb;
        border: 1px solid #f59e0b;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(245, 158, 11, 0.15);
        max-width: 520px;
    }

    .validation-icon {
        font-size: 16px;
        line-height: 1.4;
        flex-shrink: 0;
    }

    .validation-content {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .validation-item {
        font-size: 12px;
        color: #92400e;
        line-height: 1.4;
    }

    .validation-item strong {
        font-weight: 700;
    }

    .validation-item em {
        font-style: italic;
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
