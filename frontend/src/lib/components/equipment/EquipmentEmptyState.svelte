<script lang="ts">
    interface Props { onAdd?: () => void; }
    let { onAdd }: Props = $props();
</script>
<div class="border border-dashed border-border rounded-lg text-center py-8 text-sm text-muted-foreground bg-muted/30">
    <p>No equipment at this site.</p>
    <button class="mt-2 inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-sm font-medium cursor-pointer hover:brightness-90 transition-all duration-150"
            onclick={() => onAdd?.()}>+ Add equipment</button>
</div>
