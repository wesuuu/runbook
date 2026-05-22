<script lang="ts">
    import { ChevronRight } from 'lucide-svelte';
    import { eventIcon, eventTone } from '$lib/notifications';
    import { timeAgo } from '$lib/utils';
    import type { NotificationItem } from '$lib/schemas';

    interface Props {
        item: NotificationItem;
        compact?: boolean;
        onSelect: (item: NotificationItem) => void;
    }
    let { item, compact = false, onSelect }: Props = $props();

    const href = $derived(item.url);
    const Icon = $derived(eventIcon(item.event_type));
    const tone = $derived(eventTone(item.event_type));
    const unread = $derived(!item.read_at);
    const wrapperClass = $derived(
        `group flex items-start transition-colors duration-150 cursor-pointer hover:bg-accent/50 border-b border-border/30 last:border-b-0` +
        ` ${compact ? 'gap-2 px-3 py-2.5' : 'gap-3 px-4 py-3.5'}` +
        ` ${!compact && unread ? 'border-l-2 border-l-primary' : ''}` +
        ` ${!compact && !unread ? 'border-l-2 border-l-transparent' : ''}` +
        ` ${!unread ? 'opacity-70 hover:opacity-100' : ''}`
    );

    function handleClick(e: MouseEvent) {
        // For an <a>, let modified / non-left clicks open a new tab natively.
        if (href && (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0)) {
            return;
        }
        if (href) e.preventDefault();
        onSelect(item);
    }
</script>

{#snippet body()}
    <span
        class="shrink-0 rounded-lg flex items-center justify-center {tone}
            {compact ? 'size-7' : 'size-9'}"
    >
        <Icon class={compact ? 'size-4' : 'size-[18px]'} />
    </span>
    <span class="flex-1 min-w-0">
        <span class="flex items-center gap-1.5">
            {#if compact && unread}
                <span class="size-1.5 rounded-full bg-primary shrink-0"></span>
            {/if}
            <span class="text-sm font-medium truncate">{item.title}</span>
        </span>
        <span
            class="block text-xs text-muted-foreground mt-0.5 {compact
                ? 'line-clamp-2'
                : 'line-clamp-3'}"
        >{item.message}</span>
        <span class="block text-[11px] text-muted-foreground/60 mt-1">
            {timeAgo(item.created_at)}
        </span>
    </span>
    {#if href}
        <!-- Hover affordance: only navigable rows get the chevron, so the
             user can tell navigate-vs-mark-read apart before tapping. -->
        <ChevronRight
            class="shrink-0 self-center size-4 text-muted-foreground opacity-0 -translate-x-1 transition-all duration-150 group-hover:opacity-100 group-hover:translate-x-0"
        />
    {/if}
{/snippet}

{#if href}
    <a
        {href}
        onclick={handleClick}
        data-testid="notification-row"
        class={wrapperClass}
    >
        {@render body()}
    </a>
{:else}
    <button
        type="button"
        onclick={handleClick}
        data-testid="notification-row"
        class="w-full text-left {wrapperClass}"
    >
        {@render body()}
    </button>
{/if}
