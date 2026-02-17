<script lang="ts">
    import { onMount } from "svelte";
    import { page } from '$app/stores';
    import {
        SvelteFlow,
        Background,
        Controls,
        type Node,
        type Edge,
    } from "@xyflow/svelte";
    import "@xyflow/svelte/dist/style.css";

    import { api } from "$lib/api";

    const id = $derived($page.params.id);

    let experiment = $state<any>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    let selectedNode = $state<Node | null>(null);
    let nodeData = $state<any>({});

    // Flow State
    let nodes = $state<Node[]>([]);
    let edges = $state<Edge[]>([]);

    async function loadData() {
        try {
            experiment = await api.get(`/science/experiments/${id}`);
            if (experiment.graph) {
                nodes = experiment.graph.nodes || [];
                edges = experiment.graph.edges || [];
            }
        } catch (e: any) {
            error = e.message;
        } finally {
            loading = false;
        }
    }

    async function saveNodeData() {
        if (!experiment || !selectedNode) return;

        try {
            const updatedExecutionData = {
                ...experiment.execution_data,
                [selectedNode.id]: {
                    ...nodeData,
                    timestamp: new Date().toISOString(),
                },
            };

            await api.put(`/science/experiments/${experiment.id}`, {
                execution_data: updatedExecutionData,
            });

            experiment.execution_data = updatedExecutionData;
        } catch (e: any) {
            console.error(`Failed to save: ${e.message}`);
        }
    }

    function onNodeClick({ node }: { node: Node }) {
        selectedNode = node;
        nodeData =
            (experiment.execution_data && experiment.execution_data[node.id]) ||
            {};
    }

    onMount(() => {
        loadData();
    });
</script>

<div class="h-[calc(100vh-64px)] flex bg-slate-50">
    <!-- Main Execution View -->
    <div class="flex-1 relative border-r border-slate-200">
        <div
            class="absolute top-4 left-4 z-10 bg-white/90 p-2 rounded shadow backdrop-blur"
        >
            <h1 class="font-bold text-slate-800">
                {experiment?.name || "Loading..."}
            </h1>
            <a
                href="/projects/{experiment?.project_id}"
                class="text-xs text-slate-500 hover:text-teal-600"
            >
                &larr; Back to Project
            </a>
        </div>

        {#if loading}
            <div
                class="absolute inset-0 flex items-center justify-center text-slate-400"
            >
                Loading...
            </div>
        {:else}
            <SvelteFlow bind:nodes bind:edges fitView onnodeclick={onNodeClick}>
                <Background />
                <Controls />
            </SvelteFlow>
        {/if}
    </div>

    <!-- Data Entry Panel -->
    <aside class="w-80 bg-white p-6 overflow-y-auto">
        {#if selectedNode}
            <h2 class="text-xl font-bold text-slate-800 mb-4">
                {selectedNode.data.label}
            </h2>
            <div class="text-xs text-slate-400 mb-6 font-mono">
                ID: {selectedNode.id}
            </div>

            <div class="space-y-4">
                <div>
                    <label
                        for="notes"
                        class="block text-sm font-medium text-slate-700 mb-1"
                        >Notes</label
                    >
                    <textarea
                        id="notes"
                        bind:value={nodeData.notes}
                        class="w-full px-3 py-2 border border-slate-300 rounded focus:border-teal-500 outline-none"
                        rows="3"
                    ></textarea>
                </div>

                <div>
                    <label
                        for="value"
                        class="block text-sm font-medium text-slate-700 mb-1"
                        >Value (Measurement)</label
                    >
                    <input
                        type="text"
                        id="value"
                        bind:value={nodeData.value}
                        class="w-full px-3 py-2 border border-slate-300 rounded focus:border-teal-500 outline-none"
                    />
                </div>

                <button
                    onclick={saveNodeData}
                    class="w-full bg-indigo-600 text-white py-2 rounded font-medium hover:bg-indigo-700 transition"
                >
                    Log Data
                </button>

                {#if experiment?.execution_data?.[selectedNode.id]}
                    <div class="mt-6 pt-6 border-t border-slate-100">
                        <h3 class="text-sm font-semibold text-slate-500 mb-2">
                            Last Logged
                        </h3>
                        <pre
                            class="bg-slate-50 p-2 rounded text-xs overflow-auto">
{JSON.stringify(experiment.execution_data[selectedNode.id], null, 2)}
                    </pre>
                    </div>
                {/if}
            </div>
        {:else}
            <div
                class="h-full flex flex-col items-center justify-center text-slate-400 text-center"
            >
                <p>Select a node to enter data.</p>
            </div>
        {/if}
    </aside>
</div>
