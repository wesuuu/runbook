<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { page } from '$app/stores';
    import { listSignoffRequests } from '$lib/api';
    import { isAuthenticated } from '$lib/auth.svelte';

    let count = $state(0);
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    const isActive = $derived(($page?.url?.pathname ?? '').startsWith('/reviews'));

    async function fetchCount() {
        if (!isAuthenticated()) return;
        try {
            const items = await listSignoffRequests();
            count = items.length;
        } catch {
            // Silent — poll retries.
        }
    }

    onMount(() => {
        fetchCount();
        pollInterval = setInterval(fetchCount, 30000);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });
</script>

<a
    href="/reviews"
    class="hidden md:flex items-center gap-1.5 relative py-1 transition-colors {isActive
        ? 'nav-active'
        : 'text-muted-foreground hover:text-foreground'}"
>
    Reviews
    {#if count > 0}
        <span
            class="min-w-[18px] h-[18px] px-1 rounded-full bg-accent text-accent-foreground text-[10px] font-bold flex items-center justify-center leading-none"
        >
            {count > 99 ? '99+' : count}
        </span>
    {/if}
</a>
