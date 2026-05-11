<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Textarea } from '$lib/components/ui/textarea';
    import { approveProtocol, rejectProtocol } from '$lib/api';
    import { getUser, getToken } from '$lib/auth.svelte';
    import { API_BASE } from '$lib/config';
    import type { Protocol } from '$lib/schemas/protocols';

    interface Props {
        open: boolean;
        mode: 'approve' | 'reject';
        protocolId: string;
        onSuccess?: (protocol: Protocol) => void;
        onCancel?: () => void;
    }

    let {
        open = $bindable(false),
        mode,
        protocolId,
        onSuccess,
        onCancel,
    }: Props = $props();

    let comment = $state('');
    let signatureStatement = $state('');
    let submitting = $state(false);
    let errorMessage = $state<string | null>(null);

    const user = $derived(getUser());

    const signatureUrl = $derived.by(() => {
        const u = user;
        if (!u) return null;
        const path = u.signature_full_url;
        return path ? `${API_BASE}${path}?token=${getToken()}` : null;
    });

    const cursiveName = $derived(user?.full_name ?? user?.email ?? '');

    const isReject = $derived(mode === 'reject');
    const submitDisabled = $derived(
        submitting || (isReject && comment.trim().length === 0),
    );

    const title = $derived(isReject ? 'Reject Protocol' : 'Approve Protocol');
    const confirmLabel = $derived(isReject ? 'Reject' : 'Approve');

    function reset() {
        comment = '';
        signatureStatement = '';
        errorMessage = null;
        submitting = false;
    }

    function handleCancel() {
        reset();
        open = false;
        onCancel?.();
    }

    async function handleConfirm() {
        if (submitDisabled) return;
        submitting = true;
        errorMessage = null;
        try {
            const trimmedComment = comment.trim();
            const trimmedStatement = signatureStatement.trim();
            let result: Protocol;
            if (isReject) {
                result = await rejectProtocol(protocolId, {
                    comment: trimmedComment,
                    signature_statement: trimmedStatement || undefined,
                });
            } else {
                result = await approveProtocol(protocolId, {
                    signature_statement: trimmedStatement || undefined,
                });
            }
            reset();
            open = false;
            onSuccess?.(result);
        } catch (e: unknown) {
            errorMessage = e instanceof Error ? e.message : 'Failed to submit.';
            submitting = false;
        }
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Description>
                {#if isReject}
                    Reject this protocol and send it back to draft. A comment is required.
                {:else}
                    Approve this protocol so runs can be created from it.
                {/if}
            </Dialog.Description>
        </Dialog.Header>

        <div class="space-y-4">
            {#if isReject}
                <div>
                    <label for="approval-comment" class="block text-sm font-medium mb-1">
                        Comment <span class="text-destructive">*</span>
                    </label>
                    <Textarea
                        id="approval-comment"
                        bind:value={comment}
                        rows={3}
                        placeholder="Explain what needs to change…"
                    />
                </div>
            {/if}

            <div>
                <label for="approval-statement" class="block text-sm font-medium mb-1">
                    Signature statement
                    <span class="text-muted-foreground font-normal">(optional)</span>
                </label>
                <Textarea
                    id="approval-statement"
                    bind:value={signatureStatement}
                    rows={2}
                    placeholder="e.g. I have reviewed this protocol and confirm it is correct."
                />
            </div>

            <div>
                <p class="block text-sm font-medium mb-1">Signature</p>
                {#if signatureUrl}
                    <img
                        src={signatureUrl}
                        alt="Your signature"
                        data-testid="approval-signature-preview"
                        class="h-16 w-56 object-contain border border-dashed border-border rounded-md bg-background"
                    />
                {:else}
                    <div
                        data-testid="approval-signature-preview"
                        class="signature-cursive h-16 w-56 flex items-center justify-center border border-dashed border-border rounded-md bg-background text-2xl"
                    >
                        {cursiveName}
                    </div>
                {/if}
                <p class="text-xs text-muted-foreground mt-1">
                    {signatureUrl
                        ? 'Using saved signature.'
                        : 'No saved signature — using cursive name.'}
                </p>
            </div>

            {#if errorMessage}
                <p class="text-sm text-destructive">{errorMessage}</p>
            {/if}
        </div>

        <Dialog.Footer>
            <Button variant="secondary" onclick={handleCancel} disabled={submitting}>
                Cancel
            </Button>
            <Button
                variant={isReject ? 'destructive' : 'default'}
                onclick={handleConfirm}
                disabled={submitDisabled}
            >
                {submitting ? '…' : confirmLabel}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<style>
    .signature-cursive {
        font-family: 'Brush Script MT', 'Lucida Handwriting', cursive;
    }
</style>
