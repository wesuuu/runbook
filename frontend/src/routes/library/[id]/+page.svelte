<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import * as Dialog from '$lib/components/ui/dialog';
    import { toast } from 'svelte-sonner';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import {
        getFileTypeLabel,
        getStatusLabel,
        formatFileSize,
        extractSectionNav,
        extractFallbackSectionNav,
        VIEWABLE_STATUSES,
        type SectionNav,
    } from '$lib/utils/document-utils';
    import { API_BASE } from '$lib/config';
    import { getToken } from '$lib/auth.svelte';
    import { Input } from '$lib/components/ui/input';
    import { ArrowLeft, RotateCcw, Trash2, ExternalLink, Search, X, ChevronDown, ChevronRight, List } from 'lucide-svelte';
    import { fade } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { blockDuration, listDuration } from '$lib/transitions';
    import MarkdownRenderer from '$lib/components/shared/MarkdownRenderer.svelte';
    import { z } from 'zod';

    // --- Schemas ---
    const DocumentChunkSchema = z.object({
        id: z.string(),
        document_id: z.string(),
        chunk_index: z.number(),
        content: z.string(),
        token_count: z.number(),
        page_number: z.number().nullable(),
        chunk_metadata: z.record(z.string(), z.unknown()),
        created_at: z.string(),
    }).passthrough();
    type DocumentChunk = z.infer<typeof DocumentChunkSchema>;

    const ProcessingProgressSchema = z.object({
        stage: z.string(),
        stage_label: z.string(),
        current: z.number(),
        total: z.number(),
        percent: z.number(),
    }).passthrough();

    const TOCEntrySchema = z.object({
        level: z.number(),
        text: z.string(),
        page_number: z.number().nullable(),
        chunk_index: z.number().nullable(),
    }).passthrough();
    type TOCEntry = z.infer<typeof TOCEntrySchema>;

    const DocumentDetailSchema = z.object({
        id: z.string(),
        title: z.string(),
        original_filename: z.string(),
        mime_type: z.string(),
        file_size_bytes: z.number(),
        file_path: z.string(),
        status: z.string(),
        page_count: z.number().nullable(),
        source_url: z.string().nullable(),
        error_message: z.string().nullable(),
        tags: z.array(z.string()),
        chunk_count: z.number(),
        chunks_preview: z.array(DocumentChunkSchema),
        structure_metadata: z.record(z.string(), z.unknown()).nullable(),
        processing_progress: ProcessingProgressSchema.nullable(),
        table_of_contents: z.array(TOCEntrySchema),
        created_at: z.string(),
        updated_at: z.string(),
        can_delete: z.boolean(),
    }).passthrough();
    type DocumentDetail = z.infer<typeof DocumentDetailSchema>;

    let document = $state<DocumentDetail | null>(null);
    let allChunks = $state<DocumentChunk[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let loadingMoreChunks = $state(false);
    let allChunksLoaded = $state(false);
    let deleteDialogOpen = $state(false);
    let deleting = $state(false);
    let retrying = $state(false);
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    const CHUNKS_PER_PAGE = 50;

    // In-document search (non-PDF only)
    let docSearchQuery = $state('');
    let matchingChunkIndices = $state<Set<number>>(new Set());

    // Structure-aware rendering (non-PDF reader)
    let showFrontMatter = $state(false);
    let showToc = $state(false);
    let showSectionNav = $state(true);

    // PDF viewer ref for page navigation
    let pdfIframe = $state<HTMLIFrameElement | null>(null);

    const documentId = $derived($page.params.id);
    const isPdf = $derived(document?.mime_type === 'application/pdf');
    const isEnriched = $derived(
        document?.status === 'ENRICHED' || document?.status === 'READY'
    );
    const isViewable = $derived(
        document ? VIEWABLE_STATUSES.has(document.status) : false
    );

    // Build section nav for sidebar
    const sectionNav = $derived.by<SectionNav[]>(() => {
        if (!document) return [];

        // For PDFs: only use API TOC (chunk-based fallbacks don't work for iframe viewer)
        if (isPdf) {
            if (document.table_of_contents && document.table_of_contents.length > 0) {
                return document.table_of_contents
                    .filter((e: TOCEntry) => e.page_number != null)
                    .map((e: TOCEntry) => ({
                        heading: e.text,
                        chunkIndex: e.page_number!,
                    }));
            }
            return [];
        }

        // For non-PDFs: prefer API TOC, then enriched chunk metadata, then fallback
        if (document.table_of_contents && document.table_of_contents.length > 0) {
            return document.table_of_contents
                .filter((e: TOCEntry) => e.chunk_index != null)
                .map((e: TOCEntry) => ({
                    heading: e.text,
                    chunkIndex: e.chunk_index!,
                }));
        }
        const enrichedNav = extractSectionNav(allChunks);
        if (enrichedNav.length > 0) return enrichedNav;
        return extractFallbackSectionNav(allChunks);
    });

    function getChunkRole(chunk: DocumentChunk): string {
        return (chunk.chunk_metadata?.role as string) ?? 'body';
    }

    // ─── Workbench derived values ──────────────────────────────────
    type PipelineState = 'done' | 'now' | 'pending' | 'failed';
    interface PipelineStep {
        id: string;
        label: string;
        state: PipelineState;
        sub?: string;
    }

    const shortDocId = $derived(
        document
            ? `${document.id.slice(0, 8)}…${document.id.slice(-7)}`
            : ''
    );

    // True while the pipeline is actively churning: we render the
    // workbench live-card with a sliding bar + shimmer skeleton in place
    // of reader content. AWAITING_REFINEMENT is its own state below.
    const isLiveExtraction = $derived.by(() => {
        if (!document) return false;
        const s = document.status;
        const hasActiveProgress = !!(
            document.processing_progress &&
            document.processing_progress.stage !== ''
        );
        return (
            s === 'UPLOADED' ||
            s === 'QUEUED' ||
            s === 'EXTRACTING' ||
            s === 'INDEXING' ||
            s === 'PROCESSING' ||
            (s === 'INDEXED' && hasActiveProgress)
        );
    });

    const pipelineSteps = $derived.by<PipelineStep[]>(() => {
        const s = document?.status ?? '';
        const steps: PipelineStep[] = [
            {
                id: 'upload',
                label: 'Uploaded',
                state: 'done',
                sub: document ? formatDate(document.created_at) : undefined,
            },
            {
                id: 'extract',
                label: 'Extracting',
                state: 'pending',
                sub: 'docling + easyocr',
            },
            { id: 'refine', label: 'Awaiting refinement', state: 'pending' },
            { id: 'index', label: 'Indexing', state: 'pending' },
            { id: 'ready', label: 'Ready', state: 'pending' },
        ];

        if (s === 'UPLOADED' || s === 'QUEUED') {
            // upload done; extract is queued but hasn't started — leave pending
        } else if (s === 'EXTRACTING') {
            steps[1].state = 'now';
            steps[1].sub = 'docling + easyocr · running';
        } else if (s === 'AWAITING_REFINEMENT') {
            steps[1].state = 'done';
            steps[2].state = 'now';
        } else if (s === 'INDEXING' || s === 'PROCESSING') {
            steps[1].state = 'done';
            steps[2].state = 'done';
            steps[3].state = 'now';
        } else if (s === 'INDEXED' || s === 'READY' || s === 'ENRICHED') {
            steps[1].state = 'done';
            steps[2].state = 'done';
            steps[3].state = 'done';
            steps[4].state = 'done';
        }

        if (s === 'FAILED') {
            // Mark whichever step would currently be "now" as failed.
            const activeIdx = steps.findIndex(st => st.state === 'pending');
            const failIdx = activeIdx === -1 ? steps.length - 1 : activeIdx;
            steps[failIdx].state = 'failed';
        }
        return steps;
    });

    const liveStageText = $derived.by(() => {
        if (!document) return '';
        const p = document.processing_progress;
        if (p && p.stage) {
            if (p.total > 0) {
                return `stage: ${p.stage_label || p.stage} · ${p.current} / ${p.total}`;
            }
            return `stage: ${p.stage_label || p.stage}`;
        }
        switch (document.status) {
            case 'UPLOADED':
            case 'QUEUED':
                return 'stage: queued';
            case 'EXTRACTING':
                return 'stage: docling parse';
            case 'INDEXING':
            case 'PROCESSING':
                return 'stage: indexing';
            default:
                return '';
        }
    });

    const liveTitle = $derived.by(() => {
        if (!document) return '';
        switch (document.status) {
            case 'UPLOADED':
            case 'QUEUED':
                return 'Queued for extraction';
            case 'EXTRACTING':
                return 'Extraction in progress';
            case 'INDEXING':
            case 'PROCESSING':
                return 'Indexing for search';
            default:
                return 'Working…';
        }
    });

    async function loadDocument() {
        try {
            const doc = await api.get(`/library/documents/${documentId}`, { schema: DocumentDetailSchema });
            document = doc;
            allChunks = doc.chunks_preview;

            const hasActiveProgress = doc.processing_progress && doc.processing_progress.stage !== '';
            const shouldPoll =
                doc.status === 'PROCESSING' ||
                doc.status === 'QUEUED' ||
                doc.status === 'EXTRACTING' ||
                doc.status === 'INDEXING' ||
                (doc.status === 'INDEXED' && hasActiveProgress);
            if (shouldPoll && !pollTimer) {
                pollTimer = setInterval(loadDocument, 3000);
            } else if (!shouldPoll && pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load document';
        } finally {
            loading = false;
        }
    }

    async function loadMoreChunks() {
        if (!document || loadingMoreChunks) return;
        loadingMoreChunks = true;
        try {
            const offset = allChunks.length;
            const chunks = await api.get(
                `/library/documents/${documentId}/chunks?limit=${CHUNKS_PER_PAGE}&offset=${offset}`,
                { schema: z.array(DocumentChunkSchema) },
            );
            allChunks = [...allChunks, ...chunks];
            if (chunks.length < CHUNKS_PER_PAGE || allChunks.length >= document.chunk_count) {
                allChunksLoaded = true;
            }
        } catch (e: unknown) {
            toast.error('Failed to load more content');
        } finally {
            loadingMoreChunks = false;
        }
    }

    async function handleRetry() {
        retrying = true;
        try {
            await api.post(`/library/documents/${documentId}/retry`, {});
            toast.success('Reprocessing started');
            await loadDocument();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Retry failed');
        } finally {
            retrying = false;
        }
    }

    async function handleDelete() {
        deleting = true;
        try {
            await api.delete(`/library/documents/${documentId}`);
            toast.success('Document deleted');
            goto('/library');
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : 'Delete failed';
            if (msg.includes('403') || msg.includes('permission')) {
                toast.error('You do not have permission to delete this document');
            } else {
                toast.error(msg);
            }
        } finally {
            deleting = false;
            deleteDialogOpen = false;
        }
    }

    function formatDate(dateStr: string): string {
        return new Date(dateStr).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function handleDocSearch() {
        const q = docSearchQuery.trim().toLowerCase();
        if (!q) {
            matchingChunkIndices = new Set();
            return;
        }
        const matches = new Set<number>();
        for (let i = 0; i < allChunks.length; i++) {
            if (allChunks[i].content.toLowerCase().includes(q)) {
                matches.add(i);
            }
        }
        matchingChunkIndices = matches;

        if (matches.size > 0) {
            const firstIdx = Math.min(...matches);
            const el = window.document.getElementById(`chunk-${firstIdx}`);
            el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    function clearDocSearch() {
        docSearchQuery = '';
        matchingChunkIndices = new Set();
    }

    function scrollToChunk(chunkIndex: number) {
        const el = window.document.getElementById(`chunk-${chunkIndex}`);
        el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function navigatePdfToPage(pageNumber: number) {
        if (!document || !pdfIframe) return;
        // Browser PDF viewers support #page=N fragment
        pdfIframe.src = `${API_BASE}/library/documents/${document.id}/download?token=${getToken()}#page=${pageNumber}`;
    }

    function handleSidebarClick(index: number) {
        if (isPdf) {
            navigatePdfToPage(index);
        } else {
            scrollToChunk(index);
        }
    }

    onMount(async () => {
        await loadDocument();
        const chunkParam = $page.url.searchParams.get('chunk');
        if (chunkParam !== null) {
            const idx = parseInt(chunkParam, 10);
            if (!isNaN(idx)) {
                await new Promise(r => setTimeout(r, 300));
                scrollToChunk(idx);
            }
        }
    });
    onDestroy(() => {
        if (pollTimer) clearInterval(pollTimer);
    });
</script>

<div class="max-w-7xl mx-auto px-6 pb-16 pt-4">
    {#if loading}
        <div in:fade={{ duration: blockDuration() }}>
            <LoadingSpinner message="Loading document..." />
        </div>
    {:else if error}
        <div in:fade={{ duration: blockDuration() }} class="bg-destructive/10 text-destructive p-4 rounded-md">Error: {error}</div>
    {:else if document}
        <!-- ─── Topbar: breadcrumbs + doc id ─── -->
        <div in:fade={{ duration: blockDuration() }} class="flex justify-between items-center text-sm text-muted-foreground mb-7 gap-4">
            <nav class="flex items-center min-w-0">
                <a href="/library" class="hover:text-foreground transition-colors inline-flex items-center gap-1">
                    <ArrowLeft class="h-3.5 w-3.5" />
                    Library
                </a>
                <span class="opacity-50 px-2">/</span>
                <span class="text-foreground font-medium truncate">{document.title}</span>
            </nav>
            <span class="font-mono text-[11.5px] shrink-0">doc · {shortDocId}</span>
        </div>

        <!-- ─── Header: title + chips + actions ─── -->
        <header in:fade={{ duration: blockDuration() }} class="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_auto] gap-6 items-end pb-5 border-b border-border">
            <div class="min-w-0">
                <h1 class="text-3xl font-semibold tracking-tight mb-2 leading-tight truncate">{document.title}</h1>
                <div class="flex flex-wrap items-center gap-2 text-xs">
                    <!-- Status chip — pulses while live -->
                    <span class="chip" class:chip-live={isLiveExtraction} class:chip-done={document.status === 'INDEXED' || document.status === 'READY' || document.status === 'ENRICHED'} class:chip-failed={document.status === 'FAILED'} class:chip-refine={document.status === 'AWAITING_REFINEMENT'}>
                        <span class="dot"></span>{getStatusLabel(document.status)}
                    </span>
                    <span class="chip"><span class="dot"></span>{getFileTypeLabel(document.mime_type)}</span>
                    <span class="chip"><span class="dot"></span>{formatFileSize(document.file_size_bytes)}</span>
                    {#if document.page_count}
                        <span class="chip"><span class="dot"></span>{document.page_count} pages</span>
                    {/if}
                    <span class="chip"><span class="dot"></span>Uploaded {formatDate(document.created_at)}</span>
                </div>
                {#if document.source_url}
                    <p class="text-xs text-muted-foreground mt-2 truncate">
                        Imported from:
                        <a
                            href={document.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            class="text-primary hover:underline inline-flex items-center gap-1"
                        >
                            {document.source_url}
                            <ExternalLink class="h-3 w-3" />
                        </a>
                    </p>
                {/if}
            </div>
            <div class="flex items-center gap-2 shrink-0">
                {#if document.status === 'FAILED' || document.status === 'QUEUED'}
                    <Button variant="outline" size="sm" onclick={handleRetry} disabled={retrying}>
                        <RotateCcw class="mr-2 h-4 w-4" />
                        {retrying ? 'Retrying…' : 'Re-extract'}
                    </Button>
                {/if}
                {#if document.status === 'AWAITING_REFINEMENT'}
                    <a href="/library/documents/{document.id}/refine">
                        <Button size="sm">Refine document</Button>
                    </a>
                {:else if !isLiveExtraction && document.status !== 'FAILED'}
                    <Button size="sm" variant="outline" disabled>Refined</Button>
                {:else}
                    <Button size="sm" disabled>Refine document</Button>
                {/if}
                {#if document.can_delete}
                    <Button
                        variant="ghost"
                        size="sm"
                        class="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                        onclick={() => (deleteDialogOpen = true)}
                        title="Delete document"
                    >
                        <Trash2 class="h-4 w-4" />
                    </Button>
                {/if}
            </div>
        </header>

        <!-- ─── Body grid: rail + main ─── -->
        <div class="grid grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)] gap-7 mt-7">

            <!-- ─── Left rail ─── -->
            <aside in:fade={{ duration: blockDuration() }} class="flex flex-col gap-5">

                <!-- Pipeline -->
                <section class="rounded-[var(--radius)] border border-border bg-card px-4 py-4">
                    <h3 class="text-[11px] uppercase tracking-[0.09em] text-muted-foreground font-medium mb-3.5">Pipeline</h3>
                    <ol class="pipeline">
                        {#each pipelineSteps as step (step.id)}
                            <li class={step.state}>
                                <span class="node">
                                    {#if step.state === 'done'}✓{:else if step.state === 'now'}●{:else if step.state === 'failed'}!{/if}
                                </span>
                                <span class="label">{step.label}
                                    {#if step.sub}<span class="sub">{step.sub}</span>{/if}
                                </span>
                            </li>
                        {/each}
                    </ol>
                </section>

                <!-- Details -->
                <section class="rounded-[var(--radius)] border border-border bg-card px-4 py-4">
                    <h3 class="text-[11px] uppercase tracking-[0.09em] text-muted-foreground font-medium mb-3.5">Details</h3>
                    <dl class="grid grid-cols-2 gap-x-4 gap-y-3 text-[13px]">
                        <div>
                            <dt class="text-[10.5px] uppercase tracking-[0.09em] text-muted-foreground font-medium mb-0.5">Type</dt>
                            <dd class="font-mono">{document.mime_type}</dd>
                        </div>
                        <div>
                            <dt class="text-[10.5px] uppercase tracking-[0.09em] text-muted-foreground font-medium mb-0.5">Size</dt>
                            <dd class="font-mono">{formatFileSize(document.file_size_bytes)}</dd>
                        </div>
                        {#if document.page_count}
                            <div>
                                <dt class="text-[10.5px] uppercase tracking-[0.09em] text-muted-foreground font-medium mb-0.5">Pages</dt>
                                <dd class="font-mono">{document.page_count}</dd>
                            </div>
                        {/if}
                        <div>
                            <dt class="text-[10.5px] uppercase tracking-[0.09em] text-muted-foreground font-medium mb-0.5">Chunks</dt>
                            <dd class="font-mono">{document.chunk_count}</dd>
                        </div>
                        <div class="col-span-2">
                            <dt class="text-[10.5px] uppercase tracking-[0.09em] text-muted-foreground font-medium mb-0.5">Updated</dt>
                            <dd>{formatDate(document.updated_at)}</dd>
                        </div>
                    </dl>
                </section>

                <!-- Contents (when section nav available) -->
                {#if sectionNav.length > 0 && showSectionNav}
                    <section class="rounded-[var(--radius)] border border-border bg-card px-4 py-4">
                        <div class="flex items-center gap-2 mb-3">
                            <List class="h-3.5 w-3.5 text-muted-foreground" />
                            <h3 class="text-[11px] uppercase tracking-[0.09em] text-muted-foreground font-medium">Contents</h3>
                        </div>
                        <nav class="space-y-0.5 max-h-[calc(100vh-20rem)] overflow-y-auto -mx-1.5">
                            {#each sectionNav as section, i (i)}
                                <button
                                    type="button"
                                    class="block w-full text-left text-xs text-muted-foreground hover:text-foreground px-1.5 py-1 rounded hover:bg-muted/60 transition-colors duration-150 cursor-pointer truncate"
                                    onclick={() => handleSidebarClick(section.chunkIndex)}
                                    title={section.heading}
                                    animate:flip={{ duration: listDuration() }}
                                    in:fade={{ duration: listDuration() }}
                                >
                                    <span class="truncate w-full">{section.heading}</span>
                                </button>
                            {/each}
                        </nav>
                    </section>
                {/if}

                <!-- Tip card while live -->
                {#if isLiveExtraction}
                    <div in:fade={{ duration: blockDuration() }} class="rounded-[var(--radius)] border px-4 py-3 flex gap-2.5 items-start text-[12.5px]" style="background: hsl(195 80% 96%); border-color: hsl(195 50% 80%); color: hsl(195 70% 18%);">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-primary mt-px shrink-0"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                        <span>Heartbeats stream from the extractor every 10&nbsp;s. You can navigate away — we'll keep working in the background.</span>
                    </div>
                {/if}
            </aside>

            <!-- ─── Main column ─── -->
            <main class="min-w-0">
                {#if document.status === 'FAILED'}
                    <!-- Failure card -->
                    <div in:fade={{ duration: blockDuration() }} class="rounded-[var(--radius)] border border-destructive/30 bg-destructive/5 overflow-hidden">
                        <div class="px-5 py-4 border-b border-destructive/20 flex justify-between items-center gap-3">
                            <h2 class="text-sm font-medium text-destructive">Processing failed</h2>
                            <Button size="sm" variant="outline" onclick={handleRetry} disabled={retrying}>
                                <RotateCcw class="mr-2 h-3.5 w-3.5" />
                                {retrying ? 'Retrying…' : 'Retry'}
                            </Button>
                        </div>
                        {#if document.error_message}
                            <pre class="px-5 py-4 text-xs text-destructive whitespace-pre-wrap font-mono leading-relaxed">{document.error_message}</pre>
                        {/if}
                    </div>

                {:else if isLiveExtraction}
                    <!-- Live extraction card with shimmer skeleton -->
                    <div in:fade={{ duration: blockDuration() }} class="live relative rounded-[var(--radius)] border border-border bg-card overflow-hidden">
                        <div class="px-5 py-3.5 border-b border-border flex justify-between items-center gap-3" style="background: linear-gradient(180deg, hsl(200 25% 99%), var(--card));">
                            <h2 class="text-sm font-medium m-0">{liveTitle}</h2>
                            {#if liveStageText}
                                <span class="font-mono text-[11.5px] text-muted-foreground">{liveStageText}</span>
                            {/if}
                        </div>
                        <div class="progress"></div>
                        <div class="p-8 flex flex-col gap-3.5" aria-hidden="true">
                            <div class="skeleton-block h-[22px] w-[55%]"></div>
                            <div class="skeleton-block h-[11px] w-[92%]"></div>
                            <div class="skeleton-block h-[11px] w-[82%]"></div>
                            <div class="skeleton-block h-[11px] w-[48%]"></div>
                            <div class="skeleton-block h-[16px] w-[38%] mt-3"></div>
                            <div class="skeleton-block h-[11px] w-[92%]"></div>
                            <div class="skeleton-block h-[11px] w-[71%]"></div>
                            <div class="skeleton-block h-[110px] w-[65%] rounded-sm"></div>
                            <div class="skeleton-block h-[11px] w-[82%]"></div>
                            <div class="skeleton-block h-[11px] w-[92%]"></div>
                            <div class="skeleton-block h-[11px] w-[48%]"></div>
                        </div>
                        <div class="px-5 py-3 border-t border-border flex justify-between items-center text-xs text-muted-foreground" style="background: linear-gradient(0deg, hsl(200 25% 98%), var(--card));">
                            <span>Preview will appear here once the first page finishes.</span>
                            {#if document.processing_progress && document.processing_progress.percent > 0}
                                <span class="font-mono text-foreground">{document.processing_progress.percent}%</span>
                            {/if}
                        </div>
                    </div>

                {:else if document.status === 'AWAITING_REFINEMENT'}
                    <!-- Ready-for-refinement card -->
                    <div in:fade={{ duration: blockDuration() }} class="rounded-[var(--radius)] border border-border bg-card overflow-hidden">
                        <div class="px-5 py-4 border-b border-border" style="background: linear-gradient(180deg, hsl(200 25% 99%), var(--card));">
                            <h2 class="text-sm font-medium m-0">Extraction complete · awaiting refinement</h2>
                        </div>
                        <div class="px-6 py-8 flex flex-col items-start gap-3 max-w-prose">
                            <p class="text-sm text-muted-foreground leading-relaxed">
                                The raw markdown has been pulled out of your document. Open the refinement editor to review docling's output, fix any artifacts, and approve the file for indexing.
                            </p>
                            <a href="/library/documents/{document.id}/refine">
                                <Button>Refine document</Button>
                            </a>
                        </div>
                    </div>

                {:else if isPdf}
                    <!-- PDF viewer -->
                    <div in:fade={{ duration: blockDuration() }} class="rounded-[var(--radius)] border border-border bg-card overflow-hidden">
                        {#if isViewable}
                            <div class="w-full" style="height: calc(100vh - 14rem);">
                                <iframe
                                    bind:this={pdfIframe}
                                    src="{API_BASE}/library/documents/{document.id}/download?token={getToken()}"
                                    title="PDF viewer — {document.title}"
                                    class="w-full h-full"
                                ></iframe>
                            </div>
                        {:else}
                            <p class="text-muted-foreground text-center py-10 text-sm">PDF not available.</p>
                        {/if}
                    </div>

                {:else}
                    <!-- Non-PDF reader -->
                    <div in:fade={{ duration: blockDuration() }} class="rounded-[var(--radius)] border border-border bg-card overflow-hidden">
                        <div class="px-5 py-3.5 border-b border-border flex justify-between items-center gap-4" style="background: linear-gradient(180deg, hsl(200 25% 99%), var(--card));">
                            <h2 class="text-sm font-medium m-0">Reader</h2>
                            {#if allChunks.length > 0}
                                <div class="relative w-64">
                                    <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                                    <Input
                                        type="text"
                                        placeholder="Find in document…"
                                        class="pl-8 pr-8 h-8 text-sm"
                                        bind:value={docSearchQuery}
                                        oninput={handleDocSearch}
                                    />
                                    {#if docSearchQuery}
                                        <Button
                                            variant="ghost"
                                            size="icon-sm"
                                            class="absolute right-1 top-1/2 -translate-y-1/2 h-6 w-6 text-muted-foreground hover:text-foreground"
                                            onclick={clearDocSearch}
                                        >
                                            <X class="h-3.5 w-3.5" />
                                        </Button>
                                    {/if}
                                </div>
                            {/if}
                        </div>
                        {#if docSearchQuery}
                            <div class="px-5 py-2 border-b border-border text-xs text-muted-foreground">
                                {#if matchingChunkIndices.size > 0}
                                    {matchingChunkIndices.size} match{matchingChunkIndices.size !== 1 ? 'es' : ''} found
                                {:else}
                                    No matches found
                                {/if}
                            </div>
                        {/if}
                        <div class="px-6 py-6">
                            {#if isViewable && document.chunk_count === 0 && document.mime_type.startsWith('image/')}
                                <div class="text-center space-y-4">
                                    <p class="text-muted-foreground text-sm">
                                        This document is an image. Text extraction will be available in a future update.
                                    </p>
                                    <img
                                        src="{API_BASE}/library/documents/{document.id}/download?token={getToken()}"
                                        alt={document.title}
                                        class="max-w-full mx-auto rounded-md shadow-sm"
                                    />
                                </div>
                            {:else if allChunks.length === 0}
                                <p in:fade={{ duration: blockDuration() }} class="text-muted-foreground text-center py-8 text-sm">
                                    No text content available.
                                </p>
                            {:else}
                                <div class="max-w-none">
                                    {#each allChunks as chunk, i}
                                        {@const role = getChunkRole(chunk)}

                                        <!-- Collapsible front matter -->
                                        {#if isEnriched && role === 'front_matter'}
                                            {#if i === 0 || getChunkRole(allChunks[i - 1]) !== 'front_matter'}
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    class="h-auto px-0 py-1 gap-2 text-xs text-muted-foreground hover:text-foreground hover:bg-transparent mb-2 mt-4 font-normal"
                                                    onclick={() => (showFrontMatter = !showFrontMatter)}
                                                >
                                                    {#if showFrontMatter}
                                                        <ChevronDown class="h-3 w-3" />
                                                    {:else}
                                                        <ChevronRight class="h-3 w-3" />
                                                    {/if}
                                                    Front Matter
                                                </Button>
                                            {/if}
                                            {#if showFrontMatter}
                                                <div
                                                    id="chunk-{i}"
                                                    class="opacity-60 text-sm transition-colors {matchingChunkIndices.has(i) ? 'bg-yellow-100 rounded px-2 py-1 -mx-2 opacity-100' : ''}"
                                                >
                                                    <MarkdownRenderer
                                                        content={chunk.content}
                                                        format={(chunk.chunk_metadata?.content_format as string) ?? 'plaintext'}
                                                        role="front_matter"
                                                    />
                                                </div>
                                            {/if}

                                        <!-- Collapsible TOC -->
                                        {:else if isEnriched && role === 'toc'}
                                            {#if i === 0 || getChunkRole(allChunks[i - 1]) !== 'toc'}
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    class="h-auto px-0 py-1 gap-2 text-xs text-muted-foreground hover:text-foreground hover:bg-transparent mb-2 mt-4 font-normal"
                                                    onclick={() => (showToc = !showToc)}
                                                >
                                                    {#if showToc}
                                                        <ChevronDown class="h-3 w-3" />
                                                    {:else}
                                                        <ChevronRight class="h-3 w-3" />
                                                    {/if}
                                                    Table of Contents
                                                </Button>
                                            {/if}
                                            {#if showToc}
                                                <div
                                                    id="chunk-{i}"
                                                    class="opacity-60 text-sm transition-colors {matchingChunkIndices.has(i) ? 'bg-yellow-100 rounded px-2 py-1 -mx-2 opacity-100' : ''}"
                                                >
                                                    <MarkdownRenderer
                                                        content={chunk.content}
                                                        format={(chunk.chunk_metadata?.content_format as string) ?? 'plaintext'}
                                                        role="toc"
                                                    />
                                                </div>
                                            {/if}

                                        <!-- Body content -->
                                        {:else}
                                            <div
                                                id="chunk-{i}"
                                                class="transition-colors {matchingChunkIndices.has(i) ? 'bg-yellow-100 rounded px-2 py-1 -mx-2' : ''}"
                                            >
                                                <MarkdownRenderer
                                                    content={chunk.content}
                                                    format={(chunk.chunk_metadata?.content_format as string) ?? 'plaintext'}
                                                    role={role}
                                                />
                                            </div>
                                        {/if}
                                    {/each}
                                </div>

                                {#if !allChunksLoaded && document.chunk_count > allChunks.length}
                                    <div class="text-center mt-6">
                                        <Button variant="outline" onclick={loadMoreChunks} disabled={loadingMoreChunks}>
                                            {loadingMoreChunks ? 'Loading…' : `Load more (${allChunks.length} of ${document.chunk_count})`}
                                        </Button>
                                    </div>
                                {/if}
                            {/if}
                        </div>
                    </div>
                {/if}
            </main>
        </div>
    {/if}
</div>

<!-- Delete confirmation dialog -->
<Dialog.Root bind:open={deleteDialogOpen}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>Delete Document</Dialog.Title>
            <Dialog.Description>
                Are you sure you want to delete "{document?.title}"? This action cannot be undone.
            </Dialog.Description>
        </Dialog.Header>
        <Dialog.Footer>
            <Button variant="outline" onclick={() => (deleteDialogOpen = false)}>Cancel</Button>
            <Button variant="destructive" onclick={handleDelete} disabled={deleting}>
                {deleting ? 'Deleting...' : 'Delete'}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<style>
    /* ─── Chips (header status / meta) ─────────────────────────── */
    .chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 9px;
        border: 1px solid var(--border);
        background: var(--card);
        border-radius: 999px;
        color: var(--muted-fg);
        font-size: 12px;
        line-height: 1;
        white-space: nowrap;
    }
    .chip .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--muted-fg);
    }
    .chip-live {
        color: hsl(28 75% 32%);
        background: hsl(38 92% 96%);
        border-color: hsl(38 70% 80%);
    }
    .chip-live .dot {
        background: hsl(38 92% 50%);
        animation: chip-pulse 1.4s infinite;
    }
    .chip-done {
        color: hsl(155 70% 22%);
        background: hsl(155 70% 96%);
        border-color: hsl(155 50% 78%);
    }
    .chip-done .dot { background: var(--accent); }
    .chip-refine {
        color: hsl(195 70% 22%);
        background: hsl(195 80% 96%);
        border-color: hsl(195 50% 78%);
    }
    .chip-refine .dot { background: var(--primary); }
    .chip-failed {
        color: hsl(355 75% 38%);
        background: hsl(355 80% 96%);
        border-color: hsl(355 50% 82%);
    }
    .chip-failed .dot { background: var(--destructive); }

    @keyframes chip-pulse {
        0%   { box-shadow: 0 0 0 0   hsla(38 92% 50% / 0.55); }
        70%  { box-shadow: 0 0 0 6px hsla(38 92% 50% / 0); }
        100% { box-shadow: 0 0 0 0   hsla(38 92% 50% / 0); }
    }

    /* ─── Pipeline list in rail ────────────────────────────────── */
    .pipeline { list-style: none; padding: 0; margin: 0; position: relative; }
    .pipeline li {
        display: grid;
        grid-template-columns: 24px 1fr;
        gap: 12px;
        align-items: start;
        padding: 5px 0;
        position: relative;
    }
    .pipeline li + li::before {
        content: '';
        position: absolute;
        left: 11px;
        top: -10px;
        height: 14px;
        width: 2px;
        background: var(--border);
    }
    .pipeline li.done + li::before,
    .pipeline li.done + li.now::before,
    .pipeline li.done + li.failed::before {
        background: var(--accent);
    }
    .pipeline .node {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: var(--card);
        border: 2px solid var(--border);
        display: grid;
        place-items: center;
        font-size: 11px;
        color: var(--muted-fg);
        line-height: 1;
    }
    .pipeline .done .node {
        background: var(--accent);
        border-color: var(--accent);
        color: var(--accent-fg);
    }
    .pipeline .now .node {
        background: var(--card);
        border-color: hsl(38 92% 50%);
        color: hsl(38 92% 50%);
        animation: chip-pulse 1.4s infinite;
    }
    .pipeline .failed .node {
        background: var(--card);
        border-color: var(--destructive);
        color: var(--destructive);
        font-weight: 700;
    }
    .pipeline .pending .node { color: transparent; }
    .pipeline .label {
        font-size: 13px;
        line-height: 1.35;
        color: var(--fg);
        font-weight: 500;
    }
    .pipeline .label .sub {
        display: block;
        font-size: 11.5px;
        font-weight: 400;
        color: var(--muted-fg);
        margin-top: 2px;
    }
    .pipeline .pending .label {
        color: var(--muted-fg);
        font-weight: 400;
    }

    /* ─── Live extraction card ─────────────────────────────────── */
    .live::after {
        /* subtle grain texture to lift the card above the page */
        content: '';
        position: absolute;
        inset: 0;
        background-image: radial-gradient(hsl(195 30% 60% / 0.05) 1px, transparent 1px);
        background-size: 4px 4px;
        pointer-events: none;
    }
    .progress {
        position: relative;
        height: 3px;
        background: var(--muted);
        overflow: hidden;
    }
    .progress::after {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(90deg,
            transparent 0%,
            var(--primary) 40%,
            var(--primary) 60%,
            transparent 100%);
        width: 40%;
        animation: slide 1.6s ease-in-out infinite;
    }
    @keyframes slide {
        0%   { transform: translateX(-100%); }
        100% { transform: translateX(350%); }
    }

    /* ─── Markdown skeleton shimmer ────────────────────────────── */
    .skeleton-block {
        background: linear-gradient(90deg,
            hsl(205 22% 91%),
            hsl(205 22% 95%),
            hsl(205 22% 91%));
        background-size: 200% 100%;
        border-radius: 3px;
        animation: shimmer 1.8s ease-in-out infinite;
    }
    @keyframes shimmer {
        0%   { background-position: 100% 0; }
        100% { background-position: -100% 0; }
    }
</style>
