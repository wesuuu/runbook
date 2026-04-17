<script lang="ts">
    import { goto } from "$app/navigation";
    import { api } from "$lib/api";
    import { shortId, formatDate, protocolStatusClasses, protocolStatusLabel } from "./projectUtils";
    import ProjectDataTable from "./ProjectDataTable.svelte";
    import { Button } from "$lib/components/ui/button";

    interface Props {
        projectId: string;
        protocols: any[];
        onReloadProtocols: (showArchived: boolean) => Promise<void>;
        onCreateProtocol: () => void;
        onImportProtocol?: () => void;
    }

    let { projectId, protocols, onReloadProtocols, onCreateProtocol, onImportProtocol }: Props = $props();

    let showArchived = $state(false);

    const columns = [
        { key: 'id', label: 'ID', hideBelow: 'lg' as const },
        { key: 'name', label: 'Protocol Name', sortable: true },
        { key: 'description', label: 'Description', hideBelow: 'md' as const },
        { key: 'version_number', label: 'Version', sortable: true, hideBelow: 'lg' as const },
        { key: 'status', label: 'Status', sortable: true },
        { key: 'updated_at', label: 'Last Modified', sortable: true, align: 'right' as const },
        { key: '_actions', label: '', align: 'right' as const },
    ];

    $effect(() => {
        showArchived;
        if (projectId) {
            onReloadProtocols(showArchived);
        }
    });

    function filterFn(item: any, query: string): boolean {
        if (!query) return true;
        return (
            item.name.toLowerCase().includes(query) ||
            (item.description && item.description.toLowerCase().includes(query))
        );
    }

    async function deleteOrArchiveProtocol(protocolId: string) {
        if (!confirm('Are you sure you want to delete/archive this protocol?')) return;
        try {
            await api.delete(`/science/protocols/${protocolId}`);
            await onReloadProtocols(showArchived);
        } catch (e: any) {
            console.error('Failed to delete/archive protocol:', e);
        }
    }

    async function unarchiveProtocol(protocolId: string) {
        try {
            await api.put(`/science/protocols/${protocolId}/unarchive`, {});
            await onReloadProtocols(showArchived);
        } catch (e: any) {
            console.error('Failed to unarchive protocol:', e);
        }
    }
</script>

<ProjectDataTable
    items={protocols}
    {columns}
    filterPlaceholder="Filter protocols..."
    {filterFn}
    onRowClick={(proto) => goto(`/protocols/${proto.id}`)}
>
    {#snippet mobileCard(proto)}
        <Button variant="ghost" class="w-full h-auto min-h-11 py-3 px-0 flex-col items-stretch justify-start text-left" onclick={() => goto(`/protocols/${proto.id}`)}>
            <div class="flex items-center justify-between mb-1">
                <span class="text-sm font-medium text-slate-800">{proto.name}</span>
                <span class="inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full {protocolStatusClasses(proto.status)}">
                    {protocolStatusLabel(proto.status)}
                </span>
            </div>
            {#if proto.description}
                <div class="text-xs text-slate-500 line-clamp-1 mb-1">{proto.description}</div>
            {/if}
            <div class="flex items-center gap-2 text-xs text-slate-400">
                <span class="font-mono">{shortId(proto.id)}</span>
                {#if proto.version_number}
                    <span>&middot;</span>
                    <span>v{proto.version_number}</span>
                {/if}
                <span>&middot;</span>
                <span>{formatDate(proto.updated_at || proto.created_at)}</span>
            </div>
        </Button>
    {/snippet}

    {#snippet cells(proto)}
        <td class="hidden lg:table-cell py-3 px-4 pl-6 sm:pl-10 text-xs text-slate-400 font-mono whitespace-nowrap">{shortId(proto.id)}</td>
        <td class="py-3 px-4 text-sm font-medium text-slate-800">{proto.name}</td>
        <td class="hidden md:table-cell py-3 px-4 text-sm font-medium text-slate-800 max-w-[300px] whitespace-nowrap overflow-hidden text-ellipsis">{proto.description || "--"}</td>
        <td class="hidden lg:table-cell py-3 px-4 text-xs text-slate-400 font-mono whitespace-nowrap">{proto.version_number ? `v${proto.version_number}` : "--"}</td>
        <td class="py-3 px-4 whitespace-nowrap">
            <span class="inline-block text-xs font-semibold px-3 py-0.5 rounded-full {protocolStatusClasses(proto.status)}">
                {protocolStatusLabel(proto.status)}
            </span>
        </td>
        <td class="py-3 px-4 text-sm text-slate-500 whitespace-nowrap text-right">{formatDate(proto.updated_at || proto.created_at)}</td>
        <td class="py-3 px-4 pr-6 sm:pr-10 text-right whitespace-nowrap">
            {#if proto.status?.toUpperCase() === 'ARCHIVED'}
                <button
                    class="text-[12px] font-medium text-slate-500 hover:text-slate-700 px-2.5 py-1 rounded border border-slate-200 hover:border-slate-300 bg-white transition-colors"
                    onclick={(e: MouseEvent) => { e.stopPropagation(); unarchiveProtocol(proto.id); }}
                >
                    Unarchive
                </button>
            {:else if proto.status?.toUpperCase() === 'DRAFT'}
                <button
                    class="text-[12px] font-medium text-red-500 hover:text-red-700 px-2.5 py-1 rounded border border-red-200 hover:border-red-300 bg-white transition-colors"
                    onclick={(e: MouseEvent) => { e.stopPropagation(); deleteOrArchiveProtocol(proto.id); }}
                >
                    Delete
                </button>
            {:else if proto.status?.toUpperCase() === 'APPROVED'}
                <button
                    class="text-[12px] font-medium text-slate-500 hover:text-slate-700 px-2.5 py-1 rounded border border-slate-200 hover:border-slate-300 bg-white transition-colors"
                    onclick={(e: MouseEvent) => { e.stopPropagation(); deleteOrArchiveProtocol(proto.id); }}
                >
                    Archive
                </button>
            {/if}
        </td>
    {/snippet}

    {#snippet empty()}
        {#if protocols.length === 0}
            <div class="w-12 h-12 text-slate-300 mb-2">
                <svg class="w-full h-full" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"/></svg>
            </div>
            <p class="text-[15px] font-semibold text-slate-600">No protocols yet</p>
            <p class="text-[13px] text-slate-400 mb-4">Create your first protocol to define a workflow.</p>
            <button
                class="px-4.5 py-2 bg-slate-800 text-white rounded-lg text-[13px] font-semibold cursor-pointer whitespace-nowrap transition-colors hover:bg-slate-900"
                onclick={onCreateProtocol}
            >
                + New Protocol
            </button>
        {:else}
            <p class="text-[15px] font-semibold text-slate-600">No matching protocols</p>
            <p class="text-[13px] text-slate-400">Try a different search term.</p>
        {/if}
    {/snippet}
</ProjectDataTable>
