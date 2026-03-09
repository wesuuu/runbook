<script lang="ts">
    import { page } from '$app/stores';
    import { api } from "$lib/api";
    import { getUser } from "$lib/auth.svelte";
    import { goto } from '$app/navigation';
    import RoleWizard from "$lib/components/RoleWizard.svelte";
    import GoOfflineDialog from "$lib/components/GoOfflineDialog.svelte";

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

            // Load unanalyzed image count
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
    let unanalyzedCount = $state(0);
    let showGoOffline = $state(false);
    let analyzingAll = $state(false);
    let analyzeAllProgress = $state('');

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
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
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

    function getParamLabel(key: string, step: any): string {
        const props = step.paramSchema?.properties || {};
        const prop = props[key];
        return prop?.title || key.replace(/_/g, ' ');
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
    {:else if error}
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
                                View protocol →
                            </a>
                        </div>
                    </div>
                {/if}

                <!-- Role Assignments -->
                {#if getSwimLaneNodes().length > 0}
                    <div class="mb-8 p-6 card-warm rounded-xl">
                        <h2 class="text-lg font-semibold text-foreground mb-6">
                            Role Assignments
                        </h2>
                        <p class="text-sm text-muted-foreground mb-6">
                            Assign team members to each role. All roles must be assigned before starting the run.
                        </p>

                        <div class="space-y-4">
                            {#each getSwimLaneNodes() as lane}
                                {@const assignment = getRoleAssignment(lane.id)}
                                {@const selectedUserId = assignmentChanges[lane.id] ?? assignment?.user_id ?? ""}
                                <div class="flex items-end gap-4 p-4 bg-background rounded-lg">
                                    <div class="flex-1">
                                        <label class="block text-sm font-medium text-foreground/80 mb-2">
                                            {lane.data.label}
                                        </label>
                                        <select
                                            value={selectedUserId}
                                            onchange={(e) => {
                                                assignmentChanges[lane.id] = e.currentTarget.value;
                                            }}
                                            class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white"
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
                                            class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors"
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
                    <div class="mb-8 p-6 card-warm rounded-xl">
                        <h2 class="text-lg font-semibold text-foreground mb-2">
                            Run Assignee
                        </h2>
                        <p class="text-sm text-muted-foreground mb-4">
                            Assign a team member to this run before starting.
                        </p>
                        <div class="flex items-end gap-4 p-4 bg-background rounded-lg">
                            <div class="flex-1">
                                <label class="block text-sm font-medium text-foreground/80 mb-2">
                                    Operator
                                </label>
                                <select
                                    value={selectedUserId}
                                    onchange={(e) => {
                                        assignmentChanges["__run__"] = e.currentTarget.value;
                                    }}
                                    class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white"
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
                                    class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors"
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
                    <div class="mb-8 p-6 card-warm rounded-xl">
                        <h2 class="text-lg font-semibold text-foreground mb-6">
                            Documents
                        </h2>
                        <p class="text-sm text-muted-foreground mb-6">
                            Download SOPs and batch record for your run.
                        </p>

                        <div class="space-y-3">
                            <button
                                onclick={downloadSop}
                                class="w-full text-left px-4 py-3 bg-background hover:bg-muted border border-border rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-foreground">
                                        Download SOP
                                    </span>
                                    <span class="text-muted-foreground/60">↓</span>
                                </div>
                            </button>

                            <hr class="my-3" />

                            <button
                                onclick={() => downloadBatchRecord(false)}
                                class="w-full text-left px-4 py-3 bg-background hover:bg-muted border border-border rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-foreground">
                                        Download Blank Batch Record
                                    </span>
                                    <span class="text-muted-foreground/60">↓</span>
                                </div>
                            </button>
                        </div>
                    </div>
                {/if}

                <!-- Action Buttons -->
                <div class="flex justify-between items-center">
                    <a
                        href="/projects/{run.project_id}?tab=runs"
                        class="text-muted-foreground hover:text-foreground text-sm font-medium"
                    >
                        ← Back to project
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
                            ← Back to project
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
                        <div class="bg-white rounded-lg border border-border p-8">
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
                        <!-- Observer View (Non-Assigned User) -->
                        <div class="space-y-6">
                            <div class="bg-white rounded-lg border border-border p-6">
                                <h2 class="text-lg font-semibold text-foreground mb-4">
                                    Run Status
                                </h2>
                                <p class="text-muted-foreground mb-4">
                                    You are not assigned to a role in this run. Below is the current status.
                                </p>

                                <!-- Role Status Table -->
                                {#if getSwimLaneNodes().length > 0}
                                    <div class="overflow-x-auto">
                                        <table class="w-full text-sm">
                                            <thead>
                                                <tr class="border-b border-border">
                                                    <th class="text-left py-3 px-4 font-semibold text-foreground/80">Role</th>
                                                    <th class="text-left py-3 px-4 font-semibold text-foreground/80">Assigned To</th>
                                                    <th class="text-center py-3 px-4 font-semibold text-foreground/80">Progress</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {#each getSwimLaneNodes() as lane}
                                                    {@const assignment = getRoleAssignment(lane.id)}
                                                    {@const steps = getStepsForRole(lane.id)}
                                                    {@const completedCount = steps.filter((s) => run.execution_data?.[s.id]?.status === "completed").length}
                                                    {@const member = assignment ? projectMembers.find((m) => m.id === assignment.user_id) : null}
                                                    {@const isObsCurrentUser = assignment?.user_id === getUser()?.id}
                                                    {@const obsDisplayName = member?.full_name || (isObsCurrentUser ? getUser()?.full_name : null) || member?.email || 'Unknown'}
                                                    <tr class="border-b border-border/60 hover:bg-background">
                                                        <td class="py-3 px-4 font-medium text-foreground">{lane.data.label}</td>
                                                        <td class="py-3 px-4 text-muted-foreground">
                                                            {#if assignment}
                                                                {obsDisplayName}
                                                            {:else}
                                                                <span class="text-muted-foreground/60">Unassigned</span>
                                                            {/if}
                                                        </td>
                                                        <td class="py-3 px-4 text-center">
                                                            {#if steps.length > 0}
                                                                <span class="inline-block text-xs font-semibold px-2 py-1 rounded {completedCount === steps.length ? 'bg-emerald-100 text-emerald-700' : completedCount > 0 ? 'bg-blue-100 text-blue-700' : 'bg-muted text-muted-foreground'}">
                                                                    {completedCount} / {steps.length}
                                                                </span>
                                                            {:else}
                                                                <span class="text-muted-foreground/60">--</span>
                                                            {/if}
                                                        </td>
                                                    </tr>
                                                {/each}
                                            </tbody>
                                        </table>
                                    </div>
                                {:else}
                                    <!-- Roleless run: show single assignee and overall progress -->
                                    {@const assignment = roleAssignments[0]}
                                    {@const member = assignment ? projectMembers.find((m) => m.id === assignment.user_id) : null}
                                    {@const isAssignedCurrentUser = assignment?.user_id === getUser()?.id}
                                    {@const displayName = member?.full_name || (isAssignedCurrentUser ? getUser()?.full_name : null) || member?.email || 'Unknown'}
                                    {@const allSteps = getAllUnitOpSteps()}
                                    {@const completedCount = allSteps.filter((s) => run.execution_data?.[s.id]?.status === "completed").length}
                                    <div class="flex items-center justify-between py-2">
                                        <div class="flex items-center gap-3">
                                            <span class="text-sm font-medium text-foreground">Operator:</span>
                                            <span class="text-sm text-muted-foreground">{assignment ? displayName : 'Unassigned'}</span>
                                        </div>
                                        {#if allSteps.length > 0}
                                            <span class="inline-block text-xs font-semibold px-2 py-1 rounded {completedCount === allSteps.length ? 'bg-emerald-100 text-emerald-700' : completedCount > 0 ? 'bg-blue-100 text-blue-700' : 'bg-muted text-muted-foreground'}">
                                                {completedCount} / {allSteps.length} steps
                                            </span>
                                        {/if}
                                    </div>
                                {/if}
                            </div>
                        </div>
                    {/if}

                    <!-- Documents (available to all users) -->
                    {#if getAllUnitOpSteps().length > 0}
                        <div class="mt-8 bg-white rounded-lg border border-border p-6">
                            <h2 class="text-lg font-semibold text-foreground mb-6">
                                Documents
                            </h2>

                            <div class="space-y-3">
                                <button
                                    onclick={downloadSop}
                                    class="w-full text-left px-4 py-3 bg-background hover:bg-muted border border-border rounded-lg transition-colors"
                                >
                                    <div class="flex items-center justify-between">
                                        <span class="font-medium text-foreground">
                                            Download SOP
                                        </span>
                                        <span class="text-muted-foreground/60">↓</span>
                                    </div>
                                </button>

                                <hr class="my-3" />

                                <button
                                    onclick={() => downloadBatchRecord(false)}
                                    class="w-full text-left px-4 py-3 bg-background hover:bg-muted border border-border rounded-lg transition-colors"
                                >
                                    <div class="flex items-center justify-between">
                                        <span class="font-medium text-foreground">
                                            Download Blank Batch Record
                                        </span>
                                        <span class="text-muted-foreground/60">↓</span>
                                    </div>
                                </button>
                            </div>
                        </div>
                    {/if}
                </div>

                <!-- Go Offline Dialog -->
                <GoOfflineDialog
                    bind:open={showGoOffline}
                    runId={run.id}
                    runName={run.name}
                />
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
                            ← Back to project
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
                    <div class="bg-white rounded-lg border border-border p-6 mb-8">
                        <h2 class="text-lg font-semibold text-foreground mb-6">
                            Results Summary
                        </h2>

                        <div class="space-y-6">
                            {#each getSwimLaneNodes() as lane}
                                {@const steps = getStepsForRole(lane.id)}
                                {@const assignment = getRoleAssignment(lane.id)}
                                <div class="pb-6 border-b border-border/60 last:pb-0 last:border-0">
                                    <div class="flex items-center justify-between mb-4">
                                        <h3 class="font-semibold text-foreground">
                                            {lane.data.label}
                                        </h3>
                                        {#if assignment}
                                            <span class="text-sm text-muted-foreground">
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
                                            <div class="p-3 bg-background rounded border border-border">
                                                <div class="flex items-start justify-between mb-2">
                                                    <div>
                                                        <p class="font-medium text-foreground">
                                                            {step.name}
                                                        </p>
                                                        {#if step.description}
                                                            <p class="text-xs text-muted-foreground mt-1">
                                                                {step.description}
                                                            </p>
                                                        {/if}
                                                    </div>
                                                    <span
                                                        class="inline-block text-xs font-semibold px-2 py-1 rounded {stepData?.status ===
                                                        'completed'
                                                            ? 'bg-emerald-100 text-emerald-700'
                                                            : 'bg-muted text-muted-foreground'}"
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
                                                                        <p class="text-xs text-muted-foreground font-semibold mb-0.5">
                                                                            {key.replace(/_/g, ' ')}
                                                                        </p>
                                                                        <p class="font-mono text-foreground">
                                                                            {val}
                                                                        </p>
                                                                    </div>
                                                                {/each}
                                                            </div>
                                                        {:else if stepData?.value}
                                                            <div>
                                                                <p class="text-xs text-muted-foreground font-semibold mb-0.5">
                                                                    Value
                                                                </p>
                                                                <p class="font-mono text-foreground">
                                                                    {stepData.value}
                                                                </p>
                                                            </div>
                                                        {/if}
                                                        {#if stepData?.notes}
                                                            <div>
                                                                <p class="text-xs text-muted-foreground font-semibold mb-0.5">
                                                                    Notes
                                                                </p>
                                                                <p class="text-foreground/80">
                                                                    {stepData.notes}
                                                                </p>
                                                            </div>
                                                        {/if}
                                                    </div>
                                                {/if}

                                                {#if stepData?.timestamp}
                                                    <p class="text-xs text-muted-foreground mt-2">
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
                    <div class="bg-white rounded-lg border border-border p-6 mb-8">
                        <h2 class="text-lg font-semibold text-foreground mb-6">
                            Documents
                        </h2>

                        <div class="space-y-3">
                            <button
                                onclick={downloadSop}
                                class="w-full text-left px-4 py-3 bg-background hover:bg-muted border border-border rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-foreground">
                                        Download SOP
                                    </span>
                                    <span class="text-muted-foreground/60">↓</span>
                                </div>
                            </button>

                            <hr class="my-3" />

                            <button
                                onclick={() => downloadBatchRecord(false)}
                                class="w-full text-left px-4 py-3 bg-background hover:bg-muted border border-border rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-foreground">
                                        Download Blank Batch Record
                                    </span>
                                    <span class="text-muted-foreground/60">↓</span>
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
                            class="text-muted-foreground hover:text-foreground font-medium"
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
                    <div class="bg-white rounded-lg border border-border p-8 mb-8">
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
                            class="px-6 py-2 bg-muted text-foreground/80 rounded-lg font-medium hover:bg-muted transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            onclick={saveEdits}
                            disabled={savingEdits}
                            class="px-6 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 transition-colors disabled:bg-muted disabled:cursor-not-allowed"
                        >
                            {savingEdits ? 'Saving...' : 'Save Edits'}
                        </button>
                    </div>
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
                    <div class="bg-white rounded-lg border border-border p-6 mb-8">
                        <h2 class="text-lg font-semibold text-foreground mb-6">
                            Results Summary
                        </h2>

                        <div class="space-y-6">
                            {#each getSwimLaneNodes().length > 0 ? getSwimLaneNodes() : [{ id: '__all__', data: { label: 'All Steps' } }] as lane}
                                {@const steps = lane.id === '__all__' ? getAllUnitOpSteps() : getStepsForRole(lane.id)}
                                {@const assignment = lane.id === '__all__' ? null : getRoleAssignment(lane.id)}
                                <div class="pb-6 border-b border-border/60 last:pb-0 last:border-0">
                                    {#if lane.id !== '__all__'}
                                        <div class="flex items-center justify-between mb-4">
                                            <h3 class="font-semibold text-foreground">
                                                {lane.data.label}
                                            </h3>
                                            {#if assignment}
                                                <span class="text-sm text-muted-foreground">
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
                                            <div class="p-3 rounded border {isEdited ? 'bg-amber-50 border-amber-200' : 'bg-background border-border'}">
                                                <div class="flex items-start justify-between mb-2">
                                                    <div>
                                                        <p class="font-medium text-foreground">
                                                            {step.name}
                                                        </p>
                                                        {#if step.description}
                                                            <p class="text-xs text-muted-foreground mt-1">
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
                                                                : 'bg-muted text-muted-foreground'}"
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
                                                                        <p class="text-xs text-muted-foreground font-semibold mb-0.5">
                                                                            {getParamLabel(key, step)}
                                                                        </p>
                                                                        {#if origResults && key in origResults && origResults[key] !== val}
                                                                            <p class="font-mono text-muted-foreground/60 line-through">
                                                                                {origResults[key]}
                                                                            </p>
                                                                            <p class="font-mono text-foreground">
                                                                                {val}
                                                                            </p>
                                                                        {:else}
                                                                            <p class="font-mono text-foreground">
                                                                                {val}
                                                                            </p>
                                                                        {/if}
                                                                    </div>
                                                                {/each}
                                                            </div>
                                                        {:else if stepData?.value}
                                                            <div>
                                                                <p class="text-xs text-muted-foreground font-semibold mb-0.5">
                                                                    Value
                                                                </p>
                                                                {#if origValue && origValue !== stepData.value}
                                                                    <p class="font-mono text-muted-foreground/60 line-through">
                                                                        {origValue}
                                                                    </p>
                                                                    <p class="font-mono text-foreground">
                                                                        {stepData.value}
                                                                    </p>
                                                                {:else}
                                                                    <p class="font-mono text-foreground">
                                                                        {stepData.value}
                                                                    </p>
                                                                {/if}
                                                            </div>
                                                        {/if}
                                                        {#if stepData?.notes}
                                                            <div>
                                                                <p class="text-xs text-muted-foreground font-semibold mb-0.5">
                                                                    Notes
                                                                </p>
                                                                <p class="text-foreground/80">
                                                                    {stepData.notes}
                                                                </p>
                                                            </div>
                                                        {/if}
                                                    </div>
                                                {/if}

                                                {#if stepData?.timestamp}
                                                    <p class="text-xs text-muted-foreground mt-2">
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
                    <div class="bg-white rounded-lg border border-border p-6 mb-8">
                        <h2 class="text-lg font-semibold text-foreground mb-6">
                            Documents
                        </h2>

                        <div class="space-y-3">
                            <button
                                onclick={downloadSop}
                                class="w-full text-left px-4 py-3 bg-background hover:bg-muted border border-border rounded-lg transition-colors"
                            >
                                <div class="flex items-center justify-between">
                                    <span class="font-medium text-foreground">
                                        Download SOP
                                    </span>
                                    <span class="text-muted-foreground/60">↓</span>
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
                            class="text-muted-foreground hover:text-foreground font-medium"
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
                                Editing
                            </span>
                        </div>
                        <div class="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                            <p class="text-sm text-amber-700">
                                You are editing this run again. Changes will not be saved until you click "Save Edits".
                            </p>
                        </div>
                    </div>

                    <div class="bg-white rounded-lg border border-border p-8 mb-8">
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
                            class="px-6 py-2 bg-muted text-foreground/80 rounded-lg font-medium hover:bg-muted transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            onclick={saveEdits}
                            disabled={savingEdits}
                            class="px-6 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 transition-colors disabled:bg-muted disabled:cursor-not-allowed"
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
                        ← Back to project
                    </a>
                </div>

                <div class="p-8 card-warm rounded-xl text-center text-muted-foreground">
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
