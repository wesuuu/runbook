<script lang="ts">
    import { slide } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';

    interface ProjectMember {
        id: string;
        full_name?: string | null;
        email?: string | null;
    }

    interface SwimLane {
        id: string;
        data?: { label?: string };
    }

    interface Props {
        swimLaneNodes: SwimLane[];
        projectMembers: ProjectMember[];
        loadingMembers: boolean;
        assignments: Record<string, string>;
        onChange: (assignments: Record<string, string>) => void;
    }

    let {
        swimLaneNodes,
        projectMembers,
        loadingMembers,
        assignments,
        onChange,
    }: Props = $props();

    function setAssignment(key: string, userId: string) {
        const next = { ...assignments };
        if (userId) {
            next[key] = userId;
        } else {
            delete next[key];
        }
        onChange(next);
    }

    function memberLabel(m: ProjectMember): string {
        return m.full_name || m.email || m.id;
    }
</script>

<section class="step-body">
    <header class="step-header">
        <h2>Step 4 · Assign team members</h2>
        <p class="step-help">
            {#if swimLaneNodes.length > 0}
                Pick the operator for each role. You can change or assign these later from the run page.
            {:else}
                Pick the operator for this run. You can change or assign later from the run page.
            {/if}
        </p>
    </header>

    {#if loadingMembers}
        <p class="loading">Loading project members…</p>
    {:else if projectMembers.length === 0}
        <div class="empty-state">
            <p class="empty-title">No project members yet</p>
            <p class="empty-desc">
                Add teammates to this project before assigning roles. You can skip this step and
                assign later.
            </p>
        </div>
    {:else if swimLaneNodes.length > 0}
        <div class="assignee-list">
            {#each swimLaneNodes as lane (lane.id)}
                <div class="assignee-row" transition:slide={{ duration: 180, easing: cubicOut }}>
                    <label class="row-label" for="assignee-{lane.id}">
                        {lane.data?.label ?? 'Role'}
                    </label>
                    <select
                        id="assignee-{lane.id}"
                        class="input-field"
                        value={assignments[lane.id] ?? ''}
                        onchange={(e) => setAssignment(lane.id, (e.target as HTMLSelectElement).value)}
                    >
                        <option value="">Unassigned</option>
                        {#each projectMembers as m (m.id)}
                            <option value={m.id}>{memberLabel(m)}</option>
                        {/each}
                    </select>
                </div>
            {/each}
        </div>
    {:else}
        <div class="assignee-list">
            <div class="assignee-row">
                <label class="row-label" for="assignee-run">Operator</label>
                <select
                    id="assignee-run"
                    class="input-field"
                    value={assignments['__run__'] ?? ''}
                    onchange={(e) => setAssignment('__run__', (e.target as HTMLSelectElement).value)}
                >
                    <option value="">Unassigned</option>
                    {#each projectMembers as m (m.id)}
                        <option value={m.id}>{memberLabel(m)}</option>
                    {/each}
                </select>
            </div>
        </div>
    {/if}
</section>

<style>
    .step-body {
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
    }
    .step-header h2 {
        font-size: 1.25rem;
        font-weight: 600;
        color: rgb(15 23 42);
    }
    .step-help {
        font-size: 0.875rem;
        color: rgb(71 85 105);
        margin-top: 0.25rem;
    }
    .loading {
        font-size: 0.875rem;
        color: rgb(100 116 139);
    }
    .empty-state {
        padding: 1.25rem;
        border: 1px dashed rgb(203 213 225);
        border-radius: 0.5rem;
        background-color: rgb(248 250 252 / 0.5);
    }
    .empty-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: rgb(51 65 85);
        margin-bottom: 0.25rem;
    }
    .empty-desc {
        font-size: 0.8125rem;
        color: rgb(100 116 139);
    }
    .assignee-list {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }
    .assignee-row {
        display: grid;
        grid-template-columns: 12rem 1fr;
        gap: 1rem;
        align-items: center;
        padding: 0.875rem 1rem;
        border: 1px solid rgb(226 232 240);
        border-radius: 0.5rem;
        background-color: rgb(248 250 252 / 0.5);
    }
    .row-label {
        font-size: 0.875rem;
        font-weight: 500;
        color: rgb(51 65 85);
    }
    .input-field {
        width: 100%;
        padding: 0.5rem 0.75rem;
        border: 1px solid rgb(209 213 219);
        border-radius: 0.5rem;
        font-size: 0.875rem;
        background-color: white;
    }
    .input-field:focus {
        outline: none;
        border-color: transparent;
        box-shadow: 0 0 0 2px rgb(20 184 166);
    }
</style>
