<script lang="ts">
    import { goto } from "$app/navigation";
    import { paths } from "$lib/paths";
    import {
        formatDate,
        experimentStatusClasses,
        experimentStatusLabel,
    } from "./projectUtils";
    import ProjectDataTable from "./ProjectDataTable.svelte";
    import RunsTab from "./RunsTab.svelte";
    import RunCreatorWizardModal from "$lib/components/run/RunCreatorWizardModal.svelte";
    import { Button } from "$lib/components/ui/button";
    import { ChevronRight } from "lucide-svelte";

    interface Props {
        experiments: any[];
        runs: any[];
        protocols: any[];
        projectId: string;
    }

    let { experiments, runs, protocols, projectId }: Props = $props();

    let showRunModal = $state(false);
    let runModalExperiment = $state<{ id: string; name: string } | null>(null);

    // Multiple rows may be expanded at once (replaces the single-select trap).
    let expandedIds = $state<Set<string>>(new Set());

    function toggleExpanded(id: string) {
        const next = new Set(expandedIds);
        if (next.has(id)) {
            next.delete(id);
        } else {
            next.add(id);
        }
        expandedIds = next;
    }

    function openExperiment(e: any) {
        goto(paths.experiment(e.project_slug, e.slug));
    }

    function openCreateRunFor(e: any) {
        runModalExperiment = { id: e.id, name: e.name };
        showRunModal = true;
    }

    function runsFor(experimentId: string): any[] {
        return runs.filter((r: any) => r.experiment_id === experimentId);
    }

    const columns = [
        { key: "expand", label: "", align: "left" as const },
        { key: "name", label: "Name", sortable: true },
        { key: "objective", label: "Objective", hideBelow: "md" as const },
        { key: "lifecycle_status", label: "Status", sortable: true },
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
            item.objective?.toLowerCase().includes(query) ||
            item.lifecycle_status?.toLowerCase().includes(query)
        );
    }
</script>

<ProjectDataTable
    items={experiments}
    {columns}
    filterPlaceholder="Filter experiments..."
    {filterFn}
    onRowClick={openExperiment}
>
    {#snippet mobileCard(e)}
        <button
            type="button"
            class="flex w-full min-h-11 cursor-pointer flex-col justify-center px-2 py-3 text-left transition-colors hover:bg-muted/50"
            onclick={() => openExperiment(e)}
        >
            <div class="mb-1 flex items-center justify-between">
                <span class="text-sm font-medium text-foreground">{e.name}</span>
                <span
                    class="inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold {experimentStatusClasses(
                        e.lifecycle_status,
                    )}"
                >
                    {experimentStatusLabel(e.lifecycle_status)}
                </span>
            </div>
            <div class="flex items-center gap-2 text-xs text-muted-foreground">
                {#if e.objective}
                    <span class="max-w-[180px] truncate">{e.objective}</span>
                    <span>&middot;</span>
                {/if}
                <span>{e.run_count} run{e.run_count !== 1 ? "s" : ""}</span>
                <span>&middot;</span>
                <span>{formatDate(e.updated_at || e.created_at)}</span>
            </div>
        </button>
    {/snippet}

    {#snippet cells(e)}
        <td class="py-3 pl-6 pr-2 sm:pl-8">
            <button
                type="button"
                class="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={expandedIds.has(e.id) ? "Hide runs" : "Show runs"}
                aria-expanded={expandedIds.has(e.id)}
                onclick={(ev) => {
                    ev.stopPropagation();
                    toggleExpanded(e.id);
                }}
            >
                <ChevronRight
                    class="h-4 w-4 transition-transform {expandedIds.has(e.id)
                        ? 'rotate-90'
                        : ''}"
                />
            </button>
        </td>
        <td class="py-3 px-4 text-sm font-medium text-foreground">{e.name}</td>
        <td
            class="hidden max-w-[250px] truncate px-4 py-3 text-sm text-muted-foreground md:table-cell"
        >
            {e.objective || "--"}
        </td>
        <td class="whitespace-nowrap px-4 py-3">
            <span
                class="inline-block rounded-full px-3 py-0.5 text-xs font-semibold {experimentStatusClasses(
                    e.lifecycle_status,
                )}"
            >
                {experimentStatusLabel(e.lifecycle_status)}
            </span>
        </td>
        <td class="px-4 py-3 text-right text-sm text-foreground">{e.run_count}</td>
        <td
            class="whitespace-nowrap px-4 py-3 pr-6 text-right text-sm text-muted-foreground sm:pr-8"
        >
            {formatDate(e.updated_at || e.created_at)}
        </td>
    {/snippet}

    {#snippet empty()}
        {#if experiments.length === 0}
            <p class="text-[15px] font-semibold text-foreground">
                No experiments yet
            </p>
            <p class="text-[13px] text-muted-foreground">
                Create one to start organizing your runs.
            </p>
        {:else}
            <p class="text-[15px] font-semibold text-foreground">
                No matching experiments
            </p>
            <p class="text-[13px] text-muted-foreground">
                Try a different search term.
            </p>
        {/if}
    {/snippet}
</ProjectDataTable>

<!-- Inline runs panels — one per expanded row. -->
{#each experiments as e (e.id)}
    {#if expandedIds.has(e.id)}
        {@const expRuns = runsFor(e.id)}
        <div class="mt-4 px-4 sm:px-8">
            <div class="mb-3 flex items-center gap-3">
                <div class="h-px flex-1 bg-border"></div>
                <a
                    href={paths.experiment(e.project_slug, e.slug)}
                    class="text-xs font-medium uppercase tracking-wider text-primary hover:underline"
                >
                    {e.name} — Runs ({expRuns.length})
                </a>
                <div class="h-px flex-1 bg-border"></div>
            </div>
            {#if expRuns.length > 0}
                <RunsTab
                    runs={expRuns}
                    {protocols}
                    {experiments}
                    hideExperimentColumn={true}
                    hideExportColumn={true}
                />
                <div class="mt-3 text-right">
                    <Button variant="outline" size="sm" onclick={() => openCreateRunFor(e)}>
                        + Add run
                    </Button>
                </div>
            {:else}
                <div
                    class="rounded-lg border border-dashed border-border py-8 text-center"
                >
                    <p class="mb-1 text-[15px] font-semibold text-foreground">
                        This experiment doesn't have any run data yet.
                    </p>
                    <p class="mb-4 text-[13px] text-muted-foreground">
                        Create a run to start collecting data.
                    </p>
                    <Button onclick={() => openCreateRunFor(e)}>+ Create Run</Button>
                </div>
            {/if}
        </div>
    {/if}
{/each}

<RunCreatorWizardModal
    bind:open={showRunModal}
    {projectId}
    {protocols}
    forExperiment={runModalExperiment}
    onCreated={() => {
        runModalExperiment = null;
    }}
/>
