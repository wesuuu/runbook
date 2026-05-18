<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Textarea } from '$lib/components/ui/textarea';
    import type { GlpSignoffResponse } from '$lib/schemas/glpSignoff';

    interface Props {
        open: boolean;
        runId: string;
        activeSignoffs: GlpSignoffResponse[];
        onConfirm: (reason: string) => void | Promise<void>;
        onCancel: () => void;
    }

    let {
        open = $bindable(false),
        runId,
        activeSignoffs,
        onConfirm,
        onCancel,
    }: Props = $props();

    let reason = $state('');
    let submitting = $state(false);
    let errorMessage = $state<string | null>(null);

    const canSubmit = $derived(reason.trim().length > 0 && !submitting);

    function signerLabel(signoff: GlpSignoffResponse): string {
        if (signoff.signer?.name) return signoff.signer.name;
        if (signoff.signer?.email) return signoff.signer.email;
        return signoff.signer_id;
    }

    async function handleConfirm(): Promise<void> {
        if (!canSubmit) return;
        submitting = true;
        errorMessage = null;
        try {
            await onConfirm(reason.trim());
            reason = '';
            open = false;
        } catch (e: unknown) {
            errorMessage =
                e instanceof Error ? e.message : 'Reopen failed.';
        } finally {
            submitting = false;
        }
    }

    function handleCancel(): void {
        onCancel();
        reason = '';
        errorMessage = null;
        open = false;
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="max-w-[540px]" data-run-id={runId}>
        <Dialog.Header>
            <div class="flex items-center gap-2">
                <span
                    class="rounded px-2 py-0.5 text-[10px] font-semibold tracking-wide"
                    style="background:var(--destructive);color:var(--destructive-foreground,white)"
                >
                    REOPEN RUN
                </span>
                <span class="font-mono text-[11px] text-muted-foreground">
                    21 CFR §11.10(e)
                </span>
            </div>
            <Dialog.Title>Reopen completed run</Dialog.Title>
            <Dialog.Description>
                Reopening will invalidate every active sign-off. Signers will
                need to re-sign after the changes are made.
            </Dialog.Description>
        </Dialog.Header>

        {#if activeSignoffs.length > 0}
            <div
                class="rounded-md p-3 text-xs"
                style="background:color-mix(in srgb,var(--destructive) 10%,transparent);
                       border:1px solid color-mix(in srgb,var(--destructive) 30%,transparent)"
            >
                <div class="mb-1 font-semibold text-destructive">
                    The following sign-offs will be invalidated:
                </div>
                <ul class="space-y-1">
                    {#each activeSignoffs as s (s.id)}
                        <li class="flex items-baseline justify-between gap-2">
                            <span class="font-medium">{s.role}</span>
                            <span class="text-muted-foreground">
                                {signerLabel(s)}
                            </span>
                            <span
                                class="font-mono text-[10px] text-muted-foreground"
                            >
                                {s.signed_at}
                            </span>
                        </li>
                    {/each}
                </ul>
            </div>
        {/if}

        <div class="space-y-3 py-2">
            <div>
                <label
                    for="run-reopen-reason"
                    class="mb-1 block text-sm font-medium"
                >
                    Reason for reopening
                </label>
                <Textarea
                    id="run-reopen-reason"
                    rows={3}
                    bind:value={reason}
                    placeholder="Explain why this run must be reopened."
                />
            </div>
            {#if errorMessage}
                <div class="text-xs text-destructive">{errorMessage}</div>
            {/if}
        </div>

        <Dialog.Footer>
            <Button variant="outline" onclick={handleCancel}>Cancel</Button>
            <Button
                variant="destructive"
                onclick={handleConfirm}
                disabled={!canSubmit}
            >
                Reopen and invalidate sign-offs
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
