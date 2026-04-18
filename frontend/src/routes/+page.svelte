<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { getCurrentOrg, getUser } from '$lib/auth.svelte';
    import { getOrphanedActions, type QueuedAction } from '$lib/offline-db';
    import { syncNow } from '$lib/sync-manager';
    import CompletionChart from '$lib/components/CompletionChart.svelte';
    import { Button } from '$lib/components/ui/button';
    import { EmptyState } from '$lib/components/ui/empty-state';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import { toast } from '$lib/toast';
    import { timeAgo } from '$lib/utils';
    import { fade, fly } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { blockDuration, listDuration } from '$lib/transitions';
    import TourModal from '$lib/onboarding/TourModal.svelte';
    import { isWelcomeEmpty, isHydrated, markAllDismissed } from '$lib/onboarding/tourStore.svelte';

    type RunSummary = {
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
    };

    type ActivityItem = {
        id: string;
        action: string;
        entity_type: string;
        entity_id: string;
        entity_name: string | null;
        actor_name: string | null;
        changes: Record<string, any>;
        created_at: string;
    };

    type Counters = {
        active_runs: number;
        completed_this_week: number;
        planned_runs: number;
        team_members: number | null;
        active_projects: number | null;
        total_protocols: number | null;
    };

    type CompletionTrendItem = { date: string; count: number };

    type PendingAnalyses = {
        total_images: number;
        total_runs: number;
    };

    type Dashboard = {
        my_work: {
            needs_action: RunSummary[];
            active_runs: RunSummary[];
            recently_completed: RunSummary[];
            planned_runs: RunSummary[];
        };
        activity: ActivityItem[];
        counters: Counters;
        completion_trend: CompletionTrendItem[];
        pending_analyses: PendingAnalyses | null;
        is_admin: boolean;
    };

    let dashboard = $state<Dashboard | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let trendDays = $state(7);

    // Activity feed pagination
    let activityItems = $state<ActivityItem[]>([]);
    let activityTotal = $state(0);
    let activityLoading = $state(false);

    let orphanedRuns = $state<Array<{ runId: string; runName: string; count: number; dateRange: string }>>([]);
    let syncingOrphans = $state(false);

    let welcomeOpen = $state(false);

    $effect(() => {
        if (isHydrated() && isWelcomeEmpty()) {
            welcomeOpen = true;
        }
    });

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

    onMount(() => {
        loadDashboard();
        loadOrphanedQueue();
    });

    async function loadOrphanedQueue() {
        try {
            const grouped = await getOrphanedActions();
            orphanedRuns = [];
            for (const [runId, items] of grouped) {
                const dates = items.map((i) => new Date(i.queued_at).getTime());
                const oldest = new Date(Math.min(...dates)).toLocaleDateString();
                const newest = new Date(Math.max(...dates)).toLocaleDateString();
                const dateRange = oldest === newest ? oldest : `${oldest} – ${newest}`;
                orphanedRuns.push({
                    runId,
                    runName: items[0].run_name,
                    count: items.length,
                    dateRange,
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

    async function loadDashboard() {
        const org = getCurrentOrg();
        if (!org) return;

        loading = true;
        error = null;
        try {
            const data: Dashboard = await api.get(`/dashboard?org_id=${org.id}&trend_days=${trendDays}`);
            dashboard = data;
            activityItems = data.activity;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load dashboard';
        } finally {
            loading = false;
        }
    }

    function toggleTrendDays() {
        trendDays = trendDays === 7 ? 14 : 7;
        loadDashboard();
    }

    async function loadMoreActivity() {
        const org = getCurrentOrg();
        if (!org || activityLoading) return;

        activityLoading = true;
        try {
            const resp: any = await api.get(
                `/dashboard/activity?org_id=${org.id}&offset=${activityItems.length}&limit=20`
            );
            activityItems = [...activityItems, ...resp.items];
            activityTotal = resp.total;
        } catch {
            toast.warning('Failed to load more activity');
        } finally {
            activityLoading = false;
        }
    }

    function progressPercent(run: RunSummary): number {
        if (run.total_steps === 0) return 0;
        return Math.round((run.completed_steps / run.total_steps) * 100);
    }

    function formatDate(dateStr: string): string {
        return new Date(dateStr).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
        });
    }

    function activityVerb(item: ActivityItem): string {
        const t = item.entity_type;
        const a = item.action;
        if (t === 'Run' && a === 'UPDATE') {
            const newStatus = item.changes?.status;
            if (newStatus === 'ACTIVE') return 'started run';
            if (newStatus === 'COMPLETED') return 'completed run';
            if (newStatus === 'EDITED') return 'edited run';
            return 'updated run';
        }
        if (t === 'Run' && a === 'CREATE') return 'created run';
        if (t === 'Protocol' && a === 'CREATE') return 'created protocol';
        if (t === 'Protocol' && a === 'UPDATE') return 'updated protocol';
        if (t === 'Project' && a === 'CREATE') return 'created project';
        if (t === 'Project' && a === 'UPDATE') return 'updated project';
        if (a === 'STEP_COMPLETE') return 'completed a step in';
        if (a === 'STEP_UNCOMPLETE') return 'uncompleted a step in';
        if (a === 'STEP_EDIT') return 'edited a step in';
        if (t === 'RunRoleAssignment' && a === 'CREATE') return 'assigned a role in';
        if (t === 'RunRoleAssignment' && a === 'DELETE') return 'removed a role in';
        return `${a.toLowerCase()} ${t.toLowerCase()}`;
    }

    function activityLink(item: ActivityItem): string {
        if (item.entity_type === 'Run' || item.entity_type === 'RunRoleAssignment') {
            return `/runs/${item.entity_id}`;
        }
        if (item.entity_type === 'Protocol') {
            return `/protocols/${item.entity_id}`;
        }
        if (item.entity_type === 'Project') {
            return `/projects/${item.entity_id}`;
        }
        return '#';
    }

    function actorInitials(name: string | null): string {
        if (!name) return '?';
        const parts = name.trim().split(/\s+/);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        return name[0].toUpperCase();
    }

    const actorColors = ['bg-primary/15 text-primary', 'bg-accent/15 text-accent', 'bg-emerald-100 text-emerald-700', 'bg-violet-100 text-violet-700', 'bg-rose-100 text-rose-700'];

    function actorColor(name: string | null): string {
        if (!name) return actorColors[0];
        let hash = 0;
        for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
        return actorColors[Math.abs(hash) % actorColors.length];
    }

    function activityIcon(item: ActivityItem): string {
        const a = item.action;
        const t = item.entity_type;
        if (a === 'CREATE') return '+';
        if (a === 'STEP_COMPLETE') return '\u2713';
        if (t === 'Run' && item.changes?.status === 'ACTIVE') return '\u25B6';
        if (t === 'Run' && item.changes?.status === 'COMPLETED') return '\u2713';
        return '\u2022';
    }

    const userName = $derived(getUser()?.full_name?.split(' ')[0] || 'there');

    const counterData = $derived.by(() => {
        if (!dashboard) return [];
        const base = [
            { label: 'Active Runs', value: dashboard.counters.active_runs, color: 'text-primary', link: '/projects' },
            { label: 'Completed', value: dashboard.counters.completed_this_week, color: 'text-emerald-600', link: null },
            { label: 'Planned', value: dashboard.counters.planned_runs, color: 'text-foreground', link: null },
        ];
        if (dashboard.is_admin) {
            base.push(
                { label: 'Members', value: dashboard.counters.team_members ?? 0, color: 'text-foreground', link: null },
                { label: 'Projects', value: dashboard.counters.active_projects ?? 0, color: 'text-foreground', link: null },
                { label: 'Protocols', value: dashboard.counters.total_protocols ?? 0, color: 'text-foreground', link: null },
            );
        }
        return base;
    });
</script>

{#if loading}
    <div in:fade={{ duration: blockDuration() }}>
        <LoadingSpinner message="Loading dashboard..." />
    </div>
{:else if error}
    <div in:fade={{ duration: blockDuration() }} class="flex flex-col items-center justify-center py-32 gap-4">
        <div class="w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center">
            <span class="text-destructive text-lg">!</span>
        </div>
        <p class="text-sm text-destructive">{error}</p>
        <Button variant="link" class="text-muted-foreground" onclick={loadDashboard}>
            Retry
        </Button>
    </div>
{:else if dashboard}
    <div in:fade={{ duration: blockDuration() }} class="max-w-6xl mx-auto">
        <!-- Greeting -->
        <div class="mb-8">
            <h1 class="text-2xl font-bold tracking-tight text-foreground">
                {userName}'s Dashboard
            </h1>
            <p class="text-sm text-muted-foreground mt-1">What's happening across your projects today.</p>
        </div>

        <!-- Counters -->
        <div class="grid grid-cols-2 sm:grid-cols-3 {dashboard.is_admin ? 'md:grid-cols-6' : 'sm:grid-cols-3'} gap-3 mb-10">
            {#each counterData as counter, i (counter.label)}
                <button
                    type="button"
                    class="card-warm rounded-xl p-4 text-left hover:border-primary/30 hover:shadow-md transition-all duration-150 group relative overflow-hidden {counter.link ? 'cursor-pointer' : 'cursor-default'}"
                    onclick={() => counter.link ? goto(counter.link) : null}
                    animate:flip={{ duration: listDuration() }}
                    in:fly={{ y: 12, duration: blockDuration(), delay: i * 60 }}
                >
                    <div class="text-3xl font-bold {counter.color} tracking-tight">{counter.value}</div>
                    <div class="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mt-1.5">{counter.label}</div>
                    {#if counter.link}
                        <div class="absolute top-3 right-3 text-muted-foreground/30 group-hover:text-muted-foreground/60 transition-colors">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M7 17L17 7M17 7H7M17 7v10"/></svg>
                        </div>
                    {/if}
                </button>
            {/each}
        </div>

        <!-- Completion Trend Chart -->
        <CompletionChart trend={dashboard.completion_trend} onToggleDays={toggleTrendDays} />

        <!-- Main grid: My Work + Activity -->
        <div class="grid grid-cols-1 lg:grid-cols-5 gap-8">
            <!-- My Work (3/5 width) -->
            <div class="lg:col-span-3 space-y-6">
                <!-- Orphaned Offline Queue Items -->
                {#if orphanedRuns.length > 0}
                    <section in:fly={{ y: 12, duration: blockDuration(), delay: 50 }} out:fade={{ duration: blockDuration() }}>
                        <div class="bg-teal-50 border border-teal-200 rounded-xl p-4">
                            <div class="flex items-center justify-between mb-2">
                                <p class="text-sm font-semibold text-teal-800">
                                    Pending Offline Uploads
                                </p>
                                <Button
                                    variant="default"
                                    size="sm"
                                    onclick={syncOrphaned}
                                    disabled={syncingOrphans}
                                >
                                    {syncingOrphans ? 'Syncing...' : 'Sync Now'}
                                </Button>
                            </div>
                            {#each orphanedRuns as orphan}
                                <p class="text-xs text-teal-700">
                                    {orphan.count} item{orphan.count !== 1 ? 's' : ''} from <strong>{orphan.runName}</strong> captured {orphan.dateRange}
                                </p>
                            {/each}
                        </div>
                    </section>
                {/if}

                <!-- Pending Image Analyses -->
                {#if dashboard.pending_analyses}
                    <section in:fly={{ y: 12, duration: blockDuration(), delay: 100 }} out:fade={{ duration: blockDuration() }}>
                        <div class="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center justify-between">
                            <div>
                                <p class="text-sm font-semibold text-amber-800">
                                    {dashboard.pending_analyses.total_images} image{dashboard.pending_analyses.total_images !== 1 ? 's' : ''} pending analysis across {dashboard.pending_analyses.total_runs} run{dashboard.pending_analyses.total_runs !== 1 ? 's' : ''}
                                </p>
                                <p class="text-xs text-amber-600 mt-0.5">
                                    Captured images that haven't been analyzed by AI yet
                                </p>
                            </div>
                        </div>
                    </section>
                {/if}

                <!-- Needs Action -->
                {#if dashboard.my_work.needs_action.length > 0}
                    <section in:fly={{ y: 12, duration: blockDuration(), delay: 200 }} out:fade={{ duration: blockDuration() }}>
                        <h2 class="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3 flex items-center gap-2.5">
                            <span class="w-2 h-2 bg-amber-500 rounded-full status-pulse"></span>
                            Needs Your Action
                            <span class="text-[10px] font-medium text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded-md">{dashboard.my_work.needs_action.length}</span>
                        </h2>
                        <div class="space-y-2.5">
                            {#each dashboard.my_work.needs_action as run}
                                <button
                                    type="button"
                                    class="w-full card-warm rounded-xl p-4 text-left border-l-3 border-l-amber-400 hover:border-l-amber-500 hover:shadow-md transition-all duration-150 cursor-pointer"
                                    onclick={() => goto(`/runs/${run.id}`)}
                                >
                                    <div class="flex items-center justify-between mb-2.5">
                                        <div class="flex items-center gap-2.5">
                                            <span class="font-semibold text-sm text-foreground">{run.name}</span>
                                            {#if run.role_name}
                                                <span class="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-md bg-primary/8 text-primary">{run.role_name}</span>
                                            {/if}
                                        </div>
                                        <span class="text-[11px] text-muted-foreground">{timeAgo(run.updated_at)}</span>
                                    </div>
                                    <div class="flex items-center gap-3">
                                        <div class="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                                            <div
                                                class="h-full bg-amber-400 rounded-full transition-all"
                                                style="width: {progressPercent(run)}%"
                                            ></div>
                                        </div>
                                        <span class="text-[11px] font-bold text-muted-foreground tabular-nums">
                                            {run.completed_steps}/{run.total_steps}
                                        </span>
                                    </div>
                                    <div class="text-[11px] text-muted-foreground mt-2">
                                        {run.project_name}{run.protocol_name ? ` \u00B7 ${run.protocol_name}` : ''}
                                    </div>
                                </button>
                            {/each}
                        </div>
                    </section>
                {/if}

                <!-- Active Runs -->
                {#if dashboard.my_work.active_runs.length > 0}
                    <section in:fly={{ y: 12, duration: blockDuration(), delay: 300 }} out:fade={{ duration: blockDuration() }}>
                        <h2 class="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3 flex items-center gap-2.5">
                            <span class="w-2 h-2 bg-primary rounded-full"></span>
                            Active Runs
                            <span class="text-[10px] font-medium text-primary bg-primary/8 px-1.5 py-0.5 rounded-md">{dashboard.my_work.active_runs.length}</span>
                        </h2>
                        <div class="space-y-2.5">
                            {#each dashboard.my_work.active_runs as run}
                                <button
                                    type="button"
                                    class="w-full card-warm rounded-xl p-4 text-left hover:shadow-md hover:border-primary/20 transition-all duration-150 cursor-pointer"
                                    onclick={() => goto(`/runs/${run.id}`)}
                                >
                                    <div class="flex items-center justify-between mb-2.5">
                                        <div class="flex items-center gap-2.5">
                                            <span class="font-semibold text-sm text-foreground">{run.name}</span>
                                            {#if run.role_name}
                                                <span class="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-md bg-muted text-muted-foreground">{run.role_name}</span>
                                            {/if}
                                        </div>
                                        <span class="text-[11px] text-muted-foreground">{timeAgo(run.updated_at)}</span>
                                    </div>
                                    <div class="flex items-center gap-3">
                                        <div class="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                                            <div
                                                class="h-full bg-primary rounded-full transition-all"
                                                style="width: {progressPercent(run)}%"
                                            ></div>
                                        </div>
                                        <span class="text-[11px] font-bold text-muted-foreground tabular-nums">
                                            {run.completed_steps}/{run.total_steps}
                                        </span>
                                    </div>
                                    <div class="text-[11px] text-muted-foreground mt-2">
                                        {run.project_name}{run.protocol_name ? ` \u00B7 ${run.protocol_name}` : ''}
                                    </div>
                                </button>
                            {/each}
                        </div>
                    </section>
                {/if}

                <!-- Recently Completed -->
                {#if dashboard.my_work.recently_completed.length > 0}
                    <section in:fly={{ y: 12, duration: blockDuration(), delay: 400 }} out:fade={{ duration: blockDuration() }}>
                        <h2 class="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3 flex items-center gap-2.5">
                            <span class="w-2 h-2 bg-emerald-500 rounded-full"></span>
                            Recently Completed
                        </h2>
                        <div class="card-warm rounded-xl divide-y divide-border/60 overflow-hidden">
                            {#each dashboard.my_work.recently_completed as run}
                                <button
                                    type="button"
                                    class="w-full flex items-center justify-between p-3.5 text-left hover:bg-muted/40 transition-colors duration-150 cursor-pointer"
                                    onclick={() => goto(`/runs/${run.id}`)}
                                >
                                    <div class="flex items-center gap-2.5">
                                        <div class="w-6 h-6 rounded-md bg-emerald-100 flex items-center justify-center">
                                            <svg class="w-3 h-3 text-emerald-600" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>
                                        </div>
                                        <span class="text-sm font-medium text-foreground">{run.name}</span>
                                        <span class="text-[11px] text-muted-foreground">{run.project_name}</span>
                                    </div>
                                    <div class="flex items-center gap-2.5">
                                        <span class="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-md {run.status === 'EDITED' ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}">
                                            {run.status === 'EDITED' ? 'Edited' : 'Done'}
                                        </span>
                                        <span class="text-[11px] text-muted-foreground tabular-nums">{formatDate(run.updated_at)}</span>
                                    </div>
                                </button>
                            {/each}
                        </div>
                    </section>
                {/if}

                <!-- Planned Runs -->
                {#if dashboard.my_work.planned_runs.length > 0}
                    <section in:fly={{ y: 12, duration: blockDuration(), delay: 500 }} out:fade={{ duration: blockDuration() }}>
                        <h2 class="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3 flex items-center gap-2.5">
                            <span class="w-2 h-2 bg-muted-foreground/40 rounded-full"></span>
                            Planned
                            <span class="text-[10px] font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded-md">{dashboard.my_work.planned_runs.length}</span>
                        </h2>
                        <div class="card-warm rounded-xl divide-y divide-border/60 overflow-hidden">
                            {#each dashboard.my_work.planned_runs as run}
                                <button
                                    type="button"
                                    class="w-full flex items-center justify-between p-3.5 text-left hover:bg-muted/40 transition-colors duration-150 cursor-pointer group"
                                    onclick={() => goto(`/runs/${run.id}`)}
                                >
                                    <div>
                                        <span class="text-sm font-medium text-foreground">{run.name}</span>
                                        <span class="text-[11px] text-muted-foreground ml-2">{run.project_name}</span>
                                    </div>
                                    <span class="text-[11px] font-semibold text-muted-foreground group-hover:text-primary transition-colors flex items-center gap-1">
                                        Setup
                                        <svg class="w-3 h-3 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                                    </span>
                                </button>
                            {/each}
                        </div>
                    </section>
                {/if}

                <!-- Empty state -->
                {#if dashboard.my_work.needs_action.length === 0 && dashboard.my_work.active_runs.length === 0 && dashboard.my_work.recently_completed.length === 0 && dashboard.my_work.planned_runs.length === 0}
                    <div class="card-warm rounded-xl" style="animation: fadeSlideUp 0.4s ease-out 0.2s both">
                        <EmptyState
                            title="No runs yet"
                            description="Get started by creating a project and running a protocol."
                            actionLabel="View Projects"
                            onAction={() => goto('/projects')}
                            secondaryActionLabel="Take the tour"
                            secondaryOnAction={() => (welcomeOpen = true)}
                            class="py-14"
                        >
                            {#snippet icon()}
                                <svg class="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                    <path d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
                                </svg>
                            {/snippet}
                        </EmptyState>
                    </div>
                {/if}
            </div>

            <!-- Activity Feed (2/5 width) -->
            <div class="lg:col-span-2" in:fly={{ y: 12, duration: blockDuration(), delay: 350 }}>
                <h2 class="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">Recent Activity</h2>
                <div class="card-warm rounded-xl overflow-hidden">
                    {#if activityItems.length === 0}
                        <EmptyState title="No recent activity" />
                    {:else}
                        <div class="divide-y divide-border/50">
                            {#each activityItems as item (item.id)}
                                <a
                                    href={activityLink(item)}
                                    class="flex gap-3 p-3.5 hover:bg-muted/30 transition-colors"
                                    animate:flip={{ duration: listDuration() }}
                                    in:fade={{ duration: listDuration() }}
                                >
                                    <!-- Avatar -->
                                    <div class="w-7 h-7 rounded-lg {actorColor(item.actor_name)} flex items-center justify-center shrink-0 mt-0.5">
                                        <span class="text-[10px] font-bold">
                                            {actorInitials(item.actor_name)}
                                        </span>
                                    </div>
                                    <!-- Content -->
                                    <div class="min-w-0 flex-1">
                                        <p class="text-xs text-foreground/80 leading-relaxed">
                                            <span class="font-semibold text-foreground">{item.actor_name || 'Someone'}</span>
                                            {' '}{activityVerb(item)}{' '}
                                            <span class="font-semibold text-foreground">{item.entity_name || ''}</span>
                                        </p>
                                        <p class="text-[10px] text-muted-foreground mt-0.5 tabular-nums">{timeAgo(item.created_at)}</p>
                                    </div>
                                </a>
                            {/each}
                        </div>
                        {#if activityItems.length < activityTotal}
                            <div class="p-3 border-t border-border/50 text-center">
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    class="text-[11px] font-semibold text-muted-foreground hover:text-foreground tracking-wide uppercase"
                                    onclick={loadMoreActivity}
                                    disabled={activityLoading}
                                >
                                    {activityLoading ? 'Loading...' : 'Load more'}
                                </Button>
                            </div>
                        {/if}
                    {/if}
                </div>
            </div>
        </div>
    </div>
{/if}

<TourModal
    bind:open={welcomeOpen}
    title="Welcome to Batchrite"
    description="Want a quick tour of your workspace? Start with how projects are laid out."
    primaryLabel="Check out how projects are laid out"
    secondaryLabel="Dismiss"
    onPrimary={startProjectTourFromWelcome}
    onSecondary={dismissWelcome}
/>

