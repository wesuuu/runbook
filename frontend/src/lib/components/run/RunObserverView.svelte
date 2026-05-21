<script lang="ts">
    import { getUser } from "$lib/auth.svelte";

    interface Step {
        id: string;
        name: string;
        category: string;
        description: string;
        params: Record<string, any>;
        paramSchema: any;
        duration_min: number | null;
        parentId: string | null;
    }

    interface Props {
        roleNodes: any[];
        allSteps: Step[];
        roleAssignments: any[];
        projectMembers: any[];
        executionData: Record<string, any>;
        getStepsForRole: (roleNodeId: string) => Step[];
    }

    let {
        roleNodes,
        allSteps,
        roleAssignments,
        projectMembers,
        executionData,
        getStepsForRole,
    }: Props = $props();

    function getRoleAssignment(roleNodeId: string) {
        return roleAssignments.find((a) => a.lane_node_id === roleNodeId);
    }
</script>

<div class="space-y-6">
    <div class="bg-white rounded-lg border border-border p-6">
        <h2 class="text-lg font-semibold text-foreground mb-4">
            Run Status
        </h2>
        <p class="text-muted-foreground mb-4">
            You are not assigned to a role in this run. Below is the current status.
        </p>

        {#if roleNodes.length > 0}
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
                        {#each roleNodes as role}
                            {@const assignment = getRoleAssignment(role.id)}
                            {@const steps = getStepsForRole(role.id)}
                            {@const completedCount = steps.filter((s) => executionData?.[s.id]?.status === "completed").length}
                            {@const member = assignment ? projectMembers.find((m) => m.id === assignment.user_id) : null}
                            {@const isCurrentUser = assignment?.user_id === getUser()?.id}
                            {@const displayName = member?.full_name || (isCurrentUser ? getUser()?.full_name : null) || member?.email || 'Unknown'}
                            <tr class="border-b border-border/60 hover:bg-background">
                                <td class="py-3 px-4 font-medium text-foreground">{role.data.label}</td>
                                <td class="py-3 px-4 text-muted-foreground">
                                    {#if assignment}
                                        {displayName}
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
            {@const isCurrentUser = assignment?.user_id === getUser()?.id}
            {@const displayName = member?.full_name || (isCurrentUser ? getUser()?.full_name : null) || member?.email || 'Unknown'}
            {@const completedCount = allSteps.filter((s) => executionData?.[s.id]?.status === "completed").length}
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
