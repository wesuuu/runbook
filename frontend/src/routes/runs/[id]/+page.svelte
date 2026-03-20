<script lang="ts">
    import { page } from '$app/stores';
    import { api } from "$lib/api";
    import { getUser } from "$lib/auth.svelte";
    import { goto } from '$app/navigation';
    import RoleWizard from "$lib/components/RoleWizard.svelte";
    import GoOfflineDialog from "$lib/components/GoOfflineDialog.svelte";
    import RunDocuments from "$lib/components/run/RunDocuments.svelte";
    import RoleAssignmentPanel from "$lib/components/run/RoleAssignmentPanel.svelte";
    import RunResultsSummary from "$lib/components/run/RunResultsSummary.svelte";
    import RunEditMode from "$lib/components/run/RunEditMode.svelte";
    import RunObserverView from "$lib/components/run/RunObserverView.svelte";

    const id = $derived($page.params.id);

    let run = $state<any>(null);
    let protocol = $state<any>(null);
    let roleAssignments = $state<any[]>([]);
    let projectMembers = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let savingStatus = $state(false);

    // UI State
    let showStartConfirm = $state(false);
    let assignmentChanges = $state<Record<string, string>>({});
    let showCompleteConfirm = $state(false);
    let completingRun = $state(false);
    let unanalyzedCount = $state(0);
    let showGoOffline = $state(false);
    let analyzingAll = $state(false);
    let analyzeAllProgress = $state('');

    // Edit mode state
    let isEditMode = $state(false);
    let editExecutionData = $state<Record<string, any>>({});
    let savingEdits = $state(false);

    // Load data whenever id changes
    $effect(() => {
        if (id) {
            loading = true;
            error = null;
            loadData();
        }
    });

    async function loadData() {
        try {
            run = await api.get(`/science/runs/${id}`);

            if (run.protocol_id) {
                protocol = await api.get(`/science/protocols/${run.protocol_id}`);
            }

            const assignResp = await api.get(
                `/science/runs/${id}/role-assignments`
            );
            roleAssignments = assignResp.items || [];

            const membersResp = await api.get(
                `/science/projects/${run.project_id}/members`
            );
            projectMembers = membersResp || [];

            await loadUnanalyzedCount();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            loading = false;
        }
    }

    async function loadUnanalyzedCount() {
        try {
            const resp = await api.get<{ items: any[] }>(
                `/ai/runs/${id}/images?analyzed=false`
            );
            unanalyzedCount = resp.items?.length ?? 0;
        } catch {
            unanalyzedCount = 0;
        }
    }

    async function analyzeAllImages() {
        analyzingAll = true;
        analyzeAllProgress = 'Starting batch analysis...';
        try {
            const resp = await api.post<{
                total: number;
                succeeded: number;
                failed: number;
            }>(`/ai/runs/${id}/analyze-pending`, {});
            analyzeAllProgress = `Done: ${resp.succeeded} analyzed${resp.failed > 0 ? `, ${resp.failed} failed` : ''}`;
            await loadUnanalyzedCount();
        } catch (e: unknown) {
            analyzeAllProgress = e instanceof Error ? e.message : 'Analysis failed';
        } finally {
            analyzingAll = false;
        }
    }

    async function updateRoleAssignment(
        laneNodeId: string,
        roleName: string,
        userId: string | null
    ) {
        try {
            if (!userId) {
                const existing = roleAssignments.find(
                    (a) => a.lane_node_id === laneNodeId
                );
                if (existing) {
                    await api.delete(
                        `/science/runs/${id}/role-assignments/${existing.id}`
                    );
                    roleAssignments = roleAssignments.filter(
                        (a) => a.lane_node_id !== laneNodeId
                    );
                }
            } else {
                const resp = await api.post(
                    `/science/runs/${id}/role-assignments`,
                    {
                        lane_node_id: laneNodeId,
                        role_name: roleName,
                        user_id: userId,
                    }
                );
                const idx = roleAssignments.findIndex(
                    (a) => a.lane_node_id === laneNodeId
                );
                if (idx >= 0) {
                    roleAssignments[idx] = resp;
                } else {
                    roleAssignments = [...roleAssignments, resp];
                }
            }
            delete assignmentChanges[laneNodeId];
        } catch (e: unknown) {
            console.error("Failed to update assignment:", e instanceof Error ? e.message : e);
            error = e instanceof Error ? e.message : 'An error occurred';
        }
    }

    async function startRun() {
        try {
            savingStatus = true;
            await api.put(`/science/runs/${id}`, { status: "ACTIVE" });
            run = await api.get(`/science/runs/${id}`);
            showStartConfirm = false;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            savingStatus = false;
        }
    }

    function getSwimLaneNodes() {
        if (!run?.graph) return [];
        return (run.graph.nodes || []).filter((n: any) => n.type === "swimLane");
    }

    function getRoleAssignment(laneNodeId: string) {
        return roleAssignments.find((a) => a.lane_node_id === laneNodeId);
    }

    function allRolesAssigned() {
        if (roleAssignments.length === 0) return false;
        const swimLanes = getSwimLaneNodes();
        if (swimLanes.length > 0) {
            return swimLanes.every((lane: any) => getRoleAssignment(lane.id));
        }
        return true;
    }

    function getAllUnitOpSteps() {
        if (!run?.graph) return [];
        const nodes = run.graph.nodes || [];
        return nodes
            .filter((n: any) => n.type === "unitOp")
            .sort((a: any, b: any) => a.position.x - b.position.x)
            .map((n: any) => ({
                id: n.id,
                name: n.data.label,
                category: n.data.category,
                description: n.data.description,
                params: n.data.params,
                paramSchema: n.data.paramSchema,
                duration_min: n.data.duration_min,
                parentId: n.parentId || null,
            }));
    }

    function getStepsForRole(laneNodeId: string) {
        if (!run?.graph) return [];
        const all = getAllUnitOpSteps();
        const parented = all.filter((s: any) => s.parentId === laneNodeId);
        if (parented.length > 0) return parented;
        const anyParented = all.some((s: any) => s.parentId != null);
        if (!anyParented) return all;
        return [];
    }

    function downloadSop() {
        const name = run.name.replace(/\s+/g, '_');
        api.downloadBlob(
            `/science/runs/${id}/pdf/sop`,
            `SOP_${name}.pdf`
        );
    }

    function downloadBatchRecord(filled: boolean = false) {
        const name = run.name.replace(/\s+/g, '_');
        const suffix = filled ? 'COMPLETED' : 'BLANK';
        api.downloadBlob(
            `/science/runs/${id}/pdf/batch-record?filled=${filled}`,
            `BatchRecord_${name}_${suffix}.pdf`
        );
    }

    function getCurrentUserAssignment() {
        const user = getUser();
        if (!user) return null;
        return roleAssignments.find((a) => a.user_id === user.id);
    }

    function getWizardSteps() {
        const assignment = getCurrentUserAssignment();
        if (!assignment) return [];
        return getStepsForRole(assignment.lane_node_id);
    }

    function allStepsComplete() {
        const allSteps = getAllUnitOpSteps();
        if (allSteps.length === 0) return false;
        const execData = run?.execution_data || {};
        return allSteps.every(
            (s: any) => execData[s.id]?.status === 'completed',
        );
    }

    async function completeRun() {
        try {
            completingRun = true;
            await api.put(`/science/runs/${id}`, {
                status: 'COMPLETED',
                execution_data: run.execution_data,
            });
            run = await api.get(`/science/runs/${id}`);
            showCompleteConfirm = false;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            completingRun = false;
        }
    }

    function enterEditMode() {
        editExecutionData = JSON.parse(JSON.stringify(run.execution_data || {}));
        isEditMode = true;
    }

    function cancelEditMode() {
        isEditMode = false;
        editExecutionData = {};
    }

    async function saveEdits() {
        try {
            savingEdits = true;
            error = null;
            await api.put(`/science/runs/${id}`, {
                status: 'EDITED',
                execution_data: editExecutionData,
            });
            run = await api.get(`/science/runs/${id}`);
            isEditMode = false;
            editExecutionData = {};
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            savingEdits = false;
        }
    }

    function handleExecutionDataUpdate(updatedData: Record<string, any>) {
        run.execution_data = updatedData;
    }

    function handleEditDataUpdate(updatedData: Record<string, any>) {
        editExecutionData = updatedData;
    }
