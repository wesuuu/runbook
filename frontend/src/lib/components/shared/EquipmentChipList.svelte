<script lang="ts">
    interface SelectedEquipment {
        equipment_id: string;
        shareable: boolean;
    }
    interface OrgEquipment {
        id: string;
        name: string;
    }

    interface Props {
        equipment: SelectedEquipment[];
        orgEquipment: OrgEquipment[];
        conflictingIds: Set<string>;
        showSwapped?: Set<string>;
    }

    let {
        equipment,
        orgEquipment,
        conflictingIds,
        showSwapped = new Set<string>(),
    }: Props = $props();

    function nameFor(id: string): string {
        return orgEquipment.find((e) => e.id === id)?.name ?? 'Unknown';
    }
</script>

<div class="equipment-list-container">
    {#if equipment.length === 0}
        <div class="empty-message">No equipment assigned</div>
    {:else}
        {#each equipment as eq (eq.equipment_id)}
            <div
                class="equipment-chip"
                class:conflict={conflictingIds.has(eq.equipment_id) && !eq.shareable}
                class:swapped={showSwapped.has(eq.equipment_id)}
            >
                <span class="chip-name">{nameFor(eq.equipment_id)}</span>
                {#if eq.shareable}
                    <span class="chip-badge">Shared</span>
                {/if}
                {#if conflictingIds.has(eq.equipment_id) && !eq.shareable}
                    <span class="chip-warning" aria-label="conflict">⚠</span>
                {/if}
                {#if showSwapped.has(eq.equipment_id)}
                    <span class="chip-swap" aria-label="swapped">◆</span>
                {/if}
            </div>
        {/each}
    {/if}
</div>

<style>
    /* Plain CSS — TailwindCSS 4 disallows @apply in scoped <style> blocks. */
    .equipment-list-container {
        display: flex;
        flex-wrap: wrap;
        gap: 0.375rem;
    }
    .equipment-chip {
        display: inline-flex;
        align-items: center;
        gap: 0.375rem;
        padding: 0.25rem 0.5rem;
        border-radius: 0.375rem;
        font-size: 0.75rem;
        background-color: rgb(241 245 249);   /* slate-100 */
        border: 1px solid rgb(226 232 240);   /* slate-200 */
        color: rgb(51 65 85);                 /* slate-700 */
    }
    .equipment-chip.conflict {
        background-color: rgb(254 242 242);   /* red-50 */
        border-color: rgb(252 165 165);       /* red-300 */
        color: rgb(153 27 27);                /* red-800 */
    }
    .equipment-chip.swapped {
        background-color: rgb(236 253 245);   /* emerald-50 */
        border-color: rgb(52 211 153);        /* emerald-400 */
        color: rgb(6 78 59);                  /* emerald-900 */
    }
    .chip-badge {
        font-size: 0.625rem;
        text-transform: uppercase;
        opacity: 0.7;
    }
    .chip-warning {
        color: rgb(220 38 38);  /* red-600 */
    }
    .chip-swap {
        color: rgb(5 150 105);  /* emerald-600 */
    }
    .empty-message {
        font-size: 0.75rem;
        color: rgb(100 116 139);  /* slate-500 */
        font-style: italic;
    }
</style>
