<script lang="ts">
    import { onMount } from 'svelte';
    import { getAwaitingMyApproval } from '$lib/api';
    import type { AwaitingApprovalItem } from '$lib/schemas/protocolApproval';

    let items = $state<AwaitingApprovalItem[]>([]);
    let loaded = $state(false);

    onMount(async () => {
        try {
            items = await getAwaitingMyApproval();
        } catch {
            items = [];
        } finally {
            loaded = true;
        }
    });
</script>

{#if loaded && items.length > 0}
    <div class="rounded border bg-background p-4" data-testid="pending-approvals-card">
        <h3 class="font-semibold mb-2">Pending approvals</h3>
        <ul class="space-y-1">
            {#each items as item (item.protocol_id)}
                <li>
                    <a
                        class="text-primary hover:underline"
                        href={`/protocols/${item.protocol_id}`}
                        data-testid="pending-approval-row"
                    >
                        {#if item.project_name}
                            <span class="font-medium">[{item.project_name}]</span>
                        {/if}
                        {item.name}
                    </a>
                    {#if item.submitted_by?.name}
                        <span class="text-xs text-muted-foreground ml-2">
                            Submitted by {item.submitted_by.name}
                        </span>
                    {/if}
                </li>
            {/each}
        </ul>
    </div>
{/if}
