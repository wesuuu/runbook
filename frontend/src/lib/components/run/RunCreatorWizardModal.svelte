<script lang="ts">
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import { Button } from '$lib/components/ui/button';
    import FullScreenModal from '$lib/components/ui/FullScreenModal.svelte';
    import ConfirmDialog from '$lib/components/ui/confirm-dialog.svelte';
    import RunCreatorStepper from './RunCreatorStepper.svelte';
    import RunCreatorNameStep from './RunCreatorNameStep.svelte';
    import RunCreatorProtocolStep from './RunCreatorProtocolStep.svelte';
    import RunOverridesEditor from './RunOverridesEditor.svelte';
    import RunCreatorAssigneeStep from './RunCreatorAssigneeStep.svelte';
    import RunCreatorReviewStep from './RunCreatorReviewStep.svelte';
    import SaveAsNewVersionDialog from './SaveAsNewVersionDialog.svelte';
    import { computeEdits, buildOverridesPayload } from '$lib/utils/runOverrides';
    import type { Protocol, ProtocolVersion, ProtocolRole } from '$lib/schemas/protocols';
    import { fade, fly } from 'svelte/transition';
    import { blockDuration } from '$lib/transitions';

    type GraphNode = {
        id: string;
        type?: string;
        parentId?: string;
        data?: Record<string, unknown>;
        [k: string]: unknown;
    };
    type Graph = { nodes: GraphNode[]; edges: Array<{ id?: string; source: string; target: string }> };
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

    interface Props {
        open: boolean;
        projectId: string;
        protocols: Protocol[];
        experiments?: Array<{ id: string; name: string; status?: string }>;
        forExperiment?: { id: string; name: string } | null;
        onCreated?: (run: { id: string }) => void;
    }

    let {
        open = $bindable(false),
        projectId,
        protocols,
        experiments = [],
        forExperiment = null,
        onCreated,
    }: Props = $props();

    interface ProjectMember {
        id: string;
        full_name?: string | null;
        email?: string | null;
    }

    let versions = $state<ProtocolVersion[]>([]);
    let orgEquipment = $state<OrgEquipment[]>([]);
    let loadedOrgEq = $state(false);

    let runName = $state('');
    let experimentId = $state<string | null>(null);
    let producesLot = $state(false);
    let lotNumber = $state('');
    let batchNumber = $state('');

    let protocolId = $state<string | null>(null);
    let protocolVersionNumber = $state<number | null>(null);
    let originalGraph = $state<Graph | null>(null);
    let currentGraph = $state<Graph | null>(null);
    let loadingVersions = $state(false);

    let roles = $state<ProtocolRole[]>([]);
    let activeRoleId = $state<string | null>(null);

    let projectMembers = $state<ProjectMember[]>([]);
    let loadingMembers = $state(false);
    let loadedMembersForProject = $state<string | null>(null);
    let assignments = $state<Record<string, string>>({});

    type StepNum = 1 | 2 | 3 | 4 | 5;
    let currentStep = $state<StepNum>(1);
    let highestVisited = $state<StepNum>(1);
    let stepDirection = $state<'forward' | 'backward'>('forward');

    let nameValid = $state(false);
    let protocolValid = $state(false);

    let saveDialogOpen = $state(false);
    let discardConfirmOpen = $state(false);
    let creating = $state(false);
    let createError = $state<string | null>(null);

    const selectedProtocol = $derived(protocols.find((p) => p.id === protocolId) ?? null);
    const selectedVersion = $derived(
        versions.find(
            (v) => v.version_number === (protocolVersionNumber ?? selectedProtocol?.version_number),
        ) ?? null,
    );
    const isLatestVersion = $derived(
        protocolVersionNumber === null ||
        protocolVersionNumber === selectedProtocol?.version_number,
    );
    const edits = $derived(
        originalGraph && currentGraph ? computeEdits(originalGraph, currentGraph) : [],
    );
    const hasUnsaved = $derived(runName.length > 0 || edits.length > 0);

    const mediaPrepNodes = $derived(
        (currentGraph?.nodes ?? [])
            .filter((n) => n.type === 'unitOp' && (n.data as { category?: string } | undefined)?.category === 'Media Prep')
            .map((n) => ({ id: n.id, label: ((n.data as { label?: string } | undefined)?.label) ?? n.id })),
    );

    const roleNodes = $derived(
        (currentGraph?.nodes ?? [])
            .filter((n) => n.type === 'swimLane')
            .map((n) => ({ id: n.id, data: { label: ((n.data as { label?: string } | undefined)?.label) ?? 'Role' } })),
    );

    function resetState() {
        runName = '';
        experimentId = forExperiment?.id ?? null;
        producesLot = false;
        lotNumber = '';
        batchNumber = '';
        protocolId = null;
        protocolVersionNumber = null;
        originalGraph = null;
        currentGraph = null;
        versions = [];
        roles = [];
        activeRoleId = null;
        assignments = {};
        currentStep = 1;
        highestVisited = 1;
        nameValid = false;
        protocolValid = false;
        saveDialogOpen = false;
        creating = false;
        createError = null;
    }

    async function loadProjectMembers(pid: string) {
        if (loadedMembersForProject === pid) return;
        loadingMembers = true;
        try {
            const members = await api.get<ProjectMember[]>(
                `/projects/${pid}/members`,
            );
            projectMembers = members ?? [];
            loadedMembersForProject = pid;
        } catch {
            projectMembers = [];
        } finally {
            loadingMembers = false;
        }
    }

    $effect(() => {
        if (open) {
            resetState();
            if (!loadedOrgEq) {
                const org = getCurrentOrg();
                if (org) {
                    api.get<OrgEquipment[]>(`/equipment`).then((eq) => {
                        orgEquipment = eq;
                        loadedOrgEq = true;
                    }).catch(() => {});
                }
            }
            if (projectId) {
                loadProjectMembers(projectId);
            }
        }
    });

    async function loadVersions(pid: string) {
        loadingVersions = true;
        try {
            versions = await api.get<ProtocolVersion[]>(`/protocols/${pid}/versions`);
        } finally {
            loadingVersions = false;
        }
    }

    $effect(() => {
        if (!protocolId) {
            roles = [];
            activeRoleId = null;
            return;
        }
        api.get<{ roles?: ProtocolRole[] }>(`/protocols/${protocolId}`)
            .then((p) => {
                const sorted = (p.roles ?? []).slice().sort(
                    (a, b) => a.sort_order - b.sort_order,
                );
                roles = sorted;
                activeRoleId = sorted.length > 1 ? sorted[0].id : null;
            })
            .catch(() => {
                roles = [];
                activeRoleId = null;
            });
    });

    $effect(() => {
        if (!selectedVersion) {
            originalGraph = null;
            currentGraph = null;
            return;
        }
        // The versions list endpoint omits graph for performance; fall back to the
        // protocol's own graph when the user has not pinned a specific version
        // (i.e. they're using "Latest", which always matches selectedProtocol.graph).
        const sourceGraph =
            isLatestVersion && selectedProtocol?.graph
                ? selectedProtocol.graph
                : selectedVersion.graph;
        const raw = JSON.parse(JSON.stringify(sourceGraph ?? { nodes: [], edges: [] }));

        // Stamp each unitOp node with protocol_* mirror fields so RunCreatorUnitOpCard
        // can distinguish original vs edited values and show VALUE/REMOVED/ADDED diffs.
        const stamped: Graph = {
            ...raw,
            nodes: (raw.nodes as GraphNode[]).map((n: GraphNode) => {
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

        originalGraph = JSON.parse(JSON.stringify(stamped));
        currentGraph = stamped;
    });

    function jumpTo(step: StepNum) {
        if (step <= highestVisited) {
            stepDirection = step > currentStep ? 'forward' : 'backward';
            currentStep = step;
        }
    }

    function advanceTo(step: StepNum) {
        stepDirection = 'forward';
        currentStep = step;
        highestVisited = Math.max(highestVisited, step) as StepNum;
    }

    function next() {
        if (currentStep === 1 && nameValid) {
            advanceTo(2);
        } else if (currentStep === 2 && protocolValid) {
            advanceTo(3);
        } else if (currentStep === 3) {
            if (edits.length > 0) {
                saveDialogOpen = true;
            } else {
                advanceTo(4);
            }
        } else if (currentStep === 4) {
            advanceTo(5);
        }
    }

    function back() {
        if (currentStep > 1) {
            stepDirection = 'backward';
            currentStep = (currentStep - 1) as StepNum;
        }
    }

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

    function dialogJustThisRun() {
        saveDialogOpen = false;
        advanceTo(4);
    }

    async function dialogSaveAsVersion(description: string) {
        if (!protocolId || !currentGraph) return;
        try {
            const nextVer = (selectedProtocol?.version_number ?? 0) + 1;

            // Strip protocol_* mirror fields before sending graph to the backend —
            // those are UI-only annotations used for diff rendering.
            const cleanGraph = {
                ...currentGraph,
                nodes: currentGraph.nodes.map((n) => {
                    if (n.type !== 'unitOp') return n;
                    const { protocol_params, protocol_paramSchema, protocol_equipment, protocol_description, ...rest } = (n.data ?? {}) as Record<string, unknown>;
                    void protocol_params; void protocol_paramSchema; void protocol_equipment; void protocol_description;
                    return { ...n, data: rest };
                }),
            };

            // Step 1: PUT the edited graph as a draft version (creates ProtocolVersion is_draft=True)
            await api.put(`/protocols/${protocolId}?save_as_draft=true`, {
                graph: cleanGraph,
            });

            // Step 2: Publish the draft — sets is_draft=False and updates the main protocol
            await api.post(
                `/protocols/${protocolId}/publish-draft?version_number=${nextVer}`,
                { description: description || undefined },
            );
            await loadVersions(protocolId);
            protocolVersionNumber = nextVer;
            saveDialogOpen = false;
            advanceTo(4);
        } catch (e) {
            createError = e instanceof Error ? e.message : 'Failed to save version';
        }
    }

    async function persistAssignments(runId: string) {
        const hasRoles = roleNodes.length > 0;
        const entries = Object.entries(assignments).filter(([, userId]) => !!userId);
        for (const [key, userId] of entries) {
            const role = hasRoles ? roleNodes.find((r) => r.id === key) : null;
            const lane_node_id = hasRoles ? key : '__run__';
            const role_name = hasRoles
                ? (role?.data.label ?? 'Role')
                : 'Operator';
            try {
                await api.post(`/runs/${runId}/role-assignments`, {
                    lane_node_id,
                    role_name,
                    user_id: userId,
                });
            } catch {
                // Non-fatal: the run is already created. The user can retry from the run page.
            }
        }
    }

    async function createRun() {
        if (!runName || !protocolId) return;
        creating = true;
        createError = null;
        try {
            const payload: Record<string, unknown> = {
                name: runName,
                project_id: projectId,
                protocol_id: protocolId,
                produces_lot: producesLot,
            };
            if (experimentId) payload.experiment_id = experimentId;
            if (producesLot && lotNumber) payload.lot_number = lotNumber;
            if (batchNumber) payload.batch_number = batchNumber;
            if (protocolVersionNumber) payload.protocol_version_number = protocolVersionNumber;
            const overrides = buildOverridesPayload(edits, currentGraph);
            if (overrides) payload.overrides = overrides;
            const newRun = await api.post<{ id: string }>('/runs', payload);
            await persistAssignments(newRun.id);
            onCreated?.(newRun);
            open = false;
            goto(`/runs/${newRun.id}`);
        } catch (e) {
            createError = e instanceof Error ? e.message : 'Failed to create run';
        } finally {
            creating = false;
        }
    }
</script>

<FullScreenModal bind:open title={forExperiment ? `New Run for ${forExperiment.name}` : 'New Run'} onClose={requestClose}>
    {#snippet headerActions()}
        <RunCreatorStepper {currentStep} {highestVisited} onJump={jumpTo} />
    {/snippet}

    <div class="wizard-body">
        <main class="wizard-main">
          <div class="wizard-content">
            {#key currentStep}
                <div
                    class="step-pane"
                    in:fly={{
                        x: stepDirection === 'forward' ? 16 : -16,
                        duration: blockDuration(),
                    }}
                >
                    {#if currentStep === 1}
                        <RunCreatorNameStep
                            name={runName}
                            {experimentId}
                            {experiments}
                            lockedExperiment={forExperiment}
                            {producesLot}
                            {lotNumber}
                            {batchNumber}
                            {projectId}
                            onChange={(v) => { runName = v.name; experimentId = v.experimentId; producesLot = v.producesLot; lotNumber = v.lotNumber; batchNumber = v.batchNumber; }}
                            onValidate={(v) => { nameValid = v; }}
                        />
                    {:else if currentStep === 2}
                        <RunCreatorProtocolStep
                            {protocols}
                            {protocolId}
                            {protocolVersionNumber}
                            {versions}
                            {loadingVersions}
                            onChange={(v) => { protocolId = v.protocolId; protocolVersionNumber = v.protocolVersionNumber; }}
                            onValidate={(v) => { protocolValid = v; }}
                            onLoadVersions={loadVersions}
                        />
                    {:else if currentStep === 3 && currentGraph && originalGraph}
                        <RunOverridesEditor
                            {originalGraph}
                            {currentGraph}
                            {orgEquipment}
                            {mediaPrepNodes}
                            {roles}
                            {activeRoleId}
                            onChange={(g) => { currentGraph = g; }}
                            onRoleChange={(id) => { activeRoleId = id; }}
                            isStrict={selectedProtocol?.requires_approval ?? false}
                        />
                    {:else if currentStep === 4}
                        <RunCreatorAssigneeStep
                            {roleNodes}
                            {projectMembers}
                            {loadingMembers}
                            {assignments}
                            onChange={(a) => { assignments = a; }}
                        />
                    {:else if currentStep === 5}
                        <RunCreatorReviewStep
                            {runName}
                            experimentName={experiments.find((e) => e.id === experimentId)?.name ?? null}
                            protocolName={selectedProtocol?.name ?? ''}
                            versionNumber={selectedVersion?.version_number ?? 0}
                            {isLatestVersion}
                            {edits}
                            {creating}
                            error={createError}
                            onCreate={createRun}
                        />
                    {/if}
                </div>
            {/key}
          </div>
        </main>

        <footer class="wizard-footer">
            <Button variant="ghost" onclick={requestClose}>Cancel</Button>
            <div class="footer-spacer"></div>
            {#if currentStep > 1 && currentStep < 5}
                <div in:fade={{ duration: blockDuration() }}>
                    <Button variant="secondary" onclick={back}>Back</Button>
                </div>
            {/if}
            {#if currentStep === 3}
                <div in:fade={{ duration: blockDuration() }}>
                    <Button
                        variant="ghost"
                        onclick={() => { currentGraph = JSON.parse(JSON.stringify(originalGraph)); next(); }}
                    >
                        Skip · use defaults
                    </Button>
                </div>
            {/if}
            {#if currentStep === 4}
                <div in:fade={{ duration: blockDuration() }}>
                    <Button variant="ghost" onclick={() => { assignments = {}; advanceTo(5); }}>
                        Skip · assign later
                    </Button>
                </div>
            {/if}
            {#if currentStep < 5}
                <div in:fade={{ duration: blockDuration() }}>
                    <Button
                        onclick={next}
                        disabled={(currentStep === 1 && !nameValid) || (currentStep === 2 && !protocolValid)}
                    >
                        {currentStep === 4 ? 'Continue to review' : 'Continue'}
                    </Button>
                </div>
            {/if}
        </footer>
    </div>
</FullScreenModal>

<SaveAsNewVersionDialog
    bind:open={saveDialogOpen}
    {edits}
    nextVersionNumber={(selectedProtocol?.version_number ?? 0) + 1}
    onCancel={() => (saveDialogOpen = false)}
    onJustThisRun={dialogJustThisRun}
    onSaveAsVersion={dialogSaveAsVersion}
/>

<ConfirmDialog
    bind:open={discardConfirmOpen}
    title="Discard changes?"
    message="You have unsaved edits. Closing the wizard will discard them."
    confirmLabel="Discard"
    cancelLabel="Keep editing"
    confirmVariant="danger"
    onConfirm={confirmDiscard}
    onCancel={() => (discardConfirmOpen = false)}
/>

<style>
    .wizard-body {
        height: 100%;
        display: flex;
        flex-direction: column;
    }
    .wizard-main {
        flex: 1;
        overflow-y: auto;
        width: 100%;
    }
    .wizard-content {
        max-width: 72rem;
        width: 100%;
        margin-left: auto;
        margin-right: auto;
        padding: 1.5rem;
    }
    .wizard-footer {
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
    .step-pane {
        height: 100%;
    }
</style>
