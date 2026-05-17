<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import { documentSourcePageUrl } from '$lib/api/documents';
    import { ChevronLeft, ChevronRight, Check } from 'lucide-svelte';

    interface Props {
        documentId: string;
        mimeType: string;
        pageCount: number | null | undefined;
        status: string;
        sourceFormat: string | null | undefined;
        ocrEngine: string | null | undefined;
    }

    let {
        documentId,
        mimeType,
        pageCount,
        status,
        sourceFormat,
        ocrEngine,
    }: Props = $props();

    const isPdf = $derived(mimeType === 'application/pdf');
    const totalPages = $derived(Math.max(1, pageCount ?? 1));

    let currentPage = $state(1);

    const thumbnailUrl = $derived(
        isPdf ? documentSourcePageUrl(documentId, currentPage) : null,
    );

    function prevPage(): void {
        if (currentPage > 1) currentPage -= 1;
    }
    function nextPage(): void {
        if (currentPage < totalPages) currentPage += 1;
    }

    /** Ordered pipeline; index of `status` decides what is done / active / pending. */
    const STEPS: { key: string; label: string }[] = [
        { key: 'UPLOADED', label: 'Uploaded' },
        { key: 'EXTRACTING', label: 'Extracting' },
        { key: 'AWAITING_REFINEMENT', label: 'Awaiting refinement' },
        { key: 'INDEXING', label: 'Indexing' },
        { key: 'READY', label: 'Ready' },
    ];

    /** Treat QUEUED like UPLOADED for pipeline display. */
    const normalizedStatus = $derived(status === 'QUEUED' ? 'UPLOADED' : status);
    const activeIndex = $derived(
        STEPS.findIndex((s) => s.key === normalizedStatus),
    );
</script>

<aside class="space-y-4">
    {#if isPdf && thumbnailUrl}
        <div class="rounded-lg border border-border bg-card p-3 shadow-sm">
            <div class="aspect-[3/4] w-full overflow-hidden rounded-md bg-muted">
                <img
                    src={thumbnailUrl}
                    alt="Source page {currentPage}"
                    class="h-full w-full object-contain"
                />
            </div>
            {#if totalPages > 1}
                <div class="mt-2 flex items-center justify-between">
                    <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Previous page"
                        disabled={currentPage <= 1}
                        onclick={prevPage}
                    >
                        <ChevronLeft class="h-4 w-4" />
                    </Button>
                    <span class="text-xs text-muted-foreground">
                        Page {currentPage} / {totalPages}
                    </span>
                    <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Next page"
                        disabled={currentPage >= totalPages}
                        onclick={nextPage}
                    >
                        <ChevronRight class="h-4 w-4" />
                    </Button>
                </div>
            {/if}
        </div>
    {/if}

    <div class="rounded-lg border border-border bg-card p-3 shadow-sm">
        <h2 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Extraction
        </h2>
        <ul class="space-y-1.5">
            {#each STEPS as step, i (step.key)}
                {@const isDone = activeIndex >= 0 && i < activeIndex}
                {@const isActive = i === activeIndex}
                <li
                    data-active={isActive}
                    class="flex items-center gap-2 text-sm {isActive
                        ? 'font-medium text-foreground'
                        : isDone
                          ? 'text-muted-foreground'
                          : 'text-muted-foreground/50'}"
                >
                    <span
                        class="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border {isActive
                            ? 'border-primary'
                            : isDone
                              ? 'border-primary bg-primary text-primary-foreground'
                              : 'border-border'}"
                    >
                        {#if isDone}
                            <Check class="h-3 w-3" />
                        {:else if isActive}
                            <span class="h-1.5 w-1.5 rounded-full bg-primary"></span>
                        {/if}
                    </span>
                    {step.label}
                </li>
            {/each}
        </ul>
        <dl class="mt-3 space-y-1 border-t border-border pt-2 text-xs text-muted-foreground">
            {#if sourceFormat}
                <div class="flex justify-between">
                    <dt>Format</dt>
                    <dd class="font-medium text-foreground">{sourceFormat}</dd>
                </div>
            {/if}
            {#if ocrEngine}
                <div class="flex justify-between">
                    <dt>OCR engine</dt>
                    <dd class="font-medium text-foreground">{ocrEngine}</dd>
                </div>
            {/if}
        </dl>
    </div>
</aside>
