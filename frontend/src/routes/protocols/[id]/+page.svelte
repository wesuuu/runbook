<script lang="ts">
    import { onMount, setContext, tick } from "svelte";
    import { page } from '$app/stores';
    import {
        SvelteFlow,
        Background,
        Controls,
        MiniMap,
        Position,
        SelectionMode,
        type Node,
        type Edge,
        type Viewport,
    } from "@xyflow/svelte";
    import "@xyflow/svelte/dist/style.css";

    import { api, ApiError, getAwaitingMyApproval } from "$lib/api";
    import { toast } from "$lib/toast";
    import { getCurrentOrg, getUser } from "$lib/auth.svelte";
    import { ProjectSchema } from "$lib/schemas";
    import type { NodeTypes } from "@xyflow/svelte";
    import ProtocolSidebar from "$lib/components/protocol/ProtocolSidebar.svelte";
    import PublishVersionDialog from "$lib/components/protocol/PublishVersionDialog.svelte";
    import RevertOnEditConfirmDialog from "$lib/components/protocol/RevertOnEditConfirmDialog.svelte";
    import CanvasToolbar from "$lib/components/protocol/CanvasToolbar.svelte";
    import ValidationBanners from "$lib/components/protocol/ValidationBanners.svelte";
    import {
        serializeGraphData,
        buildStateSnapshot,
        parseGraphState,
        applyTimelineSizing as applyTimeline,
        clearTimelineSizing as clearTimeline,
        detectEquipmentConflicts as detectConflicts,
        findSwimLaneParent,
        adoptOrphanUnitOpsToLanes,
        applyDragStopReparenting,
    } from "$lib/components/protocol/protocolGraph";
    import {
        computeBranchValidationErrors,
        computeProcessStartValidationErrors,
    } from "$lib/components/protocol/protocolValidation";
    import {
        createProcessStartNode,
        createUnitOpNode,
        createSwimLaneNode,
        updateNodeHandleOrientation,
        updateNodeHandlePosition,
        resizeNodeForTimeline,
        removeNode,
    } from "$lib/components/protocol/protocolNodes";
    import {
        createUndoRedoState,
        pushSnapshot,
        undo as undoAction,
        redo as redoAction,
        canUndo,
        canRedo,
        buildGraphSnapshot,
    } from "$lib/components/protocol/undoRedo";
    import UnitOpNode from "$lib/components/protocol/UnitOpNode.svelte";
    import SwimLaneNode from "$lib/components/protocol/SwimLaneNode.svelte";
    import ProcessStartNode from "$lib/components/protocol/ProcessStartNode.svelte";
    import Inspector from "$lib/components/protocol/Inspector.svelte";
    import ProcessStartInspector from "$lib/components/protocol/ProcessStartInspector.svelte";
    import UnitOpPreview from "$lib/components/protocol/UnitOpPreview.svelte";
    import TimeAxis from "$lib/components/protocol/TimeAxis.svelte";
    import CreateUnitOpModal from "$lib/components/modals/CreateUnitOpModal.svelte";
    import VersionHistoryDrawer from "$lib/components/analytics/VersionHistoryDrawer.svelte";
    import PdfPreviewDrawer from "$lib/components/media/PdfPreviewDrawer.svelte";
    import ConfirmDialog from "$lib/components/ui/confirm-dialog.svelte";
    import { HelpMenu, TourModal, runProtocolTour } from "$lib/onboarding";
    import { shouldShowDot, markDismissed } from "$lib/onboarding/tourStore.svelte";
    import {
        SELECT_SAMPLE_NODE_EVENT,
        CLEAR_SAMPLE_NODE_EVENT,
    } from "$lib/onboarding/tours/protocolTour";
    import { fade } from "svelte/transition";
    import { blockDuration } from "$lib/transitions";

    // --- Embedded Mode Props ---
    // When used inside ProtocolImportModal, these props are set.
    // When used as a page, they are undefined and the component loads from API.
    interface Props {
        initialGraph?: Record<string, unknown>;
        embedded?: boolean;
        onGraphChange?: (graph: Record<string, unknown>) => void;
    }
    let { initialGraph, embedded = false, onGraphChange }: Props = $props();

    const id = $derived(embedded ? undefined : $page.params.id);

    // --- Node Types ---
    const nodeTypes = { unitOp: UnitOpNode, swimLane: SwimLaneNode, processStart: ProcessStartNode } as Record<string, any> as NodeTypes;

    // --- State ---
    let protocol = $state<any>(null);
    let unitOps = $state<any[]>([]);
    let roles = $state<any[]>([]);
    let orgEquipment = $state<any[]>([]);
    let equipmentConflicts = $state<Map<string, string[]>>(new Map());
    let loading = $state(true);
    let error = $state<string | null>(null);
    let saving = $state(false);
    let publishDialogOpen = $state(false);

    // Flow state
    let nodes = $state<Node[]>([]);
    let edges = $state<Edge[]>([]);
    let viewport = $state<Viewport>({ x: 0, y: 0, zoom: 1 });
    let flowContainer: HTMLDivElement;

    // Layout / time settings
    let layout = $state<"horizontal" | "vertical">("horizontal");
    let handleOrientation = $state<"horizontal" | "vertical">("vertical");
    let timeEnabled = $state(false);
    let pixelsPerHour = $state(200);

    // Interaction mode: pan (default) vs select
    let interactionMode = $state<"pan" | "select">("pan");

    // Versioning + approval state
    let protocolStatus = $state<string>("DRAFT");
    let versionNumber = $state(0);
    let showVersionHistory = $state(false);
    let versions = $state<any[]>([]);
    let versionsLoading = $state(false);
    let approvalRequired = $state(false);
    let projectSettingEnabled = $state(false);
    let canDesignate = $state(false);
    let canApprove = $state(false);
    let revertOnEditDialogOpen = $state(false);
    let confirmedEditAfterApproval = $state(false);
    let pendingEditAction: (() => void) | null = $state(null);

    const currentUserId = $derived(getUser()?.id ?? '');

    // PDF preview drawer
    let showPdfDrawer = $state(false);
    let projectPdfFormat = $state<Record<string, any>>({});

    // Version browsing (prev/next navigation)
    let previewingVersion = $state<number | null>(null);
    let previewLoading = $state(false);
    let savedStateBeforePreview = $state<string | null>(null);
    // Highest is_draft version_number above the published versionNumber, if any.
    // When set, the toolbar's "next" arrow can advance past versionNumber to
    // surface the unpublished draft.
    let latestDraftVersion = $state<number | null>(null);

    // Historical previews are read-only ("you're looking at v2 of an
    // APPROVED v4"); the unpublished-draft preview is editable so the user
    // can keep iterating on the draft without leaving the toggle view.
    const isHistoricalPreview = $derived(
        previewingVersion !== null
            && previewingVersion !== latestDraftVersion,
    );

    // Track unsaved changes
    let hasUnsavedChanges = $state(false);
    let lastSavedState = $state<string>("");

    // -- Onboarding Tour --
    // The pulsing dot on the HelpMenu (shown only on the sample protocol) is the trigger;
    // no auto-start. Clicking the dot opens the modal, which starts the tour.
    let protocolTourModalOpen = $state(false);

    function openProtocolTourModal() {
        protocolTourModalOpen = true;
    }

    function startProtocolTour() {
        protocolTourModalOpen = false;
        runProtocolTour(() => {});
    }

    async function dismissProtocolTour() {
        protocolTourModalOpen = false;
        await markDismissed('protocol');
    }

    // Let the protocol tour drive node selection, saves, and the PDF preview drawer.
    $effect(() => {
        if (embedded) return;
        function selectNode(e: Event) {
            const { nodeId } = (e as CustomEvent).detail ?? {};
            if (!nodeId) return;
            nodes = nodes.map((n) => ({ ...n, selected: n.id === nodeId }));
        }
        function clearNode() {
            nodes = nodes.map((n) => (n.selected ? { ...n, selected: false } : n));
        }
        function triggerSave() {
            saveDraft();
        }
        function triggerOpenPdfPreview() {
            openPdfPreview();
        }
        function triggerClosePdfPreview() {
            showPdfDrawer = false;
        }
        window.addEventListener(SELECT_SAMPLE_NODE_EVENT, selectNode);
        window.addEventListener(CLEAR_SAMPLE_NODE_EVENT, clearNode);
        window.addEventListener('onboarding:save-protocol', triggerSave);
        window.addEventListener('onboarding:open-pdf-preview', triggerOpenPdfPreview);
        window.addEventListener('onboarding:close-pdf-preview', triggerClosePdfPreview);
        return () => {
            window.removeEventListener(SELECT_SAMPLE_NODE_EVENT, selectNode);
            window.removeEventListener(CLEAR_SAMPLE_NODE_EVENT, clearNode);
            window.removeEventListener('onboarding:save-protocol', triggerSave);
            window.removeEventListener('onboarding:open-pdf-preview', triggerOpenPdfPreview);
            window.removeEventListener('onboarding:close-pdf-preview', triggerClosePdfPreview);
        };
    });

    // Confirm dialog state
    let confirmOpen = $state(false);
    let confirmTitle = $state('');
    let confirmMessage = $state('');
    let confirmLabel = $state('Confirm');
    let confirmVariant = $state<'primary' | 'danger' | 'warning'>('danger');
    let confirmAction = $state<() => void>(() => {});

    function showConfirm(opts: {
        title: string;
        message: string;
        label?: string;
        variant?: 'primary' | 'danger' | 'warning';
        onConfirm: () => void;
    }) {
        confirmTitle = opts.title;
        confirmMessage = opts.message;
        confirmLabel = opts.label ?? 'Confirm';
        confirmVariant = opts.variant ?? 'danger';
        confirmAction = opts.onConfirm;
        confirmOpen = true;
    }

    // Undo/redo
    let undoRedoState = $state(createUndoRedoState());
    let preConnectSnapshot = $state<string | null>(null);

    function pushUndoSnapshot() {
        undoRedoState = pushSnapshot(undoRedoState, buildGraphSnapshot(nodes, edges));
    }

    function handleUndo() {
        const result = undoAction(undoRedoState, buildGraphSnapshot(nodes, edges));
        if (!result) return;
        undoRedoState = result.state;
        const restored = JSON.parse(result.snapshot);
        nodes = restored.nodes;
        edges = restored.edges;
    }

    function handleRedo() {
        const result = redoAction(undoRedoState, buildGraphSnapshot(nodes, edges));
        if (!result) return;
        undoRedoState = result.state;
        const restored = JSON.parse(result.snapshot);
        nodes = restored.nodes;
        edges = restored.edges;
    }

    // Compute current state as JSON for comparison
    const currentState = $derived(() =>
        buildStateSnapshot(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour),
    );

    // Track changes
    $effect(() => {
        if (lastSavedState && currentState() !== lastSavedState) {
            hasUnsavedChanges = true;
        }
    });

    // Detect equipment conflicts when edges or nodes change
    $effect(() => {
        if (nodes.length > 0 && edges.length > 0) {
            detectEquipmentConflicts();
        }
    });

    // Provide handle orientation and node actions to child node components via context
    setContext("protocolHandleOrientation", {
        get value() {
            return handleOrientation;
        },
    });

    setContext("branchValidation", {
        get invalidNodeIds() {
            return branchInvalidNodeIds();
        },
    });

    setContext("laneInfo", {
        childCount(laneId: string): number {
            let n = 0;
            for (const node of nodes) {
                if (node.parentId === laneId) n += 1;
            }
            return n;
        },
    });

    setContext("nodeActions", {
        setNodeHandleOrientation(nodeId: string, orientation: "horizontal" | "vertical" | null) {
            pushUndoSnapshot();
            nodes = updateNodeHandleOrientation(nodes, nodeId, orientation, handleOrientation);
        },
        setNodeHandlePosition(nodeId: string, handleType: "source" | "target", position: Position) {
            pushUndoSnapshot();
            nodes = updateNodeHandlePosition(nodes, nodeId, handleType, position, handleOrientation);
        },
        onNodeResized(nodeId: string, width: number, height: number) {
            if (!timeEnabled) return;
            pushUndoSnapshot();
            nodes = resizeNodeForTimeline(nodes, nodeId, width, height, layout, pixelsPerHour);
        },
        deleteNode(nodeId: string) {
            const node = nodes.find((n) => n.id === nodeId);
            if (!node) return;
            const label = (node.data.label as string) || "this item";
            const kind = node.type === "swimLane" ? "role lane" : node.type === "processStart" ? "process start" : "unit operation";
            showConfirm({
                title: `Delete ${kind}`,
                message: `Delete ${kind} "${label}"? This cannot be undone.`,
                label: 'Delete',
                variant: 'danger',
                onConfirm: () => {
                    pushUndoSnapshot();
                    const result = removeNode(nodes, edges, nodeId);
                    nodes = result.nodes;
                    edges = result.edges;
                    if (selectedNodeId === nodeId) selectedNodeId = null;
                },
            });
        },
    });

    setContext("timelineConfig", {
        get enabled() { return timeEnabled; },
        get pixelsPerHour() { return pixelsPerHour; },
        get layout() { return layout; },
        get snapMinutes() { return 5; },
    });

    // Inspector — watch for node selection changes via SvelteFlow's built-in selection
    let selectedNodeId = $state<string | null>(null);
    let previewedOp = $state<any | null>(null);

    function handleOpPreview(op: any) {
        // Mutual exclusion: previewing clears canvas selection by
        // mutating SvelteFlow's `selected` flags. Without this, the
        // node-selection effect below would re-sync selectedNodeId
        // from the still-selected canvas node and clobber previewedOp.
        if (nodes.some((n) => n.selected)) {
            nodes = nodes.map((n) => (n.selected ? { ...n, selected: false } : n));
        }
        previewedOp = op;
    }

    function clearPreview() {
        previewedOp = null;
    }

    $effect(() => {
        const sel = nodes.find((n) => (n.type === "unitOp" || n.type === "processStart") && n.selected);
        selectedNodeId = sel ? sel.id : null;
        if (selectedNodeId) previewedOp = null;
    });

    const selectedNode = $derived(
        selectedNodeId
            ? nodes.find((n) => n.id === selectedNodeId) || null
            : null,
    );

    const hasUnitOpNodes = $derived(nodes.some((n) => n.type === "unitOp"));

    function openPdfPreview() {
        if (!protocol) return;
        const block = blockingBranchMessage();
        if (block) {
            toast.error(block);
            return;
        }
        showVersionHistory = false;
        showPdfDrawer = true;
    }

    // Create Unit Op modal
    let showCreateModal = $state(false);
    let createModalCategory = $state("");

    // --- Validation (delegated to protocolValidation.ts) ---
    const branchValidationErrors = $derived(() =>
        computeBranchValidationErrors(nodes, edges, {
            timeEnabled,
            pixelsPerHour,
            layout,
        }),
    );
    const processStartValidationErrors = $derived(() => computeProcessStartValidationErrors(nodes, edges));

    const branchInvalidNodeIds = $derived(() => {
        const ids = new Set<string>();
        for (const err of branchValidationErrors()) {
            ids.add(err.sourceNodeId);
        }
        return ids;
    });

    function blockingBranchMessage(): string | null {
        const errs = branchValidationErrors();
        if (errs.length === 0) return null;
        return `Cannot proceed: ${errs.length} branching ${errs.length === 1 ? "step needs" : "steps need"} distinct roles. See the warning banner.`;
    }

    // --- Timeline helpers ---
    const totalHours = $derived(() => {
        if (!timeEnabled) return 8;
        let maxEnd = 0;
        for (const n of nodes) {
            if (n.type !== "unitOp") continue;
            const pos = layout === "horizontal" ? n.position.x : n.position.y;
            const dur = (n.data.duration_min as number) || 30;
            const sizePx = (dur / 60) * pixelsPerHour;
            maxEnd = Math.max(maxEnd, pos + sizePx);
        }
        return Math.max(8, Math.ceil(maxEnd / pixelsPerHour) + 1);
    });

    const snapGridPx = $derived((5 / 60) * pixelsPerHour);

    function applyTimelineSizing() {
        nodes = applyTimeline(nodes, layout, pixelsPerHour);
    }

    function clearTimelineSizing() {
        nodes = clearTimeline(nodes);
    }

    // --- Graph State Helper ---
    function applyGraphState(graph: any) {
        const gs = parseGraphState(graph);
        nodes = gs.nodes;
        edges = gs.edges;
        layout = gs.layout;
        handleOrientation = gs.handleOrientation;
        timeEnabled = gs.timeEnabled;
        pixelsPerHour = gs.pixelsPerHour;
    }

    // --- Capability Resolution ---
    async function resolveCapabilities() {
        if (!protocol?.project_id) return;
        // canDesignate: project ADMIN — soft-detect via /projects/{id}/permissions (403 if not admin)
        try {
            await api.get(`/projects/${protocol.project_id}/permissions`);
            canDesignate = true;
        } catch {
            canDesignate = false;
        }
        // canApprove: only when status is PENDING_APPROVAL and the protocol appears in the
        // current user's awaiting-approval list.
        if (protocolStatus === 'PENDING_APPROVAL') {
            try {
                const items = await getAwaitingMyApproval();
                canApprove = items.some((it) => it.protocol_id === protocol.id);
            } catch {
                canApprove = false;
            }
        } else {
            canApprove = false;
        }
    }

    async function refreshProtocol() {
        if (!protocol?.id) return;
        try {
            const fresh: any = await api.get(`/science/protocols/${protocol.id}`);
            protocol = fresh;
            protocolStatus = fresh.status || 'DRAFT';
            versionNumber = fresh.version_number || 0;
            approvalRequired = (fresh.requires_approval as boolean) || false;
            await resolveCapabilities();
            // Reset edit-after-approval guard when status changes
            if (protocolStatus !== 'APPROVED') {
                confirmedEditAfterApproval = false;
            }
        } catch (e: unknown) {
            console.error('Failed to refresh protocol:', e instanceof Error ? e.message : e);
        }
    }

    // --- Revert-on-edit guard ---
    function requireEditConfirmation(action: () => void): boolean {
        // Returns true if the action can proceed immediately, false if we opened the dialog.
        if (protocolStatus !== 'APPROVED' || confirmedEditAfterApproval) {
            return true;
        }
        pendingEditAction = action;
        revertOnEditDialogOpen = true;
        return false;
    }

    function handleRevertConfirm() {
        confirmedEditAfterApproval = true;
        const fn = pendingEditAction;
        pendingEditAction = null;
        if (fn) fn();
    }

    function handleRevertCancel() {
        pendingEditAction = null;
    }

    // --- Data Loading ---
    async function loadData() {
        try {
            // Unit ops are loaded after protocol (below) to include project-scoped ops

            // Load organization equipment
            const org = getCurrentOrg();
            if (org?.id) {
                orgEquipment = await api.get(`/iam/organizations/${org.id}/equipment`);
            }

            if (id && id !== "new") {
                protocol = await api.get(`/science/protocols/${id}`);
                roles = protocol.roles || [];
                protocolStatus = protocol.status || "DRAFT";
                versionNumber = protocol.version_number || 0;
                latestDraftVersion = protocol.latest_draft_version_number ?? null;

                // Load unit ops scoped to this protocol's project
                const projectParam = protocol.project_id ? `?project_id=${protocol.project_id}` : '';
                unitOps = await api.get(`/science/unit-ops${projectParam}`);

                // Use protocol-level requires_approval as the canonical flag
                approvalRequired = (protocol.requires_approval as boolean) || false;

                // Fetch project settings for approval requirement and PDF format
                try {
                    const proj = await api.get(`/projects/${protocol.project_id}`, { schema: ProjectSchema });
                    projectSettingEnabled = (proj.settings?.require_protocol_approval as boolean) || false;
                    projectPdfFormat = (proj.settings?.pdf_format as Record<string, any>) || {};
                } catch {
                    // Ignore — approval not required if project fetch fails
                }

                // Resolve capabilities (best-effort; failures default to false)
                await resolveCapabilities();

                if (protocol.graph && protocol.graph.nodes) {
                    applyGraphState(protocol.graph);
                    detectEquipmentConflicts();
                } else {
                    // Brand-new protocol that came back from POST without
                    // a saved graph yet — seed a Process Start so the
                    // user has an anchor to wire up to.
                    nodes = [createProcessStartNode({ x: 80, y: 80 }, undefined)];
                }
            } else {
                // New protocol — load global + org ops only
                unitOps = await api.get("/science/unit-ops");
                nodes = [createProcessStartNode({ x: 80, y: 80 }, undefined)];
            }
            // Apply timeline sizing if loaded with timeline enabled
            if (timeEnabled) {
                applyTimelineSizing();
            }

            // Initialize saved state for change tracking
            lastSavedState = buildStateSnapshot(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);
            hasUnsavedChanges = false;
            undoRedoState = createUndoRedoState();

            // Populate version list so the save toast can tell whether it
            // is creating a new draft vs editing the existing one.
            if (id && id !== "new") {
                await loadVersions();
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            loading = false;
        }
    }

    // --- Save Protocol ---
    async function saveDraft() {
        if (!protocol) return;

        // Block save while previewing a historical version (editing the
        // unpublished draft is allowed and just updates that draft).
        if (isHistoricalPreview) {
            toast.warning("Exit version preview before saving");
            return;
        }

        // Block save if pending approval
        if (protocolStatus === "PENDING_APPROVAL") {
            toast.warning("Cannot save while pending approval");
            return;
        }

        // Block save if archived
        if (protocolStatus === "ARCHIVED") {
            toast.warning("Cannot save an archived protocol");
            return;
        }

        saving = true;

        try {
            const graphData = serializeGraphData(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);

            const draftVersionNumber = versionNumber + 1;
            const draftExisted = versions.some(
                (v) => v.version_number === draftVersionNumber && v.is_draft,
            );

            // Save as draft (creates draft version without modifying main protocol)
            const updated: any = await api.put(`/science/protocols/${protocol.id}?save_as_draft=true`, {
                graph: graphData,
            });
            // Reload versions to show the new draft
            await loadVersions();
            toast.success(
                draftExisted
                    ? `Draft v${draftVersionNumber} edited`
                    : `Draft saved (v${draftVersionNumber})`,
            );
            // Mark as saved and reset undo/redo
            lastSavedState = buildStateSnapshot(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);
            hasUnsavedChanges = false;
            undoRedoState = createUndoRedoState();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'An error occurred');
        } finally {
            saving = false;
        }
    }

    async function saveAndPublish() {
        if (!protocol) return;

        // Block save while previewing a historical version.
        if (isHistoricalPreview) {
            toast.warning("Exit version preview before saving");
            return;
        }

        // Block if already approved, pending, or archived
        if (protocolStatus === "PENDING_APPROVAL" || protocolStatus === "APPROVED" || protocolStatus === "ARCHIVED") {
            toast.warning(protocolStatus === "ARCHIVED" ? "Cannot save an archived protocol" : protocolStatus === "APPROVED" ? "Already published" : "Cannot save while pending approval");
            return;
        }

        const block = blockingBranchMessage();
        if (block) {
            toast.error(block);
            return;
        }

        // Open the dialog; actual publish happens in performPublish via onConfirm
        publishDialogOpen = true;
    }

    async function performPublish(payload: { description: string | undefined; change_summary: string | undefined }) {
        if (!protocol) return;

        saving = true;

        try {
            const graphData = serializeGraphData(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);

            // Save as draft first
            const draftResponse: any = await api.put(`/science/protocols/${protocol.id}?save_as_draft=true`, {
                graph: graphData,
            });
            const draftVersionNumber = versionNumber + 1;

            // Then publish the draft (with optional metadata from the dialog)
            const publishResponse: any = await api.post(
                `/science/protocols/${protocol.id}/publish-draft?version_number=${draftVersionNumber}`,
                payload,
            );

            protocolStatus = publishResponse.status || "APPROVED";
            versionNumber = publishResponse.version_number || draftVersionNumber;
            toast.success("Published");

            // Mark as saved and reset undo/redo
            lastSavedState = buildStateSnapshot(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);
            hasUnsavedChanges = false;
            undoRedoState = createUndoRedoState();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'An error occurred');
        } finally {
            saving = false;
        }
    }

    // --- Version History ---
    async function loadVersions() {
        if (!protocol) return;
        versionsLoading = true;
        try {
            versions = await api.get(`/science/protocols/${protocol.id}/versions`);
            // Refresh draft-version pointer so the toolbar's "next" arrow
            // stays accurate after save/publish/revert flows reload versions.
            const draftAbove = versions
                .filter((v: any) => v.is_draft && v.version_number > versionNumber)
                .map((v: any) => v.version_number)
                .sort((a: number, b: number) => b - a)[0];
            latestDraftVersion = draftAbove ?? null;
        } catch (e: unknown) {
            console.error("Failed to load versions:", e instanceof Error ? e.message : e);
        } finally {
            versionsLoading = false;
        }
    }

    async function revertToVersion(versionNum: number) {
        if (!protocol) return;
        showConfirm({
            title: 'Revert version',
            message: `Revert to version ${versionNum}? This creates a new version with the old graph.`,
            label: 'Revert',
            variant: 'warning',
            onConfirm: () => doRevertToVersion(versionNum),
        });
    }

    async function doRevertToVersion(versionNum: number) {
        if (!protocol) return;
        try {
            const updated: any = await api.post(
                `/science/protocols/${protocol.id}/revert/${versionNum}`,
            );
            // Reload everything from the response
            protocol = updated;
            protocolStatus = updated.status || "DRAFT";
            versionNumber = updated.version_number || 0;

            if (updated.graph && updated.graph.nodes) {
                applyGraphState(updated.graph);
            }
            if (timeEnabled) applyTimelineSizing();

            lastSavedState = buildStateSnapshot(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);
            hasUnsavedChanges = false;

            toast.success(`Reverted to v${versionNum}`);

            // Refresh version list
            await loadVersions();
        } catch (e: unknown) {
            toast.error(`Revert failed: ${e instanceof Error ? e.message : 'An error occurred'}`);
        }
    }

    function toggleVersionHistory() {
        showVersionHistory = !showVersionHistory;
        if (showVersionHistory) {
            showPdfDrawer = false;
            loadVersions();
        }
    }

    // --- Version Browsing (prev/next arrows) ---
    async function browseVersion(direction: 'prev' | 'next') {
        if (!protocol || previewLoading) return;

        // Determine which version to load
        const currentPreview = previewingVersion ?? versionNumber;
        const targetVersion = direction === 'prev' ? currentPreview - 1 : currentPreview + 1;

        // Forward ceiling is the published version, unless an unpublished
        // draft exists above it -- then the draft is reachable too.
        const maxBrowsable = latestDraftVersion ?? versionNumber;
        if (targetVersion > maxBrowsable) {
            exitPreview();
            return;
        }
        if (targetVersion < 1) return;

        previewLoading = true;
        try {
            // Save current state before first preview
            if (previewingVersion === null) {
                savedStateBeforePreview = buildStateSnapshot(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);
            }

            const ver: any = await api.get(
                `/science/protocols/${protocol.id}/versions/${targetVersion}`,
            );

            if (ver.graph && ver.graph.nodes) {
                applyGraphState(ver.graph);
            }
            if (timeEnabled) applyTimelineSizing();
            previewingVersion = targetVersion;
        } catch (e: unknown) {
            toast.error(`Failed to load v${targetVersion}: ${e instanceof Error ? e.message : 'An error occurred'}`);
        } finally {
            previewLoading = false;
        }
    }

    function exitPreview() {
        if (savedStateBeforePreview) {
            applyGraphState(JSON.parse(savedStateBeforePreview));
            if (timeEnabled) applyTimelineSizing();
        }
        previewingVersion = null;
        savedStateBeforePreview = null;
    }

    async function restorePreviewedVersion() {
        if (previewingVersion === null) return;
        const vNum = previewingVersion;
        // Clear preview state first so revert operates cleanly
        previewingVersion = null;
        savedStateBeforePreview = null;
        await revertToVersion(vNum);
    }

    // --- Approval ---
    async function submitForApproval() {
        if (!protocol) return;
        if (hasUnsavedChanges) {
            showConfirm({
                title: 'Unsaved changes',
                message: 'You have unsaved changes. Save first before submitting?',
                label: 'Save & Submit',
                variant: 'warning',
                onConfirm: async () => {
                    await saveDraft();
                    await doSubmitForApproval();
                },
            });
            return;
        }
        await doSubmitForApproval();
    }

    async function doSubmitForApproval() {
        if (!protocol) return;
        try {
            const updated: any = await api.post(
                `/science/protocols/${protocol.id}/submit-for-approval`,
            );
            protocolStatus = updated.status || "PENDING_APPROVAL";
            toast.success("Submitted for approval");
        } catch (e: unknown) {
            toast.error(`Submit failed: ${e instanceof Error ? e.message : 'An error occurred'}`);
        }
    }

    // --- Archive / Delete ---
    async function unarchiveProtocol() {
        if (!protocol) return;
        try {
            await api.put(`/science/protocols/${protocol.id}/unarchive`, {});
            await loadData();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to unarchive');
        }
    }

    async function deleteOrArchiveProtocol() {
        if (!protocol) return;
        showConfirm({
            title: 'Delete protocol',
            message: 'Are you sure you want to delete/archive this protocol?',
            label: 'Delete',
            variant: 'danger',
            onConfirm: async () => {
                try {
                    await api.delete(`/science/protocols/${protocol!.id}`);
                    if (protocol!.project_id) {
                        window.location.href = `/projects/${protocol!.project_id}`;
                    } else {
                        window.location.href = '/';
                    }
                } catch (e: unknown) {
                    toast.error(e instanceof Error ? e.message : 'Failed to delete/archive');
                }
            },
        });
    }

    // --- Drag & Drop ---
    function onDragOver(event: DragEvent) {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    }

    function onDrop(event: DragEvent) {
        event.preventDefault();
        if (!event.dataTransfer) return;

        if (isHistoricalPreview) {
            toast.warning("Exit version preview before editing");
            return;
        }

        if (protocolStatus === "PENDING_APPROVAL") {
            toast.warning("Cannot edit while pending approval");
            return;
        }

        if (protocolStatus === "ARCHIVED") {
            toast.warning("Cannot edit an archived protocol");
            return;
        }

        const opData = event.dataTransfer.getData("application/svelteflow");
        if (!opData) return;

        // Capture event data before opening dialog (event becomes invalid after async)
        const clientX = event.clientX;
        const clientY = event.clientY;

        if (!requireEditConfirmation(() => doDrop(opData, clientX, clientY))) {
            return;
        }
        doDrop(opData, clientX, clientY);
    }

    function doDrop(opData: string, clientX: number, clientY: number) {
        const op = JSON.parse(opData);

        // Convert screen coordinates to flow coordinates
        const bounds = flowContainer.getBoundingClientRect();
        const position = {
            x: (clientX - bounds.left - viewport.x) / viewport.zoom,
            y: (clientY - bounds.top - viewport.y) / viewport.zoom,
        };

        if (op._nodeType === "swimLane") {
            const role = op.role;
            if (!role || !role.id) return;
            if (nodes.some((n) => n.id === `lane-${role.id}`)) {
                toast.warning(`Lane for "${role.name}" is already on the canvas`);
                return;
            }
            pushUndoSnapshot();
            const withLane = [
                ...nodes,
                createSwimLaneNode(role, layout, roles.length - 1, position),
            ];
            nodes = adoptOrphanUnitOpsToLanes(withLane);
            return;
        }

        const { parentId, adjustedPosition } = findSwimLaneParent(nodes, position);

        pushUndoSnapshot();
        if (op._nodeType === "processStart") {
            nodes = [...nodes, createProcessStartNode(adjustedPosition, parentId)];
        } else {
            nodes = [...nodes, createUnitOpNode(op, adjustedPosition, parentId, timeEnabled, layout, pixelsPerHour)];
        }
    }

    // Snapshot taken at drag-start for undo-on-cancel when APPROVED.
    let preDragSnapshot: ReturnType<typeof buildGraphSnapshot> | null = $state(null);

    function handleNodeDragStart() {
        preDragSnapshot = buildGraphSnapshot(nodes, edges);
        pushUndoSnapshot();
    }

    function handleNodeDragStop({ targetNode }: { targetNode: Node | null }) {
        // Guard: if APPROVED and edit not yet confirmed, open the dialog and
        // revert the drag if the user cancels.
        console.log('[QAD] dragStop fired, status=', protocolStatus, 'targetNode=', targetNode?.id);
        if (protocolStatus === 'APPROVED' && !confirmedEditAfterApproval) {
            const snapshot = preDragSnapshot;
            preDragSnapshot = null;
            pendingEditAction = () => {
                // Re-apply reparenting on confirmed drag
                if (!targetNode) return;
                const updated = applyDragStopReparenting(nodes, targetNode.id);
                if (updated !== nodes) nodes = updated;
            };
            // Revert position to pre-drag state immediately so the node snaps back
            if (snapshot) {
                nodes = snapshot.nodes as typeof nodes;
                edges = snapshot.edges as typeof edges;
            }
            // Open the dialog after a short timeout to ensure we're back in
            // Svelte's reactive context after d3-drag's synthetic event handling.
            setTimeout(() => { revertOnEditDialogOpen = true; }, 0);
            return;
        }
        preDragSnapshot = null;
        if (!targetNode) return;
        const updated = applyDragStopReparenting(nodes, targetNode.id);
        if (updated === nodes) return;
        nodes = updated;
    }

    // --- Equipment Management ---
    async function handleCreateEquipment(data: { name: string; description: string; equipment_type: string; location: string }): Promise<any> {
        const org = getCurrentOrg();
        if (!org?.id) throw new Error("No organization");

        const newEquipment: any = await api.post(
            `/iam/organizations/${org.id}/equipment`,
            {
                name: data.name,
                description: data.description,
                equipment_type: data.equipment_type,
                location: data.location,
            }
        );

        orgEquipment = [...orgEquipment, newEquipment];
        return newEquipment;
    }

    // --- Equipment Conflict Detection ---
    function detectEquipmentConflicts() {
        equipmentConflicts = detectConflicts(nodes, edges);
    }

    // --- Inspector Apply ---
    function handleInspectorApply(
        nodeId: string,
        params: Record<string, any>,
        duration: number,
        description: string,
        equipment: any[] = [],
        paramSchema: Record<string, any> = {},
        position?: { x: number; y: number },
    ): void {
        if (!requireEditConfirmation(() => handleInspectorApply(nodeId, params, duration, description, equipment, paramSchema, position))) {
            return;
        }
        pushUndoSnapshot();
        nodes = nodes.map((n) => {
            if (n.id === nodeId) {
                let width = n.width;
                let height = n.height;
                if (timeEnabled) {
                    const sizePx = (duration / 60) * pixelsPerHour;
                    if (layout === "horizontal") width = sizePx;
                    else height = sizePx;
                }
                return {
                    ...n,
                    width,
                    height,
                    position: position ?? n.position,
                    data: {
                        ...n.data,
                        params,
                        duration_min: duration,
                        description,
                        equipment,
                        paramSchema,
                    },
                };
            }
            return n;
        });
        detectEquipmentConflicts();
    }

    // --- Process Start Inspector Apply ---
    function handleProcessStartInspectorApply(
        nodeId: string,
        label: string,
        description: string,
    ): void {
        if (!requireEditConfirmation(() => handleProcessStartInspectorApply(nodeId, label, description))) {
            return;
        }
        pushUndoSnapshot();
        nodes = nodes.map((n) => {
            if (n.id === nodeId) {
                return {
                    ...n,
                    data: {
                        ...n.data,
                        label,
                        description,
                    },
                };
            }
            return n;
        });
    }

    // --- isValidConnection ---
    function isValidConnection(connection: { target: string }): boolean {
        const targetNode = nodes.find((n) => n.id === connection.target);
        // Reject connections targeting a processStart node
        if (targetNode?.type === "processStart") return false;
        return true;
    }

    // --- Role Callbacks (API handled by ProtocolSidebar) ---
    function handleRoleCreated(role: any) {
        pushUndoSnapshot();
        roles = [...roles, role];
        const withLane = [...nodes, createSwimLaneNode(role, layout, roles.length - 1)];
        nodes = adoptOrphanUnitOpsToLanes(withLane);
    }

    function handleRoleDeleted(roleId: string) {
        pushUndoSnapshot();
        roles = roles.filter((r) => r.id !== roleId);
        const laneNodeId = `lane-${roleId}`;
        nodes = nodes
            .filter((n) => n.id !== laneNodeId)
            .map((n) => (n.parentId === laneNodeId ? { ...n, parentId: undefined } : n));
    }

    // --- Orientation Toggle ---
    function toggleLayout() {
        pushUndoSnapshot();
        layout = layout === "horizontal" ? "vertical" : "horizontal";
        // Update swimlane node orientations
        nodes = nodes.map((n) => {
            if (n.type === "swimLane") {
                return {
                    ...n,
                    data: { ...n.data, orientation: layout },
                    style:
                        layout === "horizontal"
                            ? "width: 800px; height: 200px;"
                            : "width: 220px; height: 500px;",
                };
            }
            return n;
        });
    }

    // --- Custom Unit Op ---
    async function handleCreateUnitOp(opData: any) {
        try {
            const created = await api.post("/science/unit-ops", opData);
            unitOps = [...unitOps, created];
            showCreateModal = false;
        } catch (e: unknown) {
            if (e instanceof ApiError && e.status === 403) {
                alert("You need to be an organization admin to create org-wide unit operations.");
            }
            console.error("Failed to create unit op:", e instanceof Error ? e.message : e);
        }
    }

    // --- Save as New Unit Op (from Inspector) ---
    async function handleSaveAsNew(
        name: string,
        paramSchema: Record<string, any>,
        category: string,
    ): Promise<void> {
        try {
            const created = await api.post('/science/unit-ops', {
                name,
                category: category || 'General',
                description: '',
                param_schema: paramSchema,
                ...(protocol?.project_id ? { project_id: protocol.project_id } : {}),
            });
            unitOps = [...unitOps, created];
        } catch (e: unknown) {
            if (e instanceof ApiError && e.status === 403) {
                alert("You need to be an organization admin to create org-wide unit operations.");
            }
            console.error("Failed to save unit op:", e instanceof Error ? e.message : e);
        }
    }

    function openCreateModal(category: string) {
        createModalCategory = category;
        showCreateModal = true;
    }

    // --- Embedded mode: apply initial graph and emit changes ---
    $effect(() => {
        if (embedded && initialGraph && loading) {
            applyGraphState(initialGraph);
            loading = false;
            lastSavedState = buildStateSnapshot(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);
            hasUnsavedChanges = false;
        }
    });

    // Expose a function to update the graph from outside (e.g., chat refinement)
    export function updateGraph(graph: Record<string, unknown>) {
        applyGraphState(graph);
    }

    // Emit graph changes to parent in embedded mode
    $effect(() => {
        if (embedded && onGraphChange && !loading) {
            const graphData = serializeGraphData(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);
            onGraphChange(graphData);
        }
    });

    onMount(() => {
        if (!embedded) loadData();

        // Warn user if they try to leave with unsaved changes
        const handleBeforeUnload = (e: BeforeUnloadEvent) => {
            if (hasUnsavedChanges) {
                e.preventDefault();
                e.returnValue = "";
                return "";
            }
        };

        // Keyboard shortcuts for undo/redo
        const handleKeydown = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "z") {
                if (e.shiftKey) {
                    e.preventDefault();
                    handleRedo();
                } else {
                    e.preventDefault();
                    handleUndo();
                }
            } else if ((e.ctrlKey || e.metaKey) && e.key === "y") {
                e.preventDefault();
                handleRedo();
            }
        };

        window.addEventListener("beforeunload", handleBeforeUnload);
        window.addEventListener("keydown", handleKeydown);

        return () => {
            window.removeEventListener("beforeunload", handleBeforeUnload);
            window.removeEventListener("keydown", handleKeydown);
        };
    });
