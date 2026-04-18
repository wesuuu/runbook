<script lang="ts">
    import { api } from '$lib/api';
    import { getUser } from '$lib/auth.svelte';
    import { activateFieldMode, type RunSnapshot } from '$lib/field-mode.svelte';
    import { goto } from '$app/navigation';
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

    let {
        open = $bindable(false),
        runId,
        runName,
    }: {
        open: boolean;
        runId: string;
        runName: string;
    } = $props();

    let password = $state('');
    let loading = $state(false);
    let error = $state<string | null>(null);
    let step = $state<'password' | 'prefetching'>('password');

    async function handleSubmit() {
        if (!password.trim()) {
            error = 'Password is required';
            return;
        }

        loading = true;
        error = null;

        try {
            // Step 1: Create offline session (validates password server-side)
            step = 'password';
            const session = await api.post<{
                offline_token: string;
                expires_at: string;
                run_id: string;
            }>('/auth/offline-session', {
                run_id: runId,
                password,
            });

            // Step 2: Prefetch run data
            step = 'prefetching';
            const snapshot = await api.get<RunSnapshot>(
                `/offline/runs/${runId}/prefetch`,
            );

            // Step 3: Activate field mode (encrypt + store in IndexedDB)
            const user = getUser();
            await activateFieldMode(
                password,
                snapshot,
                session.offline_token,
                session.expires_at,
                user?.id ?? '',
                user?.email ?? '',
            );

            // Navigate to field mode
            open = false;
            password = '';
            goto('/field');
        } catch (e: unknown) {
            if (e instanceof Error) {
                error = e.message;
            } else {
                error = 'Failed to create offline session';
            }
        } finally {
            loading = false;
        }
    }

    function handleClose() {
        if (loading) return;
        open = false;
        password = '';
        error = null;
        step = 'password';
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && !loading) handleSubmit();
    }

    function handleOpenChange(value: boolean) {
        if (!value) handleClose();
    }
</script>

<Dialog.Root bind:open onOpenChange={handleOpenChange}>
    <Dialog.Content class="sm:max-w-md p-0">
        <!-- Header -->
        <div class="px-6 py-5 border-b border-border">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg bg-amber-100 flex items-center justify-center">
                    <svg class="w-5 h-5 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z" />
                    </svg>
                </div>
                <div>
                    <h3 class="text-lg font-semibold text-foreground">Enter Field Mode</h3>
                    <p class="text-sm text-muted-foreground">Work offline on "{runName}"</p>
                </div>
            </div>
        </div>

        <!-- Body -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="px-6 py-5" onkeydown={handleKeydown}>
            {#if step === 'prefetching'}
                <div class="flex flex-col items-center py-4 gap-3">
                    <div class="w-8 h-8 border-2 border-teal-600 border-t-transparent rounded-full animate-spin"></div>
                    <p class="text-sm text-muted-foreground">Downloading run data for offline use...</p>
                    <p class="text-xs text-muted-foreground/60">This includes the protocol, role assignments, and step definitions.</p>
                </div>
            {:else}
                <p class="text-sm text-muted-foreground mb-4">
                    Confirm your password to create an encrypted offline session. Your session will be valid for 7 days.
                </p>

                <div class="space-y-4">
                    <div>
                        <label for="offline-password" class="block text-sm font-medium text-foreground/80 mb-1">
                            Password
                        </label>
                        <input
                            id="offline-password"
                            type="password"
                            bind:value={password}
                            placeholder="Enter your password"
                            disabled={loading}
                            class="w-full px-4 py-3 border border-border rounded-lg text-base focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-50"
                        />
                    </div>

                    {#if error}
                        <div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                            {error}
                        </div>
                    {/if}

                    <div class="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
                        <p class="font-medium mb-1">What happens next:</p>
                        <ul class="list-disc list-inside text-xs space-y-1 text-amber-700">
                            <li>Run data is downloaded and encrypted locally</li>
                            <li>You can capture images and enter values offline</li>
                            <li>Data syncs automatically when you reconnect</li>
                            <li>Session auto-locks after 1 hour of inactivity</li>
                        </ul>
                    </div>
                </div>
            {/if}
        </div>

        <!-- Footer -->
        <div class="px-6 py-4 border-t border-border flex gap-3">
            <Button
                variant="outline"
                class="flex-1"
                onclick={handleClose}
                disabled={loading}
            >
                Cancel
            </Button>
            <Button
                class="flex-1 bg-amber-600 hover:bg-amber-700 text-white"
                onclick={handleSubmit}
                disabled={loading || !password.trim()}
            >
                {#if loading}
                    {step === 'prefetching' ? 'Downloading...' : 'Verifying...'}
                {:else}
                    Go Offline
                {/if}
            </Button>
        </div>
    </Dialog.Content>
</Dialog.Root>
