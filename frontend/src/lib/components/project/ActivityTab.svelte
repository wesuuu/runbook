<script lang="ts">
    import { api } from "$lib/api";
    import AuditTimeline from "$lib/components/AuditTimeline.svelte";
    import { Button } from "$lib/components/ui/button";
    import type {
        AuditEntry,
        DetailLine,
    } from "$lib/components/AuditTimeline.svelte";
    import {
        stepEditSummary,
        entityBadgeClasses,
        changedKeys,
        versionSummary,
    } from "./projectUtils";

    interface Props {
        projectId: string;
    }

    let { projectId }: Props = $props();

    let activityItems = $state<any[]>([]);
    let activityTotal = $state(0);
    let activityOffset = $state(0);
    let activityLoading = $state(false);
    let activityLoaded = $state(false);
    const activityLimit = 50;

    let activityEntityFilter = $state<string[]>([]);
    let activityActionFilter = $state<string[]>([]);
    let activitySearch = $state("");
    let activitySearchDebounce: ReturnType<typeof setTimeout> | null = null;

    const allEntityTypes = ["Project", "Protocol", "Run"];
    const allActionTypes = [
        { value: "CREATE", label: "Created" },
        { value: "UPDATE", label: "Updated" },
        { value: "DELETE", label: "Deleted" },
        { value: "STEP_COMPLETE", label: "Step Complete" },
        { value: "STEP_UNCOMPLETE", label: "Step Uncomplete" },
        { value: "STEP_EDIT", label: "Step Edit" },
    ];

    const hasActiveFilters = $derived(
        activityEntityFilter.length > 0 ||
            activityActionFilter.length > 0 ||
            activitySearch.trim().length > 0,
    );

    $effect(() => {
        if (!activityLoaded) loadActivity(0);
    });

    function toggleEntityFilter(type: string) {
        if (activityEntityFilter.includes(type)) {
            activityEntityFilter = activityEntityFilter.filter(
                (t) => t !== type,
            );
        } else {
            activityEntityFilter = [...activityEntityFilter, type];
        }
        activityLoaded = false;
        loadActivity(0);
    }

    function toggleActionFilter(act: string) {
        if (activityActionFilter.includes(act)) {
            activityActionFilter = activityActionFilter.filter(
                (a) => a !== act,
            );
        } else {
            activityActionFilter = [...activityActionFilter, act];
        }
        activityLoaded = false;
        loadActivity(0);
    }

    function clearActivityFilters() {
        activityEntityFilter = [];
        activityActionFilter = [];
        activitySearch = "";
        activityLoaded = false;
        loadActivity(0);
    }

    async function loadActivity(offset: number = 0) {
        activityLoading = true;
        try {
            const params = new URLSearchParams();
            params.set("offset", String(offset));
            params.set("limit", String(activityLimit));
            if (activityEntityFilter.length > 0) {
                params.set("entity_type", activityEntityFilter.join(","));
            }
            if (activityActionFilter.length > 0) {
                params.set("action", activityActionFilter.join(","));
            }
            if (activitySearch.trim()) {
                params.set("search", activitySearch.trim());
            }
            const data: any = await api.get(
                `/projects/${projectId}/activity?${params.toString()}`,
            );
            activityItems = data.items;
            activityTotal = data.total;
            activityOffset = data.offset;
            activityLoaded = true;
        } catch (e: unknown) {
            console.error(
                "Failed to load activity:",
                e instanceof Error ? e.message : e,
            );
        } finally {
            activityLoading = false;
        }
    }
</script>

