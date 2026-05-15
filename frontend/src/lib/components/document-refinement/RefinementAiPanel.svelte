<script module lang="ts">
    /** A region the user wants the AI to fix. */
    export interface AiSelection {
        scope: 'selection' | 'block' | 'document';
        markdown: string;
        context: string;
        page?: number;
        bbox?: [number, number, number, number];
    }
</script>

<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import { Sparkles } from 'lucide-svelte';
    import { refineDocumentWithAi } from '$lib/api/documents';

    interface Props {
        documentId: string;
        selection: AiSelection | null;
        onAccept: (suggestedMarkdown: string) => void;
        onCancel: () => void;
    }

    let { documentId, selection, onAccept, onCancel }: Props = $props();

    let instruction = $state('');
    let loading = $state(false);
    let error = $state<string | null>(null);
    let suggestion = $state<string | null>(null);

    const SCOPES: AiSelection['scope'][] = ['selection', 'block', 'document'];
    // Scope chip mirrors the incoming selection but stays user-overridable.
    let scope = $state<AiSelection['scope']>('selection');
    $effect(() => {
        if (selection) scope = selection.scope;
    });

    async function submit(): Promise<void> {
        if (!selection || !instruction.trim()) return;
        loading = true;
        error = null;
        suggestion = null;
        try {
            const res = await refineDocumentWithAi(documentId, {
                scope,
                selectionMarkdown: selection.markdown,
                instruction: instruction.trim(),
                surroundingContextMarkdown: selection.context || undefined,
                page: selection.page,
                bbox: selection.bbox,
            });
            suggestion = res.suggested_markdown;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'AI request failed';
        } finally {
            loading = false;
        }
    }

    function accept(): void {
        if (suggestion != null) onAccept(suggestion);
        reset();
    }

    function reject(): void {
        reset();
        onCancel();
    }

    function reset(): void {
        instruction = '';
        suggestion = null;
        error = null;
    }
</script>

<div class="rounded-lg border border-border bg-card shadow-sm">
    <div class="flex items-center gap-2 border-b border-border px-3 py-2">
        <Sparkles class="h-4 w-4 text-violet-500" />
        <h2 class="text-sm font-semibold">AI fix</h2>
    </div>

    <div class="space-y-3 p-3">
        {#if !selection}
            <p class="text-sm text-muted-foreground">
                Select text in the document or click a flag to target an AI fix.
            </p>
        {:else}
            <div class="flex gap-1.5">
                {#each SCOPES as s (s)}
                    <button
                        type="button"
                        class="cursor-pointer rounded-full px-2.5 py-0.5 text-xs capitalize transition-colors duration-150 {scope ===
                        s
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-muted text-muted-foreground hover:bg-muted/70'}"
                        onclick={() => (scope = s)}
                    >
                        {s}
                    </button>
                {/each}
            </div>

            <div class="rounded-md bg-muted/60 p-2">
                <p class="break-words font-mono text-xs text-foreground">
                    {selection.markdown}
                </p>
            </div>

            <textarea
                class="w-full resize-none rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                rows="2"
                placeholder="How should the AI fix this?"
                bind:value={instruction}
            ></textarea>

            <Button
                size="sm"
                class="w-full"
                disabled={loading || !instruction.trim()}
                onclick={submit}
            >
                {loading ? 'Asking AI…' : 'Ask AI'}
            </Button>

            {#if error}
                <p class="text-sm text-destructive">{error}</p>
            {/if}

            {#if suggestion != null}
                <div class="space-y-2 rounded-md border border-violet-200 bg-violet-50 p-2">
                    <div>
                        <p class="text-xs font-medium text-muted-foreground">Original</p>
                        <p class="break-words font-mono text-xs text-foreground line-through decoration-destructive/60">
                            {selection.markdown}
                        </p>
                    </div>
                    <div>
                        <p class="text-xs font-medium text-muted-foreground">Suggested</p>
                        <p class="break-words font-mono text-xs text-foreground">
                            {suggestion}
                        </p>
                    </div>
                    <div class="flex gap-2 pt-1">
                        <Button size="sm" class="flex-1" onclick={accept}>Accept</Button>
                        <Button
                            size="sm"
                            variant="outline"
                            class="flex-1"
                            onclick={reject}
                        >
                            Reject
                        </Button>
                    </div>
                </div>
            {/if}
        {/if}
    </div>
</div>
