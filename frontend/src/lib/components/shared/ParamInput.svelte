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
        class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed disabled:text-gray-500"
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
        class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed disabled:text-gray-500"
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
        class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed disabled:text-gray-500"
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
        class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed disabled:text-gray-500"
        value={value ?? ''}
        oninput={handleText}
        placeholder={placeholder ?? ''}
        disabled={readonly}
    />
{/if}
