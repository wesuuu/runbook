<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { api } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import { Badge } from '$lib/components/ui/badge';
    import { Input } from '$lib/components/ui/input';
    import * as Table from '$lib/components/ui/table';
    import {
        Card,
        CardContent,
        CardHeader,
        CardTitle,
        CardDescription,
    } from '$lib/components/ui/card';
    import DocumentUploadDialog from '$lib/components/DocumentUploadDialog.svelte';
    import {
        getFileTypeLabel,
        getStatusColor,
        getStatusLabel,
        formatFileSize,
        sanitizeHighlight,
    } from '$lib/utils/document-utils';
    import { Plus, Search, X } from 'lucide-svelte';
    import { z } from 'zod';

    // --- Schemas ---
    const DocumentItemSchema = z.object({
        id: z.string(),
        title: z.string(),
        original_filename: z.string(),
        mime_type: z.string(),
        file_size_bytes: z.number(),
        status: z.string(),
        source_url: z.string().nullable(),
        created_at: z.string(),
    }).passthrough();
    type DocumentItem = z.infer<typeof DocumentItemSchema>;

    const DocumentListResponseSchema = z.object({
        items: z.array(DocumentItemSchema),
        total: z.number(),
    }).passthrough();

    const SearchResultItemSchema = z.object({
        document_id: z.string(),
        document_title: z.string(),
        chunk_id: z.string(),
        chunk_index: z.number(),
        content: z.string(),
        highlighted_content: z.string().nullable(),
        page_number: z.number().nullable(),
        score: z.number(),
    }).passthrough();

    const SearchResultGroupSchema = z.object({
        document_id: z.string(),
        document_title: z.string(),
        match_count: z.number(),
        best_score: z.number(),
        best_chunk: SearchResultItemSchema,
    }).passthrough();
    type SearchResultGroup = z.infer<typeof SearchResultGroupSchema>;

    const SearchResponseSchema = z.object({
        query: z.string(),
        items: z.array(SearchResultGroupSchema),
        total: z.number(),
        search_mode: z.string(),
    }).passthrough();

    let documents = $state<DocumentItem[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let uploadDialogOpen = $state(false);
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    // Search state
    let searchQuery = $state('');
    let searchResults = $state<SearchResultGroup[]>([]);
    let searchMode = $state('');
    let searching = $state(false);
    let searchError = $state<string | null>(null);
    let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    let searchInputEl: HTMLInputElement | null = $state(null);

    const isSearching = $derived(searchQuery.trim().length > 0);

    async function loadDocuments() {
        try {
            const res = await api.get('/library/documents?limit=50', { schema: DocumentListResponseSchema });
            documents = res.items;

            const hasProcessing = documents.some((d) => d.status === 'PROCESSING');
            if (hasProcessing && !pollTimer) {
                pollTimer = setInterval(loadDocuments, 5000);
            } else if (!hasProcessing && pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            loading = false;
        }
    }

    async function performSearch(query: string) {
        if (!query.trim()) {
            searchResults = [];
            searchError = null;
            searchMode = '';
            return;
        }
        searching = true;
        searchError = null;
        try {
            const res = await api.get(
                `/library/search?q=${encodeURIComponent(query.trim())}&limit=20`,
                { schema: SearchResponseSchema },
            );
            searchResults = res.items;
            searchMode = res.search_mode;
        } catch (e: unknown) {
            searchError = e instanceof Error ? e.message : 'Search failed';
            searchResults = [];
        } finally {
            searching = false;
        }
    }

    function handleSearchInput() {
        if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(() => {
            performSearch(searchQuery);
        }, 300);
    }

    function clearSearch() {
        searchQuery = '';
        searchResults = [];
        searchError = null;
        searchMode = '';
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
            const tag = (e.target as HTMLElement)?.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            e.preventDefault();
            searchInputEl?.focus();
        }
    }

    function formatDate(dateStr: string): string {
        return new Date(dateStr).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
        });
    }

    onMount(() => {
        loadDocuments();
        document.addEventListener('keydown', handleKeydown);
    });
    onDestroy(() => {
        if (pollTimer) clearInterval(pollTimer);
        if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
        document.removeEventListener('keydown', handleKeydown);
    });
</script>

