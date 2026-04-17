<script lang="ts">
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
        swimLaneNodes: any[];
        allSteps: Step[];
        roleAssignments: any[];
        projectMembers: any[];
        executionData: Record<string, any>;
        showEditAnnotations?: boolean;
        getStepsForRole: (laneNodeId: string) => Step[];
    }

    let {
        swimLaneNodes,
        allSteps,
        roleAssignments,
        projectMembers,
        executionData,
        showEditAnnotations = false,
        getStepsForRole,
    }: Props = $props();

    function getRoleAssignment(laneNodeId: string) {
        return roleAssignments.find((a) => a.lane_node_id === laneNodeId);
    }

    function getParamLabel(key: string, step: Step): string {
        const props = step.paramSchema?.properties || {};
        const prop = props[key];
        return prop?.title || key.replace(/_/g, ' ');
    }

    // For EDITED view, use all swimlanes or a synthetic "__all__" lane
    const lanes = $derived(
        swimLaneNodes.length > 0
            ? swimLaneNodes
            : [{ id: '__all__', data: { label: 'All Steps' } }]
    );

    function stepsForLane(laneId: string): Step[] {
        return laneId === '__all__' ? allSteps : getStepsForRole(laneId);
    }
</script>

<div class="bg-white rounded-lg border border-border p-6 mb-8">
    <h2 class="text-lg font-semibold text-foreground mb-6">
        Results Summary
    </h2>

    <div class="space-y-6">
        {#each lanes as lane}
            {@const steps = stepsForLane(lane.id)}
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
                        {@const stepData = executionData?.[step.id]}
                        {@const origResults = stepData?.original_results}
                        {@const origValue = stepData?.original_value}
                        {@const isEdited = showEditAnnotations && !!(origResults || origValue)}
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
                                                        {showEditAnnotations ? getParamLabel(key, step) : key.replace(/_/g, ' ')}
                                                    </p>
                                                    {#if showEditAnnotations && origResults && key in origResults && origResults[key] !== val}
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
                                            {#if showEditAnnotations && origValue && origValue !== stepData.value}
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
