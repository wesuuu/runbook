<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { getCurrentOrg, getUser } from '$lib/auth.svelte';
    import { getOrphanedActions } from '$lib/offline-db';
    import { syncNow } from '$lib/sync-manager';
    import { Button } from '$lib/components/ui/button';
    import { EmptyState } from '$lib/components/ui/empty-state';
    import { timeAgo } from '$lib/utils';
    import { fade, fly } from 'svelte/transition';
    import { blockDuration } from '$lib/transitions';
    import TourModal from '$lib/onboarding/TourModal.svelte';
    import { isWelcomeEmpty, isHydrated, markAllDismissed } from '$lib/onboarding/tourStore.svelte';
    import ActionCounters from '$lib/components/dashboard/ActionCounters.svelte';
    import LabStatusRail from '$lib/components/dashboard/LabStatusRail.svelte';
    import BlockerTag from '$lib/components/dashboard/BlockerTag.svelte';

    interface BlockerReason {
        code: string;
        label: string;
    }
    interface RunSummary {
        id: string;
        name: string;
        project_id: string;
        project_name: string;
        protocol_name: string | null;
        status: string;
        role_name: string | null;
        completed_steps: number;
        total_steps: number;
        updated_at: string;
        blockers: BlockerReason[];
    }
    interface ActivityItem {
        id: string;
        action: string;
        entity_type: string;
        entity_id: string;
        entity_name: string | null;
        actor_name: string | null;
        changes: Record<string, any>;
        created_at: string;
    }
    interface Counters {
        runs_blocked: number;
        calibrations_due: number;
        signoffs_pending: number;
        active_runs: number;
    }
    interface CalibrationItem {
        equipment_id: string;
        name: string;
        site_name: string | null;
        next_calibration_date: string | null;
        state: string;
    }
    interface SignoffItem {
        kind: string;
        entity_id: string;
        name: string;
        project_name: string | null;
        detail: string | null;
    }
    interface Dashboard {
        my_work: {
            needs_action: RunSummary[];
            in_progress: RunSummary[];
            planned: RunSummary[];
        };
        lab_status: {
            calibration: { overdue: CalibrationItem[]; due_soon: CalibrationItem[] };
            awaiting_signoff: SignoffItem[];
        };
        activity: ActivityItem[];
        counters: Counters;
    }

    let dashboard = $state<Dashboard | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    let orphanedRuns = $state<Array<{ runId: string; runName: string; count: number; dateRange: string }>>([]);
    let syncingOrphans = $state(false);
    let welcomeOpen = $state(false);
    let pulseTarget = $state<string | null>(null);

    $effect(() => {
        if (isHydrated() && isWelcomeEmpty()) welcomeOpen = true;
    });

    onMount(() => {
        loadDashboard();
        loadOrphanedQueue();
    });

    async function loadDashboard() {
        const org = getCurrentOrg();
        if (!org) {
            // No org resolved (failed /iam/organizations fetch on init, or an
            // account with no membership). Settle into the error state rather
            // than leaving the skeleton spinning forever.
            error = 'No organization available. Try reloading the page.';
            loading = false;
            return;
        }
        loading = true;
        error = null;
        try {
            dashboard = await api.get(`/dashboard?org_id=${org.id}`);
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load dashboard';
        } finally {
            loading = false;
        }
    }

    async function loadOrphanedQueue() {
        try {
            const grouped = await getOrphanedActions();
            orphanedRuns = [];
            for (const [runId, items] of grouped) {
                const dates = items.map((i) => new Date(i.queued_at).getTime());
                const oldest = new Date(Math.min(...dates)).toLocaleDateString();
                const newest = new Date(Math.max(...dates)).toLocaleDateString();
                orphanedRuns.push({
                    runId,
                    runName: items[0].run_name,
                    count: items.length,
                    dateRange: oldest === newest ? oldest : `${oldest} – ${newest}`,
                });
            }
        } catch (err) {
            console.warn('Failed to check offline queue:', err);
        }
    }

    async function syncOrphaned() {
        syncingOrphans = true;
        try {
            await syncNow();
            await loadOrphanedQueue();
        } finally {
            syncingOrphans = false;
        }
    }

    async function startProjectTourFromWelcome() {
        welcomeOpen = false;
        const { project_id } = await api.post<{ project_id: string }>(
            '/onboarding/tour/project/start', {},
        );
        goto(`/projects/${project_id}?tour=project`);
    }

    async function dismissWelcome() {
        welcomeOpen = false;
        await markAllDismissed();
    }

    function progressPercent(run: RunSummary): number {
        if (run.total_steps === 0) return 0;
        return Math.round((run.completed_steps / run.total_steps) * 100);
    }

    async function scrollPulse(id: string) {
        const el = document.getElementById(id);
        if (!el) return;
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        pulseTarget = id;
        await tick();
        setTimeout(() => { if (pulseTarget === id) pulseTarget = null; }, 1200);
    }

    function onCounter(key: string) {
        if (key === 'calibrations_due') goto('/settings?tab=sites');
        else if (key === 'active_runs') goto('/projects');
        else if (key === 'runs_blocked') scrollPulse('needs-action');
        else if (key === 'signoffs_pending') scrollPulse('awaiting-signoff');
    }

    function onSignoffSelect(item: SignoffItem) {
        if (item.kind === 'protocol') goto(`/protocols/${item.entity_id}`);
        else goto(`/runs/${item.entity_id}`);
    }

    const userName = $derived(getUser()?.full_name?.split(' ')[0] || 'there');
    const myWorkEmpty = $derived(
        !!dashboard &&
        dashboard.my_work.needs_action.length === 0 &&
        dashboard.my_work.in_progress.length === 0 &&
        dashboard.my_work.planned.length === 0,
    );
