<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { api } from '$lib/api';
    import { isAuthenticated } from '$lib/auth.svelte';
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
    import { Button } from '$lib/components/ui/button';

    interface NotificationItem {
        id: string;
        event_type: string;
        entity_type: string;
        entity_id: string;
        title: string;
        message: string;
        read_at: string | null;
        created_at: string;
    }

    interface NotificationListResponse {
        items: NotificationItem[];
        total: number;
    }

    interface UnreadCountResponse {
        count: number;
    }

    let unreadCount = $state(0);
    let notifications = $state<NotificationItem[]>([]);
    let loading = $state(false);
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    async function fetchUnreadCount() {
        if (!isAuthenticated()) return;
        try {
            const resp = await api.get<UnreadCountResponse>('/notifications/unread-count');
            unreadCount = resp.count;
        } catch {
            // Silently fail — poll will retry
        }
    }

    async function fetchNotifications() {
        if (!isAuthenticated()) return;
        loading = true;
        try {
            const resp = await api.get<NotificationListResponse>('/notifications/?limit=20');
            notifications = resp.items;
            // Also refresh count
            unreadCount = notifications.filter((n) => !n.read_at).length;
        } catch {
            // Silently fail
        } finally {
            loading = false;
        }
    }

    async function markRead(id: string) {
        try {
            await api.put<NotificationItem>(`/notifications/${id}/read`, {});
            const idx = notifications.findIndex((n) => n.id === id);
            if (idx !== -1) {
                notifications[idx] = { ...notifications[idx], read_at: new Date().toISOString() };
            }
            unreadCount = Math.max(0, unreadCount - 1);
        } catch {
            // Silently fail
        }
    }

    async function markAllRead() {
        try {
            await api.put('/notifications/read-all', {});
            notifications = notifications.map((n) => ({
                ...n,
                read_at: n.read_at || new Date().toISOString(),
            }));
            unreadCount = 0;
        } catch {
            // Silently fail
        }
    }

    function timeAgo(dateStr: string): string {
        const now = Date.now();
        const then = new Date(dateStr).getTime();
        const diffSec = Math.floor((now - then) / 1000);

        if (diffSec < 60) return 'just now';
        if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
        if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
        return `${Math.floor(diffSec / 86400)}d ago`;
    }

    function eventIcon(eventType: string): string {
        const icons: Record<string, string> = {
            RUN_STARTED: '\u25B6',
            RUN_COMPLETED: '\u2713',
            ROLE_ASSIGNED: '\u2192',
            ROLE_UNASSIGNED: '\u2190',
            ROLE_REASSIGNED: '\u21C4',
            PROTOCOL_APPROVED: '\u2714',
            PROTOCOL_REVERTED: '\u21A9',
            INVITE_SENT: '\u2709',
            INVITE_ACCEPTED: '\u2714',
            STEP_DEVIATION: '\u26A0',
        };
        return icons[eventType] || '\u2022';
    }

    onMount(() => {
        fetchUnreadCount();
        // Poll every 30 seconds
        pollInterval = setInterval(fetchUnreadCount, 30000);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });
</script>

<DropdownMenu.Root onOpenChange={(open) => { if (open) fetchNotifications(); }}>
    <DropdownMenu.Trigger>
        <Button
            variant="ghost"
            size="icon-sm"
            rounded="full"
            class="relative text-muted-foreground hover:text-foreground"
            aria-label="Notifications"
        >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>
                <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>
            </svg>
            {#if unreadCount > 0}
                <span
                    class="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold flex items-center justify-center leading-none"
                >
                    {unreadCount > 99 ? '99+' : unreadCount}
                </span>
            {/if}
        </Button>
    </DropdownMenu.Trigger>

    <DropdownMenu.Content align="end" class="w-80 max-w-[calc(100vw-2rem)] max-h-96 overflow-hidden bg-white z-[100]">
        <div class="flex items-center justify-between px-3 py-2 border-b border-border/60">
            <span class="text-sm font-semibold">Notifications</span>
            {#if unreadCount > 0}
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
                    <button
                        type="button"
                        class="w-full text-left px-3 py-2.5 hover:bg-accent/50 transition-colors duration-150 cursor-pointer border-b border-border/30 last:border-b-0 {notif.read_at ? 'opacity-60' : ''}"
                        onclick={() => { if (!notif.read_at) markRead(notif.id); }}
                    >
                        <div class="flex items-start gap-2">
                            <span class="text-xs mt-0.5 w-4 text-center shrink-0" title={notif.event_type}>
                                {eventIcon(notif.event_type)}
                            </span>
                            <div class="flex-1 min-w-0">
                                <div class="flex items-center gap-1.5">
                                    {#if !notif.read_at}
                                        <span class="w-1.5 h-1.5 rounded-full bg-primary shrink-0"></span>
                                    {/if}
                                    <p class="text-sm font-medium truncate">{notif.title}</p>
                                </div>
                                <p class="text-xs text-muted-foreground mt-0.5 line-clamp-2">{notif.message}</p>
                                <p class="text-[10px] text-muted-foreground/60 mt-1">{timeAgo(notif.created_at)}</p>
                            </div>
                        </div>
                    </button>
                {/each}
            {/if}
        </div>
    </DropdownMenu.Content>
</DropdownMenu.Root>