<div class="max-w-5xl mx-auto space-y-6">
    <div class="flex items-center justify-between">
        <div>
            <h1 class="text-3xl font-bold tracking-tight">Library</h1>
            <p class="text-muted-foreground">
                Your document library for SOPs, protocols, and reference materials.
            </p>
        </div>
        <Button onclick={() => (uploadDialogOpen = true)}>
            <Plus class="mr-2 h-4 w-4" /> Upload Document
        </Button>
    </div>

    <!-- Search bar -->
    <div class="relative">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
            type="text"
            placeholder="Search documents... (press / to focus)"
            class="pl-10 pr-10"
            bind:value={searchQuery}
            bind:ref={searchInputEl}
            oninput={handleSearchInput}
        />
        {#if searchQuery}
            <Button
                variant="ghost"
                size="icon-sm"
                class="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 text-muted-foreground hover:text-foreground"
                onclick={clearSearch}
            >
                <X class="h-4 w-4" />
            </Button>
        {/if}
    </div>

    {#if searching}
        <div class="text-center py-6 text-muted-foreground">Searching...</div>
    {:else if searchError}
        <div class="bg-destructive/10 text-destructive p-4 rounded-md">Search error: {searchError}</div>
    {:else if isSearching}
        <!-- Search results -->
        <Card>
            <CardHeader>
                <div class="flex items-center justify-between">
                    <div>
                        <CardTitle>Search Results</CardTitle>
                        <CardDescription>
                            {searchResults.length} document{searchResults.length !== 1 ? 's' : ''} matching "{searchQuery}"
                        </CardDescription>
                    </div>
                    {#if searchMode}
                        <Badge variant="outline" class="text-xs">
                            {searchMode === 'hybrid' ? 'Semantic + Keyword' : searchMode === 'semantic' ? 'Semantic' : 'Keyword'} search
                        </Badge>
                    {/if}
                </div>
            </CardHeader>
            <CardContent>
                {#if searchResults.length === 0}
                    <div class="text-center py-8 text-muted-foreground">
                        No matching documents found.
                    </div>
                {:else}
                    <div class="divide-y divide-border">
                        {#each searchResults as group}
                            <a href="/library/{group.document_id}" class="block py-4 px-2 hover:bg-muted/50 rounded-md transition-colors -mx-2">
                                <div class="flex items-center justify-between">
                                    <span class="font-semibold text-sm text-primary">{group.document_title}</span>
                                    <div class="flex items-center gap-2">
                                        {#if group.match_count > 1}
                                            <span class="text-xs text-muted-foreground">{group.match_count} matches</span>
                                        {/if}
                                        <span class="text-xs text-muted-foreground">{Math.round(group.best_score * 100)}%</span>
                                    </div>
                                </div>
                                {#if group.best_chunk.highlighted_content}
                                    <p class="text-sm text-muted-foreground mt-1 line-clamp-3 [&>mark]:bg-yellow-200 [&>mark]:text-foreground [&>mark]:rounded-sm [&>mark]:px-0.5">
                                        {@html sanitizeHighlight(group.best_chunk.highlighted_content)}
                                    </p>
                                {:else}
                                    <p class="text-sm text-muted-foreground mt-1 line-clamp-3">
                                        {group.best_chunk.content.substring(0, 200)}{group.best_chunk.content.length > 200 ? '...' : ''}
                                    </p>
                                {/if}
                                {#if group.best_chunk.page_number}
                                    <span class="text-xs text-muted-foreground mt-1 inline-block">Page {group.best_chunk.page_number}</span>
                                {/if}
                            </a>
                        {/each}
                    </div>
                {/if}
            </CardContent>
        </Card>
    {:else if loading}
        <div class="text-center py-10 text-muted-foreground">Loading documents...</div>
    {:else if error}
        <div class="bg-destructive/10 text-destructive p-4 rounded-md">Error: {error}</div>
    {:else}
        <!-- Document list -->
        <Card>
            <CardHeader>
                <CardTitle>Documents</CardTitle>
                <CardDescription>All documents in your organization.</CardDescription>
            </CardHeader>
            <CardContent>
                {#if documents.length === 0}
                    <div class="text-center py-10">
                        <p class="text-muted-foreground">
                            Upload your SOPs, protocols, and reference documents to build your
                            searchable knowledge base.
                        </p>
                    </div>
                {:else}
                    <!-- Mobile card layout -->
                    <div class="sm:hidden divide-y divide-border">
                        {#each documents as doc}
                            <a href="/library/{doc.id}" class="block py-3 px-1 min-h-11">
                                <div class="flex items-center gap-2">
                                    <span class="font-semibold text-sm text-primary">{doc.title}</span>
                                    <Badge variant={getStatusColor(doc.status) as any}>{getStatusLabel(doc.status)}</Badge>
                                </div>
                                <div class="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                                    <span>{getFileTypeLabel(doc.mime_type)}</span>
                                    <span>&middot;</span>
                                    <span>{formatFileSize(doc.file_size_bytes)}</span>
                                    <span>&middot;</span>
                                    <span>{formatDate(doc.created_at)}</span>
                                </div>
                            </a>
                        {/each}
                    </div>
                    <!-- Desktop table -->
                    <div class="hidden sm:block">
                        <Table.Root>
                            <Table.Caption>Your uploaded documents.</Table.Caption>
                            <Table.Header>
                                <Table.Row>
                                    <Table.Head>Title</Table.Head>
                                    <Table.Head>Type</Table.Head>
                                    <Table.Head>Status</Table.Head>
                                    <Table.Head class="hidden md:table-cell">Size</Table.Head>
                                    <Table.Head class="hidden md:table-cell">Uploaded</Table.Head>
                                    <Table.Head class="text-right">Actions</Table.Head>
                                </Table.Row>
                            </Table.Header>
                            <Table.Body>
                                {#each documents as doc}
                                    <Table.Row>
                                        <Table.Cell class="font-medium max-w-[300px] whitespace-normal break-words">
                                            <a
                                                href="/library/{doc.id}"
                                                class="font-semibold text-primary hover:underline"
                                            >
                                                {doc.title}
                                            </a>
                                        </Table.Cell>
                                        <Table.Cell>
                                            <Badge variant="outline">{getFileTypeLabel(doc.mime_type)}</Badge>
                                        </Table.Cell>
                                        <Table.Cell>
                                            <Badge variant={getStatusColor(doc.status) as any}>{getStatusLabel(doc.status)}</Badge>
                                        </Table.Cell>
                                        <Table.Cell class="hidden md:table-cell">
                                            {formatFileSize(doc.file_size_bytes)}
                                        </Table.Cell>
                                        <Table.Cell class="hidden md:table-cell">
                                            {formatDate(doc.created_at)}
                                        </Table.Cell>
                                        <Table.Cell class="text-right">
                                            <a href="/library/{doc.id}">
                                                <Button variant="ghost" size="sm">View</Button>
                                            </a>
                                        </Table.Cell>
                                    </Table.Row>
                                {/each}
                            </Table.Body>
                        </Table.Root>
                    </div>
                {/if}
            </CardContent>
        </Card>
    {/if}
</div>

<DocumentUploadDialog bind:open={uploadDialogOpen} onSuccess={loadDocuments} />
