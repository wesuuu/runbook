<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import type { GlpRole, GlpSignoffResponse } from '$lib/schemas/glpSignoff';

    interface SignerRef {
        id: string;
        full_name: string;
        email: string;
    }

    interface Props {
        entityType: 'protocol' | 'run';
        entityId: string;
        requiredRoles: GlpRole[];
        signoffs: GlpSignoffResponse[];
        signers: Record<string, SignerRef>;
        currentUserId: string;
        attestationDefaults: Partial<Record<GlpRole, string>>;
        onSignClick: (role: GlpRole, defaultAttestation: string) => void;
    }

    let {
        entityType,
        entityId,
        requiredRoles,
        signoffs,
        signers,
        currentUserId,
        attestationDefaults,
        onSignClick,
    }: Props = $props();

    function cfrCiteFor(role: GlpRole): string {
        if (role === 'QAU') return '§58.35';
        if (role === 'STUDY_DIRECTOR') return '§58.33';
        if (role === 'OPERATOR') return '§58.29';
        return '§58.10';
    }

    function activeSignoffFor(role: GlpRole): GlpSignoffResponse | undefined {
        return signoffs.find(
            (s) =>
                s.role === role &&
                s.action === 'APPROVED' &&
                (s.invalidated_at === null || s.invalidated_at === undefined),
        );
    }

    function signerNameFor(signerId: string): string {
        return signers[signerId]?.full_name ?? signerId;
    }

    function signerEmailFor(signerId: string): string | null {
        return signers[signerId]?.email ?? null;
    }
</script>

<div class="divide-y divide-border rounded-md border border-border overflow-hidden">
    {#each requiredRoles as role (role)}
        {@const active = activeSignoffFor(role)}
        {@const isSigned = active !== undefined}
        <div
            class="grid grid-cols-[120px_1fr_180px_140px] items-center gap-4 px-4 py-3"
            class:bg-accent-tint={isSigned}
            data-role={role}
            data-entity-type={entityType}
            data-entity-id={entityId}
            style={isSigned
                ? 'background:color-mix(in srgb, var(--accent) 6%, transparent)'
                : ''}
        >
            <div>
                <div class="font-mono text-[10px] text-muted-foreground">
                    {cfrCiteFor(role)}
                </div>
                <div class="text-sm font-semibold">{role}</div>
            </div>

            {#if active}
                <div class="min-w-0">
                    <div class="text-sm truncate">
                        <span>{signerNameFor(active.signer_id)}</span>
                        {#if signerEmailFor(active.signer_id)}
                            <span class="text-muted-foreground">
                                · {signerEmailFor(active.signer_id)}
                            </span>
                        {/if}
                    </div>
                    {#if active.attestation}
                        <div
                            class="text-xs text-muted-foreground italic mt-0.5 truncate"
                        >
                            "{active.attestation}"
                        </div>
                    {/if}
                </div>
                <div class="min-w-0">
                    {#if active.signature_image_path}
                        <img
                            src={active.signature_image_path}
                            alt="Signature"
                            class="h-10 object-contain"
                        />
                    {:else}
                        <span class="text-xs text-muted-foreground">—</span>
                    {/if}
                </div>
                <div class="text-right">
                    <span
                        class="inline-block rounded px-2 py-0.5 text-[10px] font-semibold"
                        style="background:color-mix(in srgb,var(--accent) 20%,transparent);color:var(--accent-foreground,inherit)"
                    >
                        Signed
                    </span>
                    <div class="font-mono text-[10px] text-muted-foreground mt-1">
                        {active.signed_at}
                    </div>
                </div>
            {:else}
                <div>
                    <div class="text-sm text-muted-foreground">
                        Required by GLP Settings
                    </div>
                </div>
                <div class="text-xs text-muted-foreground">—</div>
                <div class="text-right">
                    <Button
                        size="sm"
                        onclick={() =>
                            onSignClick(
                                role,
                                attestationDefaults[role] ?? '',
                            )}
                    >
                        Sign as {role}
                    </Button>
                </div>
            {/if}
        </div>
    {/each}
</div>
