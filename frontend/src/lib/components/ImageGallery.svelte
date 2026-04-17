<script lang="ts">
    import { API_BASE } from '$lib/config';

    interface RunImage {
        id: string;
        run_id: string;
        step_id: string;
        file_path: string;
        original_filename: string;
        mime_type: string;
        created_at: string;
    }

    let {
        images = [],
        confirmedImageIds = new Set<string>(),
        imageStatuses = {},
        onImageClick,
        onAnalyzeClick,
    }: {
        images: RunImage[];
        confirmedImageIds?: Set<string>;
        imageStatuses?: Record<string, string>;
        onImageClick?: (image: RunImage) => void;
        onAnalyzeClick?: (image: RunImage) => void;
    } = $props();

    function getStatusBadge(imageId: string): { label: string; color: string } {
        const status = imageStatuses[imageId];
        if (confirmedImageIds.has(imageId)) {
            return { label: 'Confirmed', color: 'bg-emerald-100 text-emerald-700' };
        }
        if (status === 'analyzed' || status === 'needs_clarification') {
            return { label: 'Analyzed', color: 'bg-blue-100 text-blue-700' };
        }
        return { label: 'Captured', color: 'bg-slate-100 text-slate-600' };
    }
</script>

{#if images.length > 0}
    <div class="mt-4">
        <p class="text-xs font-medium text-slate-500 mb-2">
            Captured Images ({images.length})
        </p>
        <div class="flex gap-3 flex-wrap">
            {#each images as image}
                {@const isConfirmed = confirmedImageIds.has(image.id)}
                {@const badge = getStatusBadge(image.id)}
                {@const needsAnalysis = !isConfirmed && badge.label === 'Captured'}
                <div class="flex flex-col items-center gap-1.5">
                    <button
                        onclick={() => onImageClick?.(image)}
                        title={isConfirmed ? 'Values confirmed — click to review' : 'Click to view'}
                        class="relative group w-16 h-16 rounded-lg overflow-hidden border-2 transition-colors focus:outline-none focus:ring-2 focus:ring-teal-500 {isConfirmed ? 'border-emerald-400' : badge.label === 'Analyzed' ? 'border-blue-300' : 'border-slate-200 hover:border-teal-400'}"
                    >
                        <img
                            src="{API_BASE}/uploads/images/{image.file_path}"
                            alt={image.original_filename}
                            class="w-full h-full object-cover"
                        />
                        <div class="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors"></div>
                        {#if isConfirmed}
                            <div class="absolute top-0.5 right-0.5 w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center shadow-sm">
                                <svg class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                                </svg>
                            </div>
                        {/if}
                    </button>
                    <span class="text-[10px] font-semibold px-1.5 py-0.5 rounded-full {badge.color}">
                        {badge.label}
                    </span>
                    {#if needsAnalysis}
                        <button
                            onclick={() => onAnalyzeClick?.(image)}
                            class="text-[10px] font-medium text-teal-600 hover:text-teal-800 underline"
                        >
                            Analyze
                        </button>
                    {/if}
                </div>
            {/each}
        </div>
    </div>
{/if}
