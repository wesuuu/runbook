<script lang="ts">
    import { getProtocolApprovalHistory } from '$lib/api';
    import type { ProtocolApprovalEvent } from '$lib/schemas/protocolApproval';

    interface Props {
        protocolId: string;
    }

    let { protocolId }: Props = $props();

    let open = $state(false);
    let events = $state<ProtocolApprovalEvent[] | null>(null);
    let loading = $state(false);
    let errorMessage = $state<string | null>(null);

    async function expand() {
        open = !open;
        if (open && events === null && !loading) {
            loading = true;
            errorMessage = null;
            try {
                events = await getProtocolApprovalHistory(protocolId);
            } catch (e: unknown) {
                errorMessage = e instanceof Error ? e.message : 'Failed to load history.';
            } finally {
                loading = false;
            }
        }
    }

    const COLORS: Record<string, string> = {
        SUBMITTED: 'bg-blue-100 text-blue-700',
        APPROVED: 'bg-green-100 text-green-700',
        REJECTED: 'bg-red-100 text-red-700',
        REVERTED: 'bg-amber-100 text-amber-700',
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
            {:else if events && events.length === 0}
                <div class="text-xs text-muted-foreground">No events yet.</div>
            {:else if events}
                <ol class="space-y-2">
                    {#each events as e (e.id)}
                        <li class="text-xs">
                            <span class="px-1.5 py-0.5 rounded text-[10px] font-semibold {colorFor(e.action)}">
                                {e.action}
                            </span>
                            <span class="ml-2 font-medium">{e.actor?.name ?? '—'}</span>
                            <span class="ml-2 text-muted-foreground">
                                {new Date(e.created_at).toLocaleString()}
                            </span>
                            {#if e.comment}
                                <div class="mt-1 italic text-muted-foreground">"{e.comment}"</div>
                            {/if}
                            {#if e.signature_statement}
                                <div class="mt-1 text-muted-foreground">
                                    Statement: {e.signature_statement}
                                </div>
                            {/if}
                        </li>
                    {/each}
                </ol>
            {/if}
        </div>
    {/if}
</div>
