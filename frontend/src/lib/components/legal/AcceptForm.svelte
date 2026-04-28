<script lang="ts">
    import { Button } from '$lib/components/ui/button';

    interface Props {
        onAccept: () => Promise<void>;
    }

    let { onAccept }: Props = $props();

    let agreedTerms = $state(false);
    let agreedPrivacy = $state(false);
    let submitting = $state(false);
    let error = $state<string | null>(null);

    const canAccept = $derived(agreedTerms && agreedPrivacy && !submitting);

    async function handleAccept() {
        if (!canAccept) return;
        error = null;
        submitting = true;
        try {
            await onAccept();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to record acceptance';
        } finally {
            submitting = false;
        }
    }
</script>

<form
    class="accept-form space-y-4"
    onsubmit={(e) => {
        e.preventDefault();
        handleAccept();
    }}
>
    <label class="flex items-start gap-3 cursor-pointer text-sm leading-relaxed">
        <input
            type="checkbox"
            class="mt-0.5 h-4 w-4 rounded border-border text-primary focus:ring-2 focus:ring-primary cursor-pointer"
            bind:checked={agreedTerms}
            aria-label="Terms of Service"
        />
        <span>
            I have read and agree to the <span class="font-semibold">Terms of Service above</span>.
        </span>
    </label>
    <label class="flex items-start gap-3 cursor-pointer text-sm leading-relaxed">
        <input
            type="checkbox"
            class="mt-0.5 h-4 w-4 rounded border-border text-primary focus:ring-2 focus:ring-primary cursor-pointer"
            bind:checked={agreedPrivacy}
            aria-label="Privacy Policy"
        />
        <span>
            I have read and agree to the <span class="font-semibold">Privacy Policy above</span>.
        </span>
    </label>
    {#if error}
        <p class="text-sm text-destructive">{error}</p>
    {/if}
    <Button type="submit" disabled={!canAccept} class="cursor-pointer">
        {submitting ? 'Recording…' : 'Accept and continue'}
    </Button>
</form>
