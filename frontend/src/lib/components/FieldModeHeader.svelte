<script lang="ts">
    import {
        getActiveRunName,
        getQueueCount,
        getTimeRemaining,
        getExpiryWarningLevel,
        type ExpiryWarningLevel,
    } from '$lib/field-mode.svelte';

    let {
        onEndFieldMode,
        onLock,
    }: {
        onEndFieldMode: () => void;
        onLock: () => void;
    } = $props();

    const runName = $derived(getActiveRunName());
    const queueCount = $derived(getQueueCount());
    const timeRemaining = $derived(getTimeRemaining());
    const warningLevel = $derived(getExpiryWarningLevel());

    function getWarningColor(level: ExpiryWarningLevel): string {
        switch (level) {
            case 'critical': return 'bg-red-600 text-white';
            case 'red': return 'bg-red-500 text-white';
            case 'amber': return 'bg-amber-500 text-white';
            default: return 'bg-slate-800 text-white';
        }
    }
</script>

<nav class="sticky top-0 z-50 {getWarningColor(warningLevel)} px-4 py-3 flex items-center justify-between shadow-lg">
    <div class="flex items-center gap-3">
        <div class="w-7 h-7 bg-white/20 rounded-md flex items-center justify-center">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z" />
            </svg>
        </div>
        <div>
            <p class="text-sm font-semibold leading-tight">Field Mode</p>
            <p class="text-xs opacity-80 leading-tight">{runName}</p>
        </div>
    </div>

    <div class="flex items-center gap-3">
        <!-- Queue counter -->
        <div class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/20 text-xs font-medium">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
            </svg>
            {queueCount} queued
        </div>

        <!-- Expiry -->
        <span class="text-xs opacity-80 hidden sm:inline">{timeRemaining}</span>

        <!-- Lock button -->
        <button
            onclick={onLock}
            class="p-1.5 rounded-lg bg-white/10 hover:bg-white/20 transition-colors"
            title="Lock session"
        >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
            </svg>
        </button>

        <!-- End Field Mode -->
        <button
            onclick={onEndFieldMode}
            class="px-3 py-1.5 text-xs font-medium rounded-lg bg-white/20 hover:bg-white/30 transition-colors"
        >
            End
        </button>
    </div>
</nav>
