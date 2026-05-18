<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Textarea } from '$lib/components/ui/textarea';

    interface EditedStep {
        stepId: string;
        oldValue: unknown;
        newValue: unknown;
        label: string;
    }

    interface Props {
        open: boolean;
        editedSteps: EditedStep[];
        onConfirm: (reasons: Record<string, string>) => void | Promise<void>;
        onCancel: () => void;
    }

    let {
        open = $bindable(false),
        editedSteps,
        onConfirm,
        onCancel,
    }: Props = $props();

    let reasons = $state<Record<string, string>>({});
    let submitting = $state(false);
    let errorMessage = $state<string | null>(null);

    $effect(() => {
        // Reset reasons whenever the edited-steps list changes.
        const next: Record<string, string> = {};
        for (const step of editedSteps) {
            next[step.stepId] = reasons[step.stepId] ?? '';
        }
        reasons = next;
    });

    const allReasonsProvided = $derived(
        editedSteps.length > 0 &&
            editedSteps.every(
                (s) => (reasons[s.stepId] ?? '').trim().length > 0,
            ),
    );

    const canSubmit = $derived(allReasonsProvided && !submitting);

    function formatValue(value: unknown): string {
        if (value === null || value === undefined) return '—';
        if (typeof value === 'object') {
            try {
                return JSON.stringify(value);
            } catch {
                return String(value);
            }
        }
        return String(value);
    }

    async function handleConfirm(): Promise<void> {
        if (!canSubmit) return;
        submitting = true;
        errorMessage = null;
        try {
            const trimmed: Record<string, string> = {};
            for (const step of editedSteps) {
                trimmed[step.stepId] = (reasons[step.stepId] ?? '').trim();
            }
            await onConfirm(trimmed);
            open = false;
        } catch (e: unknown) {
            errorMessage =
                e instanceof Error ? e.message : 'Could not save edits.';
        } finally {
            submitting = false;
        }
    }

    function handleCancel(): void {
        onCancel();
        errorMessage = null;
        open = false;
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="max-w-[620px]">
        <Dialog.Header>
            <div class="flex items-center gap-2">
                <span
                    class="rounded px-2 py-0.5 text-[10px] font-semibold tracking-wide"
                    style="background:var(--primary);color:var(--primary-foreground)"
                >
                    EDIT REASON REQUIRED
                </span>
                <span class="font-mono text-[11px] text-muted-foreground">
                    21 CFR §11.10(e) · §58.130
                </span>
            </div>
            <Dialog.Title>Reason for each change</Dialog.Title>
            <Dialog.Description>
                A reason is required for every modified step. The audit trail
                will record the old value, new value, and reason.
            </Dialog.Description>
        </Dialog.Header>

        <div class="space-y-3 py-2 max-h-[420px] overflow-y-auto">
            {#each editedSteps as step (step.stepId)}
                <div class="rounded-md border border-border p-3">
                    <div class="mb-2 text-sm font-semibold">{step.label}</div>
                    <div class="mb-2 grid grid-cols-2 gap-2 text-xs">
                        <div>
                            <div class="text-muted-foreground">Old value</div>
                            <div class="font-mono break-all">
                                {formatValue(step.oldValue)}
                            </div>
                        </div>
                        <div>
                            <div class="text-muted-foreground">New value</div>
                            <div class="font-mono break-all">
                                {formatValue(step.newValue)}
                            </div>
                        </div>
                    </div>
                    <label
                        for={`edit-reason-${step.stepId}`}
                        class="mb-1 block text-xs font-medium"
                    >
                        Reason for change
                    </label>
                    <Textarea
                        id={`edit-reason-${step.stepId}`}
                        rows={2}
                        bind:value={reasons[step.stepId]}
                        placeholder="Why is this value being changed?"
                    />
                </div>
            {/each}
            {#if editedSteps.length === 0}
                <div class="text-sm text-muted-foreground">
                    No edits detected.
                </div>
            {/if}
            {#if errorMessage}
                <div class="text-xs text-destructive">{errorMessage}</div>
            {/if}
        </div>

        <Dialog.Footer>
            <Button variant="outline" onclick={handleCancel}>Cancel</Button>
            <Button onclick={handleConfirm} disabled={!canSubmit}>
                Save edits with reasons
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
