<script lang="ts">
    import { deriveIndexingState } from '$lib/utils/document-utils';

    interface Props {
        document: { status: string; chunk_count: number; embedded_count: number };
        /**
         * Optional progress info for the running stage (from BackgroundJob.output_data).
         * Falls back to status-derived bucketing.
         */
        progress?: {
            stage: string;
            stage_label?: string | null;
            percent: number;
        } | null;
    }

    let { document, progress = null }: Props = $props();
    const state = $derived(deriveIndexingState(document));

    type StageState = 'done' | 'running' | 'warning' | 'failed' | 'pending';

    type StageInfo = { key: string; label: string; state: StageState };

    const stages = $derived.by<StageInfo[]>(() => {
        const k = state.kind;
        // Map jobs.output_data.stage → which pipeline stage is "running"
        const runningStage = progress?.stage ?? null;

        const make = (key: string, label: string, s: StageState): StageInfo => ({
            key,
            label,
            state: s,
        });

        if (k === 'queued') {
            return [
                make('extract', 'Extract', 'pending'),
                make('chunk', 'Chunk', 'pending'),
                make('embed', 'Embed', 'pending'),
                make('ready', 'Ready', 'pending'),
            ];
        }
        if (k === 'failed') {
            return [
                make('extract', 'Extract', 'failed'),
                make('chunk', 'Chunk', 'pending'),
                make('embed', 'Embed', 'pending'),
                make('ready', 'Ready', 'pending'),
            ];
        }
        if (k === 'processing') {
            const stageMap: Record<string, StageInfo[]> = {
                extract: [
                    make('extract', 'Extract', 'running'),
                    make('chunk', 'Chunk', 'pending'),
                    make('embed', 'Embed', 'pending'),
                    make('ready', 'Ready', 'pending'),
                ],
                chunk: [
                    make('extract', 'Extract', 'done'),
                    make('chunk', 'Chunk', 'running'),
                    make('embed', 'Embed', 'pending'),
                    make('ready', 'Ready', 'pending'),
                ],
                embed: [
                    make('extract', 'Extract', 'done'),
                    make('chunk', 'Chunk', 'done'),
                    make('embed', 'Embed', 'running'),
                    make('ready', 'Ready', 'pending'),
                ],
            };
            return stageMap[runningStage ?? ''] ?? [
                make('extract', 'Extract', 'running'),
                make('chunk', 'Chunk', 'pending'),
                make('embed', 'Embed', 'pending'),
                make('ready', 'Ready', 'pending'),
            ];
        }
        if (k === 'indexed') {
            return [
                make('extract', 'Extract', 'done'),
                make('chunk', 'Chunk', 'done'),
                make('embed', 'Embed', 'done'),
                make('ready', 'Ready', 'done'),
            ];
        }
        if (k === 'partial') {
            // Extract + Chunk done, Embed warning, Ready pending (data is viewable
            // but search is degraded)
            return [
                make('extract', 'Extract', 'done'),
                make('chunk', 'Chunk', 'done'),
                make('embed', 'Embed', 'warning'),
                make('ready', 'Ready', 'warning'),
            ];
        }
        return [
            make('extract', 'Extract', 'pending'),
            make('chunk', 'Chunk', 'pending'),
            make('embed', 'Embed', 'pending'),
            make('ready', 'Ready', 'pending'),
        ];
    });

    function connectorClass(prev: StageState, next: StageState): string {
        if (prev === 'done' && (next === 'done' || next === 'running')) {
            return 'bg-accent';
        }
        if (prev === 'warning' || next === 'warning') {
            return 'bg-amber-300';
        }
        if (prev === 'failed') {
            return 'bg-destructive';
        }
        return 'bg-border';
    }

    function dotClasses(s: StageState): string {
        switch (s) {
            case 'done':
                return 'bg-accent border-accent text-white';
            case 'running':
                return 'border-primary text-primary bg-primary/10';
            case 'warning':
                return 'border-amber-400 bg-amber-100 text-amber-700';
            case 'failed':
                return 'border-destructive bg-destructive text-white';
            default:
                return 'border-border bg-card text-muted-foreground';
        }
    }

    function labelClasses(s: StageState): string {
        switch (s) {
            case 'done':
                return 'text-accent';
            case 'running':
                return 'text-primary font-medium';
            case 'warning':
                return 'text-amber-700 font-medium';
            case 'failed':
                return 'text-destructive font-medium';
            default:
                return 'text-muted-foreground';
        }
    }
</script>

<div class="flex items-center gap-1.5 sm:gap-2 text-xs" role="list">
    {#each stages as st, i (st.key)}
        {#if i > 0}
            <span
                aria-hidden="true"
                class="h-px flex-1 min-w-3 sm:min-w-6 {connectorClass(
                    stages[i - 1].state,
                    st.state,
                )}"
            ></span>
        {/if}
        <span class="flex items-center gap-1.5" role="listitem" aria-label="{st.label}: {st.state}">
            <span
                class="relative inline-flex h-2.5 w-2.5 shrink-0 items-center justify-center rounded-full border {dotClasses(
                    st.state,
                )}"
            >
                {#if st.state === 'running'}
                    <span
                        class="absolute inset-0 rounded-full border-2 border-primary animate-ping opacity-60"
                    ></span>
                {/if}
            </span>
            <span class={labelClasses(st.state)}>{st.label}</span>
        </span>
    {/each}
</div>
