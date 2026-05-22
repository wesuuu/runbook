<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { isAuthenticated } from '$lib/auth.svelte';
    import { toast } from '$lib/toast';
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
    import { Button } from '$lib/components/ui/button';
    import NotificationRow from '$lib/components/notifications/NotificationRow.svelte';
    import { BELL_LIMIT } from '$lib/notifications';
    import {
        NotificationListResponseSchema,
        UnreadCountResponseSchema,
        type NotificationItem,
    } from '$lib/schemas';

    const POLL_MS = 30000;

    let open = $state(false);
    let unreadCount = $state(0);
    let notifications = $state<NotificationItem[]>([]);
    let loading = $state(false);
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    // Monotonic sequence: a list fetch assigns `notifications` only if its
    // sequence is still the latest, so a slow earlier response cannot
    // clobber a fresh later one.
    let listSeq = 0;

    const hasUnread = $derived(notifications.some((n) => !n.read_at));

    async function fetchUnreadCount(): Promise<void> {
        if (!isAuthenticated()) return;
        try {
            const resp = await api.get('/notifications/unread-count', {
                schema: UnreadCountResponseSchema,
            });
            unreadCount = resp.count;
        } catch (e) {
            // Background poll — log only; the next tick self-heals.
            console.error('Notification unread-count poll failed', e);
        }
    }

    async function fetchNotifications(userInitiated = false): Promise<void> {
        if (!isAuthenticated()) return;
        const seq = ++listSeq;
        loading = true;
        try {
            const resp = await api.get(`/notifications/?limit=${BELL_LIMIT}`, {
                schema: NotificationListResponseSchema,
            });
            if (seq !== listSeq) return; // a newer fetch already landed
            notifications = resp.items;
        } catch (e) {
            console.error('Notification list fetch failed', e);
            if (userInitiated) {
                toast.error('Could not load notifications');
            }
        } finally {
            if (seq === listSeq) loading = false;
        }
    }

    // NOTE: markRead / markAllRead / handleSelect are intentionally
    // duplicated in routes/notifications/+page.svelte (count-2, no shared
    // store yet). Keep the mark-read error semantics in sync across both.
    async function markRead(id: string, navigating: boolean): Promise<void> {
        const idx = notifications.findIndex((n) => n.id === id);
        if (idx === -1 || notifications[idx].read_at) return;
        // Optimistic update first (snappy).
        notifications[idx] = {
            ...notifications[idx],
            read_at: new Date().toISOString(),
        };
        unreadCount = Math.max(0, unreadCount - 1);
        try {
            await api.put(`/notifications/${id}/read`, {});
        } catch (e) {
            console.error('Mark-read failed', e);
            toast.error('Could not mark notification as read');
            // Navigating clicks unmount this component — refetch only for
            // plain (non-navigating) clicks so the UI converges.
            if (!navigating) {
                await fetchNotifications();
                await fetchUnreadCount();
            }
        }
    }

    async function markAllRead(): Promise<void> {
        const snapshot = notifications;
        const prevCount = unreadCount;
        notifications = notifications.map((n) => ({
            ...n,
            read_at: n.read_at ?? new Date().toISOString(),
        }));
        unreadCount = 0;
        try {
            await api.put('/notifications/read-all', {});
        } catch (e) {
            console.error('Mark-all-read failed', e);
            toast.error('Could not mark all as read');
            notifications = snapshot;
            unreadCount = prevCount;
            await fetchNotifications();
            await fetchUnreadCount();
        }
    }

    function handleSelect(item: NotificationItem): void {
        const href = item.url;
        if (!item.read_at) markRead(item.id, href !== null);
        if (href) {
            open = false;
            goto(href);
        }
    }

    function handleOpenChange(next: boolean): void {
        if (next) {
            fetchNotifications(true);
            fetchUnreadCount();
        }
    }

    function onPollTick(): void {
        fetchUnreadCount();
        if (open) fetchNotifications();
    }

    function onVisibility(): void {
        if (document.visibilityState !== 'visible') return;
        fetchUnreadCount();
        if (open) fetchNotifications();
    }

    onMount(() => {
        fetchUnreadCount();
        pollInterval = setInterval(onPollTick, POLL_MS);
        document.addEventListener('visibilitychange', onVisibility);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
        document.removeEventListener('visibilitychange', onVisibility);
    });
</script>

<DropdownMenu.Root bind:open onOpenChange={handleOpenChange}>
    <DropdownMenu.Trigger>
        <Button
            variant="ghost"
            size="icon-sm"
            rounded="full"
            class="relative text-muted-foreground hover:text-foreground"
            aria-label="Notifications"
        >
            <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                class={`size-5 ${unreadCount > 0 ? 'jingle' : ''}`}
            >
                <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
                <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
            </svg>
            {#if unreadCount > 0}
                <span
                    class="absolute -top-1 -right-1 inline-flex items-center justify-center"
                    aria-live="polite"
                    aria-atomic="true"
                >
                    <span
                        class="notif-ping absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75"
                    ></span>
                    <span
                        class="relative min-w-[18px] h-[18px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center leading-none"
                    >
                        {unreadCount > 99 ? '99+' : unreadCount}
                    </span>
                </span>
            {/if}
        </Button>
    </DropdownMenu.Trigger>

    <DropdownMenu.Content
        align="end"
        class="w-80 max-w-[calc(100vw-2rem)] z-[100] p-0"
    >
        <div class="flex items-center justify-between px-3 py-2 border-b border-border/60">
            <span class="text-sm font-semibold">Notifications</span>
            {#if hasUnread}
                <Button
                    variant="link"
                    size="sm"
                    class="h-auto p-0 text-xs"
                    onclick={markAllRead}
                >
                    Mark all read
                </Button>
            {/if}
        </div>

        <div class="overflow-y-auto max-h-72">
            {#if loading && notifications.length === 0}
                <div class="px-3 py-6 text-center text-sm text-muted-foreground">
                    Loading...
                </div>
            {:else if notifications.length === 0}
                <div class="px-3 py-6 text-center text-sm text-muted-foreground">
                    No notifications yet
                </div>
            {:else}
                {#each notifications as notif (notif.id)}
                    <NotificationRow
                        item={notif}
                        compact={true}
                        onSelect={handleSelect}
                    />
                {/each}
            {/if}
        </div>

        <DropdownMenu.Separator class="my-0" />
        <DropdownMenu.Item>
            {#snippet child({ props })}
                <a
                    href="/notifications"
                    {...props}
                    class="block w-full text-center px-3 py-2 text-xs font-medium text-primary cursor-pointer"
                >
                    View all notifications
                </a>
            {/snippet}
        </DropdownMenu.Item>
    </DropdownMenu.Content>
</DropdownMenu.Root>

<style>
    .jingle {
        transform-origin: 50% 10%;
        animation: jingle 2.4s ease-in-out infinite;
    }

    @keyframes jingle {
        0%, 60%, 100% { transform: rotate(0); }
        5%  { transform: rotate(-14deg); }
        10% { transform: rotate(12deg); }
        15% { transform: rotate(-10deg); }
        20% { transform: rotate(8deg); }
        25% { transform: rotate(-5deg); }
        30% { transform: rotate(3deg); }
        35% { transform: rotate(0); }
    }

    @media (prefers-reduced-motion: reduce) {
        .jingle,
        .notif-ping {
            animation: none;
        }
    }
</style>
