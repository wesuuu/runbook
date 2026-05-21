<script lang="ts">
    interface BlockerReason {
        code: string;
        label: string;
    }
    interface Props {
        blocker: BlockerReason;
    }
    let { blocker }: Props = $props();
</script>

<span
    data-testid="blocker-tag"
    class="inline-flex items-center gap-1 rounded-md bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-red-700"
>
    <span class="h-1 w-1 rounded-full bg-red-500"></span>
    {blocker.label}
</span>
