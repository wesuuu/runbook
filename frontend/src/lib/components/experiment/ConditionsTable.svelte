<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
import EmptyState from '$lib/components/ui/empty-state/empty-state.svelte';
import { computeConditions, type CondRow } from '$lib/experiments/conditions';
import type { Run } from '$lib/schemas/runs';

interface Props {
    runs: Run[];
}
let { runs }: Props = $props();

let showConstants = $state(false);

const allRows: CondRow[] = $derived(computeConditions(runs as any));
const visibleRows: CondRow[] = $derived(
    showConstants ? allRows : allRows.filter(r => r.varied)
);
const runColumns = $derived(runs.map(r => ({ id: r.id, name: r.name })));
const groupedByStep = $derived(() => {
    const groups = new Map<string, CondRow[]>();
    for (const r of visibleRows) {
        const list = groups.get(r.nodeLabel) ?? [];
        list.push(r);
        groups.set(r.nodeLabel, list);
    }
    return Array.from(groups, ([label, rows]) => ({ label, rows }));
});
</script>

<Card>
    <CardHeader class="flex flex-row items-center justify-between">
        <CardTitle>Conditions</CardTitle>
        <label class="text-sm flex items-center gap-2 cursor-pointer">
            <input type="checkbox" bind:checked={showConstants} />
            Show constants
        </label>
    </CardHeader>
    <CardContent>
        {#if runs.length === 0}
            <EmptyState title="No runs yet"
                description="Add a run to populate the design matrix." />
        {:else if visibleRows.length === 0}
            <EmptyState title="All parameters match"
                description="No varied parameters across runs." />
        {:else}
            <div class="overflow-x-auto">
                <table class="conditions-table">
                    <thead>
                        <tr>
                            <th class="sticky-left">Step / Parameter</th>
                            {#each runColumns as col}
                                <th>{col.name}</th>
                            {/each}
                        </tr>
                    </thead>
                    <tbody>
                        {#each groupedByStep() as group}
                            <tr class="group-row">
                                <td class="sticky-left font-medium" colspan={1 + runColumns.length}>
                                    {group.label}
                                </td>
                            </tr>
                            {#each group.rows as row}
                                <tr>
                                    <td class="sticky-left">
                                        {row.paramKey}
                                        {#if row.varied}<span class="varied-dot"></span>{/if}
                                        {#if row.unitConflict}
                                            <span class="unit-conflict" title="Unit mismatch across runs">⚠ unit mismatch</span>
                                        {/if}
                                    </td>
                                    {#each runColumns as col}
                                        {@const cell = row.perRun.get(col.id)}
                                        <td class="font-mono text-sm">
                                            {#if cell?.value == null}
                                                —
                                            {:else}
                                                {cell.value}{cell.unit ? ` ${cell.unit}` : ''}
                                            {/if}
                                        </td>
                                    {/each}
                                </tr>
                            {/each}
                        {/each}
                    </tbody>
                </table>
            </div>
        {/if}
    </CardContent>
</Card>

<style>
.conditions-table {
    width: 100%;
    border-collapse: collapse;
}
.conditions-table th, .conditions-table td {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border);
    text-align: left;
}
.sticky-left {
    position: sticky;
    left: 0;
    z-index: 2;
    background: var(--card);
}
.varied-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 3px;
    background: var(--accent);
    margin-left: 4px;
}
.unit-conflict {
    margin-left: 6px;
    font-size: 0.7rem;
    color: var(--destructive);
}
</style>
