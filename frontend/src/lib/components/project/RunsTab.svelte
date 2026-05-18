<script lang="ts">
    import { goto } from "$app/navigation";
    import { shortId, formatDate, statusClasses, statusLabel } from "./projectUtils";
    import ProjectDataTable from "./ProjectDataTable.svelte";
    import AssignToExperimentModal from "./AssignToExperimentModal.svelte";
    import { Button } from "$lib/components/ui/button";

    interface Props {
        runs: any[];
        protocols: any[];
        experiments: any[];
        hideExperimentColumn?: boolean;
        hideExportColumn?: boolean;
        onDataChanged?: () => void;
    }

    let {
        runs,
        protocols,
        experiments,
        hideExperimentColumn = false,
        hideExportColumn = false,
        onDataChanged,
    }: Props = $props();

    let showAssignModal = $state(false);
    let assignRunId = $state("");
    let assignRunName = $state("");

    const experimentMap = $derived(
        new Map(experiments.map((e: any) => [e.id, e.name]))
    );

    const protocolMap = $derived(
        new Map(protocols.map((p: any) => [p.id, p.name]))
    );

    function experimentName(experimentId: string | null | undefined): string {
        if (!experimentId) return "";
        return experimentMap.get(experimentId) ?? "";
    }

    function protocolName(protocolId: string | null | undefined): string {
        if (!protocolId) return "";
        return protocolMap.get(protocolId) ?? "";
    }

    function openAssignModal(run: any, e: MouseEvent) {
        e.stopPropagation();
        assignRunId = run.id;
        assignRunName = run.name;
        showAssignModal = true;
    }

    let selectedRunIds = $state<Set<string>>(new Set());
    let lotProducerFilter = $state(false);

    const exportableRuns = $derived(
        runs.filter((r: any) => r.status === 'COMPLETED' || r.status === 'EDITED')
    );

    // Enrich runs with resolved names for sorting
    const enrichedRuns = $derived(
        runs.map((r: any) => ({
            ...r,
            experiment_name: experimentName(r.experiment_id),
            protocol_name: protocolName(r.protocol_id),
        }))
    );

    const visibleRuns = $derived.by(() => {
        return lotProducerFilter ? enrichedRuns.filter((r: any) => r.produces_lot) : enrichedRuns;
    });

    const columns = $derived.by(() => {
        const cols: any[] = [
            { key: 'id', label: 'ID', hideBelow: 'lg' as const },
            { key: 'name', label: 'Run Name', sortable: true },
        ];
        if (lotProducerFilter) {
            cols.push({ key: 'lot_number', label: 'Lot #', sortable: true });
        }
        if (!hideExperimentColumn) {
            cols.push({ key: 'experiment_name', label: 'Experiment', sortable: true, hideBelow: 'md' as const });
        }
        cols.push(
            { key: 'protocol_name', label: 'Protocol', sortable: true, hideBelow: 'md' as const },
            { key: 'status', label: 'Status', sortable: true },
            { key: 'updated_at', label: 'Last Modified', sortable: true, align: 'right' as const },
        );
        if (!hideExportColumn) {
            cols.push({ key: '_export', label: 'Export', align: 'right' as const });
        }
        return cols;
    });

    function filterFn(item: any, query: string): boolean {
        if (!query) return true;
        return (
            item.name.toLowerCase().includes(query) ||
            (item.status && item.status.toLowerCase().includes(query)) ||
            (item.protocol_name && item.protocol_name.toLowerCase().includes(query)) ||
            (item.experiment_name && item.experiment_name.toLowerCase().includes(query))
        );
    }

    function toggleRunSelection(runId: string) {
        const next = new Set(selectedRunIds);
        if (next.has(runId)) {
            next.delete(runId);
        } else {
            next.add(runId);
        }
        selectedRunIds = next;
    }

    function toggleAllExportable() {
        const exportableIds = exportableRuns.map((r: any) => r.id);
        const allSelected = exportableIds.every((id: string) => selectedRunIds.has(id));
        if (allSelected) {
            selectedRunIds = new Set();
        } else {
            selectedRunIds = new Set(exportableIds);
        }
    }
</script>

<ProjectDataTable
    items={visibleRuns}
    {columns}
    filterPlaceholder="Filter runs..."
    {filterFn}
    onRowClick={(r) => goto(`/runs/${r.id}`)}
    rowClass={(r) => selectedRunIds.has(r.id) ? 'bg-blue-50/50' : ''}
