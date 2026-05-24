<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
import EmptyState from '$lib/components/ui/empty-state/empty-state.svelte';
import { computeConditions } from '$lib/experiments/conditions';
import type { Run } from '$lib/schemas/runs';

interface Props { runs: Run[]; experimentId: string; }
let { runs, experimentId }: Props = $props();

const withResult = $derived(runs.filter(r => r.key_result_value != null));
const best = $derived(
    withResult.reduce<Run | null>(
        (acc, r) => (acc == null || r.key_result_value! > acc.key_result_value!) ? r : acc, null,
    )
);

const conditions = $derived(computeConditions(runs as any));
const variedNumeric = $derived(
    conditions.filter(r => r.varied && Array.from(r.perRun.values())
        .every(c => c.value === null || typeof c.value === 'number')),
);

const sessionKey = `kr-chart-axis:${experimentId}`;
let selectedKey = $state<string | null>(
    typeof window !== 'undefined' ? window.sessionStorage.getItem(sessionKey) : null,
);
const xAxis = $derived(
    variedNumeric.find(r => `${r.nodeLabel}::${r.paramKey}` === selectedKey)
        ?? variedNumeric[0],
);

function setAxis(k: string) {
    selectedKey = k;
    if (typeof window !== 'undefined') window.sessionStorage.setItem(sessionKey, k);
}

const points = $derived(() => {
    if (!xAxis) return [];
    return withResult
        .map(r => {
            const cell = xAxis.perRun.get(r.id);
            const x = typeof cell?.value === 'number' ? cell.value : null;
            return x == null ? null : { id: r.id, name: r.name, x, y: r.key_result_value! };
        })
        .filter((p): p is { id: string; name: string; x: number; y: number } => p !== null);
});

const W = 360, H = 220, PAD = 32;
function scaleX(v: number): number {
    const pts = points();
    if (pts.length === 0) return 0;
    const xs = pts.map(p => p.x);
    const min = Math.min(...xs), max = Math.max(...xs);
    if (min === max) return W / 2;
    return PAD + ((v - min) / (max - min)) * (W - 2 * PAD);
}
function scaleY(v: number): number {
    const pts = points();
    if (pts.length === 0) return 0;
    const ys = pts.map(p => p.y);
    const min = Math.min(...ys), max = Math.max(...ys);
    if (min === max) return H / 2;
    return H - PAD - ((v - min) / (max - min)) * (H - 2 * PAD);
}

let selectedPoint = $state<{ name: string; x: number; y: number } | null>(null);
function tapPoint(p: { id: string; name: string; x: number; y: number }) {
    selectedPoint = (selectedPoint?.name === p.name) ? null : { name: p.name, x: p.x, y: p.y };
}
</script>

{#snippet axisLabels()}
    {@const pts = points()}
    {@const xs = pts.map(p => p.x)}
    {@const ys = pts.map(p => p.y)}
    {@const xMin = Math.min(...xs)}
    {@const xMax = Math.max(...xs)}
    {@const yMin = Math.min(...ys)}
    {@const yMax = Math.max(...ys)}
    <text x={PAD} y={H - PAD + 12} class="tick" font-size="9">{xMin}</text>
    <text x={W - PAD} y={H - PAD + 12} class="tick" font-size="9" text-anchor="end">{xMax}</text>
    <text x={PAD - 6} y={H - PAD} class="tick" font-size="9" text-anchor="end">{yMin}</text>
    <text x={PAD - 6} y={PAD + 4} class="tick" font-size="9" text-anchor="end">{yMax}</text>
{/snippet}

{#snippet trendPath()}
    {@const sorted = points().slice().sort((a, b) => a.x - b.x)}
    {#if sorted.length >= 2}
        <path d={`M ${scaleX(sorted[0].x)},${scaleY(sorted[0].y)} L ${scaleX(sorted[sorted.length - 1].x)},${scaleY(sorted[sorted.length - 1].y)}`}
              stroke="currentColor" stroke-dasharray="4 4" opacity="0.4" fill="none" />
    {/if}
{/snippet}

<Card>
    <CardHeader class="flex flex-row items-center justify-between">
        <CardTitle>Results — chart</CardTitle>
        {#if variedNumeric.length > 1}
            <select class="text-sm border rounded px-2 py-1"
                    onchange={e => setAxis((e.currentTarget as HTMLSelectElement).value)}>
                {#each variedNumeric as r}
                    <option value={`${r.nodeLabel}::${r.paramKey}`}
                            selected={xAxis && r.nodeLabel === xAxis.nodeLabel && r.paramKey === xAxis.paramKey}>
                        {r.nodeLabel} / {r.paramKey}
                    </option>
                {/each}
            </select>
        {/if}
    </CardHeader>

    <CardContent>
        {#if points().length === 0}
            <EmptyState title="Not enough data"
                description="Need at least two runs with a varied numeric param and a key result." />
        {:else}
            <div class="relative">
                <svg viewBox="0 0 {W} {H}" class="w-full" aria-label="Key results scatter chart">
                    <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="currentColor" opacity="0.4" />
                    <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="currentColor" opacity="0.4" />
                    {@render axisLabels()}
                    {@render trendPath()}
                    {#each points() as p}
                        <circle cx={scaleX(p.x)} cy={scaleY(p.y)} r="6"
                                class:best={best && p.id === best.id}
                                fill={best && p.id === best.id ? 'var(--accent)' : 'var(--primary)'}>
                            <title>{p.name}: ({p.x}, {p.y})</title>
                        </circle>
                    {/each}
                    {#each points() as p}
                        <circle cx={scaleX(p.x)} cy={scaleY(p.y)} r="22"
                                class="hit-target"
                                role="button"
                                tabindex="0"
                                onclick={() => tapPoint(p)}
                                onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tapPoint(p); } }}
                                aria-label={`${p.name}: ${p.x}, ${p.y}`}>
                            <title>{p.name}: ({p.x}, {p.y})</title>
                        </circle>
                    {/each}
                </svg>
                {#if selectedPoint}
                    <div class="absolute top-2 right-2 bg-card border rounded px-2 py-1 text-xs shadow">
                        <strong>{selectedPoint.name}</strong>: ({selectedPoint.x}, {selectedPoint.y})
                    </div>
                {/if}
            </div>
            <p class="text-xs text-muted-foreground mt-2">Dashed trend is a smoothing hint, not a fit.</p>
        {/if}
    </CardContent>
</Card>

<style>
.tick { fill: var(--muted-fg); }
.hit-target { fill: transparent; cursor: pointer; }
</style>
