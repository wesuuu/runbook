<script module lang="ts">
    export interface SignaturePadHandle {
        clear(): void;
        toBlob(): Promise<Blob | null>;
        isEmpty(): boolean;
    }
</script>

<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import SignaturePad from 'signature_pad';
    import { cn } from '$lib/utils';

    interface Props {
        width?: number;
        height?: number;
        class?: string;
        ariaLabel?: string;
        onChange?: (isEmpty: boolean) => void;
    }

    let {
        width = 480,
        height = 160,
        class: className = '',
        ariaLabel = 'Signature pad',
        onChange,
    }: Props = $props();

    let canvas: HTMLCanvasElement | null = $state(null);
    let pad: SignaturePad | null = null;

    function resizeCanvas() {
        if (!canvas) return;
        const ratio = Math.max(window.devicePixelRatio || 1, 1);
        canvas.width = canvas.offsetWidth * ratio;
        canvas.height = canvas.offsetHeight * ratio;
        canvas.getContext('2d')?.scale(ratio, ratio);
        pad?.clear();
    }

    onMount(() => {
        if (!canvas) return;
        pad = new SignaturePad(canvas, {
            minWidth: 0.5,
            maxWidth: 2.5,
            throttle: 16,
            velocityFilterWeight: 0.7,
            backgroundColor: 'rgba(0,0,0,0)',
            penColor: '#0f172a',
        });
        pad.addEventListener('endStroke', () => onChange?.(pad?.isEmpty() ?? true));
        resizeCanvas();
        window.addEventListener('resize', resizeCanvas);
    });

    onDestroy(() => {
        window.removeEventListener('resize', resizeCanvas);
        pad?.off();
    });

    export function clear(): void {
        pad?.clear();
        onChange?.(true);
    }

    export function isEmpty(): boolean {
        return pad?.isEmpty() ?? true;
    }

    export async function toBlob(): Promise<Blob | null> {
        if (!canvas || !pad || pad.isEmpty()) return null;
        return await new Promise<Blob | null>((resolve) => {
            canvas!.toBlob((b) => resolve(b), 'image/png');
        });
    }
</script>

<div
    class={cn(
        'relative rounded-md border border-border bg-background overflow-hidden',
        className,
    )}
    style="width: {width}px; height: {height}px;"
>
    <canvas
        bind:this={canvas}
        class="block w-full h-full cursor-crosshair touch-none"
        aria-label={ariaLabel}
    ></canvas>
    <span
        class="pointer-events-none absolute inset-x-3 bottom-2 border-t border-dashed border-muted-foreground/40"
    ></span>
    <span
        class="pointer-events-none absolute left-3 bottom-3 text-[11px] text-muted-foreground/60"
    >
        Sign here
    </span>
</div>
