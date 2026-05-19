<script lang="ts">
    interface FilterState {
        q: string;
        status: string | null;
        tag: string | null;
        includeArchived: boolean;
    }
    interface Props {
        value: FilterState;
        tags: string[];
        onChange: (next: FilterState) => void;
    }
    let { value, tags, onChange }: Props = $props();
    function update<K extends keyof FilterState>(key: K, v: FilterState[K]) {
        onChange({ ...value, [key]: v });
    }
</script>

<div class="flex items-center gap-2 flex-wrap">
    <input
        class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white max-w-xs"
        placeholder="Search by name, serial, type…"
        value={value.q}
        oninput={(e) => update('q', (e.currentTarget as HTMLInputElement).value)}
    />
    <select
        class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white max-w-[10rem]"
        value={value.status ?? ''}
        onchange={(e) => update('status', (e.currentTarget as HTMLSelectElement).value || null)}
    >
        <option value="">All status</option>
        <option value="ACTIVE">Active</option>
        <option value="MAINTENANCE">Maintenance</option>
        <option value="RETIRED">Retired</option>
    </select>
    <select
        class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white max-w-[10rem]"
        value={value.tag ?? ''}
        onchange={(e) => update('tag', (e.currentTarget as HTMLSelectElement).value || null)}
    >
        <option value="">All tags</option>
        {#each tags as t (t)}<option value={t}>{t}</option>{/each}
    </select>
    <label class="flex items-center gap-1.5 text-sm">
        <input
            type="checkbox"
            checked={value.includeArchived}
            onchange={(e) => update('includeArchived', (e.currentTarget as HTMLInputElement).checked)}
        />
        Include archived
    </label>
</div>
