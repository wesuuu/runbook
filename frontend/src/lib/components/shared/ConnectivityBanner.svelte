<script lang="ts">
    import { isOnline } from '$lib/pwa.svelte';

    const offline = $derived(!isOnline());
</script>

{#if offline}
    <div class="bg-amber-500 text-white px-4 py-2 text-center text-sm font-medium flex items-center justify-center gap-2 z-50">
        <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M18.364 5.636a9 9 0 010 12.728M5.636 18.364a9 9 0 010-12.728M8.464 15.536a5 5 0 010-7.072M15.536 8.464a5 5 0 010 7.072M12 12h.01" />
        </svg>
        You're offline — some features may be unavailable
    </div>
{/if}
