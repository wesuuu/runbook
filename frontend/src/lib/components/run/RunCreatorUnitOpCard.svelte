<script lang="ts">
    import { renderTemplate } from '$lib/utils/template';
    import ParamInput from '$lib/components/shared/ParamInput.svelte';
    import EquipmentChipList from '$lib/components/shared/EquipmentChipList.svelte';
    import SchemaEditor, { type SchemaRow } from '$lib/components/shared/SchemaEditor.svelte';
    import { Button } from '$lib/components/ui/button';
    import { slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';

    interface MediaPrepNode { id: string; label: string; }
    interface OrgEquipment { id: string; name: string; }

    type ParamProp = {
        type?: string;
        title?: string;
        enum?: string[];
        unit?: string;
        'x-ref-type'?: string;
    };

    type UnitOpData = {
        label?: string;
        category?: string;
        params?: Record<string, unknown>;
        equipment?: Array<{ equipment_id: string; shareable: boolean }>;
        paramSchema?: { type?: string; properties?: Record<string, ParamProp> };
        description?: string;
        protocol_params?: Record<string, unknown>;
        protocol_equipment?: Array<{ equipment_id: string; shareable: boolean }>;
        protocol_paramSchema?: { type?: string; properties?: Record<string, ParamProp> };
        protocol_description?: string;
    };

    type UnitOpNode = {
        id: string;
        type?: string;
        data: UnitOpData;
        [k: string]: unknown;
    };

    interface Props {
        node: UnitOpNode;
        mediaPrepNodes: MediaPrepNode[];
        orgEquipment: OrgEquipment[];
        conflictingIds: Set<string>;
        onChange: (next: UnitOpNode) => void;
        onSwapEquipment: (nodeId: string) => void;
    }

    let { node, mediaPrepNodes, orgEquipment, conflictingIds, onChange, onSwapEquipment }: Props = $props();

    const data = $derived<UnitOpData>(node.data ?? {});
    const props = $derived((data.paramSchema?.properties ?? {}) as Record<string, ParamProp>);
    const protoParams = $derived((data.protocol_params ?? {}) as Record<string, unknown>);
    const protoProps = $derived((data.protocol_paramSchema?.properties ?? {}) as Record<string, ParamProp>);

    const overriddenCount = $derived.by(() => {
        let n = 0;
        for (const k of Object.keys(props)) {
            if (k in protoProps) {
                if (JSON.stringify(data.params?.[k]) !== JSON.stringify(protoParams[k])) n++;
            }
        }
        return n;
    });
    const equipmentSwapped = $derived(
        JSON.stringify(data.equipment ?? []) !== JSON.stringify(data.protocol_equipment ?? []),
    );
    const descriptionModified = $derived((data.description ?? '') !== (data.protocol_description ?? ''));

    let showInstructions = $state(false);
    let editingDescription = $state<string>('');
    $effect(() => { editingDescription = data.description ?? ''; });

    function patchData(patch: Partial<UnitOpData>) {
        onChange({ ...node, data: { ...data, ...patch } });
    }

    function setParam(key: string, value: unknown) {
        patchData({ params: { ...(data.params ?? {}), [key]: value } });
    }

    function revertParam(key: string) {
        patchData({ params: { ...(data.params ?? {}), [key]: protoParams[key] } });
    }

    function removeParam(key: string) {
        const nextProps = { ...props };
        delete nextProps[key];
        const nextParams = { ...(data.params ?? {}) };
        delete nextParams[key];
        patchData({
            paramSchema: { ...data.paramSchema, properties: nextProps },
            params: nextParams,
        });
    }

    function setSchemaRows(rows: SchemaRow[]) {
        const nextProps: Record<string, ParamProp> = {};
        const nextParams: Record<string, unknown> = { ...(data.params ?? {}) };
        for (const r of rows) {
            if (!r.key) continue;
            nextProps[r.key] = { ...(props[r.key] ?? {}), type: r.type, title: r.title };
        }
        for (const k of Object.keys(nextParams)) {
            if (!(k in nextProps)) delete nextParams[k];
        }
        patchData({
            paramSchema: { ...data.paramSchema, properties: nextProps },
            params: nextParams,
        });
    }

    function commitDescription() {
        patchData({ description: editingDescription });
    }
    function revertDescription() {
        editingDescription = data.protocol_description ?? '';
        patchData({ description: data.protocol_description ?? '' });
    }

    const renderedDefault = $derived(renderTemplate(data.protocol_description ?? '', protoParams));
    const renderedEffective = $derived(renderTemplate(data.description ?? '', data.params ?? {}));
    const schemaRows = $derived<SchemaRow[]>(
        Object.entries(props).map(([k, v]) => ({
            key: k,
            title: v.title ?? k,
            type: (v.type ?? 'string') as SchemaRow['type'],
        })),
    );
</script>

<article class="uo-card" class:has-overrides={overriddenCount > 0 || equipmentSwapped || descriptionModified}>
    <header class="uo-head">
        <div class="uo-title">
            <span class="uo-label">{data.label ?? node.id}</span>
            {#if data.category}<span class="uo-category">{data.category}</span>{/if}
        </div>
        <div class="uo-badges">
            {#if overriddenCount > 0}
                <span class="badge badge-mint">{overriddenCount} overridden</span>
            {/if}
            {#if equipmentSwapped}
                <span class="badge badge-mint">equipment swapped</span>
            {/if}
            {#if descriptionModified}
                <span class="badge badge-amber">◆ instructions modified</span>
            {/if}
        </div>
    </header>

    <section class="uo-section">
        <h4 class="section-label">EQUIPMENT</h4>
        <div class="equipment-row">
            <EquipmentChipList
                equipment={data.equipment ?? []}
                {orgEquipment}
                {conflictingIds}
                showSwapped={equipmentSwapped ? new Set((data.equipment ?? []).map((e) => e.equipment_id)) : new Set()}
            />
            <Button variant="outline" size="sm" onclick={() => onSwapEquipment(node.id)}>Swap</Button>
        </div>
    </section>

    {#if Object.keys(props).length > 0}
        <section class="uo-section">
            <h4 class="section-label">PARAMETERS</h4>
            <table class="param-table">
                <thead>
                    <tr>
                        <th>Parameter</th>
                        <th>Default</th>
                        <th>Override for this run</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    {#each Object.entries(props) as [key, prop] (key)}
                        {@const isAdded = !(key in protoProps)}
                        {@const isModified = key in protoProps &&
                            JSON.stringify(data.params?.[key]) !== JSON.stringify(protoParams[key])}
                        <tr class:row-added={isAdded} class:row-modified={isModified}>
                            <td>
                                {prop.title ?? key}
                                {#if isAdded}<span class="row-tag row-tag-amber">+ ADDED</span>{/if}
                            </td>
                            <td class="default-cell">
                                {#if isAdded}<span class="muted">—</span>
                                {:else}{String(protoParams[key] ?? '')}{/if}
                            </td>
                            <td>
                                <ParamInput
                                    id="ov-{node.id}-{key}"
                                    schema={prop}
                                    value={data.params?.[key]}
                                    {mediaPrepNodes}
                                    onChange={(v) => setParam(key, v)}
                                />
                            </td>
                            <td class="action-cell">
                                {#if isModified}
                                    <button
                                        type="button"
                                        class="row-action"
                                        aria-label="Revert {key}"
                                        title="Revert to default"
                                        onclick={() => revertParam(key)}
                                    >↺</button>
                                {/if}
                                <button
                                    type="button"
                                    class="row-action row-action-remove"
                                    aria-label="Remove {key}"
                                    title="Remove parameter"
                                    onclick={() => removeParam(key)}
                                >✕</button>
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </section>
    {/if}

    <section class="uo-section">
        <details class="schema-details">
            <summary class="section-label cursor-pointer">+ ADD / EDIT SCHEMA</summary>
            <SchemaEditor rows={schemaRows} onChange={setSchemaRows} />
        </details>
    </section>

    <section class="uo-section instructions-section">
        <div class="instructions-head">
            <h4 class="section-label">INSTRUCTIONS</h4>
            {#if descriptionModified}<span class="badge badge-amber">◆ modified</span>{/if}
            <button
                type="button"
                class="link"
                onclick={() => (showInstructions = !showInstructions)}
            >
                {showInstructions ? 'Hide editor' : '✎ Edit instructions'}
            </button>
        </div>
        <p class="rendered-template">{renderedEffective || '— no instructions —'}</p>
        {#if showInstructions}
            <div class="instructions-editor" transition:slide={{ duration: 180, easing: cubicOut }}>
                <textarea
                    bind:value={editingDescription}
                    onblur={commitDescription}
                    rows="4"
                    class="textarea-field"
                    placeholder="Use {`{{paramKey}}`} to substitute values"
                ></textarea>
                <p class="rendered-preview">
                    Preview: {renderTemplate(editingDescription, data.params ?? {})}
                </p>
                <Button variant="ghost" size="sm" onclick={revertDescription}>↺ revert to protocol default</Button>
                <p class="muted small">Default: {renderedDefault}</p>
            </div>
        {/if}
    </section>
</article>

<style>
    .uo-card {
        border-radius: 0.75rem;
        border: 1px solid rgb(226 232 240);
        background-color: white;
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    .uo-card.has-overrides {
        border-color: rgb(110 231 183);
        background-color: rgb(236 253 245 / 0.3);
    }
    .uo-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 0.75rem;
    }
    .uo-title {
        display: flex;
        flex-direction: column;
        gap: 0.125rem;
    }
    .uo-label {
        font-size: 1rem;
        font-weight: 600;
        color: rgb(15 23 42);
    }
    .uo-category {
        font-size: 0.75rem;
        color: rgb(100 116 139);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .uo-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 0.375rem;
    }
    .badge {
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.5rem;
        border-radius: 0.375rem;
        font-size: 11px;
        font-weight: 500;
    }
    .badge-mint {
        background-color: rgb(209 250 229);
        color: rgb(6 95 70);
    }
    .badge-amber {
        background-color: rgb(254 243 199);
        color: rgb(146 64 14);
    }
    .uo-section {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .section-label {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: rgb(100 116 139);
        font-weight: 600;
    }
    .equipment-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-wrap: wrap;
    }
    .param-table {
        width: 100%;
        font-size: 0.875rem;
        border-collapse: collapse;
    }
    .param-table th {
        text-align: left;
        font-size: 0.75rem;
        text-transform: uppercase;
        color: rgb(100 116 139);
        font-weight: 500;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid rgb(226 232 240);
    }
    .param-table td {
        padding: 0.5rem 0;
        vertical-align: middle;
        border-bottom: 1px solid rgb(241 245 249);
    }
    .param-table tr.row-modified td {
        background-color: rgb(236 253 245 / 0.4);
    }
    .param-table tr.row-added td {
        background-color: rgb(255 251 235 / 0.4);
    }
    .default-cell {
        color: rgb(71 85 105);
    }
    .action-cell {
        text-align: right;
        white-space: nowrap;
    }
    .row-tag {
        margin-left: 0.375rem;
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.375rem;
        border-radius: 0.25rem;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
    }
    .row-tag-amber {
        background-color: rgb(254 243 199);
        color: rgb(146 64 14);
    }
    .row-action {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.5rem;
        height: 1.5rem;
        border-radius: 0.25rem;
        color: rgb(100 116 139);
        background: transparent;
        border: none;
        cursor: pointer;
        transition: all 150ms;
    }
    .row-action:hover {
        background-color: rgb(241 245 249);
    }
    .row-action-remove:hover {
        color: rgb(220 38 38);
        background-color: rgb(254 242 242);
    }
    .instructions-head {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .rendered-template {
        font-size: 0.875rem;
        color: rgb(51 65 85);
        line-height: 1.625;
    }
    .rendered-preview {
        font-size: 0.875rem;
        color: rgb(6 95 70);
        line-height: 1.625;
    }
    .muted {
        color: rgb(148 163 184);
    }
    .small {
        font-size: 0.75rem;
    }
    .link {
        font-size: 0.75rem;
        color: rgb(15 118 110);
        cursor: pointer;
        background: none;
        border: none;
        padding: 0;
    }
    .link:hover {
        text-decoration: underline;
    }
    .textarea-field {
        width: 100%;
        padding: 0.5rem 0.75rem;
        border: 1px solid rgb(209 213 219);
        border-radius: 0.5rem;
        font-size: 0.875rem;
        font-family: ui-monospace, SFMono-Regular, monospace;
    }
    .textarea-field:focus {
        outline: none;
        box-shadow: 0 0 0 2px rgb(20 184 166);
    }
    .schema-details summary {
        user-select: none;
    }
    .instructions-editor {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
</style>
