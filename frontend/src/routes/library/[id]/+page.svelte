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
    import {
        getFileTypeLabel,
        getStatusColor,
        getStatusLabel,
        formatFileSize,
    } from '$lib/utils/document-utils';
    import { API_BASE } from '$lib/config';
    import { Input } from '$lib/components/ui/input';
    import { ArrowLeft, RotateCcw, Trash2, ExternalLink, Search, X } from 'lucide-svelte';

    interface DocumentChunk {
        id: string;
        document_id: string;
        chunk_index: number;
        content: string;
        token_count: number;
        page_number: number | null;
        created_at: string;
    }

    interface DocumentDetail {
        id: string;
        title: string;
        original_filename: string;
        mime_type: string;
        file_size_bytes: number;
        file_path: string;
        status: string;
        page_count: number | null;
        source_url: string | null;
        error_message: string | null;
        tags: string[];
        chunk_count: number;
        chunks_preview: DocumentChunk[];
        created_at: string;
        updated_at: string;
    }

    let document = $state<DocumentDetail | null>(null);
    let allChunks = $state<DocumentChunk[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let showAllChunks = $state(false);
    let deleteDialogOpen = $state(false);
    let deleting = $state(false);
    let retrying = $state(false);
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    // In-document search
    let docSearchQuery = $state('');
    let matchingChunkIndices = $state<Set<number>>(new Set());

    const documentId = $derived($page.params.id);

    async function loadDocument() {
        try {
            const doc = await api.get<DocumentDetail>(`/library/documents/${documentId}`);
            document = doc;
            allChunks = doc.chunks_preview;

            if (doc.status === 'PROCESSING' && !pollTimer) {
                pollTimer = setInterval(loadDocument, 3000);
            } else if (doc.status !== 'PROCESSING' && pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load document';
        } finally {
            loading = false;
        }
    }

    async function loadAllChunks() {
        if (!document) return;
        try {
            const chunks = await api.get<DocumentChunk[]>(
                `/library/documents/${documentId}/chunks?limit=200`
            );
            allChunks = chunks;
            showAllChunks = true;
        } catch (e: unknown) {
            toast.error('Failed to load full content');
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
            toast.error(e instanceof Error ? e.message : 'Delete failed');
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

        // Scroll to first match
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

    onMount(loadDocument);
    onDestroy(() => {
        if (pollTimer) clearInterval(pollTimer);
    });
</script>

<div class="max-w-4xl mx-auto space-y-6">
    <!-- Back link -->
    <a
        href="/library"
        class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
    >
        <ArrowLeft class="h-4 w-4" />
        Back to Library
    </a>

    {#if loading}
        <div class="text-center py-10 text-muted-foreground">Loading document...</div>
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
            {#if document.status === 'FAILED'}
                <Button variant="outline" size="sm" onclick={handleRetry} disabled={retrying}>
                    <RotateCcw class="mr-2 h-4 w-4" />
                    {retrying ? 'Retrying...' : 'Retry Processing'}
                </Button>
            {/if}
            <Button
                variant="destructive"
                size="sm"
                onclick={() => (deleteDialogOpen = true)}
            >
                <Trash2 class="mr-2 h-4 w-4" />
                Delete
            </Button>
        </div>

        <!-- Error banner -->
        {#if document.status === 'FAILED' && document.error_message}
            <div class="bg-destructive/10 border border-destructive/20 text-destructive p-4 rounded-md">
                <p class="font-medium">Processing failed</p>
                <p class="text-sm mt-1">{document.error_message}</p>
            </div>
        {/if}

        <!-- Processing indicator -->
        {#if document.status === 'PROCESSING'}
            <div class="bg-amber-50 border border-amber-200 text-amber-800 p-4 rounded-md flex items-center gap-3">
                <div class="w-4 h-4 border-2 border-amber-600 border-t-transparent rounded-full animate-spin"></div>
                <span>Processing document... This may take a moment.</span>
            </div>
        {/if}

        <!-- Reader view -->
        <Card>
            <CardHeader>
                <div class="flex items-center justify-between gap-4">
                    <CardTitle>Content</CardTitle>
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
                                    class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
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
                {#if document.status === 'INDEXED' && document.chunk_count === 0 && document.mime_type.startsWith('image/')}
                    <div class="text-center space-y-4">
                        <p class="text-muted-foreground">
                            This document is an image. Text extraction will be available in a
                            future update.
                        </p>
                        <img
                            src="{API_BASE}/{document.file_path}"
                            alt={document.title}
                            class="max-w-full mx-auto rounded-lg shadow-sm"
                        />
                    </div>
                {:else if allChunks.length === 0}
                    <p class="text-muted-foreground text-center py-8">
                        {#if document.status === 'PROCESSING'}
                            Content will appear here once processing is complete.
                        {:else if document.status === 'UPLOADED'}
                            Document is queued for processing.
                        {:else}
                            No text content available.
                        {/if}
                    </p>
                {:else}
                    <div class="prose prose-sm max-w-none">
                        {#each allChunks as chunk, i}
                            {#if i > 0 && chunk.page_number && allChunks[i - 1]?.page_number !== chunk.page_number}
                                <div class="flex items-center gap-3 my-6">
                                    <div class="flex-1 border-t border-border"></div>
                                    <span class="text-xs text-muted-foreground font-medium">
                                        Page {chunk.page_number}
                                    </span>
                                    <div class="flex-1 border-t border-border"></div>
                                </div>
                            {/if}
                            <div
                                id="chunk-{i}"
                                class="whitespace-pre-wrap leading-relaxed text-sm transition-colors {matchingChunkIndices.has(i) ? 'bg-yellow-100 rounded px-2 py-1 -mx-2' : ''}"
                            >
                                {chunk.content}
                            </div>
                        {/each}
                    </div>

                    {#if !showAllChunks && document.chunk_count > 5}
                        <div class="text-center mt-6">
                            <Button variant="outline" onclick={loadAllChunks}>
                                Show all ({document.chunk_count} chunks)
                            </Button>
                        </div>
                    {/if}
                {/if}
            </CardContent>
        </Card>
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
