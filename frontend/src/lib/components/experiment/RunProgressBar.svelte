<script lang="ts">
  import { runSegmentClass, runSegmentLabel, isPulsing } from '../shared/runProgress';

  interface RunSummary {
    status: string;
    outcome?: string | null;
  }

  interface Props {
    /** Capped run summaries (<= 60) from the API. */
    runs: RunSummary[];
    /** True total — may exceed runs.length. */
    total: number;
  }

  let { runs, total }: Props = $props();

  const hiddenCount = $derived(Math.max(0, total - runs.length));
</script>

<div class="flex items-center gap-2">
  {#if runs.length === 0}
    <div class="h-2 flex-1 rounded-full bg-muted" aria-label="No runs yet"></div>
  {:else}
    <div class="flex h-2 flex-1 gap-1 overflow-hidden rounded-full">
      {#each runs as run, i (i)}
        <div
          class="h-full flex-1 rounded-sm {runSegmentClass(run.status, run.outcome)} {isPulsing(
            run.status,
          )
            ? 'animate-pulse'
            : ''}"
          title={runSegmentLabel(run.status, run.outcome)}
          aria-label={runSegmentLabel(run.status, run.outcome)}
        ></div>
      {/each}
    </div>
  {/if}
  <span class="whitespace-nowrap text-xs text-muted-foreground">
    {#if total === 0}
      No runs yet
    {:else if hiddenCount > 0}
      {runs.length} of {total} runs
    {:else}
      {total} run{total === 1 ? '' : 's'}
    {/if}
  </span>
</div>
