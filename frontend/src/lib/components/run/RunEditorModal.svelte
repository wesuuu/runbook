<script lang="ts">
    import { api } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import { Button } from '$lib/components/ui/button';
    import FullScreenModal from '$lib/components/ui/FullScreenModal.svelte';
    import ConfirmDialog from '$lib/components/ui/confirm-dialog.svelte';
    import RunOverridesEditor from './RunOverridesEditor.svelte';
    import RunCreatorAssigneeStep from './RunCreatorAssigneeStep.svelte';
    import { computeEdits } from '$lib/utils/runOverrides';
    import type { ProtocolRole } from '$lib/schemas/protocols';
    import { fade, fly } from 'svelte/transition';
    import { blockDuration } from '$lib/transitions';

    type GraphNode = {
        id: string;
        type?: string;
        parentId?: string;
        data?: Record<string, unknown>;
        [k: string]: unknown;
    };
    type Graph = {
        nodes: GraphNode[];
        edges: Array<{ id?: string; source: string; target: string }>;
    };

    interface OrgEquipment {
        id: string;
        name: string;
        description?: string;
        equipment_type?: string;
        location?: string;
        organization_id: string;
        created_at: string;
        updated_at: string;
    }

    interface ProjectMember {
        id: string;
        full_name?: string | null;
        email?: string | null;
    }

    interface RoleAssignment {
        id: string;
        run_id: string;
        lane_node_id: string;
        role_name: string;
        user_id: string;
    }

    interface Run {
        id: string;
        name: string;
        graph: Graph;
        protocol_id?: string | null;
    }

    interface Props {
        open: boolean;
        run: Run;
        roleAssignments: RoleAssignment[];
        projectMembers: ProjectMember[];
        onSaved: () => void;
    }

    let {
        open = $bindable(false),
        run,
        roleAssignments,
        projectMembers,
        onSaved,
    }: Props = $props();

    let runName = $state('');
    let originalName = $state('');
    let originalGraph = $state<Graph | null>(null);
    let currentGraph = $state<Graph | null>(null);

    let roles = $state<ProtocolRole[]>([]);
    let activeRoleId = $state<string | null>(null);

    let orgEquipment = $state<OrgEquipment[]>([]);
    let loadedOrgEq = $state(false);

    let assignments = $state<Record<string, string>>({});
    let originalAssignments = $state<Record<string, string>>({});

    type Tab = 'parameters' | 'assignees';
    let activeTab = $state<Tab>('parameters');

    let saving = $state(false);
    let saveError = $state<string | null>(null);
    let discardConfirmOpen = $state(false);

    function buildAssignmentsFromList(
        list: RoleAssignment[],
        graph: Graph | null,
    ): Record<string, string> {
        const out: Record<string, string> = {};
        const hasLanes = (graph?.nodes ?? []).some((n) => n.type === 'swimLane');
        for (const a of list) {
            const key = hasLanes ? a.lane_node_id : '__run__';
            out[key] = a.user_id;
        }
        return out;
    }

    function stampGraph(raw: Graph): Graph {
        return {
            ...raw,
            nodes: (raw.nodes ?? []).map((n) => {
                if (n.type !== 'unitOp') return n;
                const d = (n.data ?? {}) as Record<string, unknown>;
                return {
                    ...n,
                    data: {
                        ...d,
                        protocol_params: JSON.parse(JSON.stringify(d.params ?? {})),
                        protocol_paramSchema: JSON.parse(JSON.stringify(d.paramSchema ?? {})),
                        protocol_equipment: JSON.parse(JSON.stringify(d.equipment ?? [])),
                        protocol_description: d.description ?? '',
                    },
                };
            }),
        };
    }

    function stripGraph(graph: Graph): Graph {
        return {
            ...graph,
            nodes: graph.nodes.map((n) => {
                if (n.type !== 'unitOp') return n;
                const data = (n.data ?? {}) as Record<string, unknown>;
                const {
                    protocol_params,
                    protocol_paramSchema,
                    protocol_equipment,
                    protocol_description,
                    ...rest
                } = data;
                void protocol_params;
                void protocol_paramSchema;
                void protocol_equipment;
                void protocol_description;
                return { ...n, data: rest };
            }),
        };
    }

    function initializeFromRun() {
        runName = run.name ?? '';
        originalName = runName;
        const raw = JSON.parse(JSON.stringify(run.graph ?? { nodes: [], edges: [] })) as Graph;
        const stamped = stampGraph(raw);
        originalGraph = JSON.parse(JSON.stringify(stamped));
        currentGraph = stamped;

        const initialAssign = buildAssignmentsFromList(roleAssignments, raw);
        assignments = { ...initialAssign };
        originalAssignments = { ...initialAssign };

        activeTab = 'parameters';
        saveError = null;

        if (run.protocol_id) {
            api
                .get<{ roles?: ProtocolRole[] }>(`/science/protocols/${run.protocol_id}`)
                .then((p) => {
                    const sorted = (p.roles ?? [])
                        .slice()
                        .sort((a, b) => a.sort_order - b.sort_order);
                    roles = sorted;
                    activeRoleId = sorted.length > 1 ? sorted[0].id : null;
                })
                .catch(() => {
                    roles = [];
                    activeRoleId = null;
                });
        } else {
            roles = [];
            activeRoleId = null;
        }
    }

    $effect(() => {
        if (open) {
            initializeFromRun();
            if (!loadedOrgEq) {
                const org = getCurrentOrg();
                if (org) {
                    api
                        .get<OrgEquipment[]>(`/iam/organizations/${org.id}/equipment`)
                        .then((eq) => {
                            orgEquipment = eq;
                            loadedOrgEq = true;
                        })
                        .catch(() => {});
                }
            }
        }
    });

    const mediaPrepNodes = $derived(
        (currentGraph?.nodes ?? [])
            .filter(
                (n) =>
                    n.type === 'unitOp' &&
                    (n.data as { category?: string } | undefined)?.category === 'Media Prep',
            )
            .map((n) => ({
                id: n.id,
                label: ((n.data as { label?: string } | undefined)?.label) ?? n.id,
            })),
    );

    const swimLaneNodes = $derived(
        (currentGraph?.nodes ?? [])
            .filter((n) => n.type === 'swimLane')
            .map((n) => ({
                id: n.id,
                data: {
                    label: ((n.data as { label?: string } | undefined)?.label) ?? 'Role',
                },
            })),
    );

    const edits = $derived(
        originalGraph && currentGraph ? computeEdits(originalGraph, currentGraph) : [],
    );

    const assignmentsDirty = $derived(
        JSON.stringify(assignments) !== JSON.stringify(originalAssignments),
    );

    const nameDirty = $derived(runName !== originalName);

    const hasUnsaved = $derived(edits.length > 0 || assignmentsDirty || nameDirty);

    const canSave = $derived(hasUnsaved && runName.trim().length > 0 && !saving);

    function requestClose() {
        if (hasUnsaved) {
            discardConfirmOpen = true;
        } else {
            open = false;
        }
    }

    function confirmDiscard() {
        discardConfirmOpen = false;
        open = false;
    }

    async function persistAssignmentDiff() {
        const hasLanes = swimLaneNodes.length > 0;
        const allKeys = new Set<string>([
            ...Object.keys(originalAssignments),
            ...Object.keys(assignments),
        ]);

        for (const key of allKeys) {
            const oldUserId = originalAssignments[key];
            const newUserId = assignments[key];
            if (oldUserId === newUserId) continue;

            if (!newUserId && oldUserId) {
                const existing = roleAssignments.find(
                    (a) =>
                        (hasLanes ? a.lane_node_id === key : true) &&
                        a.user_id === oldUserId,
                );
                if (existing) {
                    await api.delete(
                        `/science/runs/${run.id}/role-assignments/${existing.id}`,
                    );
                }
                continue;
            }

            if (newUserId) {
                const lane = hasLanes ? swimLaneNodes.find((l) => l.id === key) : null;
                const lane_node_id = hasLanes ? key : '__run__';
                const role_name = hasLanes ? lane?.data.label ?? 'Role' : 'Operator';
                await api.post(`/science/runs/${run.id}/role-assignments`, {
                    lane_node_id,
                    role_name,
                    user_id: newUserId,
                });
            }
        }
    }

    async function save() {
        if (!currentGraph) return;
        saving = true;
        saveError = null;
        try {
            const body: Record<string, unknown> = {};
            if (nameDirty) body.name = runName.trim();
            if (edits.length > 0) body.graph = stripGraph(currentGraph);
            if (Object.keys(body).length > 0) {
                await api.put(`/science/runs/${run.id}`, body);
            }
            if (assignmentsDirty) {
                await persistAssignmentDiff();
            }
            onSaved();
            open = false;
        } catch (e) {
            saveError = e instanceof Error ? e.message : 'Failed to save changes';
        } finally {
            saving = false;
        }
    }
