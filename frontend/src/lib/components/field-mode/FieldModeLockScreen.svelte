<script lang="ts">
    import { getActiveRunName, getTimeRemaining, getQueueCount } from '$lib/field-mode.svelte';
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

    let {
        userEmail = '',
        onUnlock,
    }: {
        userEmail: string;
        onUnlock: (password: string) => Promise<boolean>;
    } = $props();

    let password = $state('');
    let error = $state<string | null>(null);
    let loading = $state(false);

    const runName = $derived(getActiveRunName());
    const timeRemaining = $derived(getTimeRemaining());
    const queueCount = $derived(getQueueCount());

    async function handleUnlock() {
        if (!password.trim()) {
            error = 'Password is required';
            return;
        }
        loading = true;
        error = null;
        const success = await onUnlock(password);
        if (!success) {
            error = 'Incorrect password';
            password = '';
        }
        loading = false;
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && !loading) handleUnlock();
    }
</script>

<Dialog.Root open={true}>
    <Dialog.Content
        class="w-screen h-screen max-w-none max-h-none rounded-none border-0 p-0 bg-slate-900 flex items-center justify-center"
        showCloseButton={false}
        escapeKeydownBehavior="ignore"
        interactOutsideBehavior="ignore"
    >
        <div class="w-[95%] max-w-sm text-center">
            <!-- Lock icon -->
            <div class="w-16 h-16 rounded-full bg-slate-800 border-2 border-slate-600 flex items-center justify-center mx-auto mb-6">
                <svg class="w-8 h-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
                </svg>
            </div>

            <Dialog.Title class="text-lg font-semibold text-white mb-1">Session Locked</Dialog.Title>
            <Dialog.Description class="text-sm text-slate-400 mb-1">{runName}</Dialog.Description>
            <p class="text-xs text-slate-500 mb-6">{timeRemaining}</p>

            <!-- User info -->
            <p class="text-xs text-slate-400 mb-3">{userEmail}</p>

            <!-- Password input -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="space-y-3" onkeydown={handleKeydown}>
                <input
                    type="password"
                    bind:value={password}
                    placeholder="Enter password to unlock"
                    disabled={loading}
                    class="w-full px-4 py-3 bg-slate-800 border border-slate-600 rounded-lg text-white text-center placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:opacity-50"
                />

                {#if error}
                    <p class="text-sm text-red-400">{error}</p>
                {/if}

                <Button
                    variant="default"
                    onclick={handleUnlock}
                    disabled={loading || !password.trim()}
                    class="w-full h-auto py-3 bg-teal-600 text-white rounded-lg font-medium hover:bg-teal-700"
                >
                    {loading ? 'Unlocking...' : 'Unlock'}
                </Button>
            </div>

            <!-- Queue status -->
            {#if queueCount > 0}
                <p class="mt-4 text-xs text-slate-500">
                    {queueCount} item{queueCount !== 1 ? 's' : ''} queued for sync
                </p>
            {/if}
        </div>
    </Dialog.Content>
</Dialog.Root>