</script>

<div class="min-h-screen bg-background">
    {#if loading}
        <div class="flex items-center justify-center h-screen text-muted-foreground">
            <div class="text-center">
                <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-border mx-auto mb-3"></div>
                Loading run...
            </div>
        </div>
    {:else if error && !run}
        <div class="flex items-center justify-center h-screen">
            <div class="text-center">
                <div class="text-red-500 font-semibold mb-2">Error loading run</div>
                <div class="text-muted-foreground text-sm">{error}</div>
            </div>
        </div>
    {:else if !run}
        <div class="flex items-center justify-center h-screen text-muted-foreground">
            Run not found
        </div>
    {:else}
        <!-- PLANNED State: Setup & Role Assignment -->
        {#if run.status === "PLANNED"}
            <div class="max-w-5xl mx-auto px-6 py-8">
                <!-- Header -->
                <div class="mb-8">
                    <div class="flex items-center justify-between mb-2">
                        <h1 class="text-3xl font-bold text-foreground">
                            {run.name}
                        </h1>
                        <span class="inline-block text-xs font-semibold px-3 py-1 bg-muted text-foreground/80 rounded-full">
                            Planned
                        </span>
                    </div>
                    <a
                        href="/projects/{run.project_id}?tab=runs"
                        class="text-sm text-muted-foreground hover:text-foreground/80"
                    >
                        &larr; Back to project
                    </a>
                </div>

                {#if error}
                    <div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                        {error}
                    </div>
                {/if}

                <!-- Protocol Info -->
                {#if protocol}
                    <div class="mb-8 p-6 card-warm rounded-xl">
                        <h2 class="text-lg font-semibold text-foreground mb-2">
                            Protocol
                        </h2>
                        <div class="space-y-2">
                            <p class="text-foreground/80 font-medium">{protocol.name}</p>
                            {#if protocol.description}
                                <p class="text-muted-foreground text-sm">{protocol.description}</p>
                            {/if}
                            <a
                                href="/protocols/{protocol.id}"
                                class="inline-block text-sm text-primary hover:text-primary/80 font-medium mt-2"
                            >
                                View protocol &rarr;
                            </a>
                        </div>
                    </div>
                {/if}

                <!-- Role Assignments -->
                <RoleAssignmentPanel
                    swimLaneNodes={getSwimLaneNodes()}
                    {roleAssignments}
                    {projectMembers}
                    {assignmentChanges}
                    onUpdateAssignment={updateRoleAssignment}
                    onAssignmentChange={(laneId, value) => { assignmentChanges[laneId] = value; }}
                    onShowGoOffline={() => (showGoOffline = true)}
                />

                <!-- Electronic Batch Record -->
                {#if getAllUnitOpSteps().length > 0}
                    <div class="mb-8 p-6 card-warm rounded-xl">
                        <h2 class="text-lg font-semibold text-foreground mb-6">
                            Electronic Batch Record
                        </h2>
                        <p class="text-sm text-muted-foreground mb-4">
                            {getAllUnitOpSteps().length} steps in this run.
                        </p>

                        <div class="overflow-x-auto">
                            <table class="w-full text-sm">
                                <thead>
                                    <tr class="border-b border-border">
                                        <th class="text-left py-3 px-4 font-semibold text-foreground/80 w-8">#</th>
                                        <th class="text-left py-3 px-4 font-semibold text-foreground/80">Step</th>
                                        <th class="text-left py-3 px-4 font-semibold text-foreground/80">Category</th>
                                        <th class="text-left py-3 px-4 font-semibold text-foreground/80">Duration</th>
                                        <th class="text-left py-3 px-4 font-semibold text-foreground/80">Parameters</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {#each getAllUnitOpSteps() as step, i}
                                        <tr class="border-b border-border/60 hover:bg-background">
                                            <td class="py-3 px-4 text-muted-foreground font-mono">{i + 1}</td>
                                            <td class="py-3 px-4">
                                                <p class="font-medium text-foreground">{step.name}</p>
                                                {#if step.description}
                                                    <p class="text-xs text-muted-foreground mt-1">{step.description}</p>
                                                {/if}
                                            </td>
                                            <td class="py-3 px-4">
                                                <span class="inline-block text-xs font-semibold px-2 py-1 bg-muted text-foreground/80 rounded">
                                                    {step.category || '—'}
                                                </span>
                                            </td>
                                            <td class="py-3 px-4 text-foreground/80">
                                                {step.duration_min ? `${step.duration_min} min` : '—'}
                                            </td>
                                            <td class="py-3 px-4">
                                                {#if step.params && Object.keys(step.params).length > 0}
                                                    <div class="space-y-1">
                                                        {#each Object.entries(step.params) as [key, value]}
                                                            <div class="text-xs">
                                                                <span class="text-muted-foreground">{key.replace(/_/g, ' ')}:</span>
                                                                <span class="font-medium text-foreground ml-1">{value}</span>
                                                            </div>
                                                        {/each}
                                                    </div>
                                                {:else}
                                                    <span class="text-muted-foreground/60">—</span>
                                                {/if}
                                            </td>
                                        </tr>
                                    {/each}
                                </tbody>
                            </table>
                        </div>
                    </div>
                {/if}

                <!-- Documents Section -->
                {#if getAllUnitOpSteps().length > 0}
                    <div class="mb-8">
                        <RunDocuments
                            runId={run.id}
                            runName={run.name}
                            status={run.status}
                            onDownloadSop={downloadSop}
                            onDownloadBatchRecord={downloadBatchRecord}
                        />
                    </div>
                {/if}

                <!-- Action Buttons -->
                <div class="flex justify-between items-center">
                    <a
                        href="/projects/{run.project_id}?tab=runs"
                        class="text-muted-foreground hover:text-foreground text-sm font-medium"
                    >
                        &larr; Back to project
                    </a>

                    <button
                        onclick={() => (showStartConfirm = true)}
                        disabled={!allRolesAssigned()}
                        class="px-6 py-2 bg-primary text-white rounded-lg font-medium hover:bg-primary/90 transition-colors disabled:bg-muted disabled:cursor-not-allowed"
                    >
                        Start Run
                    </button>
                </div>

                <!-- Start Confirmation Modal -->
                {#if showStartConfirm}
                    <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                        <div class="bg-white rounded-lg shadow-lg p-6 max-w-sm">
                            <h3 class="text-lg font-bold text-foreground mb-4">
                                Start Run?
                            </h3>
                            <p class="text-muted-foreground mb-6">
                                Once started, users can begin logging results for their assigned roles.
                            </p>
                            <div class="flex justify-end gap-3">
                                <button
                                    onclick={() => (showStartConfirm = false)}
                                    class="px-4 py-2 bg-muted text-foreground/80 rounded-lg font-medium hover:bg-muted transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    onclick={startRun}
                                    disabled={savingStatus}
                                    class="px-4 py-2 bg-primary text-white rounded-lg font-medium hover:bg-primary/90 transition-colors disabled:bg-muted disabled:cursor-not-allowed"
                                >
                                    {savingStatus ? "Starting..." : "Start"}
                                </button>
                            </div>
                        </div>
                    </div>
                {/if}
            </div>

        <!-- ACTIVE State: Multi-page Wizard or Observer View -->
        {:else if run.status === "ACTIVE"}
            <div class="min-h-screen bg-background">
                <div class="max-w-4xl mx-auto px-6 py-8">
                    <!-- Header -->
                    <div class="mb-8">
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <h1 class="text-3xl font-bold text-foreground">
                                    {run.name}
                                </h1>
                                {#if protocol}
                                    <p class="text-sm text-muted-foreground mt-1">
                                        Protocol: {protocol.name}
                                    </p>
                                {/if}
                            </div>
                            <div class="flex items-center gap-2">
                                <button
                                    onclick={() => (showGoOffline = true)}
                                    class="flex items-center gap-1.5 px-3 py-1 text-xs font-medium border border-amber-300 bg-amber-50 text-amber-700 rounded-full hover:bg-amber-100 transition-colors"
                                    title="Enter offline field mode for this run"
                                >
                                    <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                        <path stroke-linecap="round" stroke-linejoin="round" d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z" />
                                    </svg>
                                    Go Offline
                                </button>
                                <span class="inline-block text-xs font-semibold px-3 py-1 bg-emerald-100 text-emerald-700 rounded-full">
                                    Running
                                </span>
                            </div>
                        </div>
                        <a
                            href="/projects/{run.project_id}?tab=runs"
                            class="text-sm text-muted-foreground hover:text-foreground/80"
                        >
                            &larr; Back to project
                        </a>
                    </div>

                    <!-- Role Assignments Summary -->
                    {#if roleAssignments.length > 0}
                        <div class="mb-6 bg-white rounded-lg border border-border px-5 py-4">
                            <h3 class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Assigned Roles</h3>
                            {#if getSwimLaneNodes().length > 0}
                                <div class="flex flex-wrap gap-3">
                                    {#each getSwimLaneNodes() as lane}
                                        {@const assignment = getRoleAssignment(lane.id)}
                                        {@const steps = getStepsForRole(lane.id)}
                                        {@const completedCount = steps.filter((s) => run.execution_data?.[s.id]?.status === "completed").length}
                                        {@const isCurrentUser = assignment?.user_id === getUser()?.id}
                                        {@const member = assignment ? projectMembers.find((m) => m.id === assignment.user_id) : null}
                                        {@const displayName = member?.full_name || (isCurrentUser ? getUser()?.full_name : null) || member?.email || 'Unknown'}
                                        {@const initials = displayName !== 'Unknown' ? displayName.split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase() : '?'}
                                        <div class="flex items-center gap-2 px-3 py-2 rounded-lg {isCurrentUser ? 'bg-primary/8 border border-primary/20' : 'bg-muted/50'}">
                                            <div class="w-6 h-6 rounded-full {isCurrentUser ? 'bg-primary text-primary-foreground' : 'bg-muted-foreground/20 text-muted-foreground'} flex items-center justify-center text-[10px] font-semibold">
                                                {#if assignment}
                                                    {initials}
                                                {:else}
                                                    ?
                                                {/if}
                                            </div>
                                            <div class="text-sm">
                                                <span class="font-medium text-foreground">{lane.data.label}</span>
                                                <span class="text-muted-foreground ml-1">—
                                                    {#if assignment}
                                                        {isCurrentUser ? 'You' : displayName}
                                                    {:else}
                                                        <span class="text-muted-foreground/60">Unassigned</span>
                                                    {/if}
                                                </span>
                                            </div>
                                            {#if steps.length > 0}
                                                <span class="text-xs font-medium ml-1 px-1.5 py-0.5 rounded {completedCount === steps.length ? 'bg-emerald-100 text-emerald-700' : completedCount > 0 ? 'bg-blue-100 text-blue-700' : 'text-muted-foreground'}">
                                                    {completedCount}/{steps.length}
                                                </span>
                                            {/if}
                                        </div>
                                    {/each}
                                </div>
                            {:else}
                                <!-- Roleless run: single assignee -->
                                {@const assignment = roleAssignments[0]}
                                {@const isCurrentUser = assignment?.user_id === getUser()?.id}
                                {@const member = assignment ? projectMembers.find((m) => m.id === assignment.user_id) : null}
                                {@const displayName = member?.full_name || (isCurrentUser ? getUser()?.full_name : null) || member?.email || 'Unknown'}
                                {@const initials = displayName !== 'Unknown' ? displayName.split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase() : '?'}
                                <div class="flex items-center gap-2">
                                    <div class="w-6 h-6 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-[10px] font-semibold">
                                        {initials}
                                    </div>
                                    <span class="text-sm">
                                        <span class="font-medium text-foreground">Operator</span>
                                        <span class="text-muted-foreground ml-1">— {isCurrentUser ? 'You' : displayName}</span>
                                    </span>
                                </div>
                            {/if}
                        </div>
                    {/if}

                    <!-- Assigned User View (Wizard) -->
                    {#if getCurrentUserAssignment()}
                        <div class="bg-white rounded-lg border border-border p-2 sm:p-8">
                            <RoleWizard
                                steps={getWizardSteps()}
                                runId={run.id}
                                executionData={run.execution_data || {}}
                                onDataUpdate={handleExecutionDataUpdate}
                                onAllStepsComplete={() => {
                                    if (allStepsComplete()) {
                                        showCompleteConfirm = true;
                                    }
                                }}
                            />
                        </div>

                        <!-- Analyze All Banner -->
                        {#if unanalyzedCount > 0}
                            <div class="flex items-center justify-between bg-amber-50 border border-amber-200 rounded-lg p-4 mt-4">
                                <div>
                                    <p class="text-sm font-medium text-amber-800">
                                        {unanalyzedCount} image{unanalyzedCount !== 1 ? 's' : ''} pending analysis
                                    </p>
                                    {#if analyzeAllProgress}
                                        <p class="text-xs text-amber-600 mt-1">{analyzeAllProgress}</p>
                                    {/if}
                                </div>
                                <button
                                    onclick={analyzeAllImages}
                                    disabled={analyzingAll}
                                    class="px-4 py-2 bg-amber-600 text-white rounded-lg text-sm font-medium hover:bg-amber-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {analyzingAll ? 'Analyzing...' : 'Analyze All'}
                                </button>
                            </div>
                        {/if}

                        <!-- Complete Run Confirmation Modal -->
                        {#if showCompleteConfirm}
                            <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                                <div class="bg-white rounded-lg shadow-lg p-6 max-w-sm">
                                    <h3 class="text-lg font-bold text-foreground mb-4">
                                        Complete Run?
                                    </h3>
                                    <p class="text-muted-foreground mb-4">
                                        All steps have been completed. Finalizing will mark this run as complete. You can still edit it later if needed.
                                    </p>
                                    {#if unanalyzedCount > 0}
                                        <div class="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4">
                                            <p class="text-sm font-medium text-amber-800">
                                                You have {unanalyzedCount} unanalyzed image{unanalyzedCount !== 1 ? 's' : ''}. Complete anyway?
                                            </p>
                                            <p class="text-xs text-amber-600 mt-1">
                                                You'll be notified to review them later.
                                            </p>
                                        </div>
                                    {/if}
                                    <div class="flex justify-end gap-3">
                                        <button
                                            onclick={() => (showCompleteConfirm = false)}
                                            class="px-4 py-2 bg-muted text-foreground/80 rounded-lg font-medium hover:bg-muted transition-colors"
                                        >
                                            Cancel
                                        </button>
                                        <button
                                            onclick={completeRun}
                                            disabled={completingRun}
                                            class="px-4 py-2 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 transition-colors disabled:bg-muted disabled:cursor-not-allowed"
                                        >
                                            {completingRun ? 'Completing...' : 'Complete Run'}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        {/if}
                    {:else}
                        <RunObserverView
                            swimLaneNodes={getSwimLaneNodes()}
                            allSteps={getAllUnitOpSteps()}
                            {roleAssignments}
                            {projectMembers}
                            executionData={run.execution_data || {}}
                            {getStepsForRole}
                        />
                    {/if}

                    <!-- Documents (available to all users) -->
                    {#if getAllUnitOpSteps().length > 0}
                        <div class="mt-8">
                            <RunDocuments
                                runId={run.id}
                                runName={run.name}
                                status={run.status}
                                onDownloadSop={downloadSop}
                                onDownloadBatchRecord={downloadBatchRecord}
                            />
                        </div>
                    {/if}
                </div>
            </div>

        <!-- COMPLETED State: Summary & Results -->
        {:else if run.status === "COMPLETED"}
            <div class="min-h-screen bg-background">
                <div class="max-w-5xl mx-auto px-6 py-8">
                  {#if !isEditMode}
                    <!-- Header -->
                    <div class="mb-8">
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <h1 class="text-3xl font-bold text-foreground">
                                    {run.name}
                                </h1>
                                {#if protocol}
                                    <p class="text-sm text-muted-foreground mt-1">
                                        Protocol: {protocol.name}
                                    </p>
                                {/if}
                            </div>
                            <span class="inline-block text-xs font-semibold px-3 py-1 bg-emerald-100 text-emerald-700 rounded-full">
                                Completed
                            </span>
                        </div>
                        <a
                            href="/projects/{run.project_id}?tab=runs"
                            class="text-sm text-muted-foreground hover:text-foreground/80"
                        >
                            &larr; Back to project
                        </a>
                    </div>

                    <!-- Run Info -->
                    <div class="grid grid-cols-2 gap-6 mb-8">
                        <div class="bg-white rounded-lg border border-border p-6">
                            <h3 class="text-sm font-semibold text-muted-foreground uppercase mb-2">
                                Status
                            </h3>
                            <p class="text-lg font-bold text-emerald-600">
                                Completed
                            </p>
                        </div>
                        <div class="bg-white rounded-lg border border-border p-6">
                            <h3 class="text-sm font-semibold text-muted-foreground uppercase mb-2">
                                Completed
                            </h3>
                            <p class="text-lg font-bold text-foreground">
                                {Object.values(run.execution_data || {}).filter(
                                    (d: any) => d.status === "completed"
                                ).length} / {Object.keys(run.execution_data || {})
                                    .length} steps
                            </p>
                        </div>
                    </div>

                    <!-- Results Summary -->
                    <RunResultsSummary
                        swimLaneNodes={getSwimLaneNodes()}
                        allSteps={getAllUnitOpSteps()}
                        {roleAssignments}
                        {projectMembers}
                        executionData={run.execution_data || {}}
                        {getStepsForRole}
                    />

                    <!-- Documents Section -->
                    <div class="mb-8">
                        <RunDocuments
                            runId={run.id}
                            runName={run.name}
                            status={run.status}
                            onDownloadSop={downloadSop}
                            onDownloadBatchRecord={downloadBatchRecord}
                        />
                    </div>

                    <!-- Footer -->
                    <div class="flex justify-between items-center">
                        <a
                            href="/projects/{run.project_id}?tab=runs"
                            class="text-muted-foreground hover:text-foreground font-medium"
                        >
                            &larr; Back to project
                        </a>
                        <button
                            onclick={enterEditMode}
                            class="px-6 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 transition-colors"
                        >
                            Edit Run
                        </button>
                    </div>
                  {:else}
                    <RunEditMode
                        runId={run.id}
                        runName={run.name}
                        protocolName={protocol?.name ?? null}
                        steps={getAllUnitOpSteps()}
                        {editExecutionData}
                        {savingEdits}
                        {error}
                        onDataUpdate={handleEditDataUpdate}
                        onSave={saveEdits}
                        onCancel={cancelEditMode}
                    />
                  {/if}
                </div>
            </div>

        <!-- EDITED State: Read-only summary with edit annotations -->
        {:else if run.status === "EDITED"}
            <div class="min-h-screen bg-background">
                <div class="max-w-5xl mx-auto px-6 py-8">
                  {#if !isEditMode}
                    <!-- Header -->
                    <div class="mb-8">
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <h1 class="text-3xl font-bold text-foreground">
                                    {run.name}
                                </h1>
                                {#if protocol}
                                    <p class="text-sm text-muted-foreground mt-1">
                                        Protocol: {protocol.name}
                                    </p>
                                {/if}
                            </div>
                            <span class="inline-block text-xs font-semibold px-3 py-1 bg-amber-100 text-amber-700 rounded-full">
                                Edited
                            </span>
                        </div>
                        <a
                            href="/projects/{run.project_id}?tab=runs"
                            class="text-sm text-muted-foreground hover:text-foreground/80"
                        >
                            &larr; Back to project
                        </a>
                        <div class="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                            <p class="text-sm text-amber-700">
                                This run has been edited after completion. Changed values show the original (struck through) and the updated value.
                            </p>
                        </div>
                    </div>

                    <!-- Run Info -->
                    <div class="grid grid-cols-2 gap-6 mb-8">
                        <div class="bg-white rounded-lg border border-border p-6">
                            <h3 class="text-sm font-semibold text-muted-foreground uppercase mb-2">
                                Status
                            </h3>
                            <p class="text-lg font-bold text-amber-600">
                                Edited
                            </p>
                        </div>
                        <div class="bg-white rounded-lg border border-border p-6">
                            <h3 class="text-sm font-semibold text-muted-foreground uppercase mb-2">
                                Steps
                            </h3>
                            <p class="text-lg font-bold text-foreground">
                                {Object.values(run.execution_data || {}).filter(
                                    (d: any) => d.status === "completed"
                                ).length} / {Object.keys(run.execution_data || {})
                                    .length} completed
                            </p>
                        </div>
                    </div>

                    <!-- Edited Results Summary -->
                    <RunResultsSummary
                        swimLaneNodes={getSwimLaneNodes()}
                        allSteps={getAllUnitOpSteps()}
                        {roleAssignments}
                        {projectMembers}
                        executionData={run.execution_data || {}}
                        showEditAnnotations={true}
                        {getStepsForRole}
                    />

                    <!-- Documents Section -->
                    <div class="mb-8">
                        <RunDocuments
                            runId={run.id}
                            runName={run.name}
                            status={run.status}
                            onDownloadSop={downloadSop}
                            onDownloadBatchRecord={downloadBatchRecord}
                        />
                    </div>

                    <!-- Footer -->
                    <div class="flex justify-between items-center">
                        <a
                            href="/projects/{run.project_id}?tab=runs"
                            class="text-muted-foreground hover:text-foreground font-medium"
                        >
                            &larr; Back to project
                        </a>
                        <button
                            onclick={enterEditMode}
                            class="px-6 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 transition-colors"
                        >
                            Edit Again
                        </button>
                    </div>
                  {:else}
                    <RunEditMode
                        runId={run.id}
                        runName={run.name}
                        protocolName={protocol?.name ?? null}
                        steps={getAllUnitOpSteps()}
                        {editExecutionData}
                        {savingEdits}
                        {error}
                        reEdit={true}
                        onDataUpdate={handleEditDataUpdate}
                        onSave={saveEdits}
                        onCancel={cancelEditMode}
                    />
                  {/if}
                </div>
            </div>

        <!-- ARCHIVED: Placeholder -->
        {:else}
            <div class="max-w-5xl mx-auto px-6 py-8">
                <div class="mb-8">
                    <div class="flex items-center justify-between mb-2">
                        <h1 class="text-3xl font-bold text-foreground">
                            {run.name}
                        </h1>
                        <span class="inline-block text-xs font-semibold px-3 py-1 bg-muted text-foreground/80 rounded-full">
                            {run.status}
                        </span>
                    </div>
                    <a
                        href="/projects/{run.project_id}?tab=runs"
                        class="text-sm text-muted-foreground hover:text-foreground/80"
                    >
                        &larr; Back to project
                    </a>
                </div>

                <div class="p-8 card-warm rounded-xl text-center text-muted-foreground">
                    <p class="text-lg font-medium mb-2">Run {run.status}</p>
                    <p class="text-sm">This run is {run.status.toLowerCase()}.</p>
                </div>
            </div>
        {/if}

        <!-- Go Offline Dialog (available in PLANNED and ACTIVE states) -->
        <GoOfflineDialog
            bind:open={showGoOffline}
            runId={run.id}
            runName={run.name}
        />
    {/if}
</div>