</script>

<div class="flex {embedded ? 'h-full' : 'h-[calc(100vh-57px)]'} font-sans">
    <!-- ============= SIDEBAR ============= -->
    {#if !embedded}
    <ProtocolSidebar
        {protocol}
        {roles}
        {unitOps}
        {approvalRequired}
        {protocolStatus}
        {versionNumber}
        {saving}
        {previewingVersion}
        {isHistoricalPreview}
        {hasUnitOpNodes}
        {canDesignate}
        {canApprove}
        {currentUserId}
        {projectSettingEnabled}
        onApprovalChange={refreshProtocol}
        onNameSaved={(name) => { protocol.name = name; }}
        onDescriptionSaved={(desc) => { protocol.description = desc; }}
        onRoleCreated={handleRoleCreated}
        onRoleDeleted={handleRoleDeleted}
        onOpenCreateModal={openCreateModal}
        onOpenPdfPreview={openPdfPreview}
        onSaveDraft={saveDraft}
        onSaveAndPublish={saveAndPublish}
        onDeleteOrArchive={deleteOrArchiveProtocol}
        onUnarchive={unarchiveProtocol}
        onOpClick={handleOpPreview}
    />
    {/if}

    <PublishVersionDialog
        bind:open={publishDialogOpen}
        versionNumber={versionNumber + 1}
        onConfirm={performPublish}
    />

    <!-- ============= CANVAS ============= -->
    <div
        class="relative flex-1 bg-[hsl(240,4.8%,95.9%)]"
        ondrop={onDrop}
        ondragover={onDragOver}
        bind:this={flowContainer}
        data-tour="protocol-canvas"
    >
        {#if !embedded && protocol?.is_tour_sample}
            <div class="absolute top-3 right-3 z-30">
                <HelpMenu dotVisible={shouldShowDot('protocol')} onTakeTour={openProtocolTourModal} />
            </div>
        {/if}
        <!-- Toolbar -->
        <CanvasToolbar
            {interactionMode}
            {layout}
            {handleOrientation}
            {timeEnabled}
            {versionNumber}
            {previewingVersion}
            {previewLoading}
            {latestDraftVersion}
            {nodes}
            canUndoAction={canUndo(undoRedoState)}
            canRedoAction={canRedo(undoRedoState)}
            onUndo={handleUndo}
            onRedo={handleRedo}
            onInteractionModeChange={(mode) => (interactionMode = mode)}
            onToggleLayout={toggleLayout}
            onHandleOrientationChange={(orientation, updatedNodes) => {
                pushUndoSnapshot();
                handleOrientation = orientation;
                nodes = updatedNodes;
            }}
            onToggleTime={() => {
                pushUndoSnapshot();
                timeEnabled = !timeEnabled;
                if (timeEnabled) {
                    applyTimelineSizing();
                } else {
                    clearTimelineSizing();
                }
            }}
            onToggleVersionHistory={toggleVersionHistory}
            onBrowseVersion={browseVersion}
        />

        <!-- Status banners -->
        <ValidationBanners
            {protocolStatus}
            {previewingVersion}
            {versionNumber}
            {latestDraftVersion}
            branchValidationErrors={branchValidationErrors()}
            processStartValidationErrors={processStartValidationErrors()}
            onUnarchive={unarchiveProtocol}
            onRestorePreviewedVersion={restorePreviewedVersion}
            onExitPreview={exitPreview}
        />

        <!-- Time axis overlay -->
        {#if timeEnabled}
            <TimeAxis
                {layout}
                totalHours={totalHours()}
                {pixelsPerHour}
                viewportTransform={viewport}
            />
        {/if}

        {#if loading}
            <div in:fade={{ duration: blockDuration() }} class="flex flex-col items-center justify-center h-full gap-3 text-slate-400">
                <div class="w-7 h-7 border-3 border-slate-200 border-t-[hsl(173,58%,39%)] rounded-full animate-spin"></div>
                <p>Loading protocol...</p>
            </div>
        {:else}
            <SvelteFlow
                bind:nodes
                bind:edges
                bind:viewport
                {nodeTypes}
                {isValidConnection}
                fitView
                elevateNodesOnSelect={false}
                selectionMode={SelectionMode.Partial}
                selectionOnDrag={interactionMode === "select"}
                panOnDrag={interactionMode === "pan"}
                snapGrid={timeEnabled ? [snapGridPx, snapGridPx] : undefined}
                onnodedragstart={handleNodeDragStart}
                onnodedragstop={handleNodeDragStop}
                onconnectstart={() => { preConnectSnapshot = buildGraphSnapshot(nodes, edges); }}
                onconnect={() => {
                    if (preConnectSnapshot) {
                        undoRedoState = pushSnapshot(undoRedoState, preConnectSnapshot);
                        preConnectSnapshot = null;
                    }
                }}
                onconnectend={() => { preConnectSnapshot = null; }}
                onbeforedelete={async () => { pushUndoSnapshot(); return true; }}
            >
                <Background />
                <Controls />
                <MiniMap />
            </SvelteFlow>
        {/if}
    </div>

    <!-- ============= INSPECTOR / PREVIEW ============= -->
    {#if previewedOp}
        <UnitOpPreview op={previewedOp} onClose={clearPreview} />
    {:else if selectedNode}
        {#if selectedNode.type === "processStart"}
            <ProcessStartInspector
                node={selectedNode}
                onApply={handleProcessStartInspectorApply}
                onClose={() => (selectedNodeId = null)}
            />
        {:else}
            <Inspector
                node={selectedNode}
                allNodes={nodes}
                {orgEquipment}
                {equipmentConflicts}
                onApply={handleInspectorApply}
                onSaveAsNew={handleSaveAsNew}
                onCreateEquipment={handleCreateEquipment}
                onClose={() => (selectedNodeId = null)}
                branchErrors={selectedNodeId ? branchValidationErrors().filter((e) => e.sourceNodeId === selectedNodeId) : []}
            />
        {/if}
    {/if}

    <!-- ============= CREATE MODAL ============= -->
    <CreateUnitOpModal
        open={showCreateModal}
        defaultCategory={createModalCategory}
        projectId={protocol?.project_id}
        onClose={() => (showCreateModal = false)}
        onCreate={handleCreateUnitOp}
    />

    <!-- ============= VERSION HISTORY DRAWER ============= -->
    {#if showVersionHistory}
        <VersionHistoryDrawer
            {versions}
            currentVersion={versionNumber}
            loading={versionsLoading}
            onRevert={revertToVersion}
            onClose={() => (showVersionHistory = false)}
        />
    {/if}

    <!-- ============= PDF PREVIEW DRAWER ============= -->
    {#if showPdfDrawer && protocol}
        <PdfPreviewDrawer
            protocolId={protocol.id}
            protocolName={protocol.name}
            projectId={protocol.project_id}
            mode="protocol"
            graph={{
                nodes: nodes.map((n) => ({
                    id: n.id,
                    type: n.type,
                    position: n.position,
                    parentId: n.parentId,
                    data: n.data,
                })),
                edges: edges.map((e) => ({
                    id: e.id,
                    source: e.source,
                    target: e.target,
                })),
            }}
            onClose={() => (showPdfDrawer = false)}
        />
    {/if}
</div>

<ConfirmDialog
    bind:open={confirmOpen}
    title={confirmTitle}
    message={confirmMessage}
    confirmLabel={confirmLabel}
    {confirmVariant}
    onConfirm={() => { confirmAction(); confirmOpen = false; }}
    onCancel={() => (confirmOpen = false)}
/>

<RevertOnEditConfirmDialog
    bind:open={revertOnEditDialogOpen}
    onConfirm={handleRevertConfirm}
    onCancel={handleRevertCancel}
/>

<!-- PROTOCOL TOUR MODAL -->
<TourModal
    bind:open={protocolTourModalOpen}
    title="Tour: how to construct a protocol"
    description="A 4-step walkthrough of the protocol editor."
    primaryLabel="Take tour"
    secondaryLabel="Dismiss"
    onPrimary={startProtocolTour}
    onSecondary={dismissProtocolTour}
/>