</script>

<FullScreenModal bind:open title={`Edit Run · ${originalName}`} onClose={requestClose}>
    {#snippet headerActions()}
        <nav class="editor-tabs" aria-label="Edit sections">
            <button
                type="button"
                class="tab-btn"
                data-active={activeTab === 'parameters'}
                onclick={() => (activeTab = 'parameters')}
            >
                Parameters
                {#if edits.length > 0}
                    <span class="tab-badge">{edits.length}</span>
                {/if}
            </button>
            <button
                type="button"
                class="tab-btn"
                data-active={activeTab === 'assignees'}
                onclick={() => (activeTab = 'assignees')}
            >
                Assignees
                {#if assignmentsDirty}
                    <span class="tab-badge">•</span>
                {/if}
            </button>
        </nav>
    {/snippet}

    <div class="editor-body">
        <main class="editor-main">
            <div class="editor-content">
                <section class="name-row">
                    <label class="name-label" for="edit-run-name">Run name</label>
                    <input
                        id="edit-run-name"
                        type="text"
                        class="name-input"
                        bind:value={runName}
                        placeholder="Enter run name"
                    />
                </section>

                {#key activeTab}
                    <div class="tab-pane" in:fly={{ y: 8, duration: blockDuration() }}>
                        {#if activeTab === 'parameters' && currentGraph && originalGraph}
                            <RunOverridesEditor
                                {originalGraph}
                                {currentGraph}
                                {orgEquipment}
                                {mediaPrepNodes}
                                {roles}
                                {activeRoleId}
                                onChange={(g) => {
                                    currentGraph = g;
                                }}
                                onRoleChange={(id) => {
                                    activeRoleId = id;
                                }}
                                isStrict={run.is_strict ?? false}
                            />
                        {:else if activeTab === 'assignees'}
                            <RunCreatorAssigneeStep
                                {swimLaneNodes}
                                {projectMembers}
                                loadingMembers={false}
                                {assignments}
                                onChange={(a) => {
                                    assignments = a;
                                }}
                            />
                        {/if}
                    </div>
                {/key}

                {#if saveError}
                    <div in:fade={{ duration: blockDuration() }} class="save-error">
                        {saveError}
                    </div>
                {/if}
            </div>
        </main>

        <footer class="editor-footer">
            <Button variant="ghost" onclick={requestClose}>Cancel</Button>
            <div class="footer-spacer"></div>
            <span class="dirty-hint">
                {#if hasUnsaved}
                    Unsaved changes
                {:else}
                    No changes
                {/if}
            </span>
            <Button onclick={save} disabled={!canSave}>
                {saving ? 'Saving…' : 'Save changes'}
            </Button>
        </footer>
    </div>
</FullScreenModal>

<ConfirmDialog
    bind:open={discardConfirmOpen}
    title="Discard changes?"
    message="You have unsaved edits. Closing the editor will discard them."
    confirmLabel="Discard"
    cancelLabel="Keep editing"
    confirmVariant="danger"
    onConfirm={confirmDiscard}
    onCancel={() => (discardConfirmOpen = false)}
/>

<style>
    .editor-body {
        height: 100%;
        display: flex;
        flex-direction: column;
    }
    .editor-main {
        flex: 1;
        overflow-y: auto;
        width: 100%;
    }
    .editor-content {
        max-width: 72rem;
        width: 100%;
        margin-left: auto;
        margin-right: auto;
        padding: 1.5rem;
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
    }
    .name-row {
        display: grid;
        grid-template-columns: 12rem 1fr;
        gap: 1rem;
        align-items: center;
        padding: 0.875rem 1rem;
        border: 1px solid rgb(226 232 240);
        border-radius: 0.5rem;
        background-color: rgb(248 250 252 / 0.5);
    }
    .name-label {
        font-size: 0.875rem;
        font-weight: 500;
        color: rgb(51 65 85);
    }
    .name-input {
        width: 100%;
        padding: 0.5rem 0.75rem;
        border: 1px solid rgb(209 213 219);
        border-radius: 0.5rem;
        font-size: 0.875rem;
        background-color: white;
    }
    .name-input:focus {
        outline: none;
        border-color: transparent;
        box-shadow: 0 0 0 2px rgb(20 184 166);
    }
    .editor-tabs {
        display: flex;
        gap: 0.25rem;
    }
    .tab-btn {
        position: relative;
        display: inline-flex;
        align-items: center;
        gap: 0.375rem;
        padding: 0.375rem 0.75rem;
        font-size: 0.8125rem;
        font-weight: 500;
        color: rgb(71 85 105);
        background: transparent;
        border: 1px solid transparent;
        border-radius: 0.375rem;
        cursor: pointer;
        transition: all 150ms ease;
    }
    .tab-btn:hover {
        background-color: rgb(241 245 249);
        color: rgb(15 23 42);
    }
    .tab-btn[data-active='true'] {
        background-color: rgb(255 255 255);
        color: rgb(15 23 42);
        border-color: rgb(226 232 240);
        box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
    }
    .tab-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 1.25rem;
        height: 1.25rem;
        padding: 0 0.375rem;
        font-size: 0.6875rem;
        font-weight: 600;
        border-radius: 999px;
        background-color: rgb(20 184 166);
        color: white;
    }
    .tab-pane {
        flex: 1;
    }
    .save-error {
        padding: 0.75rem 1rem;
        font-size: 0.875rem;
        color: rgb(185 28 28);
        background-color: rgb(254 242 242);
        border: 1px solid rgb(252 165 165);
        border-radius: 0.5rem;
    }
    .editor-footer {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.75rem 1.5rem;
        border-top: 1px solid rgb(226 232 240);
        flex-shrink: 0;
    }
    .footer-spacer {
        flex: 1;
    }
    .dirty-hint {
        font-size: 0.8125rem;
        color: rgb(100 116 139);
    }
</style>
