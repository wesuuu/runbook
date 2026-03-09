<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { getUser } from '$lib/auth.svelte';
    import { isOnline } from '$lib/pwa.svelte';
    import {
        getFieldModeState,
        isFieldModeActive,
        isFieldModeLocked,
        getRunSnapshot,
        getActiveRunId,
        getQueueCount,
        lockSession,
        unlockSession,
        endFieldMode,
        recordActivity,
        initFieldMode,
        type RunSnapshot,
    } from '$lib/field-mode.svelte';
    import { syncNow, isSyncing } from '$lib/sync-manager';
    import { getUnsyncedCount } from '$lib/offline-db';
    import FieldModeHeader from '$lib/components/FieldModeHeader.svelte';
    import FieldModeRoleWizard from '$lib/components/FieldModeRoleWizard.svelte';
    import FieldModeLockScreen from '$lib/components/FieldModeLockScreen.svelte';
    import ExpiryWarningBanner from '$lib/components/ExpiryWarningBanner.svelte';

    let ready = $state(false);
    let showEndConfirm = $state(false);
    let endingSession = $state(false);
    let syncing = $state(false);

    const fieldState = $derived(getFieldModeState());
    const snapshot = $derived(getRunSnapshot());
    const queueCount = $derived(getQueueCount());
    const user = $derived(getUser());
    const online = $derived(isOnline());

    onMount(async () => {
        // If no active field mode, try to init (detects existing sessions)
        if (!isFieldModeActive()) {
            await initFieldMode();
        }
        // If still no session, redirect to dashboard
        if (getFieldModeState() === 'inactive') {
            goto('/');
            return;
        }
        ready = true;
    });

    // Track user activity for inactivity timer
    function handleInteraction() {
        recordActivity();
    }

    function getStepsForUser(snap: RunSnapshot): Array<{
        id: string;
        name: string;
        category?: string;
        description?: string;
        params?: Record<string, any>;
        paramSchema?: Record<string, any>;
        duration_min?: number;
    }> {
        const graph = snap.graph as { nodes?: any[]; edges?: any[] };
        const nodes = graph?.nodes ?? [];

        // Find the user's assignment
        const userId = user?.id;
        const assignment = snap.role_assignments.find((a) => a.user_id === userId);
        if (!assignment) {
            // Return all unitOp steps if no specific assignment
            return nodes
                .filter((n: any) => n.type === 'unitOp')
                .sort((a: any, b: any) => a.position.x - b.position.x)
                .map((n: any) => ({
                    id: n.id,
                    name: n.data.label,
                    category: n.data.category,
                    description: n.data.description,
                    params: n.data.params,
                    paramSchema: n.data.paramSchema,
                    duration_min: n.data.duration_min,
                }));
        }

        const laneNodeId = assignment.lane_node_id;
        const allSteps = nodes
            .filter((n: any) => n.type === 'unitOp')
            .sort((a: any, b: any) => a.position.x - b.position.x);

        // Steps parented to this lane
        const parented = allSteps.filter((n: any) => n.parentId === laneNodeId);
        const steps = parented.length > 0 ? parented : allSteps;

        return steps.map((n: any) => ({
            id: n.id,
            name: n.data.label,
            category: n.data.category,
            description: n.data.description,
            params: n.data.params,
            paramSchema: n.data.paramSchema,
            duration_min: n.data.duration_min,
        }));
    }

    async function handleEndFieldMode() {
        if (queueCount > 0 && !online) {
            showEndConfirm = true;
            return;
        }

        endingSession = true;
        try {
            // Sync first if online and there are queued items
            if (online && queueCount > 0) {
                syncing = true;
                await syncNow();
                syncing = false;
            }
            await endFieldMode(false); // Don't wipe queue — orphans are recoverable
            goto('/');
        } catch {
            endingSession = false;
        }
    }

    async function handleForceEnd() {
        endingSession = true;
        await endFieldMode(true); // Wipe queue
        goto('/');
    }

    async function handleUnlock(password: string): Promise<boolean> {
        return unlockSession(password);
    }

    function handleExecutionDataUpdate(data: Record<string, any>) {
        // Execution data is already saved in IndexedDB by the wizard
    }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
    class="min-h-screen bg-slate-50"
    onclick={handleInteraction}
    onkeydown={handleInteraction}
    ontouchmove={handleInteraction}
