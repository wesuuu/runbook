<script lang="ts">
    import { onDestroy } from 'svelte';
    import { fade } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { toast } from '$lib/toast';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import { EmptyState } from '$lib/components/ui/empty-state';
    import { Button } from '$lib/components/ui/button';
    import { Bell, ChevronLeft, ChevronRight } from 'lucide-svelte';
    import NotificationRow from '$lib/components/notifications/NotificationRow.svelte';
    import { HISTORY_PAGE_SIZE } from '$lib/notifications';
    import {
        NotificationListResponseSchema,
        type NotificationItem,
    } from '$lib/schemas';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();

    let items = $state<NotificationItem[]>([]);
    let total = $state(0);
    let loading = $state(true);
    let markingAll = $state(false);

    // Sequence guard — see NotificationBell. Page fetches can overlap when
    // the user pages quickly.
    let pageSeq = 0;

    // A handleSelect deep-link navigation unmounts this page while a
    // loadPage fetch may still be in flight. `destroyed` blocks the
    // resolved fetch from toasting / mutating $state on a dead component
    // (Svelte logs a warning for post-unmount state writes).
    let destroyed = false;
    onDestroy(() => {
        destroyed = true;
    });

    async function loadPage(offset: number): Promise<void> {
        const seq = ++pageSeq;
        loading = true;
        try {
            const resp = await api.get(
                `/notifications/?include_total=true&limit=${HISTORY_PAGE_SIZE}&offset=${offset}`,
                { schema: NotificationListResponseSchema },
            );
            if (destroyed || seq !== pageSeq) return;
            items = resp.items;
            total = resp.total;
        } catch (e) {
            console.error('Notification history load failed', e);
            if (!destroyed && seq === pageSeq) {
                toast.error('Could not load notifications');
            }
        } finally {
            if (!destroyed && seq === pageSeq) loading = false;
        }
    }

    // Refetch whenever the URL offset changes (back/forward, Prev/Next).
    $effect(() => {
        loadPage(data.offset);
    });

    function gotoOffset(offset: number): void {
        const query = offset > 0 ? `?offset=${offset}` : '';
        goto(`/notifications${query}`, { keepFocus: true, noScroll: true });
    }

    // NOTE: markRead / markAllRead / handleSelect mirror the same logic in
    // components/layout/NotificationBell.svelte (count-2, no shared store
    // yet). Keep the mark-read error semantics in sync across both.
    async function markRead(id: string): Promise<void> {
        const idx = items.findIndex((n) => n.id === id);
        if (idx === -1 || items[idx].read_at) return;
        const prev = items[idx];
        // Optimistic update first (snappy).
        items[idx] = { ...prev, read_at: new Date().toISOString() };
        try {
            await api.put(`/notifications/${id}/read`, {});
        } catch (e) {
            console.error('Mark-read failed', e);
            toast.error('Could not mark notification as read');
            // Roll back the optimistic update so the UI matches the server.
            const cur = items.findIndex((n) => n.id === id);
            if (cur !== -1) items[cur] = prev;
        }
    }

    // Unlike NotificationBell.markAllRead, this does no optimistic update:
    // a server-wide action invalidates rows on other pages too, so a plain
    // refetch of the current page is the correct, flicker-free convergence.
    async function markAllRead(): Promise<void> {
        if (markingAll) return; // guard against a double-tap
        markingAll = true;
        try {
            await api.put('/notifications/read-all', {});
        } catch (e) {
            console.error('Mark-all-read failed', e);
            toast.error('Could not mark all as read');
        }
        // Server-wide action: rows on other pages are now stale too.
        await loadPage(data.offset);
        markingAll = false;
    }

    function handleSelect(item: NotificationItem): void {
        const href = item.url;
        if (!item.read_at) markRead(item.id);
        if (!href) return;
        // TD-0091d: hash-bearing URLs from the resolver (#step-<id>)
        // navigate via window.location so the fragment is honored
        // even when already on the destination page.
        if (href.includes('#')) {
            window.location.href = href;
        } else {
            goto(href);
        }
    }

    const hasUnread = $derived(items.some((n) => !n.read_at));
    const rangeStart = $derived(items.length ? data.offset + 1 : 0);
    const rangeEnd = $derived(data.offset + items.length);
    const hasPrev = $derived(data.offset > 0);
    const hasNext = $derived(data.offset + HISTORY_PAGE_SIZE < total);
</script>

<div class="max-w-3xl mx-auto px-4 py-8" in:fade={{ duration: 150 }}>
    <div class="flex items-start justify-between mb-6">
        <div>
            <h1 class="text-2xl font-bold tracking-tight">Notifications</h1>
            <p class="text-sm text-muted-foreground mt-0.5">
                Activity from your runs, protocols, and team.
            </p>
        </div>
        {#if hasUnread}
            <Button
                variant="outline"
                size="sm"
                disabled={markingAll}
                onclick={markAllRead}
            >
                Mark all read
            </Button>
        {/if}
    </div>

    {#if loading && items.length === 0}
        <LoadingSpinner message="Loading notifications…" />
    {:else if items.length === 0}
        <EmptyState
            title="No notifications"
            description="Activity from your runs and protocols will appear here."
        >
            {#snippet icon()}
                <Bell class="size-7" />
            {/snippet}
        </EmptyState>
    {:else}
        <div class="rounded-lg border border-border/60 overflow-hidden bg-card">
            {#each items as item (item.id)}
                <div animate:flip={{ duration: 150 }} in:fade={{ duration: 120 }}>
                    <NotificationRow
                        {item}
                        compact={false}
                        onSelect={handleSelect}
                    />
                </div>
            {/each}
        </div>

        <div class="flex items-center justify-between mt-4 text-sm text-muted-foreground">
            <span>Showing {rangeStart}–{rangeEnd} of {total}</span>
            <div class="flex gap-2">
                <Button
                    variant="outline"
                    size="sm"
                    disabled={!hasPrev || loading}
                    onclick={() =>
                        gotoOffset(Math.max(0, data.offset - HISTORY_PAGE_SIZE))}
                >
                    <ChevronLeft class="size-3.5" />
                    Prev
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    disabled={!hasNext || loading}
                    onclick={() => gotoOffset(data.offset + HISTORY_PAGE_SIZE)}
                >
                    Next
                    <ChevronRight class="size-3.5" />
                </Button>
            </div>
        </div>
    {/if}
</div>
