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
    import { Button } from "$lib/components/ui/button";

    let { params } = $props();

    // State
    let protocol = $state<any>(null);
    let unitOps = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let saving = $state(false);
    let saveMessage = $state<string | null>(null);

    // Flow State
    let nodes = $state<Node[]>([]);
    let edges = $state<Edge[]>([]);
    let viewport = $state<Viewport>({ x: 0, y: 0, zoom: 1 });

    // Inline name editing
    let editingName = $state(false);
    let nameInput = $state("");
    let flowContainer: HTMLDivElement;

    // Group unit ops by category
    let categories = $derived(() => {
        const map = new Map<string, any[]>();
        for (const op of unitOps) {
            const cat = op.category || "General";
            if (!map.has(cat)) map.set(cat, []);
            map.get(cat)!.push(op);
        }
        return map;
    });

    async function loadData() {
        try {
            // Always load unit ops
            unitOps = await api.get("/science/unit-ops");

            // Load existing protocol
            if (params.id && params.id !== "new") {
                protocol = await api.get(`/science/protocols/${params.id}`);
                if (protocol.graph) {
                    nodes = protocol.graph.nodes || [];
                    edges = protocol.graph.edges || [];
                }
            }
        } catch (e: any) {
            error = e.message;
        } finally {
            loading = false;
        }
    }

    async function saveName() {
        if (!protocol || !nameInput.trim()) return;
        try {
            await api.put(`/science/protocols/${protocol.id}`, {
                name: nameInput.trim(),
            });
            protocol.name = nameInput.trim();
            editingName = false;
        } catch (e: any) {
            console.error("Failed to save name:", e);
        }
    }

    function startEditingName() {
        nameInput = protocol?.name || "";
        editingName = true;
    }

    function handleNameKeydown(e: KeyboardEvent) {
        if (e.key === "Enter") {
            saveName();
        } else if (e.key === "Escape") {
            editingName = false;
        }
    }

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
                    data: n.data,
                })),
                edges: edges.map((e) => ({
                    id: e.id,
                    source: e.source,
                    target: e.target,
                })),
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
        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = "move";
        }
    }

    function onDrop(event: DragEvent) {
        event.preventDefault();
        if (!event.dataTransfer) return;

        const opData = event.dataTransfer.getData("application/svelteflow");
        if (!opData) return;

        const op = JSON.parse(opData);

        // Convert screen coordinates to flow coordinates
        // accounting for SvelteFlow's viewport transform (pan + zoom)
        const bounds = flowContainer.getBoundingClientRect();
        const position = {
            x: (event.clientX - bounds.left - viewport.x) / viewport.zoom,
            y: (event.clientY - bounds.top - viewport.y) / viewport.zoom,
        };

        const newNode: Node = {
            id: crypto.randomUUID(),
            type: "default",
            position,
            data: { label: op.name, unitOpId: op.id, category: op.category },
        };

        nodes = [...nodes, newNode];
    }

    onMount(() => {
        loadData();
    });
</script>

<div class="h-[calc(100vh-57px)] flex">
    <!-- Sidebar -->
    <aside
        class="w-72 bg-background border-r border-border flex flex-col overflow-hidden"
    >
        <!-- Header -->
        <div class="p-4 border-b border-border">
            {#if editingName}
                <input
                    type="text"
                    bind:value={nameInput}
                    onblur={saveName}
                    onkeydown={handleNameKeydown}
                    class="text-lg font-bold text-foreground w-full bg-transparent border-b-2 border-primary outline-none py-0.5"
                />
            {:else}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <h1
                    class="text-lg font-bold text-foreground truncate cursor-pointer hover:text-primary transition-colors"
                    onclick={startEditingName}
                    title="Click to edit name"
                >
                    {protocol?.name || "Loading..."}
                </h1>
            {/if}
            {#if protocol?.project_id}
                <Link
                    to={`/projects/${protocol.project_id}`}
                    class="text-sm text-muted-foreground hover:text-primary transition-colors"
                >
                    &larr; Back to Project
                </Link>
            {/if}
        </div>

        <!-- Unit Operations -->
        <div class="flex-1 overflow-y-auto p-4">
            <h2
                class="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3"
            >
                Unit Operations
            </h2>
            <p class="text-xs text-muted-foreground mb-4">
                Drag onto the canvas to add
            </p>

            {#if unitOps.length === 0}
                <p class="text-sm text-muted-foreground italic">Loading...</p>
            {:else}
                {#each [...categories().entries()] as [category, ops]}
                    <div class="mb-4">
                        <h3
                            class="text-[11px] font-semibold text-primary uppercase tracking-wide mb-2"
                        >
                            {category}
                        </h3>
                        <div class="space-y-1.5">
                            {#each ops as op}
                                <div
                                    role="button"
                                    tabindex="0"
                                    draggable={true}
                                    ondragstart={(e) => onDragStart(e, op)}
                                    class="bg-muted border border-border p-2.5 rounded-md cursor-grab hover:border-primary hover:shadow-sm active:cursor-grabbing transition-all text-sm font-medium text-foreground"
                                >
                                    <div class="flex items-center gap-2">
                                        <span
                                            class="w-2 h-2 rounded-full bg-primary/60 shrink-0"
                                        ></span>
                                        {op.name}
                                    </div>
                                    {#if op.description}
                                        <p
                                            class="text-xs text-muted-foreground mt-1 ml-4"
                                        >
                                            {op.description}
                                        </p>
                                    {/if}
                                </div>
                            {/each}
                        </div>
                    </div>
                {/each}
            {/if}
        </div>

        <!-- Save Button -->
        <div class="p-4 border-t border-border">
            {#if saveMessage}
                <p
                    class="text-xs text-center mb-2 {saveMessage.startsWith(
                        'Failed',
                    )
                        ? 'text-destructive'
                        : 'text-primary'}"
                >
                    {saveMessage}
                </p>
            {/if}
            <Button
                class="w-full"
                onclick={save}
                disabled={saving || !protocol}
            >
                {saving ? "Saving..." : "Save Protocol"}
            </Button>
        </div>
    </aside>

    <!-- Flow Canvas -->
    <div
        class="flex-1 relative bg-muted/30"
        role="region"
        aria-label="Protocol Editor"
        ondrop={onDrop}
        ondragover={onDragOver}
        bind:this={flowContainer}
    >
        {#if loading}
            <div
                class="absolute inset-0 flex items-center justify-center text-muted-foreground"
            >
                Loading editor...
            </div>
        {:else if error}
            <div
                class="absolute inset-0 flex items-center justify-center text-destructive"
            >
                Error: {error}
            </div>
        {:else}
            <SvelteFlow bind:nodes bind:edges bind:viewport fitView>
                <Background />
                <Controls />
                <MiniMap />
            </SvelteFlow>
        {/if}
    </div>
</div>
