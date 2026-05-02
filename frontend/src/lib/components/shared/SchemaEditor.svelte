<script lang="ts">
    import { Button } from '$lib/components/ui/button';

    export interface SchemaRow {
        key: string;
        title: string;
        type: 'string' | 'number' | 'integer';
    }

    interface Props {
        rows: SchemaRow[];
        onChange: (next: SchemaRow[]) => void;
        readonly?: boolean;
    }

    let { rows, onChange, readonly = false }: Props = $props();

    function update(i: number, patch: Partial<SchemaRow>) {
        const next = rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
        onChange(next);
    }

    function remove(i: number) {
        onChange(rows.filter((_, idx) => idx !== i));
    }

    function add() {
        onChange([...rows, { key: '', title: '', type: 'string' }]);
    }
</script>

<div class="schema-editor">
    <div class="schema-header-row">
        <span class="col-label">Key</span>
        <span class="col-label">Label</span>
        <span class="col-label">Type</span>
    </div>

    {#each rows as row, i (i)}
        <div class="schema-row" data-schema-row>
            <input
                type="text"
                value={row.key}
                oninput={(e) => update(i, { key: (e.target as HTMLInputElement).value })}
                placeholder="key"
                class="input-field schema-input"
                disabled={readonly}
            />
            <input
                type="text"
                value={row.title}
                oninput={(e) => update(i, { title: (e.target as HTMLInputElement).value })}
                placeholder="Label"
                class="input-field schema-input"
                disabled={readonly}
            />
            <select
                value={row.type}
                onchange={(e) => update(i, { type: (e.target as HTMLSelectElement).value as SchemaRow['type'] })}
                class="input-field schema-input"
                disabled={readonly}
            >
                <option value="string">Text</option>
                <option value="number">Number</option>
                <option value="integer">Integer</option>
            </select>
            {#if !readonly}
                <Button
                    variant="ghost"
                    size="icon-sm"
                    class="text-muted-foreground hover:bg-red-100 hover:text-red-600 size-6"
                    onclick={() => remove(i)}
                    title="Remove parameter"
                    aria-label="Remove parameter"
                >✕</Button>
            {/if}
        </div>
    {/each}

    {#if !readonly}
        <Button
            variant="outline"
            size="sm"
            class="self-start text-xs h-7 px-2.5 text-[hsl(173,58%,39%)]"
            onclick={add}
        >
            + Add Parameter
        </Button>
    {/if}
</div>

<style>
    .schema-editor {
        display: flex;
        flex-direction: column;
        gap: 0.375rem;
    }

    .schema-header-row {
        display: grid;
        grid-template-columns: 1fr 1fr 100px 24px;
        gap: 0.375rem;
    }

    .col-label {
        font-size: 0.75rem;
        text-transform: uppercase;
        color: rgb(107 114 128);
        font-weight: 500;
    }

    .schema-row {
        display: grid;
        grid-template-columns: 1fr 1fr 100px 24px;
        gap: 0.375rem;
        align-items: center;
    }

    .input-field {
        padding: 0.25rem 0.5rem;
        border: 1px solid rgb(209 213 219);
        border-radius: 0.25rem;
        font-size: 0.75rem;
        background-color: white;
        color: inherit;
    }

    .input-field:focus {
        outline: none;
        box-shadow: 0 0 0 2px rgb(20 184 166 / 0.5);
        border-color: transparent;
    }

    .input-field:disabled {
        background-color: rgb(243 244 246);
        cursor: not-allowed;
        color: rgb(107 114 128);
    }

    .schema-input {
        width: 100%;
    }
</style>
