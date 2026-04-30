<script lang="ts">
    interface ParamProp {
        type?: string;
        title?: string;
        enum?: string[];
        unit?: string;
        'x-ref-type'?: string;
    }

    interface MediaPrepNode {
        id: string;
        label: string;
    }

    interface Props {
        id: string;
        schema: ParamProp;
        value: unknown;
        onChange: (next: unknown) => void;
        mediaPrepNodes?: MediaPrepNode[];
        readonly?: boolean;
        placeholder?: string;
    }

    let {
        id,
        schema,
        value,
        onChange,
        mediaPrepNodes = [],
        readonly = false,
        placeholder,
    }: Props = $props();

    function handleNumber(e: Event) {
        const raw = (e.target as HTMLInputElement).value;
        if (raw === '') {
            onChange(undefined);
            return;
        }
        const n = schema.type === 'integer' ? parseInt(raw, 10) : parseFloat(raw);
        onChange(Number.isFinite(n) ? n : undefined);
    }

    function handleText(e: Event) {
        onChange((e.target as HTMLInputElement).value);
    }

    function handleSelect(e: Event) {
        onChange((e.target as HTMLSelectElement).value);
    }
</script>

{#if schema['x-ref-type'] === 'media_prep'}
    <select
        {id}
        class="input-field"
        value={value ?? ''}
        onchange={handleSelect}
        disabled={readonly}
    >
        <option value="">— Select media —</option>
        {#each mediaPrepNodes as mp (mp.id)}
            <option value={mp.id}>{mp.label} ({mp.id.slice(0, 6)})</option>
        {/each}
    </select>
{:else if schema.enum}
    <select
        {id}
        class="input-field"
        value={value ?? ''}
        onchange={handleSelect}
        disabled={readonly}
    >
        {#each schema.enum as opt (opt)}
            <option value={opt}>{opt}</option>
        {/each}
    </select>
{:else if schema.type === 'number' || schema.type === 'integer'}
    <input
        {id}
        type="number"
        class="input-field"
        value={value ?? ''}
        oninput={handleNumber}
        step={schema.type === 'integer' ? 1 : 0.1}
        placeholder={placeholder ?? ''}
        disabled={readonly}
    />
{:else}
    <input
        {id}
        type="text"
        class="input-field"
        value={value ?? ''}
        oninput={handleText}
        placeholder={placeholder ?? ''}
        disabled={readonly}
    />
{/if}

<style>
    .input-field {
        width: 100%;
        padding: 0.5rem 0.75rem;
        border: 1px solid rgb(209 213 219);
        border-radius: 0.5rem;
        font-size: 0.875rem;
        line-height: 1.25rem;
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
</style>
