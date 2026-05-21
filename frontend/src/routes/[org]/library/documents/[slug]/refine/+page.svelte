<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { fade } from 'svelte/transition';
    import { toast } from 'svelte-sonner';
    import { ArrowLeft, Check, Save } from 'lucide-svelte';
    import { api } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import * as Dialog from '$lib/components/ui/dialog';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import ErrorAlert from '$lib/components/ui/error-alert.svelte';
    import { blockDuration } from '$lib/transitions';
    import {
        DocumentResponseSchema,
        type DocumentResponse,
        type RefinementFlag,
    } from '$lib/schemas/documents';
    import {
        completeDocumentRefinement,
        getDocumentMarkdown,
        updateDocumentMarkdown,
    } from '$lib/api/documents';
    import { toStoredMarkdown } from '$lib/utils/document-markdown';
    import RefinementSidebar from '$lib/components/document-refinement/RefinementSidebar.svelte';
    import RefinementQueue from '$lib/components/document-refinement/RefinementQueue.svelte';
    import RefinementEditor from '$lib/components/document-refinement/RefinementEditor.svelte';
    import { paths } from '$lib/paths';

    let doc = $state<DocumentResponse | null>(null);

    // Route param is the doc slug; sub-resource endpoints are keyed by the
    // document UUID, resolved once the doc loads.
    const documentId = $derived(doc?.id ?? '');
    let initialMarkdown = $state('');
    let loading = $state(true);
    let error = $state<string | null>(null);
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    // Editor bridge (bound from RefinementEditor).
    let getMarkdown = $state<(() => string) | undefined>(undefined);
    let scrollToAnchor = $state<((anchor: string) => void) | undefined>(undefined);

    // Save state.
    let saving = $state(false);
    let hasUnsavedChanges = $state(false);
    let lastSavedAt = $state<Date | null>(null);
    let savedAgoLabel = $state('');
    let autosaveTimer: ReturnType<typeof setTimeout> | null = null;
    let agoTimer: ReturnType<typeof setInterval> | null = null;

    // Right rail state — flag list only; clicking a flag scrolls the editor.
    let activeFlagId = $state<string | null>(null);

    // Complete dialog.
    let completeDialogOpen = $state(false);
    let completing = $state(false);

    const flags = $derived<RefinementFlag[]>(doc?.refinement_flags ?? []);
    const isExtracting = $derived(
        doc != null &&
            ['UPLOADED', 'QUEUED', 'EXTRACTING'].includes(doc.status),
    );
    const isFailed = $derived(doc?.status === 'FAILED');
    const alreadyDone = $derived(
        doc != null &&
            (doc.refinement_status === 'COMPLETE' ||
                ['INDEXING', 'READY', 'INDEXED', 'ENRICHED'].includes(doc.status)),
    );

    async function load(): Promise<void> {
        try {
            const fetched = await api.get(
                `/library/documents/by-slug/${$page.params.slug}`,
                {
                    schema: DocumentResponseSchema,
                },
            );
            doc = fetched;

            if (
                fetched.status === 'AWAITING_REFINEMENT' &&
                initialMarkdown === ''
            ) {
                const md = await getDocumentMarkdown(fetched.id);
                initialMarkdown = md.markdown;
            }

            // Refinement already finished elsewhere — send the user to the viewer.
            if (
                fetched.refinement_status === 'COMPLETE' ||
                ['INDEXING', 'READY', 'INDEXED', 'ENRICHED'].includes(fetched.status)
            ) {
                goto(paths.libraryDoc(fetched.slug));
                return;
            }

            // Poll while extraction is still running.
            const stillExtracting = ['UPLOADED', 'QUEUED', 'EXTRACTING'].includes(
                fetched.status,
            );
            if (stillExtracting && !pollTimer) {
                pollTimer = setInterval(load, 3000);
            } else if (!stillExtracting && pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load document';
        } finally {
            loading = false;
        }
    }

    async function save(): Promise<void> {
        if (!getMarkdown || saving) return;
        saving = true;
        try {
            const stored = toStoredMarkdown(getMarkdown(), documentId);
            await updateDocumentMarkdown(documentId, stored);
            hasUnsavedChanges = false;
            lastSavedAt = new Date();
            updateSavedAgo();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Save failed');
        } finally {
            saving = false;
        }
    }

    function handleEditorUpdate(): void {
        hasUnsavedChanges = true;
        if (autosaveTimer) clearTimeout(autosaveTimer);
        autosaveTimer = setTimeout(() => {
            void save();
        }, 8000);
    }

    function updateSavedAgo(): void {
        if (!lastSavedAt) {
            savedAgoLabel = '';
            return;
        }
        const secs = Math.round((Date.now() - lastSavedAt.getTime()) / 1000);
        if (secs < 5) savedAgoLabel = 'saved just now';
        else if (secs < 60) savedAgoLabel = `saved ${secs} sec ago`;
        else savedAgoLabel = `saved ${Math.round(secs / 60)} min ago`;
    }

    function handleFlagClick(flag: RefinementFlag): void {
        activeFlagId = flag.id;
        if (flag.block_anchor) scrollToAnchor?.(flag.block_anchor);
    }

    async function handleComplete(): Promise<void> {
        completing = true;
        try {
            if (hasUnsavedChanges) await save();
            await completeDocumentRefinement(documentId);
            toast.success('Refinement complete — indexing started');
            completeDialogOpen = false;
            hasUnsavedChanges = false;
            if (doc) goto(paths.libraryDoc(doc.slug));
        } catch (e: unknown) {
            toast.error(
                e instanceof Error ? e.message : 'Could not complete refinement',
            );
        } finally {
            completing = false;
        }
    }

    function beforeUnload(e: BeforeUnloadEvent): void {
        if (hasUnsavedChanges) {
            e.preventDefault();
            e.returnValue = '';
        }
    }

    onMount(() => {
        void load();
        window.addEventListener('beforeunload', beforeUnload);
        agoTimer = setInterval(updateSavedAgo, 5000);
    });
    onDestroy(() => {
        if (pollTimer) clearInterval(pollTimer);
        if (autosaveTimer) clearTimeout(autosaveTimer);
        if (agoTimer) clearInterval(agoTimer);
        window.removeEventListener('beforeunload', beforeUnload);
    });
</script>

<div class="mx-auto max-w-[1600px] space-y-4 px-4 py-4">
    {#if doc}
        <a
            href={paths.libraryDoc(doc.slug)}
            class="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
            <ArrowLeft class="h-4 w-4" />
            Back to document
        </a>
    {/if}

    {#if loading}
        <div in:fade={{ duration: blockDuration() }}>
            <LoadingSpinner message="Loading document…" />
        </div>
    {:else if error}
        <div in:fade={{ duration: blockDuration() }}>
            <ErrorAlert message="Error: {error}" />
        </div>
    {:else if isFailed}
        <div in:fade={{ duration: blockDuration() }}>
            <ErrorAlert
                message="Extraction failed: {doc?.error_message ??
                    'unknown error'}"
            />
        </div>
    {:else if isExtracting}
        <div
            in:fade={{ duration: blockDuration() }}
            class="rounded-md border border-amber-200 bg-amber-50 p-6 text-amber-800"
        >
            <div class="flex items-center gap-3">
                <div
                    class="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-amber-600 border-t-transparent"
                ></div>
                <span class="text-sm font-medium">
                    Extracting document — this page will update automatically.
                </span>
            </div>
        </div>
    {:else if doc}
        <!-- Toolbar -->
        <div
            in:fade={{ duration: blockDuration() }}
            class="flex flex-wrap items-center justify-between gap-3"
        >
            <div>
                <h1 class="text-xl font-bold tracking-tight">{doc.title}</h1>
                <p class="text-xs text-muted-foreground">
                    Review the extracted text, fix any artifacts, then mark
                    refinement complete.
                </p>
            </div>
            <div class="flex items-center gap-3">
                <span class="text-xs text-muted-foreground">
                    {#if saving}
                        Saving…
                    {:else if hasUnsavedChanges}
                        Unsaved changes
                    {:else if savedAgoLabel}
                        {savedAgoLabel}
                    {/if}
                </span>
                <Button
                    variant="outline"
                    size="sm"
                    disabled={saving || !hasUnsavedChanges}
                    onclick={() => save()}
                >
                    <Save class="mr-2 h-4 w-4" />
                    Save
                </Button>
                <Button size="sm" onclick={() => (completeDialogOpen = true)}>
                    <Check class="mr-2 h-4 w-4" />
                    Mark refinement complete
                </Button>
            </div>
        </div>

        <!-- Workspace: sidebar + editor, plus a flag-queue rail when there are flags to triage. -->
        <div
            class={[
                'grid gap-4',
                flags.length > 0
                    ? 'lg:grid-cols-[260px_minmax(0,1fr)_320px]'
                    : 'lg:grid-cols-[260px_minmax(0,1fr)]',
            ]}
        >
            <RefinementSidebar
                documentId={doc.id}
                mimeType={doc.mime_type}
                pageCount={doc.page_count}
                status={doc.status}
                sourceFormat={doc.source_format}
                ocrEngine={doc.doc_metadata?.ocr_engine as string | undefined}
            />

            <div class="min-h-[60vh] lg:h-[calc(100vh-12rem)]">
                <RefinementEditor
                    documentId={doc.id}
                    {initialMarkdown}
                    onUpdate={handleEditorUpdate}
                    bind:getMarkdown
                    bind:scrollToAnchor
                />
            </div>

            {#if flags.length > 0}
                <div class="space-y-4">
                    <RefinementQueue
                        {flags}
                        {activeFlagId}
                        onFlagClick={handleFlagClick}
                    />
                </div>
            {/if}
        </div>
    {/if}
</div>

<Dialog.Root bind:open={completeDialogOpen}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>Mark refinement complete?</Dialog.Title>
            <Dialog.Description>
                Indexing will begin and the document becomes searchable. You can
                re-open refinement later from the document page if needed.
            </Dialog.Description>
        </Dialog.Header>
        <Dialog.Footer>
            <Button
                variant="outline"
                onclick={() => (completeDialogOpen = false)}
                disabled={completing}
            >
                Cancel
            </Button>
            <Button onclick={handleComplete} disabled={completing}>
                {completing ? 'Finishing…' : 'Mark complete'}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
