<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import { lockoutModal, dismissLockout } from '$lib/stores/lockoutModal.svelte';
    import { openPortal } from '$lib/stores/subscription.svelte';
</script>

{#if lockoutModal.open}
    <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        role="dialog"
        aria-modal="true"
    >
        <div class="bg-background rounded-lg shadow-xl max-w-md w-full p-6 space-y-4">
            <h2 class="text-lg font-semibold">Subscription required</h2>
            <p class="text-sm text-muted-foreground">{lockoutModal.message}</p>
            <div class="flex justify-end gap-2">
                <Button variant="outline" onclick={dismissLockout}>
                    Dismiss and continue reading
                </Button>
                <Button onclick={() => openPortal()}>Add payment method</Button>
            </div>
        </div>
    </div>
{/if}
