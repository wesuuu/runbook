<script lang="ts">
    import { goto } from '$app/navigation';
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

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
        <Button
            variant="outline"
            onclick={onDownloadSop}
            class="w-full h-auto justify-between px-4 py-3 font-medium"
        >
            <span class="text-foreground">
                Download SOP
            </span>
            <span class="text-muted-foreground/60">&darr;</span>
        </Button>

        <hr class="my-3" />

        <Button
            variant="outline"
            onclick={() => onDownloadBatchRecord(false)}
            class="w-full h-auto justify-between px-4 py-3 font-medium"
        >
            <span class="text-foreground">
                Download Blank Batch Record
            </span>
            <span class="text-muted-foreground/60">&darr;</span>
        </Button>

        {#if showFilledRecord}
            <Button
                variant="outline"
                onclick={handleFilledDownload}
                class="w-full h-auto justify-between px-4 py-3 font-medium {filledBgClass}"
            >
                <span class={filledTextClass}>
                    {filledLabel}
                </span>
                <span class={filledArrowClass}>&darr;</span>
            </Button>

            <hr class="my-3" />

            <Button
                variant="outline"
                onclick={() => goto(`/export?runs=${runId}`)}
                class="w-full h-auto justify-between px-4 py-3 font-medium bg-blue-50 hover:bg-blue-100 border-blue-200"
            >
                <span class="text-blue-900">
                    Export Data (CSV / Excel / JSON)
                </span>
                <span class="text-blue-600">&darr;</span>
            </Button>
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
            <Button variant="outline" class="flex-1" onclick={() => showModal = false}>Cancel</Button>
            <Button class="flex-1" onclick={confirmDownload}>Download</Button>
        </div>
    </Dialog.Content>
</Dialog.Root>
