<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import * as Tooltip from '$lib/components/ui/tooltip';
    import { Button } from '$lib/components/ui/button';
    import { Textarea } from '$lib/components/ui/textarea';
    import { API_BASE } from '$lib/config';
    import { getToken } from '$lib/auth.svelte';
    import type { GlpRole } from '$lib/schemas/glpSignoff';

    interface Props {
        open: boolean;
        role: GlpRole;
        entityType: 'protocol' | 'run';
        entityId: string;
        defaultAttestation: string;
        signerName: string;
        signatureImageUrl: string | null;
        independenceMessage?: string;
        onConfirm: (attestation: string) => void | Promise<void>;
        onCancel: () => void;
    }

    let {
        open = $bindable(false),
        role,
        entityType,
        entityId,
        defaultAttestation,
        signerName,
        signatureImageUrl,
        independenceMessage,
        onConfirm,
        onCancel,
    }: Props = $props();

    let attestation = $state('');
    let submitting = $state(false);
    let errorMessage = $state<string | null>(null);

    // The modal stays mounted and is reused — `open` and the role's default
    // attestation are only set when a sign-off is requested. Sync the editable
    // attestation from the default each time the modal opens so the chosen
    // role's text is pre-filled (a bare `$state(defaultAttestation)` would
    // keep the empty value captured at first mount).
    $effect(() => {
        if (open) {
            attestation = defaultAttestation;
            errorMessage = null;
        }
    });
    const canSubmit = $derived(attestation.trim().length > 0 && !submitting);

    // When the signer has no uploaded signature, the backend generates a
    // cursive image from their name so sign-off still works. Preview that
    // generated image here (loaded via an <img>, so the token rides as a
    // query param). create_signoff pins its own copy at sign time.
    const defaultSignatureUrl = $derived.by(() => {
        const token = getToken();
        const qs = token ? `?token=${encodeURIComponent(token)}` : '';
        return `${API_BASE}/auth/me/default-signature${qs}`;
    });
    const cfrCite = $derived(
        role === 'QAU'
            ? '§58.35'
            : role === 'STUDY_DIRECTOR'
              ? '§58.33'
              : role === 'OPERATOR'
                ? '§58.29'
                : '§58.10',
    );

    async function handleConfirm() {
        if (!canSubmit) return;
        submitting = true;
        errorMessage = null;
        try {
            await onConfirm(attestation.trim());
            open = false;
        } catch (e: unknown) {
            errorMessage = e instanceof Error ? e.message : 'Sign-off failed.';
        } finally {
            submitting = false;
        }
    }

    function handleCancel() {
        onCancel();
        open = false;
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="max-w-[540px]">
        <Dialog.Header>
            <div class="flex items-center gap-2">
                <span
                    class="rounded px-2 py-0.5 text-[10px] font-semibold tracking-wide"
                    style="background:var(--primary);color:var(--primary-foreground)"
                >
                    {role} SIGN-OFF
                </span>
                <span class="font-mono text-[11px] text-muted-foreground">
                    21 CFR {cfrCite} · §11.50
                </span>
            </div>
            <Dialog.Title>Sign {entityType} as {role}</Dialog.Title>
            <Dialog.Description>
                Your saved signature image will be copied to this record at sign
                time and cannot be retroactively replaced.
            </Dialog.Description>
        </Dialog.Header>

        {#if independenceMessage}
            <div
                class="rounded-md p-3 text-xs"
                style="background:color-mix(in srgb,var(--accent) 10%,transparent);
                       border:1px solid color-mix(in srgb,var(--accent) 30%,transparent)"
            >
                {independenceMessage}
            </div>
        {/if}

        <div class="space-y-3 py-2">
            <div>
                <label for="signoff-attestation" class="text-sm font-medium">
                    Attestation
                </label>
                <Textarea
                    id="signoff-attestation"
                    rows={3}
                    bind:value={attestation}
                />
            </div>
            <div>
                <div
                    class="mb-1 flex items-center justify-between text-xs text-muted-foreground"
                >
                    <span>Signature</span>
                    <span class="font-mono text-[10px]">
                        snapshot at sign time
                    </span>
                </div>
                <div
                    class="flex items-center justify-between rounded-md border border-border bg-muted px-4 py-3"
                >
                    {#if signatureImageUrl}
                        <img
                            src={signatureImageUrl}
                            alt="Signature"
                            class="h-10"
                        />
                    {:else}
                        <Tooltip.Provider delayDuration={150}>
                            <Tooltip.Root>
                                <Tooltip.Trigger class="cursor-help">
                                    <img
                                        src={defaultSignatureUrl}
                                        alt="Auto-generated signature"
                                        class="h-10"
                                    />
                                </Tooltip.Trigger>
                                <Tooltip.Content class="max-w-xs text-left">
                                    This signature was generated from your name
                                    so you can sign off right away. Upload your
                                    own in Settings → Profile to replace it.
                                </Tooltip.Content>
                            </Tooltip.Root>
                        </Tooltip.Provider>
                    {/if}
                    <span class="text-sm font-medium">{signerName}</span>
                </div>
                {#if !signatureImageUrl}
                    <p class="mt-1 text-[11px] text-muted-foreground">
                        Default signature generated from your name —
                        <a
                            href="/settings?tab=profile"
                            class="underline transition-colors hover:text-foreground"
                        >
                            set your own
                        </a>.
                    </p>
                {/if}
            </div>
            {#if errorMessage}
                <div class="text-xs text-destructive">{errorMessage}</div>
            {/if}
        </div>

        <Dialog.Footer>
            <Button variant="outline" onclick={handleCancel}>Cancel</Button>
            <Button onclick={handleConfirm} disabled={!canSubmit}>
                Confirm sign-off
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
