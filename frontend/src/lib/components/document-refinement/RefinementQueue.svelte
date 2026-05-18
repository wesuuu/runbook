<script lang="ts">
    import { Badge } from '$lib/components/ui/badge';
    import { CheckCircle2 } from 'lucide-svelte';
    import type { RefinementFlag } from '$lib/schemas/documents';

    interface Props {
        flags: RefinementFlag[];
        activeFlagId: string | null;
        onFlagClick: (flag: RefinementFlag) => void;
    }

    let { flags, activeFlagId, onFlagClick }: Props = $props();

    function confidencePercent(flag: RefinementFlag): string | null {
        if (flag.confidence == null) return null;
        return `${Math.round(flag.confidence * 100)}%`;
    }
</script>

<div class="rounded-lg border border-border bg-card shadow-sm">
    <div class="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 class="text-sm font-semibold">Refinement queue</h2>
        {#if flags.length > 0}
            <Badge variant="secondary">{flags.length}</Badge>
        {/if}
    </div>

    {#if flags.length === 0}
        <div class="flex flex-col items-center gap-2 px-3 py-8 text-center">
            <CheckCircle2 class="h-6 w-6 text-muted-foreground/60" />
            <p class="text-sm text-muted-foreground">
                No flags — extraction looks clean.
            </p>
        </div>
    {:else}
        <ul class="divide-y divide-border">
            {#each flags as flag (flag.id)}
                <li>
                    <button
                        type="button"
                        data-active={flag.id === activeFlagId}
                        class="w-full cursor-pointer px-3 py-2 text-left transition-colors duration-150 hover:bg-muted/60 {flag.id ===
                        activeFlagId
                            ? 'bg-amber-50'
                            : ''}"
                        onclick={() => onFlagClick(flag)}
                    >
                        <div class="flex items-center justify-between gap-2">
                            <span class="text-xs font-medium text-muted-foreground">
                                {flag.kind.replace(/_/g, ' ')}
                            </span>
                            <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
                                {#if confidencePercent(flag)}
                                    <span>{confidencePercent(flag)}</span>
                                {/if}
                                {#if flag.page != null}
                                    <span>p.{flag.page}</span>
                                {/if}
                            </span>
                        </div>
                        {#if flag.source_text}
                            <p class="mt-1 break-words font-mono text-sm text-foreground">
                                {flag.source_text}
                            </p>
                        {/if}
                    </button>
                </li>
            {/each}
        </ul>
    {/if}
</div>
