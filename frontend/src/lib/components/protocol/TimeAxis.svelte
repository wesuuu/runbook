<script lang="ts">
    interface Props {
        layout: "horizontal" | "vertical";
        totalHours: number;
        pixelsPerHour: number;
        viewportTransform: { x: number; y: number; zoom: number };
    }

    let { layout, totalHours, pixelsPerHour, viewportTransform }: Props =
        $props();

    // Generate hour marks from 0 to totalHours
    const hourMarks = $derived(
        Array.from({ length: totalHours + 1 }, (_, i) => ({
            label: `${i}h`,
            offset: i * pixelsPerHour,
        })),
    );

    // Generate 15-minute sub-ticks between hours
    const subTicks = $derived(() => {
        const ticks: Array<{ offset: number }> = [];
        for (let h = 0; h < totalHours; h++) {
            for (const q of [15, 30, 45]) {
                ticks.push({ offset: (h + q / 60) * pixelsPerHour });
            }
        }
        return ticks;
    });
</script>

<div class="time-axis" class:vertical={layout === "vertical"}>
    {#each hourMarks as mark}
        {#if layout === "horizontal"}
            <div
                class="tick-h"
                style:left="{mark.offset * viewportTransform.zoom +
                    viewportTransform.x}px"
            >
                <span class="tick-label">{mark.label}</span>
                <div class="tick-line-h"></div>
            </div>
        {:else}
            <div
                class="tick-v"
                style:top="{mark.offset * viewportTransform.zoom +
                    viewportTransform.y}px"
            >
                <span class="tick-label">{mark.label}</span>
                <div class="tick-line-v"></div>
            </div>
        {/if}
    {/each}

    <!-- 15-minute sub-ticks -->
    {#each subTicks() as tick}
        {#if layout === "horizontal"}
            <div
                class="subtick-h"
                style:left="{tick.offset * viewportTransform.zoom +
                    viewportTransform.x}px"
            ></div>
        {:else}
            <div
                class="subtick-v"
                style:top="{tick.offset * viewportTransform.zoom +
                    viewportTransform.y}px"
            ></div>
        {/if}
    {/each}
</div>

<style>
    .time-axis {
        position: absolute;
        z-index: 5;
        pointer-events: none;
    }

    .time-axis:not(.vertical) {
        top: 0;
        left: 0;
        right: 0;
        height: 28px;
        background: linear-gradient(
            to bottom,
            hsla(0, 0%, 100%, 0.95),
            hsla(0, 0%, 100%, 0.7)
        );
        backdrop-filter: blur(4px);
        border-bottom: 1px solid hsl(240, 5.9%, 90%);
    }

    .time-axis.vertical {
        top: 0;
        left: 0;
        bottom: 0;
        width: 52px;
        background: linear-gradient(
            to right,
            hsla(0, 0%, 100%, 0.95),
            hsla(0, 0%, 100%, 0.7)
        );
        backdrop-filter: blur(4px);
        border-right: 1px solid hsl(240, 5.9%, 90%);
    }

    .tick-h {
        position: absolute;
        top: 0;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
    }

    .tick-v {
        position: absolute;
        left: 0;
        width: 100%;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .tick-label {
        font-size: 9px;
        font-weight: 600;
        color: #94a3b8;
        font-family: "JetBrains Mono", monospace;
        padding: 4px 2px;
        white-space: nowrap;
    }

    .tick-line-h {
        width: 1px;
        flex: 1;
        background: hsla(240, 5.9%, 90%, 0.6);
    }

    .tick-line-v {
        height: 1px;
        flex: 1;
        background: hsla(240, 5.9%, 90%, 0.6);
    }

    /* 15-minute sub-ticks */
    .subtick-h {
        position: absolute;
        top: 20px;
        width: 1px;
        height: 8px;
        background: hsla(240, 5.9%, 90%, 0.35);
    }

    .subtick-v {
        position: absolute;
        left: 44px;
        height: 1px;
        width: 8px;
        background: hsla(240, 5.9%, 90%, 0.35);
    }
</style>
