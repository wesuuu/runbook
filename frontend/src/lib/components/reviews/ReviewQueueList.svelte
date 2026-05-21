<script lang="ts">
    import * as Table from '$lib/components/ui/table';
    import { EmptyState } from '$lib/components/ui/empty-state';
    import ReviewQueueRow from './ReviewQueueRow.svelte';
    import type { SignoffRequestItem } from '$lib/schemas/signoffRequests';

    interface Props {
        items: SignoffRequestItem[];
    }
    let { items }: Props = $props();

    function rowKey(i: SignoffRequestItem): string {
        return i.request_id ?? `${i.type}:${i.target_id}`;
    }
</script>

{#if items.length === 0}
    <EmptyState
        title="You're all caught up"
        description="No runs or protocols are waiting for your review."
    />
{:else}
    <Table.Root>
        <Table.Header>
            <Table.Row>
                <Table.Head>Name</Table.Head>
                <Table.Head>Type</Table.Head>
                <Table.Head>Role</Table.Head>
                <Table.Head>Requested by</Table.Head>
                <Table.Head class="text-right">Action</Table.Head>
            </Table.Row>
        </Table.Header>
        <Table.Body>
            {#each items as item (rowKey(item))}
                <ReviewQueueRow {item} />
            {/each}
        </Table.Body>
    </Table.Root>
{/if}
