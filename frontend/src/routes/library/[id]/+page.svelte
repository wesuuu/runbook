<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import { Badge } from '$lib/components/ui/badge';
    import {
        Card,
        CardContent,
        CardHeader,
        CardTitle,
    } from '$lib/components/ui/card';
    import * as Dialog from '$lib/components/ui/dialog';
    import { toast } from 'svelte-sonner';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import {
        getFileTypeLabel,
        getStatusColor,
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
    import MarkdownRenderer from '$lib/components/MarkdownRenderer.svelte';
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

    async function loadDocument() {
        try {
            const doc = await api.get(`/library/documents/${documentId}`, { schema: DocumentDetailSchema });
            document = doc;
            allChunks = doc.chunks_preview;

            const hasActiveProgress = doc.processing_progress && doc.processing_progress.stage !== '';
            const shouldPoll = doc.status === 'PROCESSING' || doc.status === 'QUEUED' || (doc.status === 'INDEXED' && hasActiveProgress);
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

<div class="max-w-6xl mx-auto space-y-6">
    <!-- Back link -->
    <a
        href="/library"
        class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
    >
        <ArrowLeft class="h-4 w-4" />
        Back to Library
    </a>

    {#if loading}
        <LoadingSpinner message="Loading document..." />
    {:else if error}
        <div class="bg-destructive/10 text-destructive p-4 rounded-md">Error: {error}</div>
    {:else if document}
        <!-- Header -->
        <div class="space-y-3">
            <h1 class="text-3xl font-bold tracking-tight">{document.title}</h1>
            <div class="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <Badge variant="outline">{getFileTypeLabel(document.mime_type)}</Badge>
                <span>{formatFileSize(document.file_size_bytes)}</span>
                <Badge variant={getStatusColor(document.status) as any}>
                    {getStatusLabel(document.status)}
                </Badge>
                <span>Uploaded {formatDate(document.created_at)}</span>
                {#if document.page_count}
                    <span>&middot; {document.page_count} pages</span>
                {/if}
            </div>
            {#if document.source_url}
                <p class="text-sm text-muted-foreground">
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

        <!-- Action bar -->
        <div class="flex items-center gap-2">
            {#if document.status === 'FAILED' || document.status === 'QUEUED'}
                <Button variant="outline" size="sm" onclick={handleRetry} disabled={retrying}>
                    <RotateCcw class="mr-2 h-4 w-4" />
                    {retrying ? 'Retrying...' : 'Retry Processing'}
                </Button>
            {/if}
            {#if document.can_delete}
                <Button
                    variant="destructive"
                    size="sm"
                    onclick={() => (deleteDialogOpen = true)}
                >
                    <Trash2 class="mr-2 h-4 w-4" />
                    Delete
                </Button>
            {/if}
        </div>

        <!-- Error banner -->
        {#if document.status === 'FAILED' && document.error_message}
            <div class="bg-destructive/10 border border-destructive/20 text-destructive p-4 rounded-md">
                <p class="font-medium">Processing failed</p>
                <p class="text-sm mt-1">{document.error_message}</p>
            </div>
        {/if}

        <!-- Queued banner -->
        {#if document.status === 'QUEUED'}
            <div class="bg-blue-50 border border-blue-200 text-blue-800 p-4 rounded-md">
                <div class="flex items-center gap-3">
                    <div class="w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin shrink-0"></div>
                    <span class="text-sm font-medium">Waiting for AI processing...</span>
                </div>
                <p class="text-xs text-blue-600/70 mt-2">
                    The document is queued and will be processed when the AI service becomes available.
                </p>
            </div>
        {/if}

        <!-- Processing progress -->
        {@const activeProgress = document.processing_progress && document.processing_progress.stage !== ''}
        {#if document.status === 'PROCESSING' || (document.status === 'INDEXED' && activeProgress)}
            {@const progress = document.processing_progress}
            {@const isEnrichmentPhase = document.status === 'INDEXED'}
            <div class="bg-amber-50 border border-amber-200 text-amber-800 p-4 rounded-md space-y-3">
                <div class="flex items-center gap-3">
                    <div class="w-4 h-4 border-2 border-amber-600 border-t-transparent rounded-full animate-spin shrink-0"></div>
                    <span class="text-sm font-medium">
                        {#if progress && progress.stage_label}
                            {progress.stage_label}
                            {#if progress.total > 0}
                                ({progress.current} / {progress.total})
                            {/if}
                        {:else if isEnrichmentPhase}
                            Analyzing document structure...
                        {:else}
                            Processing document...
                        {/if}
                    </span>
                </div>
                {#if progress && progress.total > 0}
                    <div class="w-full bg-amber-200 rounded-full h-2 overflow-hidden">
                        <div
                            class="bg-amber-600 h-2 rounded-full transition-all duration-500 ease-out"
                            style="width: {progress.percent}%"
                        ></div>
                    </div>
                    <p class="text-xs text-amber-700/70">{progress.percent}% complete</p>
                {/if}
            </div>
        {/if}

        <!-- Content area with optional section nav -->
        <div class="flex gap-6">
            <!-- Section navigation sidebar -->
            {#if sectionNav.length > 0 && showSectionNav}
                <div class="w-64 shrink-0 hidden lg:block">
                    <div class="sticky top-6">
                        <div class="flex items-center gap-2 mb-3">
                            <List class="h-4 w-4 text-muted-foreground" />
                            <span class="text-sm font-medium">Contents</span>
                        </div>
                        <nav class="space-y-0.5 max-h-[calc(100vh-8rem)] overflow-y-auto">
                            {#each sectionNav as section}
                                <button
                                    class="block w-full text-left text-xs text-muted-foreground hover:text-foreground px-2 py-1.5 rounded hover:bg-muted/50 transition-colors duration-150 cursor-pointer truncate"
                                    onclick={() => handleSidebarClick(section.chunkIndex)}
                                    title={section.heading}
                                >
                                    {section.heading}
                                </button>
                            {/each}
                        </nav>
                    </div>
                </div>
            {/if}

            <!-- Main content area -->
            <Card class="flex-1 min-w-0">
                {#if isPdf}
                    <!-- ═══ PDF: embedded viewer (no tabs) ═══ -->
                    <CardContent class="p-0">
                        {#if isViewable}
                            <div class="w-full" style="height: calc(100vh - 12rem);">
                                <iframe
                                    bind:this={pdfIframe}
                                    src="{API_BASE}/library/documents/{document.id}/download?token={getToken()}"
                                    title="PDF viewer — {document.title}"
                                    class="w-full h-full rounded-md"
                                ></iframe>
                            </div>
                        {:else}
                            <div class="p-6">
                                <p class="text-muted-foreground text-center py-8">
                                    {#if document.status === 'PROCESSING'}
                                        PDF will be viewable once processing is complete.
                                    {:else if document.status === 'UPLOADED' || document.status === 'QUEUED'}
                                        Document is queued for processing.
                                    {:else}
                                        PDF not available.
                                    {/if}
                                </p>
                            </div>
                        {/if}
                    </CardContent>
                {:else}
                    <!-- ═══ Non-PDF: reader view with search ═══ -->
                    <CardHeader>
                        <div class="flex items-center justify-between gap-4">
                            <span class="text-sm font-medium text-muted-foreground">Reader</span>
                            {#if allChunks.length > 0}
                                <div class="relative w-64">
                                    <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                                    <Input
                                        type="text"
                                        placeholder="Find in document..."
                                        class="pl-8 pr-8 h-8 text-sm"
                                        bind:value={docSearchQuery}
                                        oninput={handleDocSearch}
                                    />
                                    {#if docSearchQuery}
                                        <button
                                            class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors duration-150 cursor-pointer"
                                            onclick={clearDocSearch}
                                        >
                                            <X class="h-3.5 w-3.5" />
                                        </button>
                                    {/if}
                                </div>
                            {/if}
                        </div>
                        {#if docSearchQuery && matchingChunkIndices.size > 0}
                            <p class="text-xs text-muted-foreground mt-1">
                                {matchingChunkIndices.size} match{matchingChunkIndices.size !== 1 ? 'es' : ''} found
                            </p>
                        {:else if docSearchQuery && matchingChunkIndices.size === 0}
                            <p class="text-xs text-muted-foreground mt-1">No matches found</p>
                        {/if}
                    </CardHeader>
                    <CardContent>
                        {#if isViewable && document.chunk_count === 0 && document.mime_type.startsWith('image/')}
                            <div class="text-center space-y-4">
                                <p class="text-muted-foreground">
                                    This document is an image. Text extraction will be available in a
                                    future update.
                                </p>
                                <img
                                    src="{API_BASE}/library/documents/{document.id}/download?token={getToken()}"
                                    alt={document.title}
                                    class="max-w-full mx-auto rounded-lg shadow-sm"
                                />
                            </div>
                        {:else if allChunks.length === 0}
                            <p class="text-muted-foreground text-center py-8">
                                {#if document.status === 'PROCESSING'}
                                    Content will appear here once processing is complete.
                                {:else if document.status === 'UPLOADED' || document.status === 'QUEUED'}
                                    Document is queued for processing.
                                {:else}
                                    No text content available.
                                {/if}
                            </p>
                        {:else}
                            <div class="max-w-none">
                                {#each allChunks as chunk, i}
                                    {@const role = getChunkRole(chunk)}

                                    <!-- Collapsible front matter -->
                                    {#if isEnriched && role === 'front_matter'}
                                        {#if i === 0 || getChunkRole(allChunks[i - 1]) !== 'front_matter'}
                                            <button
                                                class="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground mb-2 mt-4 transition-colors duration-150 cursor-pointer"
                                                onclick={() => (showFrontMatter = !showFrontMatter)}
                                            >
                                                {#if showFrontMatter}
                                                    <ChevronDown class="h-3 w-3" />
                                                {:else}
                                                    <ChevronRight class="h-3 w-3" />
                                                {/if}
                                                Front Matter
                                            </button>
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
                                            <button
                                                class="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground mb-2 mt-4 transition-colors duration-150 cursor-pointer"
                                                onclick={() => (showToc = !showToc)}
                                            >
                                                {#if showToc}
                                                    <ChevronDown class="h-3 w-3" />
                                                {:else}
                                                    <ChevronRight class="h-3 w-3" />
                                                {/if}
                                                Table of Contents
                                            </button>
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
                                        {loadingMoreChunks ? 'Loading...' : `Load more (${allChunks.length} of ${document.chunk_count})`}
                                    </Button>
                                </div>
                            {/if}
                        {/if}
                    </CardContent>
                {/if}
            </Card>
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
