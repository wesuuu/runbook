<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '$lib/components/ui/card';
import { Button } from '$lib/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '$lib/components/ui/dialog';
import ExportSummaryButton from './ExportSummaryButton.svelte';
import type { Experiment } from '$lib/schemas/experiments';

interface Props {
    experiment: Experiment;
    hasOpenRuns: boolean;
    canAdmin: boolean;
    onSave: (next: string) => void;
    onLock: () => void;
    onUnlock: (reason: string) => void;
}
let { experiment, hasOpenRuns, canAdmin, onSave, onLock, onUnlock }: Props = $props();

let draft = $state(experiment.conclusion ?? '');
let unlockOpen = $state(false);
let unlockReason = $state('');

const isLocked = $derived(experiment.conclusion_locked_at != null);
const lockDisabled = $derived(hasOpenRuns || draft.trim().length === 0);
const lockReason = $derived(
    hasOpenRuns
        ? 'Cannot lock — runs are still open.'
        : draft.trim().length === 0
        ? 'Cannot lock — conclusion is empty.'
        : ''
);
const unlockSubmitDisabled = $derived(unlockReason.trim().length < 8);

function saveDraft() {
    if (draft !== (experiment.conclusion ?? '')) onSave(draft);
}
function submitUnlock() {
    onUnlock(unlockReason.trim());
    unlockOpen = false;
    unlockReason = '';
}
</script>

<Card>
    <CardHeader>
        <CardTitle>Conclusion</CardTitle>
    </CardHeader>
    <CardContent>
        {#if !isLocked}
            {#if hasOpenRuns}
                <div class="warning mb-3">
                    <strong>Completion gate.</strong> Finish all runs before locking the conclusion.
                </div>
            {/if}

            <textarea class="w-full min-h-[160px] border rounded p-2"
                      bind:value={draft}
                      onblur={saveDraft}
                      placeholder="Write the conclusion of this investigation…"></textarea>
            {#if lockReason}
                <p class="mt-2 text-sm text-muted-foreground" id="lock-reason">{lockReason}</p>
            {/if}
        {:else}
            <div class="prose whitespace-pre-wrap">{experiment.conclusion}</div>
            <div class="mt-3 text-sm text-muted-foreground italic">
                Locked by {experiment.conclusion_locked_by_name ?? 'system'}
                on {new Date(experiment.conclusion_locked_at!).toLocaleString()}
            </div>
        {/if}
    </CardContent>

    <CardFooter class="flex items-center justify-between">
        <ExportSummaryButton experimentId={experiment.id} slug={(experiment as any).slug ?? experiment.id} />

        {#if !isLocked}
            <Button variant="default"
                    disabled={lockDisabled}
                    title={lockReason}
                    aria-describedby={lockReason ? 'lock-reason' : undefined}
                    onclick={onLock}>
                Lock conclusion
            </Button>
        {:else if canAdmin}
            <Button variant="outline" onclick={() => unlockOpen = true}>
                Unlock and edit (admin only)
            </Button>
        {/if}
    </CardFooter>
</Card>

<Dialog bind:open={unlockOpen}>
    <DialogContent>
        <DialogHeader>
            <DialogTitle>Unlock conclusion</DialogTitle>
        </DialogHeader>
        <label for="unlock-reason" class="text-sm">
            Reason (required, &ge; 8 characters)
        </label>
        <textarea id="unlock-reason"
                  aria-label="Reason"
                  bind:value={unlockReason}
                  class="w-full border rounded p-2 min-h-[100px]"
                  placeholder="e.g. Updated titer data from re-analysis"></textarea>
        <DialogFooter>
            <Button variant="outline"
                    onclick={() => { unlockOpen = false; unlockReason = ''; }}>
                Cancel
            </Button>
            <Button variant="default"
                    aria-label="Submit unlock"
                    disabled={unlockSubmitDisabled}
                    onclick={submitUnlock}>
                Submit unlock
            </Button>
        </DialogFooter>
    </DialogContent>
</Dialog>

<style>
.warning {
    background: color-mix(in oklch, oklch(0.85 0.18 80) 30%, transparent);
    border: 1px solid oklch(0.7 0.18 80);
    padding: 0.75rem; border-radius: 0.5rem;
}
</style>
