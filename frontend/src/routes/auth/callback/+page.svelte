<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { handleOAuthCallback } from '$lib/auth.svelte';
    import { onMount } from 'svelte';
    import { fade } from 'svelte/transition';

    let error = $state<string | null>(null);
    let loading = $state(true);

    onMount(async () => {
        const { pathname, searchParams } = $page.url;

        const provider = pathname.includes('google') ? 'google' : 'microsoft';
        const code = searchParams.get('code');
        const state = searchParams.get('state');
        const oauthError = searchParams.get('error');
        const errorDescription = searchParams.get('error_description');

        if (oauthError) {
            error = `OAuth error: ${oauthError}${errorDescription ? ` - ${errorDescription}` : ''}`;
            loading = false;
            return;
        }

        if (!code || !state) {
            error = 'Missing authorization code or state';
            loading = false;
            return;
        }

        try {
            await handleOAuthCallback(provider, code, state);
            goto('/');
        } catch (err: unknown) {
            error = err instanceof Error ? err.message : 'OAuth callback failed';
        } finally {
            loading = false;
        }
    });
</script>

<div class="min-h-screen flex items-center justify-center bg-background">
    <div class="flex flex-col items-center space-y-6">
        {#if loading}
            <div in:fade>
                <div class="flex flex-col items-center space-y-4">
                    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
                    <p class="text-muted-foreground">Completing sign in...</p>
                </div>
            </div>
        {:else if error}
            <div in:fade class="flex flex-col items-center space-y-4 max-w-sm">
                <div class="text-red-500">
                    <svg class="w-12 h-12" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
                    </svg>
                </div>
                <p class="text-sm text-red-500 font-medium text-center">{error}</p>
                <a href="/login" class="text-primary font-semibold hover:underline">
                    Back to login
                </a>
            </div>
        {/if}
    </div>
</div>
