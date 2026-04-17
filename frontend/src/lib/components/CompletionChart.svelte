<script lang="ts">
    import { Button } from '$lib/components/ui/button';

    type TrendItem = { date: string; count: number };

    let { trend = [], onToggleDays }: { trend: TrendItem[]; onToggleDays?: () => void } = $props();

    const maxCount = $derived(Math.max(...trend.map((t) => t.count), 1));
    const hasData = $derived(trend.some((t) => t.count > 0));

    let hoveredIndex = $state<number | null>(null);

    function dayLabel(dateStr: string): string {
        const d = new Date(dateStr + 'T12:00:00');
        return d.toLocaleDateString('en-US', { weekday: 'short' });
    }

    function shortDate(dateStr: string): string {
        const d = new Date(dateStr + 'T12:00:00');
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    // Layout
    const padLeft = 28;
    const padRight = 16;
    const padTop = 24;
    const padBottom = 28;
    const chartH = 80;
    const svgW = 600;
    const svgH = padTop + chartH + padBottom;

    const plotW = $derived(svgW - padLeft - padRight);

    // Point positions
    const points = $derived(
        trend.map((item, i) => {
            const x = padLeft + (trend.length > 1 ? (i / (trend.length - 1)) * plotW : plotW / 2);
            const y = padTop + chartH - (item.count / maxCount) * chartH;
            return { x, y, item, i };
        })
    );

    // SVG line path
    const linePath = $derived(
        points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
    );

    // SVG filled area path (line + close along bottom)
    const areaPath = $derived(
        linePath +
        ` L${points[points.length - 1]?.x ?? padLeft},${padTop + chartH}` +
        ` L${points[0]?.x ?? padLeft},${padTop + chartH} Z`
    );

    // Y-axis gridlines (0 to max, ~3 lines)
    const yTicks = $derived.by(() => {
        if (maxCount <= 1) return [0, 1];
        const step = Math.ceil(maxCount / 3);
        const ticks: number[] = [];
        for (let v = 0; v <= maxCount; v += step) ticks.push(v);
        if (ticks[ticks.length - 1] < maxCount) ticks.push(maxCount);
        return ticks;
    });

    function yForValue(v: number): number {
        return padTop + chartH - (v / maxCount) * chartH;
    }

    // Label thinning for 14-day mode
    function showLabel(i: number): boolean {
        if (trend.length <= 7) return true;
        return i % 2 === 0 || i === trend.length - 1;
    }
</script>

<div class="card-warm rounded-xl p-5 mb-8" style="animation: fadeSlideUp 0.4s ease-out 0.12s both">
    <div class="flex items-center justify-between mb-3">
        <h2 class="text-xs font-bold uppercase tracking-widest text-muted-foreground flex items-center gap-2.5">
            <span class="w-2 h-2 bg-emerald-500 rounded-full"></span>
            Completions
        </h2>
        {#if onToggleDays}
            <Button
                variant="ghost"
                size="sm"
                class="h-auto text-[10px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground px-2 py-1"
                onclick={onToggleDays}
            >
                {trend.length <= 7 ? '14d' : '7d'}
            </Button>
        {/if}
    </div>

    {#if !hasData}
        <div class="py-5 text-center">
            <p class="text-sm text-muted-foreground">No completions in the last {trend.length} days</p>
        </div>
    {:else}
        <svg
            viewBox="0 0 {svgW} {svgH}"
            class="w-full h-auto select-none"
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label="Run completion trend chart"
        >
            <!-- Y-axis gridlines -->
            {#each yTicks as tick}
                {@const y = yForValue(tick)}
                <line
                    x1={padLeft}
                    y1={y}
                    x2={svgW - padRight}
                    y2={y}
                    class="stroke-border"
                    stroke-width="1"
                    stroke-dasharray={tick === 0 ? 'none' : '4 3'}
                />
                <text
                    x={padLeft - 8}
                    y={y + 3.5}
                    text-anchor="end"
                    class="fill-muted-foreground/60"
                    style="font-size: 9px; font-family: inherit"
                >
                    {tick}
                </text>
            {/each}

            <!-- Gradient fill -->
            <defs>
                <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" class="text-primary" stop-color="currentColor" stop-opacity="0.18" />
                    <stop offset="100%" class="text-primary" stop-color="currentColor" stop-opacity="0.02" />
                </linearGradient>
            </defs>

            <!-- Area fill -->
            <path d={areaPath} fill="url(#areaGrad)" />

            <!-- Line -->
            <path
                d={linePath}
                fill="none"
                class="stroke-primary"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
            />

            <!-- Dots (visual layer) -->
            {#each points as p}
                {@const isHovered = hoveredIndex === p.i}

                {#if isHovered}
                    <line
                        x1={p.x}
                        y1={padTop}
                        x2={p.x}
                        y2={padTop + chartH}
                        class="stroke-border"
                        stroke-width="1"
                        stroke-dasharray="3 2"
                    />
                {/if}

                <circle
                    cx={p.x}
                    cy={p.y}
                    r={isHovered ? 5 : p.item.count > 0 ? 3 : 2}
                    class="transition-all duration-150 {isHovered ? 'fill-primary stroke-background' : p.item.count > 0 ? 'fill-primary' : 'fill-muted-foreground/30'}"
                    stroke-width={isHovered ? 2 : 0}
                    style="pointer-events: none"
                />
            {/each}

            <!-- Hit areas (topmost layer for hover detection) -->
            {#each points as p}
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <rect
                    x={p.x - (plotW / trend.length) / 2}
                    y={padTop}
                    width={plotW / trend.length}
                    height={chartH + padBottom}
                    fill="transparent"
                    onmouseenter={() => hoveredIndex = p.i}
                    onmouseleave={() => hoveredIndex = null}
                    style="cursor: pointer"
                />
            {/each}

            <!-- Tooltips (rendered last, above everything) -->
            {#each points as p}
                {#if hoveredIndex === p.i}
                    {@const label = `${p.item.count} completed`}
                    {@const sub = shortDate(p.item.date)}
                    {@const tooltipW = Math.max(label.length, sub.length) * 7 + 20}
                    {@const tooltipH = 36}
                    {@const tx = Math.max(0, Math.min(p.x - tooltipW / 2, svgW - tooltipW))}
                    {@const ty = Math.max(0, p.y - tooltipH - 10)}

                    <rect
                        x={tx}
                        y={ty}
                        width={tooltipW}
                        height={tooltipH}
                        rx={8}
                        class="fill-foreground"
                        style="pointer-events: none"
                    />
                    <polygon
                        points="{p.x - 4},{ty + tooltipH} {p.x + 4},{ty + tooltipH} {p.x},{ty + tooltipH + 5}"
                        class="fill-foreground"
                        style="pointer-events: none"
                    />
                    <text
                        x={tx + tooltipW / 2}
                        y={ty + 14}
                        text-anchor="middle"
                        fill="white"
                        style="font-size: 11px; font-weight: 600; font-family: inherit; pointer-events: none"
                    >
                        {label}
                    </text>
                    <text
                        x={tx + tooltipW / 2}
                        y={ty + 28}
                        text-anchor="middle"
                        fill="rgba(255,255,255,0.6)"
                        style="font-size: 9px; font-family: inherit; pointer-events: none"
                    >
                        {sub}
                    </text>
                {/if}
            {/each}

            <!-- X-axis labels -->
            {#each points as p}
                {#if showLabel(p.i)}
                    <text
                        x={p.x}
                        y={padTop + chartH + 16}
                        text-anchor="middle"
                        class="fill-muted-foreground"
                        style="font-size: 9px; font-family: inherit"
                    >
                        {dayLabel(p.item.date)}
                    </text>
                {/if}
            {/each}
        </svg>
    {/if}
</div>
