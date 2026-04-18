<script lang="ts">
    import { getContext, onMount } from "svelte";
    import type { Node } from "@xyflow/svelte";
    import { X } from "lucide-svelte";
    import { getCategoryColor, getCategoryIcon } from "$lib/categoryColors";
    import EquipmentPickerModal from "./EquipmentPickerModal.svelte";
    import { Button } from "$lib/components/ui/button";

    interface Equipment {
        id: string;
        name: string;
        description?: string;
        equipment_type?: string;
        location?: string;
        organization_id: string;
        created_at: string;
        updated_at: string;
    }

    interface SelectedEquipment {
        equipment_id: string;
        shareable: boolean;
    }

    interface SchemaParamRow {
        key: string;
        title: string;
        type: 'string' | 'number' | 'integer';
    }

    interface Props {
        node: Node | null;
        allNodes: Node[];
        orgEquipment?: Equipment[];
        equipmentConflicts?: Map<string, string[]>;
        onApply: (
            nodeId: string,
            params: Record<string, any>,
            duration: number,
            description: string,
            equipment?: SelectedEquipment[],
            paramSchema?: Record<string, any>,
            position?: { x: number; y: number },
        ) => void;
        onSaveAsNew: (name: string, paramSchema: Record<string, any>, category: string) => Promise<void>;
        onCreateEquipment?: (data: { name: string; description: string; equipment_type: string; location: string }) => Promise<Equipment>;
        onClose: () => void;
    }

    let { node, allNodes, orgEquipment = [], equipmentConflicts = new Map(), onApply, onSaveAsNew, onCreateEquipment, onClose }: Props = $props();

    const timelineConfig: {
        enabled: boolean;
        snapMinutes: number;
        pixelsPerHour: number;
        layout: "horizontal" | "vertical";
    } | undefined = getContext("timelineConfig");

    // Local editable state — reset when node changes
    let editParams: Record<string, any> = $state({});
    let editDuration: number = $state(30);
    let editDescription: string = $state("");
    let editEquipment: SelectedEquipment[] = $state([]);
    let equipmentModalOpen: boolean = $state(false);

    // Start time state (only used when timeline is enabled)
    let editStartHour: number = $state(0);
    let editStartMinute: number = $state(0);

    // Schema editor state
    let showSchemaEditor: boolean = $state(false);
    let editSchemaRows: SchemaParamRow[] = $state([]);

    // Listen for onboarding tour request to expand the schema editor
    onMount(() => {
        function expand() {
            showSchemaEditor = true;
        }
        window.addEventListener('onboarding:expand-schema-editor', expand);
        return () => window.removeEventListener('onboarding:expand-schema-editor', expand);
    });

    // Save-as-new-unit-op state
    let showSaveAsNew: boolean = $state(false);
    let saveAsNewName: string = $state('');
    let saveAsNewSaving: boolean = $state(false);
    let saveAsNewError: string | null = $state(null);

    // Only reinitialize edit state when a different node is selected
    let initNodeId: string | null = $state(null);

    $effect(() => {
        if (node && node.id !== initNodeId) {
            initNodeId = node.id;
            editParams = { ...(node.data.params || {}) };
            editDuration = (node.data.duration_min as number) || 30;
            editDescription = (node.data.description as string) || "";
            editEquipment = [...((node.data.equipment as SelectedEquipment[]) || [])];

            // Initialize start time from node position
            if (timelineConfig?.enabled) {
                const posAxis = timelineConfig.layout === "horizontal"
                    ? node.position.x
                    : node.position.y;
                const totalMin = Math.max(0, Math.round((posAxis / timelineConfig.pixelsPerHour) * 60));
                editStartHour = Math.floor(totalMin / 60);
                editStartMinute = totalMin % 60;
            }

            // Initialize schema editor rows from existing paramSchema
            const schema = ((node.data.paramSchema as Record<string, any>) || {}) as Record<string, any>;
            const props = (schema?.properties || {}) as Record<string, any>;
            editSchemaRows = Object.entries(props).map(([key, prop]) => ({
                key,
                title: (prop.title as string) || key,
                type: (['number', 'integer'].includes(prop.type as string)
                    ? prop.type
                    : 'string') as SchemaParamRow['type'],
            }));

            // Reset save-as-new form
            showSaveAsNew = false;
            saveAsNewName = '';
            saveAsNewError = null;
        }
    });

    // --- Schema editor helpers ---

    function addSchemaRow(): void {
        editSchemaRows = [
            ...editSchemaRows,
            { key: '', title: '', type: 'string' },
        ];
        handleApply();
    }

    function removeSchemaRow(index: number): void {
        editSchemaRows = editSchemaRows.filter((_, i) => i !== index);
        handleApply();
    }

    function buildParamSchema(): Record<string, any> {
        // Merge-and-override: preserves exotic fields (enum, x-ref-type) on existing keys
        const existingProps = ((node?.data?.paramSchema as Record<string, any>)?.properties || {}) as Record<string, any>;
        const properties: Record<string, any> = {};
        for (const row of editSchemaRows) {
            const k = row.key.trim().replace(/\s+/g, '_').toLowerCase();
            if (!k) continue;
            properties[k] = { ...(existingProps[k] || {}), type: row.type, title: row.title || row.key };
        }
        return { type: 'object', properties };
    }

    function syncParamsToSchema(
        current: Record<string, any>,
        schema: Record<string, any>,
    ): Record<string, any> {
        const props = (schema.properties || {}) as Record<string, any>;
        const synced: Record<string, any> = {};
        for (const [key, prop] of Object.entries(props)) {
            synced[key] = key in current ? current[key] : (prop.default ?? (prop.enum?.[0] ?? ''));
        }
        return synced;
    }

    function handleApply(): void {
        if (!node) return;
        const newSchema = buildParamSchema();
        const syncedParams = syncParamsToSchema({ ...editParams }, newSchema);

        // Compute position from edited start time when timeline is on
        let position: { x: number; y: number } | undefined;
        if (timelineConfig?.enabled) {
            const totalMin = editStartHour * 60 + editStartMinute;
            const posPx = (totalMin / 60) * timelineConfig.pixelsPerHour;
            if (timelineConfig.layout === "horizontal") {
                position = { x: posPx, y: node.position.y };
            } else {
                position = { x: node.position.x, y: posPx };
            }
        }

        onApply(node.id, syncedParams, editDuration, editDescription, editEquipment, newSchema, position);
    }

    function getEquipmentName(equipmentId: string): string {
        return orgEquipment.find(e => e.id === equipmentId)?.name || equipmentId.slice(0, 8);
    }

    function handleEquipmentApply(equipment: SelectedEquipment[]): void {
        editEquipment = equipment;
        handleApply();
    }

    async function handleSaveAsNew(): Promise<void> {
        if (!saveAsNewName.trim() || !node) return;
        saveAsNewSaving = true;
        saveAsNewError = null;
        try {
            const schema = buildParamSchema();
            await onSaveAsNew(saveAsNewName.trim(), schema, node.data.category as string);
            showSaveAsNew = false;
            saveAsNewName = '';
        } catch (e: unknown) {
            saveAsNewError = e instanceof Error ? e.message : 'Failed to save';
        } finally {
            saveAsNewSaving = false;
        }
    }

    // --- Template rendering ---
    function renderTemplate(template: string, params: Record<string, any>): string {
        return template.replace(/\{\{(\w+)\}\}/g, (match, key) => {
            const val = params[key];
            if (val === undefined || val === null || val === '' || (Array.isArray(val) && val.length === 0)) {
                return match;
            }
            if (typeof val === 'boolean') return val ? 'Yes' : 'No';
            if (Array.isArray(val)) return val.join(', ');
            return String(val);
        });
    }

    // --- Derived state ---
    const schema = $derived((node?.data?.paramSchema as Record<string, any>) || {});
    const properties = $derived<[string, Record<string, any>][]>(
        schema?.properties
            ? Object.entries(schema.properties) as [string, Record<string, any>][]
            : [],
    );
    const color = $derived(getCategoryColor((node?.data?.category as string) || "General"));
    const icon = $derived(getCategoryIcon((node?.data?.category as string) || "General"));
    const shortId = $derived(node?.id?.slice(0, 8).toUpperCase() || "");

    const paramKeys = $derived(
        Object.keys(
            ((node?.data?.paramSchema as Record<string, any>)?.properties ?? {})
        )
    );

    const renderedPreview = $derived(
        editDescription
            ? renderTemplate(editDescription, editParams)
            : ''
    );

    // Get media prep nodes for x-ref-type dropdowns
    const mediaPrepNodes = $derived(
        allNodes.filter(
            (n) =>
                n.type === "unitOp" &&
                n.data?.category === "Media Prep" &&
                n.id !== node?.id,
        ),
    );
