<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent } from '$lib/components/ui/card';
import EmptyState from '$lib/components/ui/empty-state/empty-state.svelte';
import { paths } from '$lib/paths';
import { formatDate } from '$lib/components/project/projectUtils';
import type { ObservationItem } from '$lib/schemas/observation';

interface Props {
    items: ObservationItem[];
    truncated: boolean;
    loading: boolean;
}
let { items, truncated, loading }: Props = $props();
</script>

<aside class="sticky top-4">
    <Card>
        <CardHeader>
            <CardTitle>Observations</CardTitle>
        </CardHeader>
        <CardContent>
            {#if loading}
                <div class="text-sm text-muted-foreground">Loading…</div>
            {:else if items.length === 0}
                <EmptyState title="Nothing flagged yet"
                    description="No observations or anomalies flagged yet." />
            {:else}
                <ol class="timeline">
                    {#each items as item (item.id)}
                        <li class="timeline-item">
                            <span class="flag" class:anomaly={item.flag === 'anomaly'}>
                                {item.flag}
                            </span>
                            <div>
                                <div class="text-sm">{item.body}</div>
                                <div class="text-xs text-muted-foreground">
                                    {item.author_name} • <span title={new Date(item.created_at).toLocaleString()}>{formatDate(item.created_at)}</span>
                                    {#if item.source === 'run' && item.run_label}
                                        {#if item.run_slug && item.run_project_slug}
                                            • <a class="underline" href={paths.run(item.run_project_slug, item.run_slug)}>{item.run_label}</a>
                                        {:else}
                                            • {item.run_label}
                                        {/if}
                                    {/if}
                                </div>
                            </div>
                        </li>
                    {/each}
                </ol>
                {#if truncated}
                    <div class="text-xs text-amber-700 mt-2 flex items-start gap-1.5">
                        <span aria-hidden="true">⚠</span>
                        <span>
                            Showing the 500 most recent observations.
                            Older entries are hidden — export the PDF for a complete record.
                        </span>
                    </div>
                {/if}
            {/if}
        </CardContent>
    </Card>
</aside>

<style>
.timeline { list-style: none; padding: 0; margin: 0; }
.timeline-item {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.5rem;
    padding: 0.5rem 0;
    border-left: 2px solid var(--border);
    padding-left: 0.75rem;
    margin-left: 0.25rem;
}
.flag {
    font-size: 0.65rem;
    text-transform: uppercase;
    background: var(--muted);
    color: var(--muted-fg);
    padding: 0.1rem 0.35rem;
    border-radius: 0.25rem;
    height: fit-content;
}
.flag.anomaly {
    background: color-mix(in oklch, oklch(0.85 0.18 80) 30%, transparent);
    color: oklch(0.4 0.2 60);
}
</style>
