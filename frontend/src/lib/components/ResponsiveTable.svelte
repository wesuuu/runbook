<script lang="ts">
    import type { Snippet } from 'svelte';

    type Column = {
        key: string;
        label: string;
        priority?: 1 | 2 | 3;
        class?: string;
        hideOnMobile?: boolean;
    };

    let {
        columns,
        rows,
        onRowClick,
        cardSnippet,
    }: {
        columns: Column[];
        rows: Record<string, any>[];
        onRowClick?: (row: Record<string, any>) => void;
        cardSnippet?: Snippet<[Record<string, any>, number]>;
    } = $props();

    function priorityClass(col: Column): string {
        if (col.hideOnMobile || col.priority === 2) return 'hidden md:table-cell';
        if (col.priority === 3) return 'hidden lg:table-cell';
        return '';
    }
</script>

<!-- Mobile card view (<640px) -->
{#if cardSnippet}
    <div class="sm:hidden divide-y divide-border">
        {#each rows as row, i}
            {@render cardSnippet(row, i)}
        {/each}
    </div>
{/if}

<!-- Table view (>=640px, or always if no cardSnippet) -->
<div class="{cardSnippet ? 'hidden sm:block' : ''} overflow-x-auto">
    <table class="w-full border-collapse text-sm">
        <thead>
            <tr class="border-b border-border">
                {#each columns as col}
                    <th class="text-left py-2.5 px-4 text-[11px] font-bold text-muted-foreground uppercase tracking-wide whitespace-nowrap {priorityClass(col)} {col.class || ''}">
                        {col.label}
                    </th>
                {/each}
            </tr>
        </thead>
        <tbody>
            {#each rows as row, i}
                <tr
                    class="border-b border-border/50 transition-colors hover:bg-muted/40 {onRowClick ? 'cursor-pointer' : ''}"
                    onclick={() => onRowClick?.(row)}
                >
                    {#each columns as col}
                        <td class="py-3 px-4 whitespace-nowrap {priorityClass(col)} {col.class || ''}">
                            {row[col.key] ?? ''}
                        </td>
                    {/each}
                </tr>
            {/each}
        </tbody>
    </table>
</div>
