<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { paths } from '$lib/paths';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import ErrorAlert from '$lib/components/ui/error-alert.svelte';
    import RunProgressBar from '$lib/components/experiment/RunProgressBar.svelte';
    import ExperimentCreateModal from '$lib/components/experiment/ExperimentCreateModal.svelte';
    import type { Experiment } from '$lib/schemas/experiments';
    import {
        shortId,
        formatDate,
        experimentStatusClasses,
        experimentStatusLabel,
    } from '$lib/components/project/projectUtils';

    interface ExperimentRow {
        id: string;
        slug: string;
        name: string;
        objective: string | null;
        project_id: string;
        project_slug: string;
        project_name: string;
        lifecycle_status: string;
        run_count: number;
        run_summaries: { status: string; outcome: string | null }[];
        owner: { id: string; name: string; initials: string } | null;
        created_at: string;
        updated_at: string;
    }

    let experiments = $state<ExperimentRow[]>([]);
    let projects = $state<{ id: string; slug: string; name: string }[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let createOpen = $state(false);

    // Filter state.
    const FILTERS = ['All', 'In progress', 'Complete', 'Draft'] as const;
    let activeFilter = $state<(typeof FILTERS)[number]>('All');
    let query = $state('');

    async function load() {
        loading = true;
        error = null;
        try {
            // TODO(F-0093 follow-up): add ExperimentSummarySchema and pass { schema } when defined.
            const org = getCurrentOrg();
            const projectsQuery = org ? `?organization_id=${org.id}` : '';
            const [exps, projs] = await Promise.all([
                api.get('/experiments') as Promise<ExperimentRow[]>,
                api.get(`/projects${projectsQuery}`) as Promise<{ id: string; slug: string; name: string }[]>,
            ]);
            experiments = exps;
            projects = projs;
        } catch (e) {
            error = e instanceof Error ? e.message : 'Failed to load experiments.';
        } finally {
            loading = false;
        }
    }

    onMount(load);

    function onCreated(exp: Experiment) {
        goto(paths.experiment(exp.project_slug, exp.slug));
    }

    // NOTE: `filtered` and `stats` below run over the full client-side list.
    // That is correct only while GET /experiments is unpaginated (§1.1). When
    // pagination lands (deferred follow-up), filtering and the stat strip must
    // move server-side or they will silently reflect only the loaded page.
    const filtered = $derived(
        experiments.filter((e) => {
            const matchesFilter =
                activeFilter === 'All' ||
                (activeFilter === 'In progress' && e.lifecycle_status === 'IN_PROGRESS') ||
                (activeFilter === 'Complete' && e.lifecycle_status === 'COMPLETE') ||
                (activeFilter === 'Draft' && e.lifecycle_status === 'DRAFT');
            const q = query.trim().toLowerCase();
            const matchesQuery =
                !q ||
                e.name.toLowerCase().includes(q) ||
                (e.objective ?? '').toLowerCase().includes(q) ||
                e.project_name.toLowerCase().includes(q);
            return matchesFilter && matchesQuery;
        }),
    );

    const stats = $derived({
        total: experiments.length,
        inProgress: experiments.filter((e) => e.lifecycle_status === 'IN_PROGRESS').length,
        runs: experiments.reduce((sum, e) => sum + e.run_count, 0),
    });
</script>

<div class="space-y-6">
    <div class="flex items-start justify-between gap-4">
        <div>
            <p class="font-mono text-xs uppercase tracking-widest text-accent">
                Investigations
            </p>
            <h1 class="mt-1 text-2xl font-semibold text-foreground">Experiments</h1>
            <p class="mt-1 text-sm text-muted-foreground">
                Every investigation across your projects — objective, runs, and status.
            </p>
        </div>
        {#if !loading && !error && projects.length > 0}
            <Button onclick={() => (createOpen = true)}>+ New experiment</Button>
        {/if}
    </div>

    {#if loading}
        <LoadingSpinner />
    {:else if error}
        <div class="space-y-2">
            <ErrorAlert message={error} />
            <Button variant="outline" size="sm" onclick={load}>Retry</Button>
        </div>
    {:else}
        <!-- Stat strip -->
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div class="rounded-lg border border-border bg-card p-4">
                <p class="text-xs text-muted-foreground">Experiments</p>
                <p class="mt-1 font-mono text-2xl font-semibold text-foreground">{stats.total}</p>
            </div>
            <div class="rounded-lg border border-border bg-card p-4">
                <p class="text-xs text-muted-foreground">In progress</p>
                <p class="mt-1 font-mono text-2xl font-semibold text-foreground">{stats.inProgress}</p>
            </div>
            <div class="rounded-lg border border-border bg-card p-4">
                <p class="text-xs text-muted-foreground">Runs across all</p>
                <p class="mt-1 font-mono text-2xl font-semibold text-foreground">{stats.runs}</p>
            </div>
        </div>

        <!-- Filter row — composed from shadcn `Button` / `Input` primitives, not
             raw <button>/<input> (conventions.md "Frontend components"). -->
        <div class="flex flex-wrap items-center gap-3">
            <div class="flex gap-1">
                {#each FILTERS as f}
                    <Button
                        variant={activeFilter === f ? 'default' : 'outline'}
                        size="sm"
                        onclick={() => (activeFilter = f)}
                    >
                        {f}
                    </Button>
                {/each}
            </div>
            <Input
                bind:value={query}
                placeholder="Search experiments…"
                class="h-9 min-w-[200px] flex-1"
            />
        </div>

        <!-- Rows -->
        {#if filtered.length === 0}
            <div class="rounded-lg border border-dashed border-border py-16 text-center">
                <p class="text-sm font-semibold text-foreground">
                    {experiments.length === 0 ? 'No experiments yet' : 'No matching experiments'}
                </p>
                <p class="mt-1 text-sm text-muted-foreground">
                    {experiments.length === 0
                        ? projects.length === 0
                            ? 'Create a project first, then start your first investigation.'
                            : 'Start your first investigation to ask a question of the data.'
                        : 'Try a different filter or search term.'}
                </p>
                {#if experiments.length === 0 && projects.length > 0}
                    <div class="mt-4">
                        <Button onclick={() => (createOpen = true)}>+ New experiment</Button>
                    </div>
                {/if}
            </div>
        {:else}
            <div class="space-y-2">
                {#each filtered as e (e.id)}
                    <a
                        href={paths.experiment(e.project_slug, e.slug)}
                        class="block rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/40"
                    >
                        <div class="flex items-start justify-between gap-4">
                            <div class="min-w-0 flex-1">
                                <div class="flex items-center gap-2">
                                    <span class="truncate font-medium text-foreground">{e.name}</span>
                                    <span class="shrink-0 font-mono text-xs text-muted-foreground">
                                        EXP-{shortId(e.id)}
                                    </span>
                                    <span
                                        class="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold cursor-help {experimentStatusClasses(
                                            e.lifecycle_status,
                                        )}"
                                        title="Status is derived from this experiment's runs — add or complete runs to advance it."
                                    >
                                        {#if e.lifecycle_status === 'IN_PROGRESS'}
                                            <span class="h-1.5 w-1.5 rounded-full bg-current"></span>
                                        {/if}
                                        {experimentStatusLabel(e.lifecycle_status)}
                                        <span class="opacity-70 font-normal">(auto)</span>
                                    </span>
                                </div>
                                {#if e.objective}
                                    <p class="mt-1 truncate text-sm text-muted-foreground">
                                        {e.objective}
                                    </p>
                                {:else}
                                    <p class="mt-1 truncate text-sm italic text-muted-foreground/70">
                                        Objective not set yet — add an objective and the first run to begin.
                                    </p>
                                {/if}
                                <div class="mt-3 max-w-md">
                                    <RunProgressBar runs={e.run_summaries} total={e.run_count} />
                                </div>
                            </div>
                            <div
                                class="flex flex-col items-end gap-1 whitespace-nowrap text-xs text-muted-foreground"
                            >
                                <span class="rounded bg-muted px-1.5 py-0.5">{e.project_name}</span>
                                <span
                                    class="flex h-6 w-6 items-center justify-center rounded-full bg-muted text-[10px] font-semibold text-muted-foreground"
                                    title={e.owner?.name ?? 'Unknown owner'}
                                >
                                    {e.owner?.initials ?? '—'}
                                </span>
                                <span>{formatDate(e.updated_at)}</span>
                            </div>
                        </div>
                    </a>
                {/each}
            </div>
        {/if}
    {/if}
</div>

<ExperimentCreateModal
    bind:open={createOpen}
    projects={projects}
    onCreated={onCreated}
/>
