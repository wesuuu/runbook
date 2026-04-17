<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import {
        buildTsv,
        saveExportSettings,
        loadExportSettings,
        applyRestoredColumns,
        PRESETS,
    } from '$lib/export-utils';
    import type { ColumnDef, ExportLayout, ExportFormat, ExportPreset } from '$lib/export-utils';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import * as Table from '$lib/components/ui/table';

    // Parse run IDs from URL
    const runIds = $derived(
        ($page.url.searchParams.get('runs') || '').split(',').filter(Boolean)
    );

    let layout = $state<ExportLayout>('long');
    let format = $state<ExportFormat>('csv');
    let columns = $state<ColumnDef[]>([]);
    let rows = $state<any[]>([]);
    let selectedColumns = $state<Set<string>>(new Set());
    let loading = $state(false);
    let downloading = $state(false);
    let error = $state<string | null>(null);
    let runCount = $state(0);

    // Clipboard
    let copyFeedback = $state(false);

    // Quick Setup preset dropdown
    let presetOpen = $state(false);

    // Pending preset column groups (applied after preview reloads)
    let pendingPresetGroups = $state<string[] | null>(null);

    // Restore last-used settings on init (before first preview)
    const restored = loadExportSettings();
    if (restored) {
        format = restored.format;
        layout = restored.layout;
    }

    // Preview pagination
    const PAGE_SIZE = 50;
    let previewPage = $state(0);
    const totalPages = $derived(Math.max(1, Math.ceil(rows.length / PAGE_SIZE)));
    const pagedRows = $derived(
        rows.slice(previewPage * PAGE_SIZE, (previewPage + 1) * PAGE_SIZE)
    );

    // Column groups for bulk toggling
    const columnGroups = $derived.by(() => {
        const groups: Record<string, ColumnDef[]> = {};
        for (const col of columns) {
            if (!groups[col.group]) groups[col.group] = [];
            groups[col.group].push(col);
        }
        return groups;
    });

    const groupLabels: Record<string, string> = {
        metadata: 'Run Info',
        step: 'Step Details',
        data: 'Data',
        audit: 'Audit Trail',
    };

    // Visible columns (filtered by selection)
    const visibleColumns = $derived(
        columns.filter((c) => selectedColumns.has(c.key))
    );

    // Load preview when runIds or layout changes
    $effect(() => {
        if (runIds.length > 0) {
            loadPreview();
        }
    });

    async function loadPreview() {
        loading = true;
        error = null;
        previewPage = 0;
        try {
            const resp: any = await api.post('/science/export/preview', {
                run_ids: runIds,
                layout,
            });
            columns = resp.columns;
            rows = resp.rows;
            runCount = resp.run_count;

            // Apply pending preset column groups if a preset was just selected
            if (pendingPresetGroups) {
                const groupSet = new Set(pendingPresetGroups);
                selectedColumns = new Set(
                    columns.filter((c: ColumnDef) => groupSet.has(c.group)).map((c: ColumnDef) => c.key)
                );
                pendingPresetGroups = null;
            } else if (restored && restored.columnKeys.length > 0) {
                // Try to restore saved column selection
                const restoredCols = applyRestoredColumns(restored.columnKeys, columns);
                selectedColumns = restoredCols ?? new Set(columns.map((c: ColumnDef) => c.key));
                // Clear restored so subsequent layout changes don't re-apply
                restored.columnKeys = [];
            } else {
                selectedColumns = new Set(columns.map((c: ColumnDef) => c.key));
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load preview';
            columns = [];
            rows = [];
        } finally {
            loading = false;
        }
    }

    function toggleColumn(key: string) {
        const next = new Set(selectedColumns);
        if (next.has(key)) {
            next.delete(key);
        } else {
            next.add(key);
        }
        selectedColumns = next;
    }

    function toggleGroup(group: string) {
        const groupCols = columns.filter((c) => c.group === group);
        const allSelected = groupCols.every((c) => selectedColumns.has(c.key));
        const next = new Set(selectedColumns);
        for (const col of groupCols) {
            if (allSelected) {
                next.delete(col.key);
            } else {
                next.add(col.key);
            }
        }
        selectedColumns = next;
    }

    function isGroupSelected(group: string): boolean {
        const groupCols = columns.filter((c) => c.group === group);
        return groupCols.length > 0 && groupCols.every((c) => selectedColumns.has(c.key));
    }

    function isGroupPartial(group: string): boolean {
        const groupCols = columns.filter((c) => c.group === group);
        const count = groupCols.filter((c) => selectedColumns.has(c.key)).length;
        return count > 0 && count < groupCols.length;
    }

    async function download() {
        const selectedKeys = [...selectedColumns];
        if (selectedKeys.length === 0) return;

        downloading = true;
        try {
            const filename = runCount === 1
                ? `export.${format}`
                : `export_${runCount}_runs.${format}`;

            await api.postDownloadBlob(
                '/science/export/download',
                {
                    run_ids: runIds,
                    format,
                    layout,
                    columns: selectedKeys,
                },
                filename,
            );
            saveExportSettings(format, layout, selectedKeys);
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Download failed';
        } finally {
            downloading = false;
        }
    }

    async function copyToClipboard() {
        if (rows.length === 0 || selectedColumns.size === 0) return;

        const tsv = buildTsv(columns, rows, selectedColumns);
        await navigator.clipboard.writeText(tsv);
        saveExportSettings(format, layout, [...selectedColumns]);
        copyFeedback = true;
        setTimeout(() => { copyFeedback = false; }, 2000);
    }

    function applyPreset(preset: ExportPreset) {
        format = preset.format;
        layout = preset.layout;
        pendingPresetGroups = preset.columnGroups;
        presetOpen = false;
    }

    function selectAll() {
        selectedColumns = new Set(columns.map((c) => c.key));
    }

    function selectNone() {
        selectedColumns = new Set();
    }

    function goBack() {
        history.back();
    }
</script>

<div class="min-h-screen bg-slate-50 flex flex-col">
    <!-- Top bar -->
    <header class="bg-white border-b border-slate-200 px-4 sm:px-6 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0">
        <div class="flex items-center gap-4">
            <button
                onclick={goBack}
                class="text-sm text-slate-500 hover:text-slate-700 font-medium flex items-center gap-1 min-h-11 min-w-11 sm:min-h-0 sm:min-w-0 transition-colors duration-150 cursor-pointer"
            >
                <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M19 12H5M12 19l-7-7 7-7" />
                </svg>
                Back
            </button>
            <div class="h-5 w-px bg-slate-200"></div>
            <div>
                <h1 class="text-lg font-semibold text-slate-900">Export Run Data</h1>
                {#if !loading}
                    <p class="text-xs text-slate-500">
                        {runCount} run{runCount !== 1 ? 's' : ''} &middot;
                        {rows.length} row{rows.length !== 1 ? 's' : ''} &middot;
                        {selectedColumns.size} of {columns.length} columns selected
                    </p>
                {/if}
            </div>
        </div>

        <div class="flex items-center gap-3 flex-wrap">
            <!-- Format selector -->
            <div class="flex items-center gap-2">
                <span class="text-xs font-medium text-slate-500 uppercase tracking-wide hidden sm:inline">Format</span>
                <div class="flex rounded-lg border border-slate-200 overflow-hidden">
                    <button
                        class="px-3 py-1.5 text-xs font-medium transition-colors duration-150 cursor-pointer min-h-11 sm:min-h-0 {format === 'csv' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}"
                        onclick={() => { format = 'csv'; }}
                    >CSV</button>
                    <button
                        class="px-3 py-1.5 text-xs font-medium transition-colors duration-150 cursor-pointer min-h-11 sm:min-h-0 {format === 'xlsx' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}"
                        onclick={() => { format = 'xlsx'; }}
                    >Excel</button>
                    <button
                        class="px-3 py-1.5 text-xs font-medium transition-colors duration-150 cursor-pointer min-h-11 sm:min-h-0 {format === 'json' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}"
                        onclick={() => { format = 'json'; }}
                    >JSON</button>
                </div>
            </div>

            <!-- Copy to Clipboard -->
            <button
                class="px-4 py-2 bg-white text-slate-700 text-sm font-medium rounded-lg border border-slate-200 hover:bg-slate-50 transition-colors duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 min-h-11 sm:min-h-0"
                disabled={selectedColumns.size === 0 || rows.length === 0}
                onclick={copyToClipboard}
            >
                {#if copyFeedback}
                    <svg class="w-4 h-4 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M20 6 9 17l-5-5" />
                    </svg>
                    Copied!
                {:else}
                    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                    </svg>
                    Copy
                {/if}
            </button>

            <!-- Download -->
            <button
                class="px-5 py-2 bg-slate-800 text-white text-sm font-medium rounded-lg hover:bg-slate-700 transition-colors duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 min-h-11 sm:min-h-0"
                disabled={selectedColumns.size === 0 || rows.length === 0 || downloading}
                onclick={download}
            >
                {#if downloading}
                    <svg class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 2v4m0 12v4m-7.07-3.93l2.83-2.83m8.48-8.48l2.83-2.83M2 12h4m12 0h4m-3.93 7.07l-2.83-2.83M7.76 7.76 4.93 4.93" />
                    </svg>
                {:else}
                    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                {/if}
                Download {format.toUpperCase()}
            </button>
        </div>
    </header>

    <!-- Toolbar -->
    <div class="bg-white border-b border-slate-100 px-4 sm:px-6 py-2.5 flex flex-wrap items-center gap-3 sm:gap-6 shrink-0">
        <!-- Quick Setup presets -->
        <div class="relative">
            <button
                class="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 flex items-center gap-1.5 transition-colors duration-150 cursor-pointer"
                onclick={() => { presetOpen = !presetOpen; }}
            >
                Quick Setup
                <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="m6 9 6 6 6-6" />
                </svg>
            </button>
            {#if presetOpen}
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div
                    class="fixed inset-0 z-10"
                    onclick={() => { presetOpen = false; }}
                    onkeydown={(e) => { if (e.key === 'Escape') presetOpen = false; }}
                ></div>
                <div class="absolute top-full left-0 mt-1 w-56 bg-white rounded-lg border border-slate-200 shadow-lg z-20 py-1">
                    {#each PRESETS as preset}
                        <button
                            class="w-full text-left px-3 py-2 hover:bg-slate-50 transition-colors duration-150 cursor-pointer"
                            onclick={() => applyPreset(preset)}
                        >
                            <div class="text-xs font-medium text-slate-700">{preset.label}</div>
                            <div class="text-[11px] text-slate-400">{preset.description}</div>
                        </button>
                    {/each}
                </div>
            {/if}
        </div>

        <div class="h-5 w-px bg-slate-200"></div>

        <!-- Layout toggle -->
        <div class="flex items-center gap-2">
            <span class="text-xs font-medium text-slate-500 uppercase tracking-wide">Layout</span>
            <div class="flex rounded-lg border border-slate-200 overflow-hidden">
                <button
                    class="px-3 py-1.5 text-xs font-medium transition-colors duration-150 cursor-pointer {layout === 'long' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}"
                    onclick={() => { layout = 'long'; }}
                >
                    Long
                </button>
                <button
                    class="px-3 py-1.5 text-xs font-medium transition-colors duration-150 cursor-pointer {layout === 'wide' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}"
                    onclick={() => { layout = 'wide'; }}
                >
                    Wide
                </button>
            </div>
            <span class="text-[11px] text-slate-400 ml-1">
                {layout === 'long' ? 'One row per parameter (best for SAS/Prism)' : 'One row per step (best for Excel)'}
            </span>
        </div>

        <div class="h-5 w-px bg-slate-200"></div>

        <!-- Column groups -->
        <div class="flex items-center gap-2">
            <span class="text-xs font-medium text-slate-500 uppercase tracking-wide">Columns</span>
            {#each Object.entries(columnGroups) as [group, cols]}
                <button
                    class="px-2.5 py-1 text-xs font-medium rounded-full border transition-colors duration-150 cursor-pointer
                        {isGroupSelected(group)
                            ? 'bg-slate-800 text-white border-slate-800'
                            : isGroupPartial(group)
                                ? 'bg-slate-200 text-slate-700 border-slate-300'
                                : 'bg-white text-slate-500 border-slate-200 hover:border-slate-300'}"
                    onclick={() => toggleGroup(group)}
                    title="{cols.length} columns"
                >
                    {groupLabels[group] || group}
                </button>
            {/each}
            <button
                class="text-xs text-slate-400 hover:text-slate-600 transition-colors duration-150 cursor-pointer ml-1"
                onclick={selectAll}
            >All</button>
            <span class="text-slate-300">|</span>
            <button
                class="text-xs text-slate-400 hover:text-slate-600 transition-colors duration-150 cursor-pointer"
                onclick={selectNone}
            >None</button>
        </div>
    </div>

    <!-- Table -->
    <div class="flex-1 overflow-auto">
        {#if loading}
            <LoadingSpinner message="Loading preview..." size="sm" />
        {:else if error}
            <div class="flex flex-col items-center justify-center py-32 gap-3">
                <div class="text-sm text-red-500">{error}</div>
                <button
                    class="text-sm text-slate-500 hover:text-slate-700 underline transition-colors duration-150 cursor-pointer"
                    onclick={loadPreview}
                >Retry</button>
            </div>
        {:else if runIds.length === 0}
            <div class="flex flex-col items-center justify-center py-32 gap-3">
                <div class="text-sm text-slate-400">No runs specified.</div>
                <button
                    class="text-sm text-slate-500 hover:text-slate-700 underline transition-colors duration-150 cursor-pointer"
                    onclick={goBack}
                >Go back</button>
            </div>
        {:else if rows.length === 0}
            <div class="flex items-center justify-center py-32">
                <div class="text-sm text-slate-400">No data to export.</div>
            </div>
        {:else}
            <Table.Root class="text-xs">
                <Table.Header class="sticky top-0 z-10 bg-muted">
                    <Table.Row>
                        <Table.Head class="text-center w-[50px] text-muted-foreground">
                            #
                        </Table.Head>
                        {#each visibleColumns as col}
                            <Table.Head>
                                <button
                                    class="flex items-center gap-1.5 hover:text-red-500 group transition-colors duration-150 cursor-pointer"
                                    onclick={() => toggleColumn(col.key)}
                                    title="Hide '{col.label}' column"
                                >
                                    <span>{col.label}</span>
                                    <svg class="w-3 h-3 text-muted-foreground/40 group-hover:text-red-400 transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M18 6 6 18M6 6l12 12" />
                                    </svg>
                                </button>
                            </Table.Head>
                        {/each}
                    </Table.Row>
                </Table.Header>
                <Table.Body>
                    {#each pagedRows as row, i}
                        <Table.Row class={i % 2 === 0 ? '' : 'bg-muted/30'}>
                            <Table.Cell class="text-center text-muted-foreground font-mono">
                                {previewPage * PAGE_SIZE + i + 1}
                            </Table.Cell>
                            {#each visibleColumns as col}
                                <Table.Cell class="max-w-[250px] truncate" title={String(row[col.key] ?? '')}>
                                    {#if col.key === 'edited'}
                                        <span class="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium {row[col.key] ? 'bg-amber-100 text-amber-700' : 'bg-muted text-muted-foreground'}">
                                            {row[col.key] ? 'Yes' : 'No'}
                                        </span>
                                    {:else}
                                        {row[col.key] ?? ''}
                                    {/if}
                                </Table.Cell>
                            {/each}
                        </Table.Row>
                    {/each}
                </Table.Body>
            </Table.Root>
        {/if}
    </div>

    <!-- Footer / Pagination -->
    {#if rows.length > 0}
        <div class="bg-white border-t border-slate-200 px-4 sm:px-6 py-2.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 shrink-0">
            <span class="text-xs text-slate-400">
                Showing {previewPage * PAGE_SIZE + 1}–{Math.min((previewPage + 1) * PAGE_SIZE, rows.length)} of {rows.length} rows
            </span>
            {#if totalPages > 1}
                <div class="flex items-center gap-2">
                    <button
                        class="px-2.5 py-1 text-xs font-medium text-slate-500 hover:text-slate-700 border border-slate-200 rounded hover:bg-slate-50 transition-colors duration-150 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                        disabled={previewPage === 0}
                        onclick={() => previewPage--}
                    >Prev</button>
                    <span class="text-xs text-slate-400 min-w-[80px] text-center">
                        Page {previewPage + 1} / {totalPages}
                    </span>
                    <button
                        class="px-2.5 py-1 text-xs font-medium text-slate-500 hover:text-slate-700 border border-slate-200 rounded hover:bg-slate-50 transition-colors duration-150 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                        disabled={previewPage >= totalPages - 1}
                        onclick={() => previewPage++}
                    >Next</button>
                </div>
            {/if}
        </div>
    {/if}
</div>