>
    {#snippet toolbar()}
        <Button
            type="button"
            data-testid="lot-producer-filter"
            size="sm"
            rounded="full"
            variant={lotProducerFilter ? 'default' : 'outline'}
            class={lotProducerFilter
                ? 'bg-primary/10 text-primary hover:bg-primary/15 shadow-none text-xs'
                : 'text-foreground/70 text-xs'}
            onclick={() => { lotProducerFilter = !lotProducerFilter; }}
        >
            Lot producer only
            {#if lotProducerFilter}
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>
            {/if}
        </Button>
        {#if !hideExportColumn && selectedRunIds.size > 0}
            <Button
                size="sm"
                class="bg-blue-600 text-white hover:bg-blue-700"
                onclick={() => goto(`/export?runs=${[...selectedRunIds].join(',')}`)}
            >
                <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                Export {selectedRunIds.size} Run{selectedRunIds.size !== 1 ? 's' : ''}
            </Button>
        {/if}
    {/snippet}

    {#snippet mobileCard(r)}
        <Button variant="ghost" class="w-full h-auto min-h-11 py-3 px-0 flex-col items-stretch justify-start text-left" onclick={() => goto(`/runs/${r.id}`)}>
            <div class="flex items-center justify-between mb-1">
                <span class="text-sm font-medium text-slate-800">{r.name}</span>
                <span class="inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full {statusClasses(r.status)}">
                    {statusLabel(r.status)}
                </span>
            </div>
            <div class="flex items-center gap-2 text-xs text-slate-400">
                <span class="font-mono">{shortId(r.id)}</span>
                <span>&middot;</span>
                <span>{formatDate(r.updated_at || r.created_at)}</span>
            </div>
        </Button>
    {/snippet}

    {#snippet cells(r)}
        <td class="hidden lg:table-cell py-3 px-4 pl-6 sm:pl-10 text-xs text-slate-400 font-mono whitespace-nowrap">{shortId(r.id)}</td>
        <td class="py-3 px-4 text-sm font-medium text-slate-800">{r.name}</td>
        {#if lotProducerFilter}
            <td class="py-3 px-4 text-sm font-mono text-teal-600 whitespace-nowrap">{r.lot_number ?? ''}</td>
        {/if}
        {#if !hideExperimentColumn}
            <td class="hidden md:table-cell py-3 px-4 text-sm text-slate-800 whitespace-nowrap">
                {#if r.experiment_id}
                    <a
                        href="/experiments/{r.experiment_id}"
                        class="text-teal-600 hover:underline"
                        onclick={(e: MouseEvent) => e.stopPropagation()}
                    >
                        {r.experiment_name}
                    </a>
                {:else}
                    <Button
                        variant="outline"
                        size="sm"
                        class="h-auto px-2 py-0.5 text-xs font-medium text-teal-600 border-teal-200 hover:bg-teal-600 hover:text-white hover:border-teal-600"
                        onclick={(e: MouseEvent) => openAssignModal(r, e)}
                    >
                        Assign
                    </Button>
                {/if}
            </td>
        {/if}
        <td class="hidden md:table-cell py-3 px-4 text-sm font-medium text-slate-800 whitespace-nowrap">
            {#if r.protocol_name}
                {r.protocol_name}
            {:else}
                <span class="text-slate-400">--</span>
            {/if}
        </td>
        <td class="py-3 px-4 whitespace-nowrap">
            <span class="inline-block text-xs font-semibold px-3 py-0.5 rounded-full {statusClasses(r.status)}">
                {statusLabel(r.status)}
            </span>
        </td>
        <td class="py-3 px-4 text-sm text-slate-500 whitespace-nowrap text-right">{formatDate(r.updated_at || r.created_at)}</td>
        {#if !hideExportColumn}
            <td class="py-3 px-4 pr-6 sm:pr-10 text-right">
                {#if r.status === 'COMPLETED' || r.status === 'EDITED'}
                    <input
                        type="checkbox"
                        class="w-3.5 h-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                        checked={selectedRunIds.has(r.id)}
                        onclick={(e: MouseEvent) => { e.stopPropagation(); toggleRunSelection(r.id); }}
                    />
                {/if}
            </td>
        {/if}
    {/snippet}

    {#snippet empty()}
        {#if runs.length === 0}
            <div class="w-12 h-12 text-slate-300 mb-2">
                <svg class="w-full h-full" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5"/></svg>
            </div>
            <p class="text-[15px] font-semibold text-slate-600">No runs yet</p>
            <p class="text-[13px] text-slate-400">Create your first run to get started.</p>
        {:else}
            <p class="text-[15px] font-semibold text-slate-600">No matching runs</p>
            <p class="text-[13px] text-slate-400">Try a different search term.</p>
        {/if}
    {/snippet}
</ProjectDataTable>

<AssignToExperimentModal
    bind:open={showAssignModal}
    runId={assignRunId}
    runName={assignRunName}
    {experiments}
    onAssigned={onDataChanged}
/>
