<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { getCurrentOrg, getUser } from '$lib/auth.svelte';

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

    type Dashboard = {
        my_work: {
            needs_action: RunSummary[];
            active_runs: RunSummary[];
            recently_completed: RunSummary[];
            planned_runs: RunSummary[];
        };
        activity: ActivityItem[];
        counters: Counters;
        is_admin: boolean;
    };

    let dashboard = $state<Dashboard | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    // Activity feed pagination
    let activityItems = $state<ActivityItem[]>([]);
    let activityTotal = $state(0);
    let activityLoading = $state(false);

    onMount(() => {
        loadDashboard();
    });

    async function loadDashboard() {
        const org = getCurrentOrg();
        if (!org) return;

        loading = true;
        error = null;
        try {
            const data: Dashboard = await api.get(`/dashboard?org_id=${org.id}`);
            dashboard = data;
            activityItems = data.activity;
        } catch (e: any) {
            error = e.message || 'Failed to load dashboard';
        } finally {
            loading = false;
        }
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
            // silent
        } finally {
            activityLoading = false;
        }
    }

    function progressPercent(run: RunSummary): number {
        if (run.total_steps === 0) return 0;
        return Math.round((run.completed_steps / run.total_steps) * 100);
    }

    function timeAgo(dateStr: string): string {
        const now = Date.now();
        const then = new Date(dateStr).getTime();
        const diff = now - then;
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return 'just now';
        if (mins < 60) return `${mins}m ago`;
        const hours = Math.floor(mins / 60);
        if (hours < 24) return `${hours}h ago`;
        const days = Math.floor(hours / 24);
        if (days < 7) return `${days}d ago`;
        return new Date(dateStr).toLocaleDateString();
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

    const userName = $derived(getUser()?.full_name?.split(' ')[0] || 'there');
</script>

{#if loading}
    <div class="flex items-center justify-center py-32">
        <div class="flex flex-col items-center gap-3">
            <div class="w-7 h-7 border-3 border-slate-200 border-t-slate-600 rounded-full animate-spin"></div>
            <p class="text-sm text-slate-400">Loading dashboard...</p>
        </div>
    </div>
{:else if error}
    <div class="flex flex-col items-center justify-center py-32 gap-3">
        <p class="text-sm text-red-500">{error}</p>
        <button class="text-sm text-slate-500 hover:text-slate-700 underline" onclick={loadDashboard}>
            Retry
        </button>
    </div>
{:else if dashboard}
    <div class="max-w-6xl mx-auto">
        <!-- Greeting -->
        <div class="mb-6">
            <h1 class="text-2xl font-bold text-slate-900">Hey {userName}</h1>
            <p class="text-sm text-slate-500 mt-0.5">Here's what's happening today.</p>
        </div>

        <!-- Counters -->
        <div class="grid grid-cols-3 {dashboard.is_admin ? 'md:grid-cols-6' : 'md:grid-cols-3'} gap-3 mb-8">
            <button
                class="bg-white border border-slate-200 rounded-lg p-4 text-left hover:border-slate-300 transition-colors"
                onclick={() => goto('/projects')}
            >
                <div class="text-2xl font-bold text-slate-900">{dashboard.counters.active_runs}</div>
                <div class="text-xs font-medium text-slate-500 mt-1">Active Runs</div>
            </button>
            <div class="bg-white border border-slate-200 rounded-lg p-4">
                <div class="text-2xl font-bold text-emerald-600">{dashboard.counters.completed_this_week}</div>
                <div class="text-xs font-medium text-slate-500 mt-1">Completed This Week</div>
            </div>
            <div class="bg-white border border-slate-200 rounded-lg p-4">
                <div class="text-2xl font-bold text-slate-900">{dashboard.counters.planned_runs}</div>
                <div class="text-xs font-medium text-slate-500 mt-1">Planned</div>
            </div>
            {#if dashboard.is_admin}
                <div class="bg-white border border-slate-200 rounded-lg p-4">
                    <div class="text-2xl font-bold text-slate-900">{dashboard.counters.team_members ?? 0}</div>
                    <div class="text-xs font-medium text-slate-500 mt-1">Team Members</div>
                </div>
                <div class="bg-white border border-slate-200 rounded-lg p-4">
                    <div class="text-2xl font-bold text-slate-900">{dashboard.counters.active_projects ?? 0}</div>
                    <div class="text-xs font-medium text-slate-500 mt-1">Projects</div>
                </div>
                <div class="bg-white border border-slate-200 rounded-lg p-4">
                    <div class="text-2xl font-bold text-slate-900">{dashboard.counters.total_protocols ?? 0}</div>
                    <div class="text-xs font-medium text-slate-500 mt-1">Protocols</div>
                </div>
            {/if}
        </div>

        <!-- Main grid: My Work + Activity -->
        <div class="grid grid-cols-1 lg:grid-cols-5 gap-6">
            <!-- My Work (3/5 width) -->
            <div class="lg:col-span-3 space-y-5">
                <!-- Needs Action -->
                {#if dashboard.my_work.needs_action.length > 0}
                    <section>
                        <h2 class="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-2">
                            <span class="w-2 h-2 bg-amber-500 rounded-full"></span>
                            Needs Your Action
                            <span class="text-xs font-normal text-slate-400">({dashboard.my_work.needs_action.length})</span>
                        </h2>
                        <div class="space-y-2">
                            {#each dashboard.my_work.needs_action as run}
                                <button
                                    class="w-full bg-white border border-amber-200 rounded-lg p-4 text-left hover:border-amber-300 hover:bg-amber-50/30 transition-colors"
                                    onclick={() => goto(`/runs/${run.id}`)}
                                >
                                    <div class="flex items-center justify-between mb-2">
                                        <div>
                                            <span class="font-semibold text-sm text-slate-900">{run.name}</span>
                                            {#if run.role_name}
                                                <span class="ml-2 text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{run.role_name}</span>
                                            {/if}
                                        </div>
                                        <span class="text-xs text-slate-400">{timeAgo(run.updated_at)}</span>
                                    </div>
                                    <div class="flex items-center gap-3">
                                        <div class="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                            <div
                                                class="h-full bg-amber-500 rounded-full transition-all"
                                                style="width: {progressPercent(run)}%"
                                            ></div>
                                        </div>
                                        <span class="text-xs font-medium text-slate-500 whitespace-nowrap">
                                            {run.completed_steps}/{run.total_steps}
                                        </span>
                                    </div>
                                    <div class="text-xs text-slate-400 mt-1.5">
                                        {run.project_name}{run.protocol_name ? ` · ${run.protocol_name}` : ''}
                                    </div>
                                </button>
                            {/each}
                        </div>
                    </section>
                {/if}

                <!-- Active Runs -->
                {#if dashboard.my_work.active_runs.length > 0}
                    <section>
                        <h2 class="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-2">
                            <span class="w-2 h-2 bg-blue-500 rounded-full"></span>
                            Active Runs
                            <span class="text-xs font-normal text-slate-400">({dashboard.my_work.active_runs.length})</span>
                        </h2>
                        <div class="space-y-2">
                            {#each dashboard.my_work.active_runs as run}
                                <button
                                    class="w-full bg-white border border-slate-200 rounded-lg p-4 text-left hover:border-slate-300 transition-colors"
                                    onclick={() => goto(`/runs/${run.id}`)}
                                >
                                    <div class="flex items-center justify-between mb-2">
                                        <div>
                                            <span class="font-semibold text-sm text-slate-900">{run.name}</span>
                                            {#if run.role_name}
                                                <span class="ml-2 text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">{run.role_name}</span>
                                            {/if}
                                        </div>
                                        <span class="text-xs text-slate-400">{timeAgo(run.updated_at)}</span>
                                    </div>
                                    <div class="flex items-center gap-3">
                                        <div class="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                            <div
                                                class="h-full bg-blue-500 rounded-full transition-all"
                                                style="width: {progressPercent(run)}%"
                                            ></div>
                                        </div>
                                        <span class="text-xs font-medium text-slate-500 whitespace-nowrap">
                                            {run.completed_steps}/{run.total_steps}
                                        </span>
                                    </div>
                                    <div class="text-xs text-slate-400 mt-1.5">
                                        {run.project_name}{run.protocol_name ? ` · ${run.protocol_name}` : ''}
                                    </div>
                                </button>
                            {/each}
                        </div>
                    </section>
                {/if}

                <!-- Recently Completed -->
                {#if dashboard.my_work.recently_completed.length > 0}
                    <section>
                        <h2 class="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-2">
                            <span class="w-2 h-2 bg-emerald-500 rounded-full"></span>
                            Recently Completed
                        </h2>
                        <div class="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
                            {#each dashboard.my_work.recently_completed as run}
                                <button
                                    class="w-full flex items-center justify-between p-3.5 text-left hover:bg-slate-50 transition-colors first:rounded-t-lg last:rounded-b-lg"
                                    onclick={() => goto(`/runs/${run.id}`)}
                                >
                                    <div>
                                        <span class="text-sm font-medium text-slate-900">{run.name}</span>
                                        <span class="text-xs text-slate-400 ml-2">{run.project_name}</span>
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <span class="text-xs px-2 py-0.5 rounded-full {run.status === 'EDITED' ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'}">
                                            {run.status === 'EDITED' ? 'Edited' : 'Completed'}
                                        </span>
                                        <span class="text-xs text-slate-400">{formatDate(run.updated_at)}</span>
                                    </div>
                                </button>
                            {/each}
                        </div>
                    </section>
                {/if}

                <!-- Planned Runs -->
                {#if dashboard.my_work.planned_runs.length > 0}
                    <section>
                        <h2 class="text-sm font-semibold text-slate-900 mb-3 flex items-center gap-2">
                            <span class="w-2 h-2 bg-slate-400 rounded-full"></span>
                            Planned
                            <span class="text-xs font-normal text-slate-400">({dashboard.my_work.planned_runs.length})</span>
                        </h2>
                        <div class="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
                            {#each dashboard.my_work.planned_runs as run}
                                <button
                                    class="w-full flex items-center justify-between p-3.5 text-left hover:bg-slate-50 transition-colors first:rounded-t-lg last:rounded-b-lg"
                                    onclick={() => goto(`/runs/${run.id}`)}
                                >
                                    <div>
                                        <span class="text-sm font-medium text-slate-900">{run.name}</span>
                                        <span class="text-xs text-slate-400 ml-2">{run.project_name}</span>
                                    </div>
                                    <span class="text-xs text-slate-500 font-medium">Setup →</span>
                                </button>
                            {/each}
                        </div>
                    </section>
                {/if}

                <!-- Empty state -->
                {#if dashboard.my_work.needs_action.length === 0 && dashboard.my_work.active_runs.length === 0 && dashboard.my_work.recently_completed.length === 0 && dashboard.my_work.planned_runs.length === 0}
                    <div class="bg-white border border-slate-200 rounded-lg p-12 text-center">
                        <div class="text-slate-300 mb-3">
                            <svg class="w-12 h-12 mx-auto" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <path d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
                            </svg>
                        </div>
                        <p class="text-sm font-medium text-slate-600 mb-1">No runs yet</p>
                        <p class="text-xs text-slate-400 mb-4">Get started by creating a project and running a protocol.</p>
                        <button
                            class="text-sm font-medium text-slate-700 hover:text-slate-900 underline"
                            onclick={() => goto('/projects')}
                        >View Projects</button>
                    </div>
                {/if}
            </div>

            <!-- Activity Feed (2/5 width) -->
            <div class="lg:col-span-2">
                <h2 class="text-sm font-semibold text-slate-900 mb-3">Recent Activity</h2>
                <div class="bg-white border border-slate-200 rounded-lg">
                    {#if activityItems.length === 0}
                        <div class="p-8 text-center">
                            <p class="text-sm text-slate-400">No recent activity.</p>
                        </div>
                    {:else}
                        <div class="divide-y divide-slate-100">
                            {#each activityItems as item}
                                <a
                                    href={activityLink(item)}
                                    class="flex gap-3 p-3.5 hover:bg-slate-50 transition-colors first:rounded-t-lg last:rounded-b-lg"
                                >
                                    <!-- Avatar -->
                                    <div class="w-7 h-7 rounded-full bg-slate-200 flex items-center justify-center shrink-0 mt-0.5">
                                        <span class="text-[10px] font-bold text-slate-600">
                                            {actorInitials(item.actor_name)}
                                        </span>
                                    </div>
                                    <!-- Content -->
                                    <div class="min-w-0 flex-1">
                                        <p class="text-xs text-slate-700 leading-relaxed">
                                            <span class="font-semibold">{item.actor_name || 'Someone'}</span>
                                            {' '}{activityVerb(item)}{' '}
                                            <span class="font-semibold">{item.entity_name || ''}</span>
                                        </p>
                                        <p class="text-[11px] text-slate-400 mt-0.5">{timeAgo(item.created_at)}</p>
                                    </div>
                                </a>
                            {/each}
                        </div>
                        {#if activityItems.length < activityTotal}
                            <div class="p-3 border-t border-slate-100 text-center">
                                <button
                                    class="text-xs font-medium text-slate-500 hover:text-slate-700"
                                    onclick={loadMoreActivity}
                                    disabled={activityLoading}
                                >
                                    {activityLoading ? 'Loading...' : 'Load more'}
                                </button>
                            </div>
                        {/if}
                    {/if}
                </div>
            </div>
        </div>
    </div>
{/if}
