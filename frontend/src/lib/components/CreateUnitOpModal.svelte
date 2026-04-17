<script lang="ts">
    import { categoryColors } from "$lib/categoryColors";
    import * as Dialog from "$lib/components/ui/dialog";
    import { Button } from "$lib/components/ui/button";

    interface Props {
        open: boolean;
        defaultCategory?: string;
        projectId?: string | null;
        onClose: () => void;
        onCreate: (unitOp: {
            name: string;
            category: string;
            description: string;
            param_schema: Record<string, any>;
            project_id?: string;
        }) => void;
    }

    let { open, defaultCategory = "", projectId = null, onClose, onCreate }: Props = $props();

    let name = $state("");
    let category = $state("");
    let description = $state("");
    let scopeChoice = $state<"project" | "organization">("project");
    let params: Array<{
        name: string;
        type: string;
        title: string;
        defaultVal: string;
    }> = $state([]);

    // Reset when category default changes
    $effect(() => {
        if (defaultCategory) category = defaultCategory;
    });

    const categories = Object.keys(categoryColors);

    function addParam() {
        params = [
            ...params,
            { name: "", type: "string", title: "", defaultVal: "" },
        ];
    }

    function removeParam(index: number) {
        params = params.filter((_, i) => i !== index);
    }

    function handleCreate() {
        if (!name.trim() || !category) return;

        const properties: Record<string, any> = {};
        for (const p of params) {
            if (!p.name.trim()) continue;
            const prop: Record<string, any> = {
                type: p.type,
                title: p.title || p.name,
            };
            if (p.defaultVal) {
                if (p.type === "number" || p.type === "integer") {
                    prop.default = Number(p.defaultVal);
                } else {
                    prop.default = p.defaultVal;
                }
            }
            properties[p.name.trim().replace(/\s+/g, "_").toLowerCase()] = prop;
        }

        const opData: Parameters<typeof onCreate>[0] = {
            name: name.trim(),
            category,
            description: description.trim(),
            param_schema: {
                type: "object",
                properties,
            },
        };

        // Only set project_id for project-scoped ops
        if (scopeChoice === "project" && projectId) {
            opData.project_id = projectId;
        }

        onCreate(opData);

        // Reset
        name = "";
        description = "";
        params = [];
        scopeChoice = "project";
    }

    function handleOpenChange(value: boolean) {
        if (!value) onClose();
    }
</script>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>Create Unit Operation</Dialog.Title>
        </Dialog.Header>

        <div class="form">
            <div class="field">
                <label for="op-name">Name</label>
                <input
                    id="op-name"
                    type="text"
                    bind:value={name}
                    placeholder="e.g., Centrifugation"
                />
            </div>

            <div class="field">
                <label for="op-category">Category</label>
                <select id="op-category" bind:value={category}>
                    <option value="">Select category...</option>
                    {#each categories as cat}
                        <option value={cat}>{cat}</option>
                    {/each}
                </select>
            </div>

            <div class="field">
                <label for="op-desc">Description</label>
                <textarea
                    id="op-desc"
                    bind:value={description}
                    placeholder="Brief description..."
                    rows="2"
                ></textarea>
            </div>

            <!-- Scope Picker -->
            {#if projectId}
                <fieldset class="field">
                    <legend class="field-legend">Availability</legend>
                    <div class="scope-picker">
                        <label class="scope-option">
                            <input type="radio" name="scope" value="project" bind:group={scopeChoice} />
                            <span class="scope-dot scope-project-dot"></span>
                            <span class="scope-label">This project only</span>
                        </label>
                        <label class="scope-option">
                            <input type="radio" name="scope" value="organization" bind:group={scopeChoice} />
                            <span class="scope-dot scope-org-dot"></span>
                            <span class="scope-label">Entire organization</span>
                        </label>
                    </div>
                </fieldset>
            {/if}

            <!-- Parameter Builder -->
            <div class="params-section">
                <div class="params-header">
                    <span class="params-title">Parameters</span>
                    <Button size="sm" variant="outline" onclick={addParam}>+ Add</Button>
                </div>

                {#each params as param, i}
                    <div class="param-builder-row">
                        <input
                            type="text"
                            bind:value={param.name}
                            placeholder="Key"
                            class="param-input key"
                        />
                        <input
                            type="text"
                            bind:value={param.title}
                            placeholder="Label"
                            class="param-input label"
                        />
                        <select bind:value={param.type} class="param-input type">
                            <option value="string">Text</option>
                            <option value="number">Number</option>
                            <option value="integer">Integer</option>
                        </select>
                        <button
                            class="remove-param-btn"
                            onclick={() => removeParam(i)}>✕</button
                        >
                    </div>
                {/each}
            </div>
        </div>

        <Dialog.Footer>
            <button
                class="px-4 py-2 bg-muted text-foreground/80 rounded-lg text-sm font-medium hover:bg-muted/80 transition-colors"
                onclick={onClose}
            >
                Cancel
            </button>
            <button
                class="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                onclick={handleCreate}
                disabled={!name.trim() || !category}
            >
                Create
            </button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<style>
    .form {
        display: flex;
        flex-direction: column;
        gap: 14px;
        padding: 0;
    }

    .field {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .field label {
        font-size: 12px;
        font-weight: 600;
        color: hsl(var(--muted-foreground));
    }

    .field input,
    .field select,
    .field textarea {
        padding: 8px 10px;
        border: 1px solid hsl(var(--border));
        border-radius: 6px;
        font-size: 13px;
        font-family: inherit;
        color: hsl(var(--foreground));
        background: hsl(var(--background));
    }

    .field input:focus,
    .field select:focus,
    .field textarea:focus {
        outline: none;
        border-color: hsl(var(--primary));
        box-shadow: 0 0 0 2px hsl(var(--primary) / 0.15);
    }

    .field-legend {
        font-size: 12px;
        font-weight: 600;
        color: hsl(var(--muted-foreground));
        margin-bottom: 4px;
    }

    .scope-picker {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .scope-option {
        display: flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
        font-size: 13px;
        color: hsl(var(--foreground));
        padding: 6px 8px;
        border-radius: 6px;
        transition: background 0.15s;
    }

    .scope-option:hover {
        background: hsl(var(--muted));
    }

    .scope-option input[type="radio"] {
        accent-color: hsl(var(--primary));
    }

    .scope-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .scope-project-dot {
        background-color: #22c55e;
    }

    .scope-org-dot {
        background-color: #3b82f6;
    }

    .scope-label {
        font-weight: 500;
    }

    .params-section {
        border-top: 1px solid hsl(var(--border));
        padding-top: 14px;
    }

    .params-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
    }

    .params-title {
        font-size: 12px;
        font-weight: 600;
        color: hsl(var(--muted-foreground));
    }

    .param-builder-row {
        display: flex;
        gap: 6px;
        margin-bottom: 6px;
        align-items: center;
    }

    .param-input {
        padding: 6px 8px;
        border: 1px solid hsl(var(--border));
        border-radius: 4px;
        font-size: 12px;
        font-family: inherit;
    }

    .param-input.key {
        flex: 1;
    }

    .param-input.label {
        flex: 1.5;
    }

    .param-input.type {
        width: 80px;
    }

    .param-input:focus {
        outline: none;
        border-color: hsl(var(--primary));
    }

    .remove-param-btn {
        width: 24px;
        height: 24px;
        border: none;
        background: transparent;
        color: hsl(var(--muted-foreground));
        cursor: pointer;
        border-radius: 4px;
        font-size: 12px;
        flex-shrink: 0;
    }

    .remove-param-btn:hover {
        background: #fee2e2;
        color: #ef4444;
    }
</style>