</script>

{#if node}
    <aside class="inspector" data-tour="protocol-inspector">
        <!-- Header -->
        <div class="inspector-header">
            <div class="header-top">
                <div class="header-icon" style:background={color}>
                    {icon}
                </div>
                <h2 class="header-title">INSPECTOR</h2>
                <Button variant="ghost" size="icon-sm" onclick={onClose} aria-label="Close">
                    <X class="size-4" />
                </Button>
            </div>

            <div class="node-info">
                <h3 class="node-name">{node.data.label}</h3>
                <div class="node-badges">
                    <span class="badge id-badge">{shortId}</span>
                    <span
                        class="badge cat-badge"
                        style:background="{color}20"
                        style:color
                    >
                        {node.data.category}
                    </span>
                </div>
            </div>
        </div>

        <!-- Description -->
        <div class="section" data-tour="inspector-instruction">
            <label class="section-label" for="node-description">Instruction</label>
            {#if paramKeys.length > 0}
                <p class="template-hint">
                    Available: {paramKeys.map(k => `{{${k}}}`).join('  ')}
                </p>
            {/if}
            <textarea
                id="node-description"
                class="input-field description-textarea"
                bind:value={editDescription}
                oninput={handleApply}
                placeholder="Add context for this step..."
                rows="3"
            ></textarea>
            {#if renderedPreview}
                <div class="template-preview">
                    <span class="preview-label">Preview</span>
                    <p class="preview-text">{renderedPreview}</p>
                </div>
            {/if}
        </div>

        <!-- Duration -->
        <div class="section">
            <label class="section-label">
                Duration
                {#if timelineConfig?.enabled}
                    <span class="timeline-hint">(5-min steps)</span>
                {/if}
            </label>
            <div class="duration-input-row">
                <input
                    type="number"
                    bind:value={editDuration}
                    oninput={handleApply}
                    min={timelineConfig?.enabled ? 5 : 1}
                    step={timelineConfig?.enabled ? 5 : 1}
                    class="input-field duration-input"
                />
                <span class="input-unit">min</span>
            </div>
        </div>

        <!-- Start Time (only when timeline is enabled) -->
        {#if timelineConfig?.enabled}
            <div class="section">
                <label class="section-label">Start Time</label>
                <div class="start-time-row">
                    <div class="time-input-group">
                        <input
                            type="number"
                            bind:value={editStartHour}
                            oninput={handleApply}
                            min="0"
                            class="input-field time-input"
                        />
                        <span class="time-label">h</span>
                    </div>
                    <span class="time-colon">:</span>
                    <div class="time-input-group">
                        <input
                            type="number"
                            bind:value={editStartMinute}
                            oninput={handleApply}
                            min="0"
                            max="59"
                            step="5"
                            class="input-field time-input"
                        />
                        <span class="time-label">m</span>
                    </div>
                </div>
            </div>
        {/if}

        <!-- Equipment -->
        {#if orgEquipment.length > 0 || onCreateEquipment}
            <div class="section equipment-section">
                <label class="section-label">Equipment</label>
                <div class="equipment-list-container">
                    {#if editEquipment.length > 0}
                        {#each editEquipment as eq (eq.equipment_id)}
                            <div class="equipment-chip" class:conflict={equipmentConflicts.get(node?.id || '')?.includes(eq.equipment_id) && !eq.shareable}>
                                <span class="chip-name">{getEquipmentName(eq.equipment_id)}</span>
                                {#if eq.shareable}
                                    <span class="chip-badge">Shared</span>
                                {/if}
                                {#if equipmentConflicts.get(node?.id || '')?.includes(eq.equipment_id) && !eq.shareable}
                                    <span class="chip-warning">⚠</span>
                                {/if}
                            </div>
                        {/each}
                    {:else}
                        <div class="empty-message">No equipment assigned</div>
                    {/if}
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    class="self-start"
                    onclick={() => (equipmentModalOpen = true)}
                >
                    Manage Equipment
                </Button>
            </div>
        {/if}

        <!-- Equipment Modal -->
        {#if onCreateEquipment}
            <EquipmentPickerModal
                open={equipmentModalOpen}
                nodeId={node?.id || ''}
                currentEquipment={editEquipment}
                {orgEquipment}
                conflictingIds={new Set(equipmentConflicts.get(node?.id || '') || [])}
                onClose={() => (equipmentModalOpen = false)}
                onApply={handleEquipmentApply}
                onCreateEquipment={onCreateEquipment}
            />
        {/if}

        <!-- Parameters -->
        {#if properties.length > 0}
            <div class="section">
                <label class="section-label">PARAMETERS</label>

                <div class="params-grid">
                    {#each properties as [key, prop]}
                        <div class="param-field">
                            <label class="param-label" for="param-{key}">
                                {prop.title || key}
                            </label>

                            {#if prop["x-ref-type"] === "media_prep"}
                                <!-- Media reference dropdown -->
                                <select
                                    id="param-{key}"
                                    class="input-field"
                                    bind:value={editParams[key]}
                                    onchange={handleApply}
                                >
                                    <option value="">— Select media —</option>
                                    {#each mediaPrepNodes as mpNode}
                                        <option value={mpNode.id}>
                                            {mpNode.data.label} ({mpNode.id.slice(
                                                0,
                                                6,
                                            )})
                                        </option>
                                    {/each}
                                </select>
                            {:else if prop.enum}
                                <!-- Enum dropdown -->
                                <select
                                    id="param-{key}"
                                    class="input-field"
                                    bind:value={editParams[key]}
                                    onchange={handleApply}
                                >
                                    {#each prop.enum as option}
                                        <option value={option}>{option}</option>
                                    {/each}
                                </select>
                            {:else if prop.type === "number" || prop.type === "integer"}
                                <!-- Number input -->
                                <input
                                    id="param-{key}"
                                    type="number"
                                    class="input-field"
                                    bind:value={editParams[key]}
                                    oninput={handleApply}
                                    step={prop.type === "integer" ? 1 : 0.1}
                                />
                            {:else}
                                <!-- Text input -->
                                <input
                                    id="param-{key}"
                                    type="text"
                                    class="input-field"
                                    bind:value={editParams[key]}
                                    oninput={handleApply}
                                />
                            {/if}
                        </div>
                    {/each}
                </div>
            </div>
        {/if}

        <!-- Schema Editor (collapsible) -->
        <div class="section schema-section" data-tour="inspector-schema">
            <Button
                variant="ghost"
                class="w-full justify-between px-0 hover:bg-transparent"
                onclick={() => (showSchemaEditor = !showSchemaEditor)}
            >
                <span class="section-label" style="margin-bottom: 0;">EDIT SCHEMA</span>
                <span class="schema-chevron" class:open={showSchemaEditor}>▾</span>
            </Button>

            {#if showSchemaEditor}
                <div class="schema-editor">
                    <!-- Column headers -->
                    <div class="schema-header-row">
                        <span class="col-label">Key</span>
                        <span class="col-label">Label</span>
                        <span class="col-label">Type</span>
                    </div>

                    <!-- Schema rows -->
                    {#each editSchemaRows as row, i}
                        <div class="schema-row">
                            <input
                                type="text"
                                bind:value={row.key}
                                oninput={handleApply}
                                placeholder="key"
                                class="input-field schema-input"
                            />
                            <input
                                type="text"
                                bind:value={row.title}
                                oninput={handleApply}
                                placeholder="Label"
                                class="input-field schema-input"
                            />
                            <select
                                bind:value={row.type}
                                onchange={handleApply}
                                class="input-field schema-input"
                            >
                                <option value="string">Text</option>
                                <option value="number">Number</option>
                                <option value="integer">Integer</option>
                            </select>
                            <Button
                                variant="ghost"
                                size="icon-sm"
                                class="text-muted-foreground hover:bg-red-100 hover:text-red-600 size-6"
                                onclick={() => removeSchemaRow(i)}
                                title="Remove parameter"
                                aria-label="Remove parameter"
                            >✕</Button>
                        </div>
                    {/each}

                    <!-- Add Parameter button -->
                    <Button
                        variant="outline"
                        size="sm"
                        class="self-start text-xs h-7 px-2.5 text-[hsl(173,58%,39%)]"
                        onclick={addSchemaRow}
                    >
                        + Add Parameter
                    </Button>

                    <!-- Save as New Unit Op -->
                    <div class="save-as-new-area">
                        {#if !showSaveAsNew}
                            <Button
                                variant="link"
                                size="sm"
                                class="h-auto p-0 text-xs text-muted-foreground hover:text-[hsl(173,58%,39%)]"
                                onclick={() => (showSaveAsNew = true)}
                            >
                                Save as New Unit Op...
                            </Button>
                        {:else}
                            <div class="save-as-new-form">
                                <input
                                    type="text"
                                    bind:value={saveAsNewName}
                                    placeholder="New unit op name..."
                                    class="input-field"
                                />
                                {#if saveAsNewError}
                                    <span class="save-as-new-error">{saveAsNewError}</span>
                                {/if}
                                <div class="save-as-new-actions">
                                    <Button
                                        variant="secondary"
                                        size="sm"
                                        onclick={() => { showSaveAsNew = false; saveAsNewName = ''; }}
                                    >Cancel</Button>
                                    <Button
                                        variant="default"
                                        size="sm"
                                        onclick={handleSaveAsNew}
                                        disabled={!saveAsNewName.trim() || saveAsNewSaving}
                                    >
                                        {saveAsNewSaving ? 'Saving...' : 'Save'}
                                    </Button>
                                </div>
                            </div>
                        {/if}
                    </div>
                </div>
            {/if}
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

    .cat-badge {
        text-transform: uppercase;
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

    .description-textarea {
        resize: vertical;
        min-height: 60px;
        line-height: 1.4;
    }

    .template-hint {
        font-size: 11px;
        color: #94a3b8;
        margin: 0 0 6px 0;
        line-height: 1.4;
        font-family: "JetBrains Mono", monospace;
        word-break: break-all;
    }

    .template-preview {
        margin-top: 8px;
        padding: 8px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
    }

    .preview-label {
        font-size: 10px;
        font-weight: 600;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .preview-text {
        font-size: 13px;
        color: #334155;
        margin: 4px 0 0 0;
        line-height: 1.4;
    }

    .timeline-hint {
        font-weight: 500;
        color: hsl(173, 58%, 39%);
        text-transform: none;
        letter-spacing: normal;
    }

    .start-time-row {
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .time-input-group {
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .time-input {
        width: 56px;
        text-align: center;
        font-family: "JetBrains Mono", monospace;
    }

    .time-colon {
        font-size: 16px;
        font-weight: 700;
        color: #94a3b8;
    }

    .time-label {
        font-size: 11px;
        color: #94a3b8;
        font-weight: 500;
    }

    .duration-input-row {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .duration-input {
        width: 80px;
    }

    .input-unit {
        font-size: 12px;
        color: #94a3b8;
        font-weight: 500;
    }

    .params-grid {
        display: flex;
        flex-direction: column;
        gap: 14px;
    }

    .param-field {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .param-label {
        font-size: 12px;
        font-weight: 500;
        color: #475569;
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
        border-color: hsl(173, 58%, 39%);
        box-shadow: 0 0 0 2px hsla(173, 58%, 39%, 0.15);
    }

    select.input-field {
        cursor: pointer;
        appearance: auto;
    }

    /* --- Schema Editor --- */
    .schema-section {
        padding-top: 12px;
        padding-bottom: 12px;
    }

    .schema-chevron {
        font-size: 10px;
        color: #94a3b8;
        transition: transform 0.15s;
    }

    .schema-chevron.open {
        transform: rotate(180deg);
    }

    .schema-editor {
        margin-top: 12px;
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .schema-header-row {
        display: grid;
        grid-template-columns: 1fr 1.2fr 72px 24px;
        gap: 4px;
        padding: 0 2px;
    }

    .col-label {
        font-size: 10px;
        font-weight: 600;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .schema-row {
        display: grid;
        grid-template-columns: 1fr 1.2fr 72px 24px;
        gap: 4px;
        align-items: center;
    }

    .schema-input {
        padding: 5px 7px !important;
        font-size: 12px !important;
        height: 28px !important;
    }

    .save-as-new-area {
        border-top: 1px solid #f1f5f9;
        padding-top: 10px;
        margin-top: 4px;
    }

    .save-as-new-form {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .save-as-new-error {
        font-size: 11px;
        color: hsl(0, 84.2%, 60.2%);
    }

    .save-as-new-actions {
        display: flex;
        gap: 6px;
        justify-content: flex-end;
    }

    /* --- Equipment --- */
    .equipment-section {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .equipment-list-container {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin-bottom: 8px;
        min-height: 28px;
    }

    .equipment-chip {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        background-color: #e0f2fe;
        border: 1px solid #7dd3fc;
        border-radius: 4px;
        font-size: 12px;
        color: #0369a1;
    }

    .equipment-chip.conflict {
        background-color: #fef08a;
        border-color: #fcd34d;
        color: #92400e;
    }

    .chip-name {
        flex: 1;
        font-weight: 500;
    }

    .chip-badge {
        display: inline-block;
        padding: 2px 6px;
        background-color: rgba(255, 255, 255, 0.7);
        border-radius: 3px;
        font-size: 10px;
        font-weight: 600;
    }

    .chip-warning {
        font-size: 14px;
        margin-left: auto;
    }

    .empty-message {
        font-size: 12px;
        color: #94a3b8;
        font-style: italic;
        padding: 8px 0;
    }

</style>
