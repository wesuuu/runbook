<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { fly, fade } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import Sparkles from '@lucide/svelte/icons/sparkles';
    import Check from '@lucide/svelte/icons/check';
    import type { ToolEvent } from '$lib/chat-store.svelte';

    interface Props {
        active: ToolEvent | null;
        trail: ToolEvent[];
    }

    let { active, trail }: Props = $props();

    // Cap visible trail rows so the stream doesn't grow unboundedly on
    // tool-heavy turns. Most-recent first.
    const visibleTrail = $derived(trail.slice(0, 3));

    // Live duration ticker on the active row. Reset whenever the active
    // tool's id changes (a new tool started); paused when there's no
    // active tool.
    let activeId = $state<number | null>(null);
    let startedAt = $state<number>(0);
    let elapsedMs = $state<number>(0);

    $effect(() => {
        const id = active?.id ?? null;
        if (id !== activeId) {
            activeId = id;
            startedAt = Date.now();
            elapsedMs = 0;
        }
    });

    let timer: ReturnType<typeof setInterval> | null = null;
    onMount(() => {
        timer = setInterval(() => {
            if (active) elapsedMs = Date.now() - startedAt;
        }, 100);
    });
    onDestroy(() => {
        if (timer) clearInterval(timer);
    });

    function fmtDuration(ms: number): string {
        return `${(ms / 1000).toFixed(1)}s`;
    }
</script>

<div class="flex justify-start">
    <div class="flex flex-col gap-1.5 w-full max-w-[420px]">
        {#if active}
            <div
                in:fly={{ y: 6, duration: 220 }}
                class="thinking-active relative overflow-hidden rounded-lg border border-primary/40 bg-card px-3 py-2.5 shadow-sm ring-1 ring-primary/15"
            >
                <div class="shimmer pointer-events-none absolute inset-0"></div>
                <div class="relative flex items-center gap-3">
                    <div class="grid place-items-center w-7 h-7 rounded-md bg-primary text-primary-foreground shrink-0">
                        <Sparkles class="w-3.5 h-3.5 animate-pulse" />
                    </div>
                    <div class="flex-1 min-w-0">
                        <div class="text-sm font-medium text-foreground truncate">
                            {active.label}
                        </div>
                        <div class="font-mono text-[10.5px] tracking-wider text-muted-foreground/80 truncate">
                            {active.name}
                        </div>
                    </div>
                    <div class="font-mono text-xs tabular-nums text-primary shrink-0">
                        {fmtDuration(elapsedMs)}
                    </div>
                </div>
            </div>
        {/if}

        {#each visibleTrail as t (t.id)}
            <div
                in:fade={{ duration: 180 }}
                animate:flip={{ duration: 220 }}
                class="flex items-center gap-3 rounded-lg border border-border/60 bg-transparent px-3 py-2 text-muted-foreground"
            >
                <div class="grid place-items-center w-7 h-7 rounded-md bg-muted text-muted-foreground/70 shrink-0">
                    <Check class="w-3.5 h-3.5" />
                </div>
                <div class="flex-1 min-w-0">
                    <div class="text-sm truncate line-through decoration-muted-foreground/30 decoration-[0.75px]">
                        {t.label}
                    </div>
                </div>
            </div>
        {/each}
    </div>
</div>

<style>
    .shimmer {
        /* `--primary` is intentionally dark across all three themes (deep teal
         * / navy / forest green), so we mix to a higher percentage than we
         * would for a saturated accent. */
        background: linear-gradient(
            100deg,
            transparent 30%,
            color-mix(in oklab, var(--primary) 18%, transparent) 50%,
            transparent 70%
        );
        transform: translateX(-100%);
        animation: shimmer 2.4s ease-in-out infinite;
    }
    @keyframes shimmer {
        0%   { transform: translateX(-100%); }
        60%  { transform: translateX(120%); }
        100% { transform: translateX(120%); }
    }
    @media (prefers-reduced-motion: reduce) {
        .shimmer { animation: none; }
    }
</style>
