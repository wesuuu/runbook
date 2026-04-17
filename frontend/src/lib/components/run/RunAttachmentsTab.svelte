<script lang="ts">
    import { api } from '$lib/api';
    import type { RunAttachment } from '$lib/schemas';

    let {
        runId,
        attachments = $bindable([]),
        steps = [],
    }: {
        runId: string;
        attachments: RunAttachment[];
        steps: { id: string; name: string }[];
    } = $props();

    let filter = $state<string | null>(null);
    let uploading = $state(false);
    let error = $state<string | null>(null);
    let fileInput: HTMLInputElement;

    const visible = $derived(
        attachments
            .filter((a) => !a.deleted)
            .filter((a) => {
                if (filter === null) return true;
                if (filter === 'run-level') return !a.step_id;
                return a.step_id === filter;
            })
    );

    // Cache blob URLs for image previews (loaded with auth)
    let blobUrls = $state<Record<string, string>>({});

    function isImage(contentType: string) {
        return contentType.startsWith('image/');
    }

    function downloadEndpoint(att: RunAttachment) {
        return `/science/runs/${runId}/attachments/${att.id}/download`;
    }

    async function downloadFile(att: RunAttachment) {
        try {
            await api.downloadBlob(downloadEndpoint(att), att.filename);
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Download failed';
        }
    }

    async function loadImagePreview(att: RunAttachment) {
        if (blobUrls[att.id]) return;
        try {
            const url = await api.fetchBlobUrl(downloadEndpoint(att));
            blobUrls = { ...blobUrls, [att.id]: url };
        } catch {
            // Preview failed — show fallback
        }
    }

    // Load image previews for visible images
    $effect(() => {
        for (const att of visible) {
            if (isImage(att.content_type) && !blobUrls[att.id]) {
                loadImagePreview(att);
            }
        }
    });

    function formatSize(bytes: number): string {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    function stepName(stepId: string | null | undefined): string {
        if (!stepId) return 'Run-level';
        const step = steps.find((s) => s.id === stepId);
        return step?.name ?? stepId;
    }

    async function handleUpload(e: Event) {
        const input = e.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;
        uploading = true;
        error = null;
        try {
            const att = await api.uploadFile<RunAttachment>(
                `/science/runs/${runId}/attachments`,
                file,
            );
            attachments = [...attachments, att];
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Upload failed';
        } finally {
            uploading = false;
            input.value = '';
        }
    }

    async function deleteAttachment(id: string) {
        try {
            await api.delete(`/science/runs/${runId}/attachments/${id}`);
            attachments = attachments.map((a) =>
                a.id === id ? { ...a, deleted: true } : a,
            );
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Delete failed';
        }
    }
</script>

<div class="max-w-4xl mx-auto py-6">
    <!-- Filter bar + upload -->
    <div class="flex items-center justify-between mb-4">
        <select
            bind:value={filter}
            class="border border-border rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-primary"
        >
            <option value={null}>All attachments</option>
            <option value="run-level">Run-level only</option>
            {#each steps as step}
                <option value={step.id}>{step.name}</option>
            {/each}
        </select>

        <label
            class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium cursor-pointer hover:bg-primary/90 transition-colors
                {uploading ? 'opacity-50 cursor-not-allowed' : ''}"
        >
            {uploading ? 'Uploading...' : 'Upload File'}
            <input
                bind:this={fileInput}
                type="file"
                onchange={handleUpload}
                class="hidden"
                accept=".jpg,.jpeg,.png,.tiff,.webp,.pdf,.csv,.xlsx,.txt"
                disabled={uploading}
            />
        </label>
    </div>

    <!-- Error -->
    {#if error}
        <div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
        </div>
    {/if}

    <!-- Empty state -->
    {#if visible.length === 0}
        <div class="text-center py-12 text-muted-foreground">
            <p class="text-lg font-medium mb-1">No attachments</p>
            <p class="text-sm">Upload files, images, or instrument data.</p>
        </div>
    {:else}
        <!-- Grid -->
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            {#each visible as att}
                <div class="bg-white rounded-lg border border-border p-3 group">
                    <!-- Preview -->
                    {#if isImage(att.content_type)}
                        <button onclick={() => downloadFile(att)} class="block w-full cursor-pointer">
                            {#if blobUrls[att.id]}
                                <img
                                    src={blobUrls[att.id]}
                                    alt={att.filename}
                                    class="w-full h-32 object-cover rounded"
                                />
                            {:else}
                                <div class="flex items-center justify-center h-32 bg-muted rounded text-sm text-muted-foreground">
                                    Loading...
                                </div>
                            {/if}
                        </button>
                    {:else}
                        <button
                            onclick={() => downloadFile(att)}
                            class="flex items-center justify-center h-32 w-full bg-muted rounded text-2xl hover:bg-muted/80 transition-colors cursor-pointer"
                        >
                            {#if att.content_type === 'application/pdf'}
                                <span>PDF</span>
                            {:else if att.content_type === 'text/csv'}
                                <span>CSV</span>
                            {:else}
                                <span>FILE</span>
                            {/if}
                        </button>
                    {/if}

                    <!-- Info -->
                    <p class="text-sm font-medium mt-2 truncate" title={att.filename}>
                        {att.filename}
                    </p>
                    <p class="text-xs text-muted-foreground">
                        {stepName(att.step_id)} &middot; {formatSize(att.size_bytes)}
                    </p>
                    <div class="flex items-center justify-between mt-1">
                        <span class="text-[10px] px-1.5 py-0.5 bg-muted rounded font-medium">
                            {att.run_status}
                        </span>
                        <button
                            onclick={() => deleteAttachment(att.id)}
                            class="text-xs text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                            Remove
                        </button>
                    </div>
                </div>
            {/each}
        </div>
    {/if}
</div>
