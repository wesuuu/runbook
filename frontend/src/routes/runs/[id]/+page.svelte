<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { api } from "$lib/api";
    import { getUser } from "$lib/auth.svelte";
    import { goto } from '$app/navigation';
    import RoleWizard from "$lib/components/RoleWizard.svelte";

    const id = $derived($page.params.id);

    let run = $state<any>(null);
    let protocol = $state<any>(null);
    let roleAssignments = $state<any[]>([]);
    let projectMembers = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let savingStatus = $state(false);

    // UI State
    let selectedNodeId = $state<string | null>(null);
    let nodeEditData = $state<any>({});
    let showStartConfirm = $state(false);

    // Temp state for assignment updates
    let assignmentChanges = $state<Record<string, string>>({});

    // Load data whenever id changes
    $effect(() => {
        if (id) {
            loading = true;
            error = null;
            loadData();
        }
    });

    onMount(() => {
        if (id) {
            loadData();
        }
    });

    async function loadData() {
        try {
            run = await api.get(`/science/runs/${id}`);

            // Load protocol if linked
            if (run.protocol_id) {
                protocol = await api.get(`/science/protocols/${run.protocol_id}`);
            }

            // Load role assignments
            const assignResp = await api.get(
                `/science/runs/${id}/role-assignments`
            );
            roleAssignments = assignResp.items || [];

            // Load project members
            const membersResp = await api.get(
                `/science/projects/${run.project_id}/members`
            );
            projectMembers = membersResp || [];
        } catch (e: any) {
            error = e.message;
        } finally {
            loading = false;
        }
    }

    async function updateRoleAssignment(
        laneNodeId: string,
        roleName: string,
        userId: string | null
    ) {
        try {
            if (!userId) {
                // Delete assignment if user cleared
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
                // Create or update assignment
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
        } catch (e: any) {
            console.error("Failed to update assignment:", e.message);
            error = e.message;
        }
    }

    async function startRun() {
        try {
            savingStatus = true;
            await api.put(`/science/runs/${id}`, { status: "ACTIVE" });
            run = await api.get(`/science/runs/${id}`);
            showStartConfirm = false;
        } catch (e: any) {
            error = e.message;
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
        // At least one person must be assigned
        if (roleAssignments.length === 0) {
            return false;
        }

        // If there are swimlanes, all must be assigned
        const swimLanes = getSwimLaneNodes();
        if (swimLanes.length > 0) {
            return swimLanes.every((lane: any) => getRoleAssignment(lane.id));
        }

        // If no swimlanes, at least one assignment is enough
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

        // Fallback: if no unitOps are parented to ANY swimlane, return all steps
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

    let showCompleteConfirm = $state(false);
    let completingRun = $state(false);

    // Edit mode state
    let isEditMode = $state(false);
    let editExecutionData = $state<Record<string, any>>({});
    let savingEdits = $state(false);

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
        } catch (e: any) {
            error = e.message;
        } finally {
            completingRun = false;
        }
    }

    function enterEditMode() {
        // Deep clone execution_data so edits are local until saved
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
        } catch (e: any) {
            error = e.message;
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

    function getParamLabel(key: string, step: any): string {
        const props = step.paramSchema?.properties || {};
        const prop = props[key];
        return prop?.title || key.replace(/_/g, ' ');
    }

</script>

<div class="min-h-screen bg-slate-50">
    {#if loading}
        <div class="flex items-center justify-center h-screen text-slate-500">
            <div class="text-center">
                <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-slate-400 mx-auto mb-3"></div>
                Loading run...
            </div>
        </div>
    {:else if error}
        <div class="flex items-center justify-center h-screen">
            <div class="text-center">
                <div class="text-red-500 font-semibold mb-2">Error loading run</div>
                <div class="text-slate-500 text-sm">{error}</div>
            </div>
        </div>
    {:else if !run}
        <div class="flex items-center justify-center h-screen text-slate-500">
            Run not found
        </div>
    {:else}
        <!-- PLANNED State: Setup & Role Assignment -->
        {#if run.status === "PLANNED"}
            <div class="max-w-5xl mx-auto px-6 py-8">
                <!-- Header -->
                <div class="mb-8">
                    <div class="flex items-center justify-between mb-2">
                        <h1 class="text-3xl font-bold text-slate-900">
                            {run.name}
                        </h1>
                        <span class="inline-block text-xs font-semibold px-3 py-1 bg-slate-200 text-slate-700 rounded-full">
                            Planned
                        </span>
                    </div>
                    <a
                        href="/projects/{run.project_id}?tab=runs"
                        class="text-sm text-slate-500 hover:text-slate-700"
                    >
                        ← Back to project
                    </a>
                </div>

                {#if error}
                    <div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                        {error}
                    </div>
                {/if}

                <!-- Protocol Info -->
                {#if protocol}
                    <div class="mb-8 p-6 bg-white border border-slate-200 rounded-lg">
                        <h2 class="text-lg font-semibold text-slate-900 mb-2">
                            Protocol
                        </h2>
                        <div class="space-y-2">
                            <p class="text-slate-700 font-medium">{protocol.name}</p>
                            {#if protocol.description}
                                <p class="text-slate-600 text-sm">{protocol.description}</p>
                            {/if}
                            <a
                                href="/protocols/{protocol.id}"
                                class="inline-block text-sm text-teal-600 hover:text-teal-700 font-medium mt-2"
                            >
                                View protocol →
                            </a>
                        </div>
                    </div>
                {/if}

                <!-- Role Assignments -->
                {#if getSwimLaneNodes().length > 0}
                    <div class="mb-8 p-6 bg-white border border-slate-200 rounded-lg">
                        <h2 class="text-lg font-semibold text-slate-900 mb-6">
                            Role Assignments
                        </h2>
                        <p class="text-sm text-slate-600 mb-6">
                            Assign team members to each role. All roles must be assigned before starting the run.
                        </p>

                        <div class="space-y-4">
                            {#each getSwimLaneNodes() as lane}
                                {@const assignment = getRoleAssignment(lane.id)}
                                {@const selectedUserId = assignmentChanges[lane.id] ?? assignment?.user_id ?? ""}
                                <div class="flex items-end gap-4 p-4 bg-slate-50 rounded-lg">
                                    <div class="flex-1">
                                        <label class="block text-sm font-medium text-slate-700 mb-2">
                                            {lane.data.label}
                                        </label>
                                        <select
                                            value={selectedUserId}
                                            onchange={(e) => {
                                                assignmentChanges[lane.id] = e.currentTarget.value;
                                            }}
                                            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent bg-white"
                                        >
                                            <option value="">Select user...</option>
                                            {#each projectMembers as member}
                                                <option value={member.id}>
                                                    {member.full_name || member.email}
                                                </option>
                                            {/each}
                                        </select>
                                    </div>
                                    {#if selectedUserId && selectedUserId !== (assignment?.user_id ?? "")}
                                        <button
                                            onclick={() =>
                                                updateRoleAssignment(lane.id, lane.data.label, selectedUserId)
                                            }
                                            class="px-4 py-2 bg-teal-600 text-white rounded-lg text-sm font-medium hover:bg-teal-700 transition-colors"
                                        >
                                            Save
                                        </button>
                                    {/if}
                                    {#if assignment?.user_id && !selectedUserId}
                                        <button
                                            onclick={() =>
                                                updateRoleAssignment(lane.id, lane.data.label, null)
                                            }
                                            class="px-4 py-2 bg-red-100 text-red-700 rounded-lg text-sm font-medium hover:bg-red-200 transition-colors"
                                        >
                                            Clear
                                        </button>
                                    {/if}
                                </div>
                            {/each}
                        </div>
                    </div>
                {/if}

                <!-- Assign User (No Roles / Roleless Run) -->
                {#if getSwimLaneNodes().length === 0}
                    {@const assignment = getRoleAssignment("__run__")}
                    {@const selectedUserId = assignmentChanges["__run__"] ?? assignment?.user_id ?? ""}
                    <div class="mb-8 p-6 bg-white border border-slate-200 rounded-lg">
                        <h2 class="text-lg font-semibold text-slate-900 mb-2">
                            Run Assignee
                        </h2>
                        <p class="text-sm text-slate-600 mb-4">
                            Assign a team member to this run before starting.
                        </p>
                        <div class="flex items-end gap-4 p-4 bg-slate-50 rounded-lg">
                            <div class="flex-1">
                                <label class="block text-sm font-medium text-slate-700 mb-2">
                                    Operator
                                </label>
                                <select
                                    value={selectedUserId}
                                    onchange={(e) => {
                                        assignmentChanges["__run__"] = e.currentTarget.value;
                                    }}
                                    class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent bg-white"
                                >
                                    <option value="">Select user...</option>
                                    {#each projectMembers as member}
                                        <option value={member.id}>
                                            {member.full_name || member.email}
                                        </option>
                                    {/each}
                                </select>
                            </div>
                            {#if selectedUserId && selectedUserId !== (assignment?.user_id ?? "")}
                                <button
                                    onclick={() =>
                                        updateRoleAssignment("__run__", "Operator", selectedUserId)
                                    }
                                    class="px-4 py-2 bg-teal-600 text-white rounded-lg text-sm font-medium hover:bg-teal-700 transition-colors"
                                >
                                    Save
                                </button>
                            {/if}
                            {#if assignment?.user_id && !selectedUserId}
                                <button
                                    onclick={() =>
                                        updateRoleAssignment("__run__", "Operator", null)
                                    }
                                    class="px-4 py-2 bg-red-100 text-red-700 rounded-lg text-sm font-medium hover:bg-red-200 transition-colors"
                                >
                                    Clear
                                </button>
                            {/if}
                        </div>
                    </div>
                {/if}

                <!-- Electronic Batch Record -->
                {#if getAllUnitOpSteps().length > 0}
                    <div class="mb-8 p-6 bg-white border border-slate-200 rounded-lg">
                        <h2 class="text-lg font-semibold text-slate-900 mb-6">
                            Electronic Batch Record
                        </h2>
                        <p class="text-sm text-slate-600 mb-4">
                            {getAllUnitOpSteps().length} steps in this run.
                        </p>

                        <div class="overflow-x-auto">
                            <table class="w-full text-sm">
                                <thead>
                                    <tr class="border-b border-slate-200">
                                        <th class="text-left py-3 px-4 font-semibold text-slate-700 w-8">#</th>
                                        <th class="text-left py-3 px-4 font-semibold text-slate-700">Step</th>
                                        <th class="text-left py-3 px-4 font-semibold text-slate-700">Category</th>
                                        <th class="text-left py-3 px-4 font-semibold text-slate-700">Duration</th>
                                        <th class="text-left py-3 px-4 font-semibold text-slate-700">Parameters</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {#each getAllUnitOpSteps() as step, i}
                                        <tr class="border-b border-slate-100 hover:bg-slate-50">
                                            <td class="py-3 px-4 text-slate-500 font-mono">{i + 1}</td>
                                            <td class="py-3 px-4">
                                                <p class="font-medium text-slate-900">{step.name}</p>
                                                {#if step.description}
                                                    <p class="text-xs text-slate-500 mt-1">{step.description}</p>
                                                {/if}
                                            </td>
                                            <td class="py-3 px-4">
                                                <span class="inline-block text-xs font-semibold px-2 py-1 bg-slate-100 text-slate-700 rounded">
                                                    {step.category || '—'}
                                                </span>
                                            </td>
                                            <td class="py-3 px-4 text-slate-700">
                                                {step.duration_min ? `${step.duration_min} min` : '—'}
                                            </td>
                                            <td class="py-3 px-4">
                                                {#if step.params && Object.keys(step.params).length > 0}
                                                    <div class="space-y-1">
                                                        {#each Object.entries(step.params) as [key, value]}
                                                            <div class="text-xs">
                                                                <span class="text-slate-500">{key.replace(/_/g, ' ')}:</span>
                                                                <span class="font-medium text-slate-800 ml-1">{value}</span>
                                                            </div>
                                                        {/each}
                                                    </div>
                                                {:else}
                                                    <span class="text-slate-400">—</span>
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
                    <div class="mb-8 p-6 bg-white border border-slate-200 rounded-lg">
                        <h2 class="text-lg font-semibold text-slate-900 mb-6">
                            Documents
                        </h2>
                        <p class="text-sm text-slate-600 mb-6">
                            Download SOPs and batch record for your run.
                        </p>

                        <div class="space-y-3">
                            <button
                                onclick={downloadSop}
                                class="w-full text-left px-4 py-3 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-slate-900">
                                        Download SOP
                                    </span>
                                    <span class="text-slate-400">↓</span>
                                </div>
                            </button>

                            <hr class="my-3" />

                            <button
                                onclick={() => downloadBatchRecord(false)}
                                class="w-full text-left px-4 py-3 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-slate-900">
                                        Download Blank Batch Record
                                    </span>
                                    <span class="text-slate-400">↓</span>
                                </div>
                            </button>
                        </div>
                    </div>
                {/if}

                <!-- Action Buttons -->
                <div class="flex justify-between items-center">
                    <a
                        href="/projects/{run.project_id}?tab=runs"
                        class="text-slate-600 hover:text-slate-800 text-sm font-medium"
                    >
                        ← Back to project
                    </a>

                    <button
                        onclick={() => (showStartConfirm = true)}
                        disabled={!allRolesAssigned()}
                        class="px-6 py-2 bg-teal-600 text-white rounded-lg font-medium hover:bg-teal-700 transition-colors disabled:bg-slate-300 disabled:cursor-not-allowed"
                    >
                        Start Run
                    </button>
                </div>

                <!-- Start Confirmation Modal -->
                {#if showStartConfirm}
                    <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                        <div class="bg-white rounded-lg shadow-lg p-6 max-w-sm">
                            <h3 class="text-lg font-bold text-slate-900 mb-4">
                                Start Run?
                            </h3>
                            <p class="text-slate-600 mb-6">
                                Once started, users can begin logging results for their assigned roles.
                            </p>
                            <div class="flex justify-end gap-3">
                                <button
                                    onclick={() => (showStartConfirm = false)}
                                    class="px-4 py-2 bg-slate-100 text-slate-700 rounded-lg font-medium hover:bg-slate-200 transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    onclick={startRun}
                                    disabled={savingStatus}
                                    class="px-4 py-2 bg-teal-600 text-white rounded-lg font-medium hover:bg-teal-700 transition-colors disabled:bg-slate-400 disabled:cursor-not-allowed"
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
            <div class="min-h-screen bg-slate-50">
                <div class="max-w-4xl mx-auto px-6 py-8">
                    <!-- Header -->
                    <div class="mb-8">
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <h1 class="text-3xl font-bold text-slate-900">
                                    {run.name}
                                </h1>
                                {#if protocol}
                                    <p class="text-sm text-slate-500 mt-1">
                                        Protocol: {protocol.name}
                                    </p>
                                {/if}
                            </div>
                            <span class="inline-block text-xs font-semibold px-3 py-1 bg-emerald-100 text-emerald-700 rounded-full">
                                Running
                            </span>
                        </div>
                        <a
                            href="/projects/{run.project_id}?tab=runs"
                            class="text-sm text-slate-500 hover:text-slate-700"
                        >
                            ← Back to project
                        </a>
                    </div>

                    <!-- Assigned User View (Wizard) -->
                    {#if getCurrentUserAssignment()}
                        <div class="bg-white rounded-lg border border-slate-200 p-8">
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

                        <!-- Complete Run Confirmation Modal -->
                        {#if showCompleteConfirm}
                            <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                                <div class="bg-white rounded-lg shadow-lg p-6 max-w-sm">
                                    <h3 class="text-lg font-bold text-slate-900 mb-4">
                                        Complete Run?
                                    </h3>
                                    <p class="text-slate-600 mb-6">
                                        All steps have been completed. Finalizing will mark this run as complete. You can still edit it later if needed.
                                    </p>
                                    <div class="flex justify-end gap-3">
                                        <button
                                            onclick={() => (showCompleteConfirm = false)}
                                            class="px-4 py-2 bg-slate-100 text-slate-700 rounded-lg font-medium hover:bg-slate-200 transition-colors"
                                        >
                                            Cancel
                                        </button>
                                        <button
                                            onclick={completeRun}
                                            disabled={completingRun}
                                            class="px-4 py-2 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 transition-colors disabled:bg-slate-400 disabled:cursor-not-allowed"
                                        >
                                            {completingRun ? 'Completing...' : 'Complete Run'}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        {/if}
                    {:else}
                        <!-- Observer View (Non-Assigned User) -->
                        <div class="space-y-6">
                            <div class="bg-white rounded-lg border border-slate-200 p-6">
                                <h2 class="text-lg font-semibold text-slate-900 mb-4">
                                    Run Status
                                </h2>
                                <p class="text-slate-600 mb-4">
                                    You are not assigned to a role in this run. Below is the current status.
                                </p>

                                <!-- Role Status Table -->
                                <div class="overflow-x-auto">
                                    <table class="w-full text-sm">
                                        <thead>
                                            <tr class="border-b border-slate-200">
                                                <th class="text-left py-3 px-4 font-semibold text-slate-700">
                                                    Role
                                                </th>
                                                <th class="text-left py-3 px-4 font-semibold text-slate-700">
                                                    Assigned To
                                                </th>
                                                <th class="text-center py-3 px-4 font-semibold text-slate-700">
                                                    Progress
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {#each getSwimLaneNodes() as lane}
                                                {@const assignment = getRoleAssignment(lane.id)}
                                                {@const steps = getStepsForRole(lane.id)}
                                                {@const completedCount = steps.filter(
                                                    (s) =>
                                                        run.execution_data?.[s.id]?.status ===
                                                        "completed"
                                                ).length}
                                                <tr class="border-b border-slate-100 hover:bg-slate-50">
                                                    <td class="py-3 px-4 font-medium text-slate-900">
                                                        {lane.data.label}
                                                    </td>
                                                    <td class="py-3 px-4 text-slate-600">
                                                        {#if assignment}
                                                            {#each projectMembers.filter(
                                                                (m) =>
                                                                    m.id === assignment.user_id
                                                            ) as member}
                                                                {member.full_name ||
                                                                    member.email}
                                                            {/each}
                                                        {:else}
                                                            <span class="text-slate-400">
                                                                Unassigned
                                                            </span>
                                                        {/if}
                                                    </td>
                                                    <td class="py-3 px-4 text-center">
                                                        {#if steps.length > 0}
                                                            <span
                                                                class="inline-block text-xs font-semibold px-2 py-1 rounded {completedCount ===
                                                                steps.length
                                                                    ? 'bg-emerald-100 text-emerald-700'
                                                                    : completedCount > 0
                                                                      ? 'bg-blue-100 text-blue-700'
                                                                      : 'bg-slate-100 text-slate-600'}"
                                                            >
                                                                {completedCount} / {steps.length}
                                                            </span>
                                                        {:else}
                                                            <span class="text-slate-400">
                                                                --
                                                            </span>
                                                        {/if}
                                                    </td>
                                                </tr>
                                            {/each}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    {/if}

                    <!-- Documents (available to all users) -->
                    {#if getAllUnitOpSteps().length > 0}
                        <div class="mt-8 bg-white rounded-lg border border-slate-200 p-6">
                            <h2 class="text-lg font-semibold text-slate-900 mb-6">
                                Documents
                            </h2>

                            <div class="space-y-3">
                                <button
                                    onclick={downloadSop}
                                    class="w-full text-left px-4 py-3 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg transition-colors"
                                >
                                    <div class="flex items-center justify-between">
                                        <span class="font-medium text-slate-900">
                                            Download SOP
                                        </span>
                                        <span class="text-slate-400">↓</span>
                                    </div>
                                </button>

                                <hr class="my-3" />

                                <button
                                    onclick={() => downloadBatchRecord(false)}
                                    class="w-full text-left px-4 py-3 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg transition-colors"
                                >
                                    <div class="flex items-center justify-between">
                                        <span class="font-medium text-slate-900">
                                            Download Blank Batch Record
                                        </span>
                                        <span class="text-slate-400">↓</span>
                                    </div>
                                </button>
                            </div>
                        </div>
                    {/if}
                </div>
            </div>

        <!-- COMPLETED State: Summary & Results -->
        {:else if run.status === "COMPLETED"}
            <div class="min-h-screen bg-slate-50">
                <div class="max-w-5xl mx-auto px-6 py-8">
                  {#if !isEditMode}
                    <!-- Header -->
                    <div class="mb-8">
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <h1 class="text-3xl font-bold text-slate-900">
                                    {run.name}
                                </h1>
                                {#if protocol}
                                    <p class="text-sm text-slate-500 mt-1">
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
                            class="text-sm text-slate-500 hover:text-slate-700"
                        >
                            ← Back to project
                        </a>
                    </div>

                    <!-- Run Info -->
                    <div class="grid grid-cols-2 gap-6 mb-8">
                        <div class="bg-white rounded-lg border border-slate-200 p-6">
                            <h3 class="text-sm font-semibold text-slate-500 uppercase mb-2">
                                Status
                            </h3>
                            <p class="text-lg font-bold text-emerald-600">
                                Completed
                            </p>
                        </div>
                        <div class="bg-white rounded-lg border border-slate-200 p-6">
                            <h3 class="text-sm font-semibold text-slate-500 uppercase mb-2">
                                Completed
                            </h3>
                            <p class="text-lg font-bold text-slate-900">
                                {Object.values(run.execution_data || {}).filter(
                                    (d: any) => d.status === "completed"
                                ).length} / {Object.keys(run.execution_data || {})
                                    .length} steps
                            </p>
                        </div>
                    </div>

                    <!-- Results Summary -->
                    <div class="bg-white rounded-lg border border-slate-200 p-6 mb-8">
                        <h2 class="text-lg font-semibold text-slate-900 mb-6">
                            Results Summary
                        </h2>

                        <div class="space-y-6">
                            {#each getSwimLaneNodes() as lane}
                                {@const steps = getStepsForRole(lane.id)}
                                {@const assignment = getRoleAssignment(lane.id)}
                                <div class="pb-6 border-b border-slate-100 last:pb-0 last:border-0">
                                    <div class="flex items-center justify-between mb-4">
                                        <h3 class="font-semibold text-slate-900">
                                            {lane.data.label}
                                        </h3>
                                        {#if assignment}
                                            <span class="text-sm text-slate-600">
                                                {#each projectMembers.filter(
                                                    (m) => m.id === assignment.user_id
                                                ) as member}
                                                    {member.full_name ||
                                                        member.email}
                                                {/each}
                                            </span>
                                        {/if}
                                    </div>

                                    <div class="space-y-3">
                                        {#each steps as step}
                                            {@const stepData =
                                                run.execution_data?.[
                                                    step.id
                                                ]}
                                            <div class="p-3 bg-slate-50 rounded border border-slate-200">
                                                <div class="flex items-start justify-between mb-2">
                                                    <div>
                                                        <p class="font-medium text-slate-900">
                                                            {step.name}
                                                        </p>
                                                        {#if step.description}
                                                            <p class="text-xs text-slate-600 mt-1">
                                                                {step.description}
                                                            </p>
                                                        {/if}
                                                    </div>
                                                    <span
                                                        class="inline-block text-xs font-semibold px-2 py-1 rounded {stepData?.status ===
                                                        'completed'
                                                            ? 'bg-emerald-100 text-emerald-700'
                                                            : 'bg-slate-100 text-slate-600'}"
                                                    >
                                                        {stepData?.status?.replace(
                                                            /_/g,
                                                            " "
                                                        ) || "PENDING"}
                                                    </span>
                                                </div>

                                                {#if stepData?.results || stepData?.value || stepData?.notes}
                                                    <div class="text-sm space-y-2 mt-2">
                                                        {#if stepData?.results && Object.keys(stepData.results).length > 0}
                                                            <div class="grid grid-cols-2 gap-3">
                                                                {#each Object.entries(stepData.results) as [key, val]}
                                                                    <div>
                                                                        <p class="text-xs text-slate-600 font-semibold mb-0.5">
                                                                            {key.replace(/_/g, ' ')}
                                                                        </p>
                                                                        <p class="font-mono text-slate-900">
                                                                            {val}
                                                                        </p>
                                                                    </div>
                                                                {/each}
                                                            </div>
                                                        {:else if stepData?.value}
                                                            <div>
                                                                <p class="text-xs text-slate-600 font-semibold mb-0.5">
                                                                    Value
                                                                </p>
                                                                <p class="font-mono text-slate-900">
                                                                    {stepData.value}
                                                                </p>
                                                            </div>
                                                        {/if}
                                                        {#if stepData?.notes}
                                                            <div>
                                                                <p class="text-xs text-slate-600 font-semibold mb-0.5">
                                                                    Notes
                                                                </p>
                                                                <p class="text-slate-700">
                                                                    {stepData.notes}
                                                                </p>
                                                            </div>
                                                        {/if}
                                                    </div>
                                                {/if}

                                                {#if stepData?.timestamp}
                                                    <p class="text-xs text-slate-500 mt-2">
                                                        {new Date(
                                                            stepData.timestamp
                                                        ).toLocaleString()}
                                                    </p>
                                                {/if}
                                            </div>
                                        {/each}
                                    </div>
                                </div>
                            {/each}
                        </div>
                    </div>

                    <!-- Documents Section -->
                    <div class="bg-white rounded-lg border border-slate-200 p-6 mb-8">
                        <h2 class="text-lg font-semibold text-slate-900 mb-6">
                            Documents
                        </h2>

                        <div class="space-y-3">
                            <button
                                onclick={downloadSop}
                                class="w-full text-left px-4 py-3 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-slate-900">
                                        Download SOP
                                    </span>
                                    <span class="text-slate-400">↓</span>
                                </div>
                            </button>

                            <hr class="my-3" />

                            <button
                                onclick={() => downloadBatchRecord(false)}
                                class="w-full text-left px-4 py-3 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-slate-900">
                                        Download Blank Batch Record
                                    </span>
                                    <span class="text-slate-400">↓</span>
                                </div>
                            </button>

                            <button
                                onclick={() => downloadBatchRecord(true)}
                                class="w-full text-left px-4 py-3 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-emerald-900">
                                        Download Completed Batch Record
                                    </span>
                                    <span class="text-emerald-600">↓</span>
                                </div>
                            </button>

                            <hr class="my-3" />

                            <button
                                onclick={() => goto(`/export?runs=${id}`)}
                                class="w-full text-left px-4 py-3 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-blue-900">
                                        Export Data (CSV / Excel / JSON)
                                    </span>
                                    <span class="text-blue-600">↓</span>
                                </div>
                            </button>
                        </div>
                    </div>

                    <!-- Footer -->
                    <div class="flex justify-between items-center">
                        <a
                            href="/projects/{run.project_id}?tab=runs"
                            class="text-slate-600 hover:text-slate-800 font-medium"
                        >
                            ← Back to project
                        </a>
                        <button
                            onclick={enterEditMode}
                            class="px-6 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 transition-colors"
                        >
                            Edit Run
                        </button>
                    </div>
                  {:else}
                    <!-- Edit Mode Sub-View -->
                    <div class="mb-8">
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <h1 class="text-3xl font-bold text-slate-900">
                                    {run.name}
                                </h1>
                                {#if protocol}
                                    <p class="text-sm text-slate-500 mt-1">
                                        Protocol: {protocol.name}
                                    </p>
                                {/if}
                            </div>
                            <span class="inline-block text-xs font-semibold px-3 py-1 bg-amber-100 text-amber-700 rounded-full">
                                Editing
                            </span>
                        </div>
                        <div class="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                            <p class="text-sm text-amber-700">
                                You are editing a completed run. Changes will not be saved until you click "Save Edits". Original values will be preserved for GMP audit trail.
                            </p>
                        </div>
                    </div>

                    <!-- Edit Wizard (draft mode — no API calls until Save) -->
                    <div class="bg-white rounded-lg border border-slate-200 p-8 mb-8">
                        <RoleWizard
                            steps={getAllUnitOpSteps()}
                            runId={run.id}
                            executionData={editExecutionData}
                            draftMode={true}
                            onDataUpdate={handleEditDataUpdate}
                        />
                    </div>

                    {#if error}
                        <div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-base">
                            {error}
                        </div>
                    {/if}

                    <!-- Edit Mode Actions -->
                    <div class="flex justify-between items-center">
                        <button
                            onclick={cancelEditMode}
                            class="px-6 py-2 bg-slate-200 text-slate-700 rounded-lg font-medium hover:bg-slate-300 transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            onclick={saveEdits}
                            disabled={savingEdits}
                            class="px-6 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 transition-colors disabled:bg-slate-400 disabled:cursor-not-allowed"
                        >
                            {savingEdits ? 'Saving...' : 'Save Edits'}
                        </button>
                    </div>
                  {/if}
                </div>
            </div>

        <!-- EDITED State: Read-only summary with edit annotations -->
        {:else if run.status === "EDITED"}
            <div class="min-h-screen bg-slate-50">
                <div class="max-w-5xl mx-auto px-6 py-8">
                  {#if !isEditMode}
                    <!-- Header -->
                    <div class="mb-8">
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <h1 class="text-3xl font-bold text-slate-900">
                                    {run.name}
                                </h1>
                                {#if protocol}
                                    <p class="text-sm text-slate-500 mt-1">
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
                            class="text-sm text-slate-500 hover:text-slate-700"
                        >
                            ← Back to project
                        </a>
                        <div class="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                            <p class="text-sm text-amber-700">
                                This run has been edited after completion. Changed values show the original (struck through) and the updated value.
                            </p>
                        </div>
                    </div>

                    <!-- Run Info -->
                    <div class="grid grid-cols-2 gap-6 mb-8">
                        <div class="bg-white rounded-lg border border-slate-200 p-6">
                            <h3 class="text-sm font-semibold text-slate-500 uppercase mb-2">
                                Status
                            </h3>
                            <p class="text-lg font-bold text-amber-600">
                                Edited
                            </p>
                        </div>
                        <div class="bg-white rounded-lg border border-slate-200 p-6">
                            <h3 class="text-sm font-semibold text-slate-500 uppercase mb-2">
                                Steps
                            </h3>
                            <p class="text-lg font-bold text-slate-900">
                                {Object.values(run.execution_data || {}).filter(
                                    (d: any) => d.status === "completed"
                                ).length} / {Object.keys(run.execution_data || {})
                                    .length} completed
                            </p>
                        </div>
                    </div>

                    <!-- Edited Results Summary -->
                    <div class="bg-white rounded-lg border border-slate-200 p-6 mb-8">
                        <h2 class="text-lg font-semibold text-slate-900 mb-6">
                            Results Summary
                        </h2>

                        <div class="space-y-6">
                            {#each getSwimLaneNodes().length > 0 ? getSwimLaneNodes() : [{ id: '__all__', data: { label: 'All Steps' } }] as lane}
                                {@const steps = lane.id === '__all__' ? getAllUnitOpSteps() : getStepsForRole(lane.id)}
                                {@const assignment = lane.id === '__all__' ? null : getRoleAssignment(lane.id)}
                                <div class="pb-6 border-b border-slate-100 last:pb-0 last:border-0">
                                    {#if lane.id !== '__all__'}
                                        <div class="flex items-center justify-between mb-4">
                                            <h3 class="font-semibold text-slate-900">
                                                {lane.data.label}
                                            </h3>
                                            {#if assignment}
                                                <span class="text-sm text-slate-600">
                                                    {#each projectMembers.filter(
                                                        (m) => m.id === assignment.user_id
                                                    ) as member}
                                                        {member.full_name || member.email}
                                                    {/each}
                                                </span>
                                            {/if}
                                        </div>
                                    {/if}

                                    <div class="space-y-3">
                                        {#each steps as step}
                                            {@const stepData = run.execution_data?.[step.id]}
                                            {@const origResults = stepData?.original_results}
                                            {@const origValue = stepData?.original_value}
                                            {@const isEdited = !!(origResults || origValue)}
                                            <div class="p-3 rounded border {isEdited ? 'bg-amber-50 border-amber-200' : 'bg-slate-50 border-slate-200'}">
                                                <div class="flex items-start justify-between mb-2">
                                                    <div>
                                                        <p class="font-medium text-slate-900">
                                                            {step.name}
                                                        </p>
                                                        {#if step.description}
                                                            <p class="text-xs text-slate-600 mt-1">
                                                                {step.description}
                                                            </p>
                                                        {/if}
                                                    </div>
                                                    <div class="flex items-center gap-2">
                                                        {#if isEdited}
                                                            <span class="inline-block text-xs font-semibold px-2 py-1 rounded bg-amber-100 text-amber-700">
                                                                EDITED
                                                            </span>
                                                        {/if}
                                                        <span
                                                            class="inline-block text-xs font-semibold px-2 py-1 rounded {stepData?.status === 'completed'
                                                                ? 'bg-emerald-100 text-emerald-700'
                                                                : 'bg-slate-100 text-slate-600'}"
                                                        >
                                                            {stepData?.status?.replace(/_/g, " ") || "PENDING"}
                                                        </span>
                                                    </div>
                                                </div>

                                                {#if stepData?.results || stepData?.value || stepData?.notes}
                                                    <div class="text-sm space-y-2 mt-2">
                                                        {#if stepData?.results && Object.keys(stepData.results).length > 0}
                                                            <div class="grid grid-cols-2 gap-3">
                                                                {#each Object.entries(stepData.results) as [key, val]}
                                                                    <div>
                                                                        <p class="text-xs text-slate-600 font-semibold mb-0.5">
                                                                            {getParamLabel(key, step)}
                                                                        </p>
                                                                        {#if origResults && key in origResults && origResults[key] !== val}
                                                                            <p class="font-mono text-slate-400 line-through">
                                                                                {origResults[key]}
                                                                            </p>
                                                                            <p class="font-mono text-slate-900">
                                                                                {val}
                                                                            </p>
                                                                        {:else}
                                                                            <p class="font-mono text-slate-900">
                                                                                {val}
                                                                            </p>
                                                                        {/if}
                                                                    </div>
                                                                {/each}
                                                            </div>
                                                        {:else if stepData?.value}
                                                            <div>
                                                                <p class="text-xs text-slate-600 font-semibold mb-0.5">
                                                                    Value
                                                                </p>
                                                                {#if origValue && origValue !== stepData.value}
                                                                    <p class="font-mono text-slate-400 line-through">
                                                                        {origValue}
                                                                    </p>
                                                                    <p class="font-mono text-slate-900">
                                                                        {stepData.value}
                                                                    </p>
                                                                {:else}
                                                                    <p class="font-mono text-slate-900">
                                                                        {stepData.value}
                                                                    </p>
                                                                {/if}
                                                            </div>
                                                        {/if}
                                                        {#if stepData?.notes}
                                                            <div>
                                                                <p class="text-xs text-slate-600 font-semibold mb-0.5">
                                                                    Notes
                                                                </p>
                                                                <p class="text-slate-700">
                                                                    {stepData.notes}
                                                                </p>
                                                            </div>
                                                        {/if}
                                                    </div>
                                                {/if}

                                                {#if stepData?.timestamp}
                                                    <p class="text-xs text-slate-500 mt-2">
                                                        {new Date(stepData.timestamp).toLocaleString()}
                                                    </p>
                                                {/if}
                                            </div>
                                        {/each}
                                    </div>
                                </div>
                            {/each}
                        </div>
                    </div>

                    <!-- Documents Section -->
                    <div class="bg-white rounded-lg border border-slate-200 p-6 mb-8">
                        <h2 class="text-lg font-semibold text-slate-900 mb-6">
                            Documents
                        </h2>

                        <div class="space-y-3">
                            <button
                                onclick={downloadSop}
                                class="w-full text-left px-4 py-3 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-slate-900">
                                        Download SOP
                                    </span>
                                    <span class="text-slate-400">↓</span>
                                </div>
                            </button>

                            <hr class="my-3" />

                            <button
                                onclick={() => downloadBatchRecord(true)}
                                class="w-full text-left px-4 py-3 bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-amber-900">
                                        Download Edited Batch Record
                                    </span>
                                    <span class="text-amber-600">↓</span>
                                </div>
                            </button>

                            <hr class="my-3" />

                            <button
                                onclick={() => goto(`/export?runs=${id}`)}
                                class="w-full text-left px-4 py-3 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-blue-900">
                                        Export Data (CSV / Excel / JSON)
                                    </span>
                                    <span class="text-blue-600">↓</span>
                                </div>
                            </button>
                        </div>
                    </div>

                    <!-- Footer -->
                    <div class="flex justify-between items-center">
                        <a
                            href="/projects/{run.project_id}?tab=runs"
                            class="text-slate-600 hover:text-slate-800 font-medium"
                        >
                            ← Back to project
                        </a>
                        <button
                            onclick={enterEditMode}
                            class="px-6 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 transition-colors"
                        >
                            Edit Again
                        </button>
                    </div>
                  {:else}
                    <!-- Edit Mode Sub-View (re-editing an already edited run) -->
                    <div class="mb-8">
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <h1 class="text-3xl font-bold text-slate-900">
                                    {run.name}
                                </h1>
                                {#if protocol}
                                    <p class="text-sm text-slate-500 mt-1">
                                        Protocol: {protocol.name}
                                    </p>
                                {/if}
                            </div>
                            <span class="inline-block text-xs font-semibold px-3 py-1 bg-amber-100 text-amber-700 rounded-full">
                                Editing
                            </span>
                        </div>
                        <div class="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                            <p class="text-sm text-amber-700">
                                You are editing this run again. Changes will not be saved until you click "Save Edits".
                            </p>
                        </div>
                    </div>

                    <div class="bg-white rounded-lg border border-slate-200 p-8 mb-8">
                        <RoleWizard
                            steps={getAllUnitOpSteps()}
                            runId={run.id}
                            executionData={editExecutionData}
                            draftMode={true}
                            onDataUpdate={handleEditDataUpdate}
                        />
                    </div>

                    {#if error}
                        <div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-base">
                            {error}
                        </div>
                    {/if}

                    <div class="flex justify-between items-center">
                        <button
                            onclick={cancelEditMode}
                            class="px-6 py-2 bg-slate-200 text-slate-700 rounded-lg font-medium hover:bg-slate-300 transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            onclick={saveEdits}
                            disabled={savingEdits}
                            class="px-6 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 transition-colors disabled:bg-slate-400 disabled:cursor-not-allowed"
                        >
                            {savingEdits ? 'Saving...' : 'Save Edits'}
                        </button>
                    </div>
                  {/if}
                </div>
            </div>

        <!-- ARCHIVED: Placeholder -->
        {:else}
            <div class="max-w-5xl mx-auto px-6 py-8">
                <div class="mb-8">
                    <div class="flex items-center justify-between mb-2">
                        <h1 class="text-3xl font-bold text-slate-900">
                            {run.name}
                        </h1>
                        <span class="inline-block text-xs font-semibold px-3 py-1 bg-slate-100 text-slate-700 rounded-full">
                            {run.status}
                        </span>
                    </div>
                    <a
                        href="/projects/{run.project_id}?tab=runs"
                        class="text-sm text-slate-500 hover:text-slate-700"
                    >
                        ← Back to project
                    </a>
                </div>

                <div class="p-8 bg-white border border-slate-200 rounded-lg text-center text-slate-500">
                    <p class="text-lg font-medium mb-2">Run {run.status}</p>
                    <p class="text-sm">This run is {run.status.toLowerCase()}.</p>
                </div>
            </div>
        {/if}
    {/if}
</div>

<style>
    :global(body) {
        margin: 0;
        padding: 0;
    }
</style>
