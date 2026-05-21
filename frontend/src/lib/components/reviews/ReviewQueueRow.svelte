<script lang="ts">
    import * as Table from '$lib/components/ui/table';
    import { Badge } from '$lib/components/ui/badge';
    import { Button } from '$lib/components/ui/button';
    import type { SignoffRequestItem } from '$lib/schemas/signoffRequests';

    interface Props {
        item: SignoffRequestItem;
    }
    let { item }: Props = $props();

    // Long-wait threshold: 3 days. Purely presentational.
    const LONG_WAIT_MS = 3 * 24 * 60 * 60 * 1000;
    const isLongWait = $derived(
        item.created_at
            ? Date.now() - new Date(item.created_at).getTime() > LONG_WAIT_MS
            : false,
    );

    const href = $derived(
        item.type === 'run' ? `/runs/${item.target_id}` : `/protocols/${item.target_id}`,
    );
    const roleLabel = $derived(
        item.role === 'STUDY_DIRECTOR'
            ? 'Study Director'
            : item.role === 'QAU'
              ? 'QAU'
              : 'Approver',
    );
</script>

<Table.Row class={isLongWait ? 'bg-amber-50' : ''}>
    <Table.Cell class="font-medium">
        <a href={href} class="font-semibold text-primary hover:underline">
            {item.target_name}
        </a>
    </Table.Cell>
    <Table.Cell>
        <Badge variant="outline">{item.type === 'run' ? 'Run' : 'Protocol'}</Badge>
    </Table.Cell>
    <Table.Cell>Sign as {roleLabel}</Table.Cell>
    <Table.Cell>
        {#if item.assigned && item.requested_by}
            {item.requested_by.name}
        {:else if !item.assigned}
            <span class="text-xs text-muted-foreground italic">
                Unassigned · any org QAU
            </span>
        {:else}
            <span class="text-xs text-muted-foreground">—</span>
        {/if}
    </Table.Cell>
    <Table.Cell class="text-right">
        <a href={href}><Button variant="ghost" size="sm">Review →</Button></a>
    </Table.Cell>
</Table.Row>
