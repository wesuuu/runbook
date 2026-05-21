<script lang="ts">
    interface CalibrationItem {
        equipment_id: string;
        name: string;
        site_name: string | null;
        next_calibration_date: string | null;
        state: string;
    }
    interface CalibrationStatus {
        overdue: CalibrationItem[];
        due_soon: CalibrationItem[];
    }
    interface Props {
        calibration: CalibrationStatus;
        cap?: number;
        onViewAll: () => void;
    }
    let { calibration, cap = 5, onViewAll }: Props = $props();

    const total = $derived(calibration.overdue.length + calibration.due_soon.length);
    // Overdue fills the cap before any due-soon item is shown.
    const shownOverdue = $derived(calibration.overdue.slice(0, cap));
    const shownDueSoon = $derived(
        calibration.due_soon.slice(0, Math.max(0, cap - shownOverdue.length)),
    );
    const overflow = $derived(total - shownOverdue.length - shownDueSoon.length);
</script>

<div class="card-warm rounded-xl p-4">
    <h3 class="mb-2 text-xs font-bold uppercase tracking-widest text-muted-foreground">
        Equipment Calibration
    </h3>
    {#if total === 0}
        <p data-testid="calibration-empty" class="text-xs text-muted-foreground">
            No calibrations due.
        </p>
    {:else}
        <ul class="space-y-1.5">
            {#each shownOverdue as item (item.equipment_id)}
                <li class="flex items-center justify-between gap-2 text-xs">
                    <span class="truncate font-medium text-foreground">{item.name}</span>
                    <span class="shrink-0 rounded-md bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-red-700">
                        Overdue
                    </span>
                </li>
            {/each}
            {#each shownDueSoon as item (item.equipment_id)}
                <li class="flex items-center justify-between gap-2 text-xs">
                    <span class="truncate font-medium text-foreground">{item.name}</span>
                    <span class="shrink-0 rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-700">
                        Due soon
                    </span>
                </li>
            {/each}
        </ul>
        {#if overflow > 0}
            <button
                type="button"
                data-testid="calibration-more"
                class="mt-2 cursor-pointer text-[11px] font-semibold text-primary transition-all duration-150 hover:underline"
                onclick={onViewAll}
            >
                +{overflow} more
            </button>
        {/if}
    {/if}
</div>
