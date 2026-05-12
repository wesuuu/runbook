<script lang="ts">
    interface Props {
        label: string | null;
    }
    let { label }: Props = $props();
</script>

<div class="flex justify-start">
    <div class="bg-muted/70 rounded-xl px-4 py-3">
        <div class="flex items-center gap-2">
            {#if label}
                <span class="text-sm text-muted-foreground/80">{label}</span>
            {/if}
            <div class="flex items-center gap-1.5">
                <div class="w-2 h-2 rounded-full bg-muted-foreground/40 animate-bounce" style="animation-delay: 0ms"></div>
                <div class="w-2 h-2 rounded-full bg-muted-foreground/40 animate-bounce" style="animation-delay: 150ms"></div>
                <div class="w-2 h-2 rounded-full bg-muted-foreground/40 animate-bounce" style="animation-delay: 300ms"></div>
            </div>
        </div>
    </div>
</div>
