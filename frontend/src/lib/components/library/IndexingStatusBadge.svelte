<script lang="ts">
    import { Badge } from '$lib/components/ui/badge';
    import { Loader2, CheckCircle2, AlertTriangle, XCircle, Clock } from 'lucide-svelte';
    import { deriveIndexingState } from '$lib/utils/document-utils';

    interface Props {
        document: { status: string; chunk_count: number; embedded_count: number };
        /** Show coverage % for partial state, ratio for processing. */
        verbose?: boolean;
    }

    let { document, verbose = false }: Props = $props();
    const state = $derived(deriveIndexingState(document));
</script>

{#if state.kind === 'queued'}
    <Badge variant="outline" class="gap-1 text-muted-foreground border-border">
        <Clock class="h-3 w-3" /> Queued
    </Badge>
{:else if state.kind === 'processing'}
    <Badge
        variant="outline"
        class="gap-1 border-primary/30 bg-primary/5 text-primary"
    >
        <Loader2 class="h-3 w-3 animate-spin" />
        Indexing{verbose && state.chunkCount > 0
            ? ` · ${state.embeddedCount}/${state.chunkCount}`
            : ''}
    </Badge>
{:else if state.kind === 'indexed'}
    <Badge
        variant="outline"
        class="gap-1 border-accent/40 bg-accent/10 text-accent"
    >
        <CheckCircle2 class="h-3 w-3" /> Indexed
    </Badge>
{:else if state.kind === 'partial'}
    <Badge
        variant="outline"
        class="gap-1 border-amber-300 bg-amber-50 text-amber-800"
    >
        <AlertTriangle class="h-3 w-3" />
        Partial{verbose ? ` · ${state.coverage}%` : ''}
    </Badge>
{:else if state.kind === 'failed'}
    <Badge variant="destructive" class="gap-1">
        <XCircle class="h-3 w-3" /> Failed
    </Badge>
{:else}
    <Badge variant="outline" class="text-muted-foreground">{state.label}</Badge>
{/if}
