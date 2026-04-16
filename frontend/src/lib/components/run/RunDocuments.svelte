<script lang="ts">
    import { goto } from '$app/navigation';
    import * as Dialog from '$lib/components/ui/dialog';

    interface Props {
        runId: string;
        runName: string;
        status: string;
        hasAttachments?: boolean;
        onDownloadSop: () => void;
        onDownloadBatchRecord: (filled: boolean, embedImages?: boolean, includeAttachments?: boolean) => void;
    }

    let { runId, runName, status, hasAttachments = false, onDownloadSop, onDownloadBatchRecord }: Props = $props();

    let showModal = $state(false);
    let embedImages = $state(true);
    let includeAttachments = $state(false);

    const showFilledRecord = $derived(status === 'COMPLETED' || status === 'EDITED');
    const filledLabel = $derived(status === 'EDITED' ? 'Download Edited Batch Record' : 'Download Completed Batch Record');
    const filledBgClass = $derived(status === 'EDITED'
        ? 'bg-amber-50 hover:bg-amber-100 border-amber-200'
        : 'bg-emerald-50 hover:bg-emerald-100 border-emerald-200');
    const filledTextClass = $derived(status === 'EDITED' ? 'text-amber-900' : 'text-emerald-900');
    const filledArrowClass = $derived(status === 'EDITED' ? 'text-amber-600' : 'text-emerald-600');

    function handleFilledDownload() {
        if (hasAttachments) {
            showModal = true;
        } else {
            onDownloadBatchRecord(true);
        }
    }

    function confirmDownload() {
        onDownloadBatchRecord(true, embedImages, includeAttachments);
        showModal = false;
        embedImages = true;
        includeAttachments = false;
    }
</script>

<div class="bg-white rounded-lg border border-border p-6">
    <h2 class="text-lg font-semibold text-foreground mb-6">
        Documents
    </h2>
    {#if status === 'PLANNED'}
        <p class="text-sm text-muted-foreground mb-6">
            Download SOPs and batch record for your run.
        </p>
    {/if}

    <div class="space-y-3">
        <button
            onclick={onDownloadSop}
            class="w-full text-left px-4 py-3 bg-background hover:bg-muted border border-border rounded-lg transition-colors"
        >
            <div class="flex items-center justify-between">
                <span class="font-medium text-foreground">
                    Download SOP
                </span>
                <span class="text-muted-foreground/60">&darr;</span>
            </div>
        </button>

        <hr class="my-3" />

        <button
            onclick={() => onDownloadBatchRecord(false)}
            class="w-full text-left px-4 py-3 bg-background hover:bg-muted border border-border rounded-lg transition-colors"
        >
            <div class="flex items-center justify-between">
                <span class="font-medium text-foreground">
                    Download Blank Batch Record
                </span>
                <span class="text-muted-foreground/60">&darr;</span>
            </div>
        </button>

        {#if showFilledRecord}
            <button
                onclick={handleFilledDownload}
                class="w-full text-left px-4 py-3 {filledBgClass} border rounded-lg transition-colors"
            >
                <div class="flex items-center justify-between">
                    <span class="font-medium {filledTextClass}">
                        {filledLabel}
                    </span>
                    <span class={filledArrowClass}>&darr;</span>
                </div>
            </button>

            <hr class="my-3" />

            <button
                onclick={() => goto(`/export?runs=${runId}`)}
                class="w-full text-left px-4 py-3 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
            >
                <div class="flex items-center justify-between">
                    <span class="font-medium text-blue-900">
                        Export Data (CSV / Excel / JSON)
                    </span>
                    <span class="text-blue-600">&darr;</span>
                </div>
            </button>
        {/if}
    </div>
</div>

<!-- Download Options Modal -->
<Dialog.Root bind:open={showModal}>
    <Dialog.Content class="max-w-sm">
        <Dialog.Header>
            <Dialog.Title class="text-lg font-semibold text-foreground">Batch Record Options</Dialog.Title>
            <Dialog.Description class="text-sm text-muted-foreground">
                Choose what to include in your download.
            </Dialog.Description>
        </Dialog.Header>

        <div class="space-y-3">
            <label class="flex items-start gap-3 cursor-pointer p-2 rounded-lg hover:bg-muted/50">
                <input type="checkbox" bind:checked={embedImages}
                    class="rounded border-slate-300 mt-0.5" />
                <div>
                    <p class="text-sm font-medium text-foreground">Embed images in PDF</p>
                    <p class="text-xs text-muted-foreground">Photos and image attachments rendered as figures</p>
                </div>
            </label>

            <label class="flex items-start gap-3 cursor-pointer p-2 rounded-lg hover:bg-muted/50">
                <input type="checkbox" bind:checked={includeAttachments}
                    class="rounded border-slate-300 mt-0.5" />
                <div>
                    <p class="text-sm font-medium text-foreground">Export all other attachments</p>
                    <p class="text-xs text-muted-foreground">Download as ZIP with PDF + attachment files</p>
                </div>
            </label>
        </div>

        <div class="flex gap-3 mt-6">
            <button onclick={() => showModal = false}
                class="flex-1 px-4 py-2 border border-border rounded-lg text-sm font-medium hover:bg-muted transition-colors cursor-pointer">
                Cancel
            </button>
            <button onclick={confirmDownload}
                class="flex-1 px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors cursor-pointer">
                Download
            </button>
        </div>
    </Dialog.Content>
</Dialog.Root>
