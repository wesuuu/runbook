<script lang="ts">
    import { deriveIndexingState } from '$lib/utils/document-utils';
    import { Button } from '$lib/components/ui/button';
    import {
        AlertTriangle,
        XCircle,
        Loader2,
        Clock,
        RotateCcw,
    } from 'lucide-svelte';

    interface Props {
        document: { status: string; chunk_count: number; embedded_count: number };
        /** Optional latest error message from the document (shown in failed state). */
        errorMessage?: string | null;
        /** Called when the user clicks the retry CTA (failed or partial). */
        onRetry?: () => void;
        retrying?: boolean;
    }

    let { document, errorMessage = null, onRetry, retrying = false }: Props = $props();
    const state = $derived(deriveIndexingState(document));
</script>

{#if state.kind === 'queued'}
    <div
        class="flex items-start gap-3 rounded-md border-l-4 border-l-border bg-muted/40 px-4 py-3"
        role="status"
    >
        <Clock class="h-5 w-5 text-muted-foreground mt-0.5 shrink-0" />
        <div class="text-sm">
            <p class="font-medium">Queued for processing</p>
            <p class="text-muted-foreground">
                We've received your document and it'll start indexing shortly.
            </p>
        </div>
    </div>
{:else if state.kind === 'processing'}
    <div
        class="flex items-start gap-3 rounded-md border-l-4 border-l-primary bg-primary/5 px-4 py-3"
        role="status"
    >
        <Loader2 class="h-5 w-5 text-primary mt-0.5 shrink-0 animate-spin" />
        <div class="text-sm">
            <p class="font-medium text-primary">Indexing in progress</p>
            <p class="text-muted-foreground">
                Extracting text, chunking, and embedding for semantic search.
                {#if state.chunkCount > 0}
                    {state.embeddedCount}/{state.chunkCount} chunks embedded so far.
                {/if}
            </p>
        </div>
    </div>
{:else if state.kind === 'partial'}
    <div
        class="flex items-start gap-3 rounded-md border-l-4 border-l-amber-400 bg-amber-50 px-4 py-3"
        role="status"
    >
        <AlertTriangle class="h-5 w-5 text-amber-600 mt-0.5 shrink-0" />
        <div class="text-sm flex-1">
            <p class="font-medium text-amber-900">Partially indexed — semantic search degraded</p>
            <p class="text-amber-800">
                {state.coverage}% of chunks have embeddings ({state.missing} missing).
                The document is readable, but semantic search won't surface the
                un-embedded chunks. Retry to re-run embedding.
            </p>
        </div>
        {#if onRetry}
            <Button
                size="sm"
                variant="outline"
                class="shrink-0 border-amber-400 text-amber-900 hover:bg-amber-100"
                disabled={retrying}
                onclick={onRetry}
            >
                <RotateCcw class="h-3.5 w-3.5 mr-1.5 {retrying ? 'animate-spin' : ''}" />
                {retrying ? 'Retrying...' : 'Retry embedding'}
            </Button>
        {/if}
    </div>
{:else if state.kind === 'failed'}
    <div
        class="flex items-start gap-3 rounded-md border-l-4 border-l-destructive bg-destructive/5 px-4 py-3"
        role="alert"
    >
        <XCircle class="h-5 w-5 text-destructive mt-0.5 shrink-0" />
        <div class="text-sm flex-1">
            <p class="font-medium text-destructive">Indexing failed</p>
            {#if errorMessage}
                <p class="text-destructive/90 break-words">{errorMessage}</p>
            {:else}
                <p class="text-muted-foreground">
                    Something went wrong while processing this document.
                </p>
            {/if}
        </div>
        {#if onRetry}
            <Button
                size="sm"
                variant="outline"
                class="shrink-0 border-destructive/40 text-destructive hover:bg-destructive/10"
                disabled={retrying}
                onclick={onRetry}
            >
                <RotateCcw class="h-3.5 w-3.5 mr-1.5 {retrying ? 'animate-spin' : ''}" />
                {retrying ? 'Retrying...' : 'Retry'}
            </Button>
        {/if}
    </div>
{/if}
