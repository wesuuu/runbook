<script lang="ts">
    import type { Snippet } from 'svelte';
    import { flip } from 'svelte/animate';
    import { fade } from 'svelte/transition';
    import { compareValues, sortIndicator, type SortDir } from './projectUtils';
    import { Button } from '$lib/components/ui/button';

    interface Column {
        key: string;
        label: string;
        sortable?: boolean;
        align?: 'left' | 'center' | 'right';
        hideBelow?: 'md' | 'lg';
    }

    interface Props {
        items: any[];
        columns: Column[];
        filterPlaceholder?: string;
        defaultSortKey?: string;
        defaultSortDir?: SortDir;
        /** Extra filter fn applied after search (e.g. archived toggle) */
        filterFn?: (item: any, query: string) => boolean;
        /** Optional click handler for rows */
        onRowClick?: (item: any) => void;
        /** Optional extra class for a row (e.g. selected highlight) */
        rowClass?: (item: any) => string;
        toolbar?: Snippet;
        mobileCard: Snippet<[item: any]>;
        cells: Snippet<[item: any]>;
        empty?: Snippet;
    }

    let {
        items,
        columns,
        filterPlaceholder = 'Filter...',
        defaultSortKey = 'updated_at',
        defaultSortDir = 'desc',
        filterFn,
        onRowClick,
        rowClass,
        toolbar,
        mobileCard,
        cells,
        empty,
    }: Props = $props();

    let searchQuery = $state('');
    // svelte-ignore state_referenced_locally
    let sortKey = $state<string>(defaultSortKey);
    // svelte-ignore state_referenced_locally
    let sortDir = $state<SortDir>(defaultSortDir);
    let pageSize = $state(25);
    let page = $state(1);

    const filteredItems = $derived(() => {
        let list = items;
        if (searchQuery.trim() || filterFn) {
            const q = searchQuery.toLowerCase();
            list = list.filter((item) => {
                if (filterFn) return filterFn(item, q);
                // Default: search across all string column values
                return columns.some((col) => {
                    const val = item[col.key];
                    return typeof val === 'string' && val.toLowerCase().includes(q);
                });
            });
        }
        list = [...list].sort((a, b) => compareValues(a, b, sortKey, sortDir));
        return list;
    });

    const totalFiltered = $derived(filteredItems().length);
    const totalPages = $derived(Math.max(1, Math.ceil(totalFiltered / pageSize)));
    const paginatedItems = $derived(() => {
        const all = filteredItems();
        const start = (page - 1) * pageSize;
        return all.slice(start, start + pageSize);
    });

    $effect(() => {
        searchQuery;
        page = 1;
    });

    function toggleSort(key: string) {
        if (sortKey === key) {
            sortDir = sortDir === 'asc' ? 'desc' : 'asc';
        } else {
            sortKey = key;
            sortDir = key === 'name' ? 'asc' : 'desc';
        }
        page = 1;
    }

    function colAlignClass(col: Column): string {
        if (col.align === 'right') return 'text-right';
        if (col.align === 'center') return 'text-center';
        return 'text-left';
    }

    function colHideClass(col: Column): string {
        if (col.hideBelow === 'md') return 'hidden md:table-cell';
        if (col.hideBelow === 'lg') return 'hidden lg:table-cell';
        return '';
    }
</script>

