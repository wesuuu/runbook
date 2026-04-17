<script lang="ts">
    import { getExpiryWarningLevel, getTimeRemaining, type ExpiryWarningLevel } from '$lib/field-mode.svelte';
    import * as Dialog from '$lib/components/ui/dialog';

    const warningLevel = $derived(getExpiryWarningLevel());
    const timeRemaining = $derived(getTimeRemaining());

    let dismissed = $state(false);

    function getStyles(level: ExpiryWarningLevel): { bg: string; text: string; icon: string } {
        switch (level) {
            case 'critical':
                return { bg: 'bg-red-600', text: 'text-white', icon: 'text-red-200' };
            case 'red':
                return { bg: 'bg-red-500', text: 'text-white', icon: 'text-red-200' };
            case 'amber':
                return { bg: 'bg-amber-500', text: 'text-white', icon: 'text-amber-200' };
            default:
                return { bg: '', text: '', icon: '' };
        }
    }
</script>

{#if warningLevel === 'critical' && !dismissed}
    <!-- Full-screen modal for critical (<1h) -->
    <Dialog.Root open={true}>
        <Dialog.Content
            class="max-w-sm text-center p-8 bg-white rounded-xl shadow-2xl"
            showCloseButton={false}
            escapeKeydownBehavior="ignore"
            interactOutsideBehavior="ignore"
        >
            <div class="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-4">
                <svg class="w-8 h-8 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
            </div>
            <Dialog.Title class="text-lg font-bold text-slate-900 mb-2">Session Expiring Soon</Dialog.Title>
            <Dialog.Description class="text-sm text-slate-600 mb-2">{timeRemaining}</Dialog.Description>
            <p class="text-sm text-slate-500 mb-6">
                Your offline session is about to expire. Connect to the internet and sync your data now to avoid losing queued items.
            </p>
            <button
                onclick={() => (dismissed = true)}
                class="px-6 py-2.5 bg-red-600 text-white rounded-lg font-medium hover:bg-red-700 transition-colors cursor-pointer"
            >
                I Understand
            </button>
        </Dialog.Content>
    </Dialog.Root>
{:else if (warningLevel === 'amber' || warningLevel === 'red') && !dismissed}
    {@const styles = getStyles(warningLevel)}
    <div class="{styles.bg} {styles.text} px-4 py-2 text-center text-sm font-medium flex items-center justify-center gap-2">
        <svg class="w-4 h-4 {styles.icon}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>Session expires in {timeRemaining}. Sync your data soon.</span>
        <button onclick={() => (dismissed = true)} class="ml-2 opacity-70 hover:opacity-100">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
        </button>
    </div>
{/if}
