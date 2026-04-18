<script lang="ts">
    import { getUser } from "$lib/auth.svelte";
    import { Button } from "$lib/components/ui/button";

    interface Props {
        swimLaneNodes: any[];
        roleAssignments: any[];
        projectMembers: any[];
        assignmentChanges: Record<string, string>;
        onUpdateAssignment: (laneNodeId: string, roleName: string, userId: string | null) => void;
        onAssignmentChange: (laneNodeId: string, value: string) => void;
        onShowGoOffline: () => void;
    }

    let {
        swimLaneNodes,
        roleAssignments,
        projectMembers,
        assignmentChanges,
        onUpdateAssignment,
        onAssignmentChange,
        onShowGoOffline,
    }: Props = $props();

    function getRoleAssignment(laneNodeId: string) {
        return roleAssignments.find((a) => a.lane_node_id === laneNodeId);
    }

    function getCurrentUserAssignment() {
        const user = getUser();
        if (!user) return null;
        return roleAssignments.find((a) => a.user_id === user.id);
    }
</script>

{#if swimLaneNodes.length > 0}
    <div class="mb-8 p-6 card-warm rounded-xl">
        <h2 class="text-lg font-semibold text-foreground mb-6">
            Role Assignments
        </h2>
        <p class="text-sm text-muted-foreground mb-6">
            Assign team members to each role. All roles must be assigned before starting the run.
        </p>

        <div class="space-y-4">
            {#each swimLaneNodes as lane}
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
                                onAssignmentChange(lane.id, e.currentTarget.value);
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
                        <Button
                            size="sm"
                            onclick={() =>
                                onUpdateAssignment(lane.id, lane.data.label, selectedUserId)
                            }
                        >
                            Save
                        </Button>
                    {/if}
                    {#if assignment?.user_id && !selectedUserId}
                        <Button
                            variant="destructive"
                            size="sm"
                            onclick={() =>
                                onUpdateAssignment(lane.id, lane.data.label, null)
                            }
                        >
                            Clear
                        </Button>
                    {/if}
                </div>
            {/each}
        </div>

        <!-- Go Offline option for current user (role-based) -->
        {#if getCurrentUserAssignment()}
            <div class="mt-6 pt-5 border-t border-border/60">
                <Button
                    variant="outline"
                    onclick={onShowGoOffline}
                    class="border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100 hover:text-amber-700"
                    title="Prepare offline session before starting the run"
                >
                    <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M8.288 15.038a5.25 5.25 0 017.424 0M5.106 11.856c3.807-3.808 9.98-3.808 13.788 0M1.924 8.674c5.565-5.565 14.587-5.565 20.152 0M12.53 18.22l-.53.53-.53-.53a.75.75 0 011.06 0z" />
                    </svg>
                    Prepare Offline Session
                </Button>
                <p class="text-xs text-muted-foreground mt-2">
                    Download run data now so you can work offline when the run starts.
                </p>
            </div>
        {/if}
    </div>
{:else}
    <!-- Roleless run: single assignee -->
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
                        onAssignmentChange("__run__", e.currentTarget.value);
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
                <Button
                    size="sm"
                    onclick={() =>
                        onUpdateAssignment("__run__", "Operator", selectedUserId)
                    }
                >
                    Save
                </Button>
            {/if}
            {#if assignment?.user_id && !selectedUserId}
                <Button
                    variant="destructive"
                    size="sm"
                    onclick={() =>
                        onUpdateAssignment("__run__", "Operator", null)
                    }
                >
                    Clear
                </Button>
            {/if}
        </div>

        <!-- Offline mode checkbox for role-less runs -->
        {#if assignment?.user_id === getUser()?.id}
            <label class="mt-5 flex items-start gap-3 p-4 bg-background rounded-lg cursor-pointer group">
                <input
                    type="checkbox"
                    checked={false}
                    onchange={(e) => {
                        if (e.currentTarget.checked) {
                            onShowGoOffline();
                            e.currentTarget.checked = false;
                        }
                    }}
                    class="mt-0.5 w-4 h-4 rounded border-amber-300 text-amber-600 focus:ring-amber-500"
                />
                <div>
                    <span class="text-sm font-medium text-foreground group-hover:text-amber-700 transition-colors">
                        Enable offline mode
                    </span>
                    <p class="text-xs text-muted-foreground mt-0.5">
                        Download run data to this device so you can work without internet.
                    </p>
                </div>
            </label>
        {/if}
    </div>
{/if}
