<script lang="ts">
    import { goto } from "$app/navigation";
    import { paths } from "$lib/paths";
    import { tick } from "svelte";
    import {
        formatDate,
        experimentStatusClasses,
        experimentStatusLabel,
    } from "./projectUtils";
    import ProjectDataTable from "./ProjectDataTable.svelte";
    import RunsTab from "./RunsTab.svelte";
    import RunCreatorWizardModal from "$lib/components/run/RunCreatorWizardModal.svelte";
    import { Button } from "$lib/components/ui/button";

    interface Props {
        experiments: any[];
        runs: any[];
        protocols: any[];
        projectId: string;
    }

    let { experiments, runs, protocols, projectId }: Props = $props();

    let showRunModal = $state(false);
    let runModalExperiment = $state<{ id: string; name: string } | null>(null);

    let runsVisible = $state(false);

    $effect(() => {
        if (selectedExperimentId) {
            runsVisible = false;
            tick().then(() => { runsVisible = true; });
        } else {
            runsVisible = false;
        }
    });

    function openCreateRunForExperiment() {
        if (!selectedExperiment) return;
        runModalExperiment = { id: selectedExperiment.id, name: selectedExperiment.name };
        showRunModal = true;
    }

    let selectedExperimentId = $state<string | null>(null);

    const selectedExperiment = $derived(
        experiments.find((e: any) => e.id === selectedExperimentId)
    );

    const experimentRuns = $derived(
        selectedExperimentId
            ? runs.filter((r: any) => r.experiment_id === selectedExperimentId)
            : []
    );

    const columns = [
        { key: "name", label: "Name", sortable: true },
        { key: "description", label: "Description", hideBelow: "md" as const },
        { key: "status", label: "Status", sortable: true },
        { key: "run_count", label: "Runs", align: "right" as const },
        {
            key: "updated_at",
            label: "Last Modified",
            sortable: true,
            align: "right" as const,
        },
    ];

    function filterFn(item: any, query: string): boolean {
        if (!query) return true;
        return (
            item.name?.toLowerCase().includes(query) ||
            item.description?.toLowerCase().includes(query) ||
            item.status?.toLowerCase().includes(query)
        );
    }

    function selectExperiment(e: any) {
        if (selectedExperimentId === e.id) {
            goto(paths.experiment(e.project_slug, e.slug));
        } else {
            selectedExperimentId = e.id;
        }
    }
</script>

<ProjectDataTable
    items={experiments}
    {columns}
    filterPlaceholder="Filter experiments..."
    {filterFn}
    onRowClick={selectExperiment}
    rowClass={(e) => selectedExperimentId === e.id ? 'bg-slate-50 border-l-[3px] !border-l-teal-500' : ''}
>
    {#snippet mobileCard(e)}
        <Button
            variant="ghost"
            class="w-full h-auto min-h-11 py-3 px-0 flex-col items-stretch justify-start text-left"
            onclick={() => selectExperiment(e)}
        >
            <div class="flex items-center justify-between mb-1">
                <span class="text-sm font-medium text-slate-800"
                    >{e.name}</span
                >
                <span
                    class="inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full {experimentStatusClasses(e.status)}"
                >
                    {experimentStatusLabel(e.status)}
                </span>
            </div>
            <div class="flex items-center gap-2 text-xs text-slate-400">
                {#if e.description}
                    <span class="truncate max-w-[180px]">{e.description}</span>
                    <span>&middot;</span>
                {/if}
                <span
                    >{e.run_count} run{e.run_count !== 1 ? "s" : ""}</span
                >
                <span>&middot;</span>
                <span>{formatDate(e.updated_at || e.created_at)}</span>
            </div>
        </Button>
    {/snippet}

    {#snippet cells(e)}
        <td class="py-3 px-4 pl-6 sm:pl-10 text-sm font-medium text-slate-800"
            >{e.name}</td
        >
        <td
            class="hidden md:table-cell py-3 px-4 text-sm text-slate-500 max-w-[250px] truncate"
        >
            {e.description || "--"}
        </td>
        <td class="py-3 px-4 whitespace-nowrap">
            <span
                class="inline-block text-xs font-semibold px-3 py-0.5 rounded-full {experimentStatusClasses(e.status)}"
            >
                {experimentStatusLabel(e.status)}
            </span>
        </td>
        <td class="py-3 px-4 text-sm text-slate-600 text-right"
            >{e.run_count}</td
        >
        <td
            class="py-3 px-4 pr-6 sm:pr-10 text-sm text-slate-500 whitespace-nowrap text-right"
            >{formatDate(e.updated_at || e.created_at)}</td
        >
    {/snippet}

    {#snippet empty()}
        {#if experiments.length === 0}
            <div class="w-12 h-12 text-slate-300 mb-2">
                <svg
                    class="w-full h-full"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                >
                    <path
                        d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m5.231 13.481L15 17.25m-4.5-15H5.625c-.621 0-1.125.504-1.125 1.125v16.5c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Zm3.75 11.625a2.625 2.625 0 1 1-5.25 0 2.625 2.625 0 0 1 5.25 0Z"
                    />
                </svg>
            </div>
            <p class="text-[15px] font-semibold text-slate-600">
                No experiments yet
            </p>
            <p class="text-[13px] text-slate-400">
                Create one to start organizing your runs.
            </p>
        {:else}
            <p class="text-[15px] font-semibold text-slate-600">
                No matching experiments
            </p>
            <p class="text-[13px] text-slate-400">
                Try a different search term.
            </p>
        {/if}
    {/snippet}
</ProjectDataTable>

<!-- Experiment Runs Section -->
{#if selectedExperiment && runsVisible}
    <div class="runs-panel">
    <div class="mt-6 px-4 sm:px-8">
        <div class="flex items-center gap-3 mb-3">
            <div class="h-px flex-1 bg-slate-200"></div>
            <a
                href={paths.experiment(selectedExperiment.project_slug, selectedExperiment.slug)}
                class="text-xs font-medium text-teal-600 uppercase tracking-wider hover:underline"
            >
                {selectedExperiment.name} — Runs ({experimentRuns.length})
            </a>
            <div class="h-px flex-1 bg-slate-200"></div>
        </div>
    </div>

    {#if experimentRuns.length > 0}
        <RunsTab
            runs={experimentRuns}
            {protocols}
            {experiments}
            hideExperimentColumn={true}
            hideExportColumn={true}
        />
    {:else}
        <div class="mx-4 sm:mx-8 border border-dashed border-slate-200 rounded-lg py-8 text-center">
            <p class="text-[15px] font-semibold text-slate-600 mb-1">This experiment doesn't have any run data yet.</p>
            <p class="text-[13px] text-slate-400 mb-4">Create a run to start collecting data.</p>
            <Button onclick={openCreateRunForExperiment}>
                + Create Run
            </Button>
        </div>
    {/if}
    </div>
{/if}

<RunCreatorWizardModal
    bind:open={showRunModal}
    {projectId}
    {protocols}
    forExperiment={runModalExperiment}
    onCreated={() => { runModalExperiment = null; }}
/>

<style>
    .runs-panel {
        animation: fadeSlideIn 250ms ease-out both;
    }

    @keyframes fadeSlideIn {
        from {
            opacity: 0;
            transform: translateY(6px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
</style>
