<script lang="ts">
    import { onMount } from 'svelte';
    import { fade } from 'svelte/transition';
    import { blockDuration } from '$lib/transitions';
    import { listSignoffRequests } from '$lib/api';
    import {
        Card,
        CardContent,
        CardHeader,
        CardTitle,
        CardDescription,
    } from '$lib/components/ui/card';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import ErrorAlert from '$lib/components/ui/error-alert.svelte';
    import ReviewQueueList from '$lib/components/reviews/ReviewQueueList.svelte';
    import type { SignoffRequestItem } from '$lib/schemas/signoffRequests';

    let items = $state<SignoffRequestItem[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);

    async function load() {
        loading = true;
        try {
            items = await listSignoffRequests();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            loading = false;
        }
    }

    onMount(load);
</script>

<div class="max-w-5xl mx-auto space-y-6">
    <div class="flex items-center justify-between">
        <h1 class="text-3xl font-bold tracking-tight">Reviews</h1>
    </div>

    {#if loading}
        <div in:fade={{ duration: blockDuration() }}>
            <LoadingSpinner message="Loading review queue..." />
        </div>
    {:else if error}
        <div in:fade={{ duration: blockDuration() }}>
            <ErrorAlert message="Error: {error}" />
        </div>
    {:else}
        <div in:fade={{ duration: blockDuration() }}>
            <Card>
                <CardHeader>
                    <CardTitle>Awaiting your review</CardTitle>
                    <CardDescription>
                        Completed runs and protocols waiting for your sign-off.
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <ReviewQueueList {items} />
                </CardContent>
            </Card>
        </div>
    {/if}
</div>