<!-- Toolbar -->
<div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 px-4 sm:px-8 py-4">
    <div class="relative w-full sm:w-60">
        <svg
            class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
        ><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
        <input
            type="text"
            bind:value={searchQuery}
            placeholder={filterPlaceholder}
            class="w-full py-1.5 pl-8 pr-2.5 border border-slate-200 rounded-lg text-[13px] text-slate-800 bg-white placeholder:text-slate-400 focus:outline-none focus:border-slate-400 focus:ring-2 focus:ring-slate-400/15"
        />
    </div>
    <div class="flex items-center gap-4">
        {#if toolbar}
            {@render toolbar()}
        {/if}
        <span class="text-[13px] text-slate-400 font-medium">
            {filteredItems().length} of {items.length} item{items.length !== 1 ? 's' : ''}
        </span>
    </div>
</div>

{#if filteredItems().length === 0}
    <div class="flex flex-col items-center justify-center py-16 px-8 text-center gap-2">
        {#if empty}
            {@render empty()}
        {:else if items.length === 0}
            <p class="text-[15px] font-semibold text-slate-600">No items yet</p>
        {:else}
            <p class="text-[15px] font-semibold text-slate-600">No matching items</p>
            <p class="text-[13px] text-slate-400">Try a different search term.</p>
        {/if}
    </div>
{:else}
    <!-- Mobile card view -->
    <div class="sm:hidden divide-y divide-slate-100 px-4">
        {#each paginatedItems() as item (item.id)}
            <div
                in:fade={{ duration: 200 }}
                out:fade={{ duration: 150 }}
                animate:flip={{ duration: 250 }}
            >
                {@render mobileCard(item)}
            </div>
        {/each}
    </div>
    <!-- Desktop table view -->
    <div class="hidden sm:block overflow-x-auto">
    <table class="w-full border-collapse">
        <thead>
            <tr class="border-b border-border">
                {#each columns as col, i}
                    <th
                        class="{colHideClass(col)} {colAlignClass(col)} py-2.5 px-4
                            {i === 0 ? 'pl-6 sm:pl-10' : ''}
                            {i === columns.length - 1 ? 'pr-6 sm:pr-10' : ''}
                            text-sm font-medium whitespace-nowrap
                            {col.sortable ? 'cursor-pointer select-none hover:text-foreground' : ''}
                            {col.sortable && sortKey === col.key ? 'text-foreground' : 'text-muted-foreground'}"
                        onclick={col.sortable ? () => toggleSort(col.key) : undefined}
                    >
                        <span class="inline-flex items-center gap-1">
                            {col.label}
                            {#if col.sortable}
                                <svg
                                    class="w-3.5 h-3.5 transition-transform duration-200 {sortKey === col.key ? 'opacity-100' : 'opacity-0'}"
                                    style="transform: rotate({sortKey === col.key && sortDir === 'asc' ? '180' : '0'}deg)"
                                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
                                ><path d="m6 9 6 6 6-6"/></svg>
                            {/if}
                        </span>
                    </th>
                {/each}
            </tr>
        </thead>
        <tbody>
            {#each paginatedItems() as item (item.id)}
                <tr
                    class="border-b border-slate-50 transition-colors hover:bg-slate-50 {onRowClick ? 'cursor-pointer' : ''} {rowClass ? rowClass(item) : ''}"
                    onclick={onRowClick ? () => onRowClick(item) : undefined}
                    in:fade={{ duration: 200 }}
                    out:fade={{ duration: 150 }}
                    animate:flip={{ duration: 250 }}
                >
                    {@render cells(item)}
                </tr>
            {/each}
        </tbody>
    </table>
    </div>
    <!-- Pagination -->
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 px-4 sm:px-8 py-3.5 border-t border-slate-100">
        <div class="flex items-center gap-2">
            <span class="text-[13px] text-slate-400 font-medium">
                Showing {Math.min((page - 1) * pageSize + 1, totalFiltered)}–{Math.min(page * pageSize, totalFiltered)} of {totalFiltered}
            </span>
            {#if totalFiltered > 25}
                <select
                    class="ml-2 text-[12px] border border-slate-200 rounded px-1.5 py-0.5 text-slate-600 bg-white"
                    bind:value={pageSize}
                    onchange={() => { page = 1; }}
                >
                    <option value={25}>25 / page</option>
                    <option value={50}>50 / page</option>
                    <option value={100}>100 / page</option>
                </select>
            {/if}
        </div>
        {#if totalPages > 1}
            <div class="flex items-center gap-1">
                <Button
                    variant="outline"
                    size="sm"
                    class="h-auto px-2.5 py-1 text-[12px] font-medium text-slate-500 border-slate-200 hover:bg-slate-50"
                    disabled={page <= 1}
                    onclick={() => { page = page - 1; }}
                >Prev</Button>
                <span class="text-[12px] text-slate-500 px-2">
                    {page} / {totalPages}
                </span>
                <Button
                    variant="outline"
                    size="sm"
                    class="h-auto px-2.5 py-1 text-[12px] font-medium text-slate-500 border-slate-200 hover:bg-slate-50"
                    disabled={page >= totalPages}
                    onclick={() => { page = page + 1; }}
                >Next</Button>
            </div>
        {/if}
    </div>
{/if}
