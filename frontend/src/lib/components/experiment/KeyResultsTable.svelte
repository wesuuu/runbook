<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
import EmptyState from '$lib/components/ui/empty-state/empty-state.svelte';
import { computeConditions } from '$lib/experiments/conditions';
import type { Run } from '$lib/schemas/runs';

interface Props { runs: Run[]; }
let { runs }: Props = $props();

const withResult = $derived(
    runs.filter(r => r.key_result_value != null)
        .sort((a, b) => (b.key_result_value ?? 0) - (a.key_result_value ?? 0))
);

// Baseline = the smallest reported value. Each row's delta% is reported
// relative to this baseline (NOT a median): more intuitive when comparing
// against a control, and stable as runs are added.
const baseline = $derived(
    withResult.length === 0
        ? null
        : Math.min(...withResult.map(r => r.key_result_value!))
);

const best = $derived(withResult[0]);

const condByRun = $derived(() => {
    const rows = computeConditions(runs as any).filter(r => r.varied);
    const m = new Map<string, string>();
    for (const r of runs) {
        const parts: string[] = [];
        for (const row of rows) {
            const cell = row.perRun.get(r.id);
            if (cell?.value != null) {
                parts.push(`${row.paramKey}=${cell.value}${cell.unit ? ' ' + cell.unit : ''}`);
            }
        }
        m.set(r.id, parts.join(', '));
    }
    return m;
});

function deltaPct(value: number): string {
    if (baseline === null || baseline === 0) return '';
    const pct = ((value - baseline) / baseline) * 100;
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(0)}%`;
}
</script>

<Card>
    <CardHeader>
        <CardTitle>Key results</CardTitle>
    </CardHeader>
    <CardContent>
        {#if withResult.length === 0}
            <EmptyState title="No key results yet"
                description="Enter a key result on each run's detail page." />
        {:else}
            <table class="w-full">
                <thead>
                    <tr><th>Run</th><th>Condition</th><th>Label</th><th>Value</th><th>vs. baseline</th></tr>
                </thead>
                <tbody>
                    {#each withResult as r}
                        <tr class:best={r.id === best.id}>
                            <td>{r.name}</td>
                            <td class="text-sm text-muted-foreground">{condByRun().get(r.id) ?? ''}</td>
                            <td>{r.key_result_label}</td>
                            <td class="font-mono">
                                {r.key_result_value}{r.key_result_unit ? ` ${r.key_result_unit}` : ''}
                            </td>
                            <td>
                                <span class="text-xs text-muted-foreground">{deltaPct(r.key_result_value!)}</span>
                                {#if r.id === best.id}
                                    <span class="tag-best ml-2">best</span>
                                {/if}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        {/if}
    </CardContent>
</Card>

<style>
.best { background: color-mix(in oklch, var(--accent) 8%, transparent); }
.tag-best { font-size: 0.75rem; color: var(--accent-fg); }
</style>