>
    {#if !ready}
        <div class="flex items-center justify-center h-screen">
            <div class="text-center">
                <div class="w-8 h-8 border-2 border-teal-600 border-t-transparent rounded-full animate-spin mx-auto mb-3"></div>
                <p class="text-sm text-slate-500">Loading field mode...</p>
            </div>
        </div>
    {:else if fieldState === 'locked'}
        <FieldModeLockScreen
            userEmail={user?.email ?? ''}
            onUnlock={handleUnlock}
        />
    {:else if snapshot}
        <FieldModeHeader
            onEndFieldMode={handleEndFieldMode}
            onLock={lockSession}
        />
        <ExpiryWarningBanner />

        <div class="max-w-2xl mx-auto px-4 py-6">
            <!-- Run info -->
            <div class="mb-4">
                <h1 class="text-lg font-bold text-slate-900">{snapshot.run_name}</h1>
                {#if snapshot.role_assignments.length > 0}
                    {@const myAssignment = snapshot.role_assignments.find((a) => a.user_id === user?.id)}
                    {#if myAssignment}
                        <p class="text-xs text-slate-500">Role: {myAssignment.role_name}</p>
                    {/if}
                {/if}
            </div>

            <!-- Wizard -->
            <div class="bg-white rounded-xl border border-slate-200 p-4 sm:p-6 shadow-sm">
                <FieldModeRoleWizard
                    steps={getStepsForUser(snapshot)}
                    runId={snapshot.run_id}
                    executionData={snapshot.execution_data as Record<string, any>}
                    onDataUpdate={handleExecutionDataUpdate}
                />
            </div>

            <!-- Online sync hint -->
            {#if online && queueCount > 0}
                <div class="mt-4 p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-center">
                    <p class="text-xs text-emerald-700 mb-2">
                        You're back online! {queueCount} item{queueCount !== 1 ? 's' : ''} ready to sync.
                    </p>
                    <button
                        onclick={async () => { syncing = true; await syncNow(); syncing = false; }}
                        disabled={syncing}
                        class="px-4 py-1.5 bg-emerald-600 text-white text-xs rounded-lg font-medium hover:bg-emerald-700 disabled:opacity-50"
                    >
                        {syncing ? 'Syncing...' : 'Sync Now'}
                    </button>
                </div>
            {/if}
        </div>
    {:else}
        <div class="flex items-center justify-center h-screen text-slate-500">
            <p>No active field session. <a href="/" class="text-teal-600 underline">Go to Dashboard</a></p>
        </div>
    {/if}
</div>

<!-- End Field Mode Confirmation (unsynced while offline) -->
{#if showEndConfirm}
    <div class="fixed inset-0 z-[9999] bg-black/50 flex items-center justify-center">
        <div class="bg-white rounded-xl shadow-2xl p-6 max-w-sm w-[95%]">
            <h3 class="text-lg font-bold text-slate-900 mb-2">Unsynced Data</h3>
            <p class="text-sm text-slate-600 mb-4">
                You have <strong>{queueCount}</strong> unsynced item{queueCount !== 1 ? 's' : ''}. Connect to the internet first to avoid losing data.
            </p>
            <div class="flex gap-3">
                <button
                    onclick={() => (showEndConfirm = false)}
                    class="flex-1 py-2.5 border border-slate-300 rounded-lg text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                    Stay
                </button>
                <button
                    onclick={handleForceEnd}
                    class="flex-1 py-2.5 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700"
                >
                    End & Lose Data
                </button>
            </div>
        </div>
    </div>
{/if}
