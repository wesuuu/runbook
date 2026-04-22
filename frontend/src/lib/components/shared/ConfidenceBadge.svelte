<script lang="ts">
    interface Props {
        confidence: number;
    }

    let { confidence }: Props = $props();

    const level = $derived(confidence >= 0.8 ? 'high' : confidence >= 0.5 ? 'medium' : 'low');
    const pct = $derived(Math.round(confidence * 100));
    const colors: Record<string, string> = {
        high: 'bg-green-100 text-green-800',
        medium: 'bg-yellow-100 text-yellow-800',
        low: 'bg-red-100 text-red-800',
    };
</script>

<span
    class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {colors[level]}"
    title="{pct}% confidence"
>
    {pct}%
</span>
