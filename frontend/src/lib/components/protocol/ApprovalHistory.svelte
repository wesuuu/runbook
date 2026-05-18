<script lang="ts">
    import { getProtocolSignoffs } from '$lib/api';
    import type { GlpSignoffResponse } from '$lib/schemas/glpSignoff';

    interface Props {
        protocolId: string;
    }

    let { protocolId }: Props = $props();

    let open = $state(false);
    let signoffs = $state<GlpSignoffResponse[] | null>(null);
    let loading = $state(false);
    let errorMessage = $state<string | null>(null);

    async function expand() {
        open = !open;
        if (open && signoffs === null && !loading) {
            loading = true;
            errorMessage = null;
            try {
                signoffs = await getProtocolSignoffs(protocolId);
            } catch (e: unknown) {
                errorMessage = e instanceof Error ? e.message : 'Failed to load history.';
            } finally {
                loading = false;
            }
        }
    }

    const COLORS: Record<string, string> = {
        APPROVED: 'bg-green-100 text-green-700',
        REJECTED: 'bg-red-100 text-red-700',
        REQUESTED_CHANGES: 'bg-amber-100 text-amber-700',
    };
    const colorFor = (action: string): string => COLORS[action] ?? 'bg-gray-100 text-gray-700';
</script>

<div class="border-t pt-3 mt-3">
    <button
        type="button"
        class="text-sm font-medium text-foreground cursor-pointer hover:text-primary transition-colors"
        onclick={expand}
        aria-expanded={open}
    >
        {open ? '▼' : '▶'} Approval history
    </button>
    {#if open}
        <div class="mt-2">
            {#if loading}
                <div class="text-xs text-muted-foreground">Loading…</div>
            {:else if errorMessage}
                <div class="text-xs text-destructive">{errorMessage}</div>
            {:else if signoffs && signoffs.length === 0}
                <div class="text-xs text-muted-foreground">No signoffs yet.</div>
            {:else if signoffs}
                <ol class="space-y-2">
                    {#each signoffs as s (s.id)}
                        <li class="text-xs">
                            <span class="px-1.5 py-0.5 rounded text-[10px] font-semibold {colorFor(s.action)}">
                                {s.action}
                            </span>
                            <span class="ml-2 text-[10px] uppercase text-muted-foreground">
                                {s.role}
                            </span>
                            <span class="ml-2 font-medium">{s.signer?.name ?? '—'}</span>
                            <span class="ml-2 text-muted-foreground">
                                {new Date(s.signed_at).toLocaleString()}
                            </span>
                            {#if s.attestation}
                                <div class="mt-1 italic text-muted-foreground">"{s.attestation}"</div>
                            {/if}
                            {#if s.invalidated_at}
                                <div class="mt-1 text-destructive">
                                    Invalidated {new Date(s.invalidated_at).toLocaleString()}{s.invalidated_reason ? `: ${s.invalidated_reason}` : ''}
                                </div>
                            {/if}
                        </li>
                    {/each}
                </ol>
            {/if}
        </div>
    {/if}
</div>
