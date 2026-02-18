<script lang="ts">
    import { onMount } from "svelte";
    import { page } from '$app/stores';
    import { api } from "$lib/api";
    import { getUser } from "$lib/auth.svelte";

    const id = $derived($page.params.id);

    let experiment = $state<any>(null);
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

    async function loadData() {
        try {
            experiment = await api.get(`/science/experiments/${id}`);

            // Load protocol if linked
            if (experiment.protocol_id) {
                protocol = await api.get(`/science/protocols/${experiment.protocol_id}`);
            }

            // Load role assignments
            const assignResp = await api.get(
                `/science/experiments/${id}/role-assignments`
            );
            roleAssignments = assignResp.items || [];

            // Load project members
            const membersResp = await api.get(
                `/science/projects/${experiment.project_id}/members`
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
                        `/science/experiments/${id}/role-assignments/${existing.id}`
                    );
                    roleAssignments = roleAssignments.filter(
                        (a) => a.lane_node_id !== laneNodeId
                    );
                }
            } else {
                // Create or update assignment
                const resp = await api.post(
                    `/science/experiments/${id}/role-assignments`,
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

    async function startExperiment() {
        try {
            savingStatus = true;
            await api.put(`/science/experiments/${id}`, { status: "ACTIVE" });
            experiment = await api.get(`/science/experiments/${id}`);
            showStartConfirm = false;
        } catch (e: any) {
            error = e.message;
        } finally {
            savingStatus = false;
        }
    }

    function getSwimLaneNodes() {
        if (!experiment?.graph) return [];
        return (experiment.graph.nodes || []).filter((n: any) => n.type === "swimLane");
    }

    function getRoleAssignment(laneNodeId: string) {
        return roleAssignments.find((a) => a.lane_node_id === laneNodeId);
    }

    function allRolesAssigned() {
        const swimLanes = getSwimLaneNodes();
        return swimLanes.every((lane: any) => getRoleAssignment(lane.id));
    }

    onMount(() => {
        loadData();
    });
</script>

<div class="min-h-screen bg-slate-50">
    {#if loading}
        <div class="flex items-center justify-center h-screen text-slate-500">
            <div class="text-center">
                <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-slate-400 mx-auto mb-3"></div>
                Loading experiment...
            </div>
        </div>
    {:else if error}
        <div class="flex items-center justify-center h-screen">
            <div class="text-center">
                <div class="text-red-500 font-semibold mb-2">Error loading experiment</div>
                <div class="text-slate-500 text-sm">{error}</div>
            </div>
        </div>
    {:else if !experiment}
        <div class="flex items-center justify-center h-screen text-slate-500">
            Experiment not found
        </div>
    {:else}
        <!-- PLANNED State: Setup & Role Assignment -->
        {#if experiment.status === "PLANNED"}
            <div class="max-w-5xl mx-auto px-6 py-8">
                <!-- Header -->
                <div class="mb-8">
                    <div class="flex items-center justify-between mb-2">
                        <h1 class="text-3xl font-bold text-slate-900">
                            {experiment.name}
                        </h1>
                        <span class="inline-block text-xs font-semibold px-3 py-1 bg-slate-200 text-slate-700 rounded-full">
                            Planned
                        </span>
                    </div>
                    <a
                        href="/projects/{experiment.project_id}"
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
                            Assign team members to each role. All roles must be assigned before starting the experiment.
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

                <!-- Action Buttons -->
                <div class="flex justify-between items-center">
                    <a
                        href="/projects/{experiment.project_id}"
                        class="text-slate-600 hover:text-slate-800 text-sm font-medium"
                    >
                        ← Back to project
                    </a>

                    {#if getSwimLaneNodes().length > 0}
                        <button
                            onclick={() => (showStartConfirm = true)}
                            disabled={!allRolesAssigned()}
                            class="px-6 py-2 bg-teal-600 text-white rounded-lg font-medium hover:bg-teal-700 transition-colors disabled:bg-slate-300 disabled:cursor-not-allowed"
                        >
                            Start Experiment
                        </button>
                    {/if}
                </div>

                <!-- Start Confirmation Modal -->
                {#if showStartConfirm}
                    <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                        <div class="bg-white rounded-lg shadow-lg p-6 max-w-sm">
                            <h3 class="text-lg font-bold text-slate-900 mb-4">
                                Start Experiment?
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
                                    onclick={startExperiment}
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

        <!-- ACTIVE, COMPLETED, ARCHIVED: Placeholder for now -->
        {:else}
            <div class="max-w-5xl mx-auto px-6 py-8">
                <div class="mb-8">
                    <div class="flex items-center justify-between mb-2">
                        <h1 class="text-3xl font-bold text-slate-900">
                            {experiment.name}
                        </h1>
                        <span class="inline-block text-xs font-semibold px-3 py-1 bg-emerald-100 text-emerald-700 rounded-full">
                            {experiment.status}
                        </span>
                    </div>
                    <a
                        href="/projects/{experiment.project_id}"
                        class="text-sm text-slate-500 hover:text-slate-700"
                    >
                        ← Back to project
                    </a>
                </div>

                <div class="p-8 bg-white border border-slate-200 rounded-lg text-center text-slate-500">
                    <p class="text-lg font-medium mb-2">Experiment {experiment.status}</p>
                    <p class="text-sm">
                        {#if experiment.status === "ACTIVE"}
                            Multi-page wizard runner coming soon
                        {:else if experiment.status === "COMPLETED"}
                            Completed results view coming soon
                        {:else}
                            View coming soon
                        {/if}
                    </p>
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