</script>

{#snippet runCard(run: RunSummary, accent: 'amber' | 'primary')}
    <button
        type="button"
        class="w-full card-warm rounded-xl p-4 text-left transition-all duration-150 hover:shadow-md cursor-pointer
               {accent === 'amber' ? 'border-l-3 border-l-amber-400 hover:border-l-amber-500' : 'hover:border-primary/20'}"
        onclick={() => goto(`/runs/${run.id}`)}
    >
        <div class="mb-2.5 flex items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-2">
                <span class="text-sm font-semibold text-foreground">{run.name}</span>
                {#if run.role_name}
                    <span class="rounded-md bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{run.role_name}</span>
                {/if}
                {#each run.blockers as blocker}
                    <BlockerTag {blocker} />
                {/each}
            </div>
            <span class="shrink-0 text-[11px] text-muted-foreground">{timeAgo(run.updated_at)}</span>
        </div>
        <div class="flex items-center gap-3">
            <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                    class="h-full rounded-full transition-all {accent === 'amber' ? 'bg-amber-400' : 'bg-primary'}"
                    style="width: {progressPercent(run)}%"
                ></div>
            </div>
            <span class="text-[11px] font-bold tabular-nums text-muted-foreground">
                {run.completed_steps}/{run.total_steps}
            </span>
        </div>
        <div class="mt-2 text-[11px] text-muted-foreground">
            {run.project_name}{run.protocol_name ? ` · ${run.protocol_name}` : ''}
        </div>
    </button>
{/snippet}

<div class="mx-auto max-w-6xl">
    <!-- Greeting -->
    <div class="mb-8">
        <h1 class="text-2xl font-bold tracking-tight text-foreground">{userName}'s Dashboard</h1>
        <p class="mt-1 text-sm text-muted-foreground">What needs your attention across the lab today.</p>
    </div>

    {#if loading}
        <!-- Skeleton mirrors the final layout -->
        <div in:fade={{ duration: blockDuration() }}>
            <div class="mb-10 grid grid-cols-2 gap-3 lg:grid-cols-4">
                {#each Array(4) as _}
                    <div class="card-warm h-24 animate-pulse rounded-xl"></div>
                {/each}
            </div>
            <div class="grid grid-cols-1 gap-8 lg:grid-cols-3">
                <div class="space-y-3 lg:col-span-2">
                    {#each Array(3) as _}
                        <div class="card-warm h-24 animate-pulse rounded-xl"></div>
                    {/each}
                </div>
                <div class="space-y-6">
                    {#each Array(3) as _}
                        <div class="card-warm h-40 animate-pulse rounded-xl"></div>
                    {/each}
                </div>
            </div>
        </div>
    {:else if error}
        <div in:fade={{ duration: blockDuration() }} class="flex flex-col items-center justify-center gap-4 py-32">
            <div class="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
                <span class="text-lg text-destructive">!</span>
            </div>
            <p class="text-sm text-destructive">{error}</p>
            <Button variant="link" class="text-muted-foreground" onclick={loadDashboard}>Retry</Button>
        </div>
    {:else if dashboard}
        <div in:fade={{ duration: blockDuration() }}>
            <!-- Orphaned offline-queue banner -->
            {#if orphanedRuns.length > 0}
                <div class="mb-6 rounded-xl border border-teal-200 bg-teal-50 p-4" out:fade>
                    <div class="mb-2 flex items-center justify-between">
                        <p class="text-sm font-semibold text-teal-800">Pending Offline Uploads</p>
                        <Button variant="default" size="sm" onclick={syncOrphaned} disabled={syncingOrphans}>
                            {syncingOrphans ? 'Syncing...' : 'Sync Now'}
                        </Button>
                    </div>
                    {#each orphanedRuns as orphan}
                        <p class="text-xs text-teal-700">
                            {orphan.count} item{orphan.count !== 1 ? 's' : ''} from <strong>{orphan.runName}</strong> captured {orphan.dateRange}
                        </p>
                    {/each}
                </div>
            {/if}

            <!-- Action counters -->
            <div class="mb-10">
                <ActionCounters counters={dashboard.counters} onActivate={onCounter} />
            </div>

            <!-- My Work hero + Lab Status rail -->
            <div class="grid grid-cols-1 gap-8 lg:grid-cols-3">
                <div class="space-y-6 lg:col-span-2">
                    <!-- Needs action -->
                    <section id="needs-action" class:section-pulse={pulseTarget === 'needs-action'}>
                        <h2 class="mb-3 flex items-center gap-2.5 text-xs font-bold uppercase tracking-widest text-muted-foreground">
                            <span class="h-2 w-2 rounded-full bg-amber-500"></span>
                            Needs Your Action
                            {#if dashboard.my_work.needs_action.length > 0}
                                <span class="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-600">
                                    {dashboard.my_work.needs_action.length}
                                </span>
                            {/if}
                        </h2>
                        {#if dashboard.my_work.needs_action.length > 0}
                            <div class="space-y-2.5">
                                {#each dashboard.my_work.needs_action as run (run.id)}
                                    {@render runCard(run, 'amber')}
                                {/each}
                            </div>
                        {:else}
                            <p class="text-xs text-muted-foreground">Nothing needs action right now.</p>
                        {/if}
                    </section>

                    <!-- In progress -->
                    {#if dashboard.my_work.in_progress.length > 0}
                        <section in:fly={{ y: 12, duration: blockDuration() }}>
                            <h2 class="mb-3 flex items-center gap-2.5 text-xs font-bold uppercase tracking-widest text-muted-foreground">
                                <span class="h-2 w-2 rounded-full bg-primary"></span>
                                In Progress
                                <span class="rounded-md bg-primary/8 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                                    {dashboard.my_work.in_progress.length}
                                </span>
                            </h2>
                            <div class="space-y-2.5">
                                {#each dashboard.my_work.in_progress as run (run.id)}
                                    {@render runCard(run, 'primary')}
                                {/each}
                            </div>
                        </section>
                    {/if}

                    <!-- Planned -->
                    {#if dashboard.my_work.planned.length > 0}
                        <section in:fly={{ y: 12, duration: blockDuration() }}>
                            <h2 class="mb-3 flex items-center gap-2.5 text-xs font-bold uppercase tracking-widest text-muted-foreground">
                                <span class="h-2 w-2 rounded-full bg-muted-foreground/40"></span>
                                Planned
                                <span class="rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                                    {dashboard.my_work.planned.length}
                                </span>
                            </h2>
                            <div class="card-warm divide-y divide-border/60 overflow-hidden rounded-xl">
                                {#each dashboard.my_work.planned as run (run.id)}
                                    <button
                                        type="button"
                                        class="group flex w-full items-center justify-between p-3.5 text-left transition-colors duration-150 hover:bg-muted/40 cursor-pointer"
                                        onclick={() => goto(`/runs/${run.id}`)}
                                    >
                                        <div>
                                            <span class="text-sm font-medium text-foreground">{run.name}</span>
                                            <span class="ml-2 text-[11px] text-muted-foreground">{run.project_name}</span>
                                        </div>
                                        <span class="text-[11px] font-semibold text-muted-foreground transition-colors group-hover:text-primary">Setup →</span>
                                    </button>
                                {/each}
                            </div>
                        </section>
                    {/if}

                    {#if myWorkEmpty}
                        <div class="card-warm rounded-xl">
                            <EmptyState
                                title="No runs yet"
                                description="Get started by creating a project and running a protocol."
                                actionLabel="View Projects"
                                onAction={() => goto('/projects')}
                                secondaryActionLabel="Take the tour"
                                secondaryOnAction={() => (welcomeOpen = true)}
                                class="py-14"
                            />
                        </div>
                    {/if}
                </div>

                <!-- Lab Status rail -->
                <div
                    in:fly={{ y: 12, duration: blockDuration(), delay: 100 }}
                    class:section-pulse={pulseTarget === 'awaiting-signoff'}
                >
                    <LabStatusRail
                        calibration={dashboard.lab_status.calibration}
                        awaitingSignoff={dashboard.lab_status.awaiting_signoff}
                        activity={dashboard.activity}
                        onCalibrationViewAll={() => goto('/settings?tab=sites')}
                        {onSignoffSelect}
                    />
                </div>
            </div>
        </div>
    {/if}
</div>

<TourModal
    bind:open={welcomeOpen}
    title="Welcome to Batchrite"
    description="Want a quick tour of your workspace? Start with how projects are laid out."
    primaryLabel="Check out how projects are laid out"
    secondaryLabel="Dismiss"
    onPrimary={startProjectTourFromWelcome}
    onSecondary={dismissWelcome}
/>

<style>
    .section-pulse {
        animation: section-pulse 1.2s ease-out;
    }
    @keyframes section-pulse {
        0% { background-color: color-mix(in oklch, var(--color-amber-200, #fde68a) 55%, transparent); }
        100% { background-color: transparent; }
    }
</style>
