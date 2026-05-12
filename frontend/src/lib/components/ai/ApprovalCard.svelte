<script lang="ts">
    import { fly } from 'svelte/transition';
    import Check from '@lucide/svelte/icons/check';
    import X from '@lucide/svelte/icons/x';
    import AlertTriangle from '@lucide/svelte/icons/triangle-alert';
    import { Button } from '$lib/components/ui/button';

    interface PayloadPreview {
        title: string;
        source_url: string;
        step_count: number;
        duration_min_total?: number | null;
        license: string;
        deviations: string[];
    }

    interface Props {
        toolCallId: string;
        toolName: string;
        title: string;
        sourceUrl: string;
        payloadPreview: PayloadPreview;
        pending?: boolean;
        onApprove: (toolCallId: string) => void;
        onReject: (toolCallId: string) => void;
    }

    let {
        toolCallId,
        title,
        sourceUrl,
        payloadPreview,
        pending = false,
        onApprove,
        onReject,
    }: Props = $props();

    const sourceHost = $derived.by(() => {
        try {
            return new URL(sourceUrl).host;
        } catch {
            return sourceUrl;
        }
    });
</script>

<div
    in:fly={{ y: 6, duration: 220 }}
    class="approval-card overflow-hidden rounded-xl"
>
    <div class="label-row flex items-center gap-2 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider">
        <AlertTriangle class="w-3.5 h-3.5" />
        External protocol · review before import
    </div>

    <div class="space-y-3 px-3.5 py-3">
        <div>
            <div class="meta-label">Title</div>
            <div class="text-[15px] font-semibold leading-tight text-foreground">
                {title}
            </div>
        </div>

        <div class="grid grid-cols-3 gap-2 text-[12px]">
            <div>
                <div class="meta-label">Steps</div>
                <div class="text-[15px] font-semibold text-foreground">
                    {payloadPreview.step_count}
                </div>
            </div>
            <div>
                <div class="meta-label">Total time</div>
                <div class="text-[15px] font-semibold text-foreground">
                    {#if payloadPreview.duration_min_total != null}
                        ~{payloadPreview.duration_min_total} min
                    {:else}
                        —
                    {/if}
                </div>
            </div>
            <div>
                <div class="meta-label">License</div>
                <div class="font-mono text-[12px] font-semibold text-foreground">
                    {payloadPreview.license}
                </div>
            </div>
        </div>

        <div>
            <div class="meta-label mb-1">Source</div>
            <a
                href={sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                class="font-mono text-[12px] text-primary underline decoration-primary/30 underline-offset-2 break-all hover:decoration-primary"
            >
                {sourceHost}
            </a>
        </div>

        <div>
            <div class="meta-label mb-1">Deviations</div>
            {#if payloadPreview.deviations.length === 0}
                <span
                    class="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-medium text-success-foreground"
                    style="background: rgba(22, 163, 74, 0.12); color: #166534;"
                >
                    <Check class="w-3 h-3" />
                    None — copied verbatim
                </span>
            {:else}
                <ul class="flex flex-col gap-1">
                    {#each payloadPreview.deviations as dev}
                        <li
                            class="rounded-md border border-dashed px-2 py-1 text-[11.5px]"
                            style="background: rgba(220, 38, 38, 0.06); color: #991b1b; border-color: rgba(220, 38, 38, 0.3);"
                        >
                            {dev}
                        </li>
                    {/each}
                </ul>
            {/if}
        </div>

        <div class="flex items-center justify-end gap-2 pt-1.5">
            <Button
                variant="outline"
                size="sm"
                disabled={pending}
                onclick={() => onReject(toolCallId)}
                aria-label="Reject"
            >
                <X class="w-3.5 h-3.5 mr-1" />
                Reject
            </Button>
            <Button
                variant="default"
                size="sm"
                disabled={pending}
                onclick={() => onApprove(toolCallId)}
                aria-label="Approve & draft"
            >
                <Check class="w-3.5 h-3.5 mr-1" />
                Approve & draft
            </Button>
        </div>
    </div>
</div>

<style>
    .approval-card {
        background: linear-gradient(180deg, #fffaf0 0%, #fff7e6 100%);
        border: 1px solid #fde68a;
        box-shadow:
            inset 0 0 0 1px rgba(217, 119, 6, 0.05),
            0 1px 2px rgba(217, 119, 6, 0.08);
    }
    .label-row {
        background: #fef3c7;
        border-bottom: 1px solid #fde68a;
        color: #92400e;
    }
    .meta-label {
        font-family: 'JetBrains Mono', ui-monospace, monospace;
        font-size: 10.5px;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: #92400e;
        margin-bottom: 2px;
    }
    :global(.dark) .approval-card {
        background: linear-gradient(180deg, rgba(120, 53, 15, 0.18) 0%, rgba(120, 53, 15, 0.1) 100%);
        border-color: rgba(217, 119, 6, 0.4);
    }
    :global(.dark) .label-row {
        background: rgba(217, 119, 6, 0.15);
        border-bottom-color: rgba(217, 119, 6, 0.3);
        color: #fbbf24;
    }
    :global(.dark) .meta-label {
        color: #fbbf24;
    }
</style>
