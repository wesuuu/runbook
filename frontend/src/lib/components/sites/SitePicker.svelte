<!-- frontend/src/lib/components/sites/SitePicker.svelte -->
<script lang="ts">
    import type { Site } from '$lib/schemas/sites';

    interface Props {
        sites: Site[];
        value: string | null;
        onChange: (id: string) => void;
        disabled?: boolean;
        excludeId?: string | null;
        includeArchived?: boolean;
    }

    let {
        sites,
        value,
        onChange,
        disabled = false,
        excludeId = null,
        includeArchived = false,
    }: Props = $props();

    const visible = $derived(
        sites
            .filter((s) => includeArchived || !s.archived_at)
            .filter((s) => !excludeId || s.id !== excludeId)
            .sort((a, b) => a.name.localeCompare(b.name)),
    );
</script>

<select
    role="combobox"
    class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white"
    value={value ?? ''}
    {disabled}
    onchange={(e) => onChange((e.currentTarget as HTMLSelectElement).value)}
>
    {#each visible as s (s.id)}
        <option value={s.id}>{s.name}</option>
    {/each}
</select>
