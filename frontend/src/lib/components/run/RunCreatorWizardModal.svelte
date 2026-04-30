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
    import RunCreatorReviewStep from './RunCreatorReviewStep.svelte';
    import SaveAsNewVersionDialog from './SaveAsNewVersionDialog.svelte';
    import { computeEdits, buildOverridesPayload } from '$lib/utils/runOverrides';
    import type { Protocol, ProtocolVersion, ProtocolRole } from '$lib/schemas/protocols';

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

    let versions = $state<ProtocolVersion[]>([]);
    let orgEquipment = $state<OrgEquipment[]>([]);
    let loadedOrgEq = $state(false);

    let runName = $state('');
    let experimentId = $state<string | null>(null);

    let protocolId = $state<string | null>(null);
    let protocolVersionNumber = $state<number | null>(null);
    let originalGraph = $state<Graph | null>(null);
    let currentGraph = $state<Graph | null>(null);
    let loadingVersions = $state(false);

    let roles = $state<ProtocolRole[]>([]);
    let activeRoleId = $state<string | null>(null);

    let currentStep = $state<1 | 2 | 3 | 4>(1);
    let highestVisited = $state<1 | 2 | 3 | 4>(1);

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

    function resetState() {
        runName = '';
        experimentId = forExperiment?.id ?? null;
        protocolId = null;
        protocolVersionNumber = null;
        originalGraph = null;
        currentGraph = null;
        versions = [];
        roles = [];
        activeRoleId = null;
        currentStep = 1;
        highestVisited = 1;
        nameValid = false;
        protocolValid = false;
        saveDialogOpen = false;
        creating = false;
        createError = null;
    }

    $effect(() => {
        if (open) {
            resetState();
            if (!loadedOrgEq) {
                const org = getCurrentOrg();
                if (org) {
                    api.get<OrgEquipment[]>(`/iam/organizations/${org.id}/equipment`).then((eq) => {
                        orgEquipment = eq;
                        loadedOrgEq = true;
                    }).catch(() => {});
                }
            }
        }
    });

    async function loadVersions(pid: string) {
        loadingVersions = true;
        try {
            versions = await api.get<ProtocolVersion[]>(`/science/protocols/${pid}/versions`);
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
        api.get<{ roles?: ProtocolRole[] }>(`/science/protocols/${protocolId}`)
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

    function jumpTo(step: 1 | 2 | 3 | 4) {
        if (step <= highestVisited) currentStep = step;
    }

    function next() {
        if (currentStep === 1 && nameValid) {
            currentStep = 2;
            highestVisited = Math.max(highestVisited, 2) as typeof highestVisited;
        } else if (currentStep === 2 && protocolValid) {
            currentStep = 3;
            highestVisited = Math.max(highestVisited, 3) as typeof highestVisited;
        } else if (currentStep === 3) {
            if (edits.length > 0) {
                saveDialogOpen = true;
            } else {
                currentStep = 4;
                highestVisited = Math.max(highestVisited, 4) as typeof highestVisited;
            }
        }
    }

    function back() {
        if (currentStep > 1) currentStep = (currentStep - 1) as typeof currentStep;
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
        currentStep = 4;
        highestVisited = Math.max(highestVisited, 4) as typeof highestVisited;
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
            await api.put(`/science/protocols/${protocolId}?save_as_draft=true`, {
                graph: cleanGraph,
            });

            // Step 2: Publish the draft — sets is_draft=False and updates the main protocol
            await api.post(
                `/science/protocols/${protocolId}/publish-draft?version_number=${nextVer}`,
                { description: description || undefined },
            );
            await loadVersions(protocolId);
            protocolVersionNumber = nextVer;
            saveDialogOpen = false;
            currentStep = 4;
            highestVisited = Math.max(highestVisited, 4) as typeof highestVisited;
        } catch (e) {
            createError = e instanceof Error ? e.message : 'Failed to save version';
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
            };
            if (experimentId) payload.experiment_id = experimentId;
            if (protocolVersionNumber) payload.protocol_version_number = protocolVersionNumber;
            const overrides = buildOverridesPayload(edits, currentGraph);
            if (overrides) payload.overrides = overrides;
            const newRun = await api.post<{ id: string }>('/science/runs', payload);
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
            {#if currentStep === 1}
                <RunCreatorNameStep
                    name={runName}
                    {experimentId}
                    {experiments}
                    lockedExperiment={forExperiment}
                    onChange={(v) => { runName = v.name; experimentId = v.experimentId; }}
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
                />
            {:else if currentStep === 4}
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
        </main>

        <footer class="wizard-footer">
            <Button variant="ghost" onclick={requestClose}>Cancel</Button>
            <div class="footer-spacer"></div>
            {#if currentStep > 1 && currentStep < 4}
                <Button variant="secondary" onclick={back}>Back</Button>
            {/if}
            {#if currentStep === 3}
                <Button
                    variant="ghost"
                    onclick={() => { currentGraph = JSON.parse(JSON.stringify(originalGraph)); next(); }}
                >
                    Skip · use defaults
                </Button>
            {/if}
            {#if currentStep < 4}
                <Button
                    onclick={next}
                    disabled={(currentStep === 1 && !nameValid) || (currentStep === 2 && !protocolValid)}
                >
                    {currentStep === 3 ? 'Continue to review' : 'Continue'}
                </Button>
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
        padding: 1.5rem;
        max-width: 72rem;
        width: 100%;
        margin-left: auto;
        margin-right: auto;
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
</style>
