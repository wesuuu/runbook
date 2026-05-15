<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import type { Editor } from '@tiptap/core';
    import { getToken } from '$lib/auth.svelte';
    import { toDisplayMarkdown } from '$lib/utils/document-markdown';

    interface SelectionPayload {
        markdown: string;
        context: string;
    }

    interface Props {
        documentId: string;
        /** Stored markdown (relative image refs) — rewritten to display form on mount. */
        initialMarkdown: string;
        editable?: boolean;
        /** Fired on every editor change. */
        onUpdate?: () => void;
        /** Fired when the user changes the text selection. */
        onSelectionChange?: (payload: SelectionPayload) => void;
        /** Bindable: returns current editor markdown in DISPLAY form (absolute image URLs). */
        getMarkdown?: () => string;
        /** Bindable: replaces the current selection with the given markdown. */
        applyToSelection?: (markdown: string) => void;
        /** Bindable: best-effort scroll to a flagged block by anchor. */
        scrollToAnchor?: (anchor: string) => void;
    }

    let {
        documentId,
        initialMarkdown,
        editable = true,
        onUpdate,
        onSelectionChange,
        getMarkdown = $bindable(),
        applyToSelection = $bindable(),
        scrollToAnchor = $bindable(),
    }: Props = $props();

    // Dynamically imported edra components (kept out of the base bundle / jsdom).
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let EdraEditor: any = $state(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let EdraToolBar: any = $state(null);
    let editor = $state<Editor>();

    const displayMarkdown = $derived(
        toDisplayMarkdown(initialMarkdown, documentId, getToken()),
    );

    onMount(async () => {
        const edra = await import('$lib/components/edra/shadcn');
        EdraEditor = edra.EdraEditor;
        EdraToolBar = edra.EdraToolBar;
    });

    // Wire the bindable bridge + selection listener once the editor exists.
    $effect(() => {
        if (!editor) return;
        const ed = editor;

        getMarkdown = () => ed.storage.markdown.getMarkdown() as string;

        applyToSelection = (markdown: string) => {
            // AI suggestions may carry relative image refs — normalise to display form.
            const display = toDisplayMarkdown(markdown, documentId, getToken());
            ed.chain().focus().insertContent(display).run();
        };

        scrollToAnchor = (anchor: string) => {
            // Forward-compat: Phase 1 emits no flags, so no anchored nodes exist yet.
            const el = ed.view.dom.querySelector(`[data-anchor="${anchor}"]`);
            if (el instanceof HTMLElement) {
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        };

        const handleSelection = () => {
            const { from, to } = ed.state.selection;
            const markdown = ed.state.doc.textBetween(from, to, '\n');
            const before = ed.state.doc.textBetween(Math.max(0, from - 200), from, '\n');
            const after = ed.state.doc.textBetween(
                to,
                Math.min(ed.state.doc.content.size, to + 200),
                '\n',
            );
            onSelectionChange?.({ markdown, context: `${before}${markdown}${after}` });
        };
        ed.on('selectionUpdate', handleSelection);
        return () => {
            ed.off('selectionUpdate', handleSelection);
        };
    });

    onDestroy(() => {
        if (editor && !editor.isDestroyed) editor.destroy();
    });
</script>

<div class="refinement-editor flex h-full flex-col rounded-lg border border-border bg-card shadow-sm">
    {#if EdraEditor && EdraToolBar}
        {@const ToolBar = EdraToolBar}
        {@const Editor = EdraEditor}
        {#if editor}
            <ToolBar {editor} class="border-b border-border" />
        {/if}
        <div class="min-h-0 flex-1 overflow-y-auto">
            <Editor
                bind:editor
                content={displayMarkdown}
                {editable}
                {onUpdate}
                class="p-6"
            />
        </div>
    {:else}
        <div class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            Loading editor…
        </div>
    {/if}
</div>