<div class="p-8">
    <!-- Filter Bar -->
    <div class="mb-6 space-y-3">
        <div class="flex flex-wrap items-center gap-3 p-2">
            <div class="flex items-center gap-1.5">
                {#each allEntityTypes as et}
                    <Button
                        variant="outline"
                        size="sm"
                        rounded="full"
                        class={"h-auto px-2.5 py-1.5 text-xs font-medium " +
                            (activityEntityFilter.includes(et)
                                ? entityBadgeClasses(et) + ' ring-1 ring-offset-1'
                                : 'bg-white text-slate-400 border-slate-200 hover:text-slate-600 hover:border-slate-300')}
                        onclick={() => toggleEntityFilter(et)}
                    >
                        {et}
                    </Button>
                {/each}
            </div>

            <div class="h-5 w-px bg-slate-200"></div>

            <div class="flex items-center gap-1.5 flex-wrap">
                {#each allActionTypes as at}
                    <Button
                        variant={activityActionFilter.includes(at.value) ? "default" : "outline"}
                        size="sm"
                        rounded="full"
                        class={"h-auto px-2.5 py-1.5 text-xs font-medium " +
                            (activityActionFilter.includes(at.value)
                                ? ''
                                : 'bg-white text-slate-400 border-slate-200 hover:text-slate-600 hover:border-slate-300')}
                        onclick={() => toggleActionFilter(at.value)}
                    >
                        {at.label}
                    </Button>
                {/each}
            </div>

            <div class="ml-auto flex items-center gap-2">
                {#if hasActiveFilters}
                    <Button
                        variant="link"
                        size="sm"
                        class="h-auto p-0 text-xs text-slate-400 hover:text-slate-600"
                        onclick={clearActivityFilters}
                    >
                        Clear filters
                    </Button>
                {/if}
                <div class="relative">
                    <input
                        type="text"
                        placeholder="Search activity..."
                        class="w-48 pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-slate-400 focus:border-slate-400"
                        bind:value={activitySearch}
                        oninput={() => {
                            if (activitySearchDebounce)
                                clearTimeout(activitySearchDebounce);
                            activitySearchDebounce = setTimeout(() => {
                                activityLoaded = false;
                                loadActivity(0);
                            }, 400);
                        }}
                    />
                    <svg
                        class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    >
                        <circle cx="11" cy="11" r="8" /><path
                            d="m21 21-4.3-4.3"
                        />
                    </svg>
                </div>
            </div>
        </div>
    </div>

    {#if activityLoading && !activityLoaded}
        <div
            class="flex items-center justify-center py-16 text-sm text-slate-400"
        >
            Loading activity...
        </div>
    {:else if activityItems.length === 0}
        <div
            class="flex flex-col items-center justify-center py-16 text-center gap-2"
        >
            <div class="w-12 h-12 text-slate-300 mb-2">
                <svg
                    class="w-full h-full"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    ><path
                        d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
                    /></svg
                >
            </div>
            {#if hasActiveFilters}
                <p class="text-[15px] font-semibold text-slate-600">
                    No matching activity
                </p>
                <p class="text-[13px] text-slate-400">
                    Try adjusting your filters or search term.
                </p>
                <Button
                    variant="link"
                    size="sm"
                    class="mt-2 h-auto p-0 text-xs text-slate-500 hover:text-slate-700"
                    onclick={clearActivityFilters}
                >
                    Clear all filters
                </Button>
            {:else}
                <p class="text-[15px] font-semibold text-slate-600">
                    No activity yet
                </p>
                <p class="text-[13px] text-slate-400">
                    Changes to this project and its protocols and runs will
                    appear here.
                </p>
            {/if}
        </div>
    {:else}
        <AuditTimeline
            entries={activityItems}
            total={activityTotal}
            offset={activityOffset}
            limit={activityLimit}
            loading={activityLoading}
            showEntityBadge={true}
            onPageChange={(newOffset) => loadActivity(newOffset)}
            getDetails={(entry) => {
                const c = entry.changes ?? {};
                const lines: DetailLine[] = [];
                const vs = versionSummary(entry);
                if (vs) lines.push({ label: "Version", value: vs });
                if (
                    entry.action === "STEP_EDIT" &&
                    c.step_name &&
                    c.field_label
                ) {
                    lines.push({ label: "Step", value: c.step_name });
                    lines.push({
                        label: c.field_label,
                        value: String(c.new_value ?? ""),
                        oldValue: String(c.old_value ?? ""),
                    });
                } else if (entry.action === "UPDATE" && c) {
                    const keys = changedKeys(c);
                    if (keys.includes("status"))
                        lines.push({ label: "Status", value: c.status });
                    else if (keys.length > 0)
                        lines.push({
                            label: "Changed",
                            value: keys.join(", "),
                        });
                } else if (entry.action === "STEP_COMPLETE" && c.step_name) {
                    lines.push({
                        label: "Step",
                        value: c.step_name ?? c.step_id,
                    });
                } else if (entry.action === "NOTE_ADDED" && c.content) {
                    lines.push({ label: "Content", value: c.content });
                } else if (
                    (entry.action === "ATTACHMENT_UPLOADED" ||
                        entry.action === "ATTACHMENT_DELETED") &&
                    c.filename
                ) {
                    lines.push({ label: "File", value: c.filename });
                }
                return lines;
            }}
        />
    {/if}
</div>
