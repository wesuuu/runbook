<script lang="ts">
import { Card, CardHeader, CardTitle, CardContent, CardFooter } from '$lib/components/ui/card';
import { Button } from '$lib/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '$lib/components/ui/dialog';
import { Textarea } from '$lib/components/ui/textarea';
import ExportSummaryButton from './ExportSummaryButton.svelte';
import { formatDate } from '$lib/components/project/projectUtils';
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
const hasUnsaved = $derived(!isLocked && draft !== (experiment.conclusion ?? ''));
const unlockReasonChars = $derived(unlockReason.trim().length);
const unlockSubmitDisabled = $derived(unlockReasonChars < 8);

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

            <Textarea class="min-h-[160px]"
                      bind:value={draft}
                      onblur={saveDraft}
                      placeholder="Write the conclusion of this investigation…" />
            <div class="mt-2 flex items-center justify-between text-sm">
                {#if lockReason}
                    <p class="text-muted-foreground" id="lock-reason">{lockReason}</p>
                {:else}
                    <span></span>
                {/if}
                {#if hasUnsaved}
                    <span class="text-amber-600" aria-live="polite">Unsaved changes</span>
                {/if}
            </div>
        {:else}
            <div class="prose whitespace-pre-wrap">{experiment.conclusion}</div>
            <div class="mt-3 text-sm text-muted-foreground italic"
                 title={new Date(experiment.conclusion_locked_at!).toLocaleString()}>
                Locked by {experiment.conclusion_locked_by_name ?? 'system'}
                {formatDate(experiment.conclusion_locked_at!)}
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
        <Textarea id="unlock-reason"
                  aria-label="Reason"
                  bind:value={unlockReason}
                  class="min-h-[100px]"
                  placeholder="e.g. Updated titer data from re-analysis" />
        <p class="text-xs text-muted-foreground text-right"
           class:text-amber-600={unlockReasonChars > 0 && unlockReasonChars < 8}
           aria-live="polite">
            {unlockReasonChars} / 8 characters
        </p>
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
