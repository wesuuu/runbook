<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { lockoutModal, dismissLockout } from '$lib/stores/lockoutModal.svelte';
    import { openPortal, subscription } from '$lib/stores/subscription.svelte';

    const open = $derived(lockoutModal.open);
</script>

<Dialog.Root {open} onOpenChange={(v) => { if (!v) dismissLockout(); }}>
    <Dialog.Content class="max-w-md">
        <Dialog.Header>
            <Dialog.Title>Subscription required</Dialog.Title>
            <Dialog.Description>{lockoutModal.message}</Dialog.Description>
        </Dialog.Header>
        <Dialog.Footer>
            <Button variant="outline" onclick={dismissLockout}>
                Dismiss and continue reading
            </Button>
            <Button disabled={subscription.portalLoading} onclick={() => openPortal()}>
                {#if subscription.portalLoading}
                    <span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
                    Opening portal…
                {:else}
                    Add payment method
                {/if}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
