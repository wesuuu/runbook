<script lang="ts">
    import type { Node } from "@xyflow/svelte";
    import { X } from "lucide-svelte";
    import { fly } from "svelte/transition";
    import { cubicOut } from "svelte/easing";
    import { Button } from "$lib/components/ui/button";

    interface Props {
        node: Node | null;
        onApply: (nodeId: string, label: string, description: string) => void;
        onClose: () => void;
    }

    let { node, onApply, onClose }: Props = $props();

    let editLabel: string = $state("");
    let editDescription: string = $state("");
    let initNodeId: string | null = $state(null);

    $effect(() => {
        if (node && node.id !== initNodeId) {
            initNodeId = node.id;
            editLabel = (node.data.label as string) || "";
            editDescription = (node.data.description as string) || "";
        }
    });

    function handleApply(): void {
        if (!node) return;
        onApply(node.id, editLabel, editDescription);
    }

    const shortId = $derived(node?.id?.slice(0, 8).toUpperCase() || "");
</script>

{#if node}
    <aside
    class="inspector"
    data-tour="protocol-inspector"
    transition:fly|global={{ x: 320, duration: 220, easing: cubicOut, opacity: 1 }}
>
        <!-- Header -->
        <div class="inspector-header">
            <div class="header-top">
                <div class="header-icon">&#x25B6;</div>
                <h2 class="header-title">INSPECTOR</h2>
                <Button variant="ghost" size="icon-sm" onclick={onClose} aria-label="Close">
                    <X class="size-4" />
                </Button>
            </div>

            <div class="node-info">
                <h3 class="node-name">{editLabel || "Process Start"}</h3>
                <div class="node-badges">
                    <span class="badge id-badge">{shortId}</span>
                    <span class="badge type-badge">PROCESS START</span>
                </div>
            </div>
        </div>

        <!-- Process Name -->
        <div class="section">
            <label class="section-label" for="process-name">Process Name</label>
            <input
                id="process-name"
                type="text"
                class="input-field"
                bind:value={editLabel}
                oninput={handleApply}
                placeholder="e.g. Upstream Process"
            />
        </div>

        <!-- Description -->
        <div class="section">
            <label class="section-label" for="process-description">Description</label>
            <textarea
                id="process-description"
                class="input-field description-textarea"
                bind:value={editDescription}
                oninput={handleApply}
                placeholder="Describe this process section..."
                rows="4"
            ></textarea>
        </div>
    </aside>
{/if}

<style>
    .inspector {
        width: 320px;
        background: white;
        border-left: 1px solid hsl(240, 5.9%, 90%);
        display: flex;
        flex-direction: column;
        overflow-y: auto;
        font-family: "Inter", system-ui, sans-serif;
        position: relative;
        z-index: 20;
    }

    .inspector-header {
        padding: 16px;
        border-bottom: 1px solid hsl(240, 5.9%, 90%);
    }

    .header-top {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 14px;
    }

    .header-icon {
        width: 32px;
        height: 32px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 16px;
        background: #6366f1;
        color: white;
    }

    .header-title {
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: #64748b;
        flex: 1;
    }

    .node-info {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .node-name {
        font-size: 18px;
        font-weight: 700;
        color: #0f172a;
        margin: 0;
    }

    .node-badges {
        display: flex;
        gap: 6px;
    }

    .badge {
        font-size: 10px;
        font-weight: 600;
        padding: 3px 8px;
        border-radius: 4px;
    }

    .id-badge {
        background: #f1f5f9;
        color: #64748b;
        font-family: "JetBrains Mono", monospace;
    }

    .type-badge {
        background: #eef2ff;
        color: #6366f1;
        letter-spacing: 0.04em;
    }

    .section {
        padding: 16px;
        border-bottom: 1px solid #f1f5f9;
    }

    .section-label {
        display: block;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: #94a3b8;
        text-transform: uppercase;
        margin-bottom: 12px;
    }

    .input-field {
        width: 100%;
        padding: 8px 10px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        font-size: 13px;
        color: #1e293b;
        background: white;
        transition: border-color 0.15s;
        font-family: inherit;
        box-sizing: border-box;
    }

    .input-field:focus {
        outline: none;
        border-color: #6366f1;
        box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.15);
    }

    .description-textarea {
        resize: vertical;
        min-height: 60px;
        line-height: 1.4;
    }
</style>
