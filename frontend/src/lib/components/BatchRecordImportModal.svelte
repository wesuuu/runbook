<script lang="ts">
    import { api } from '$lib/api';
    import { toast } from 'svelte-sonner';
    import FullScreenModal from '$lib/components/ui/FullScreenModal.svelte';
    import ConfidenceBadge from '$lib/components/ConfidenceBadge.svelte';
    import { Button } from '$lib/components/ui/button';
    import ConfirmDialog from '$lib/components/ui/confirm-dialog.svelte';
    import {
        BatchRecordImportResponseSchema,
        BatchRecordFinalizeResponseSchema,
        type BatchRecordImportResponse,
        type ExtractedStep,
        type ExtractedParameterValue,
        type StepMapping,
        type ParamMapping,
        type ValueAssignment,
    } from '$lib/schemas/batchRecordImport';

    interface ProtocolStep {
        id: string;
        name: string;
        paramSchema: Record<string, any>;
    }

    interface Props {
        open: boolean;
        projectId: string;
        protocols: any[];
        onSuccess?: (runId: string) => void;
    }

    let { open = $bindable(false), projectId, protocols, onSuccess }: Props = $props();

    // ── Wizard state ────────────────────────────────────────────────
    let wizardStep = $state<'upload' | 'processing' | 'review'>('upload');
    let selectedFile = $state<File | null>(null);
    let selectedProtocolId = $state('');
    let importResult = $state<BatchRecordImportResponse | null>(null);
    let runName = $state('');
    let error = $state<string | null>(null);
    let uploading = $state(false);
    let finalizing = $state(false);
    let dragOver = $state(false);
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    // ── Review state ────────────────────────────────────────────────
    let paramAssignments = $state<Map<string, ValueAssignment>>(new Map());
    let naSteps = $state<Map<string, string>>(new Map());
    let expandedSteps = $state<Set<string>>(new Set());

    // ── Derived ─────────────────────────────────────────────────────

    const nonArchivedProtocols = $derived(
        protocols.filter((p: any) => p.status?.toUpperCase() !== 'ARCHIVED')
    );

    const protocolSteps = $derived.by<ProtocolStep[]>(() => {
        if (!importResult?.extraction) return [];
        const proto = protocols.find((p: any) => p.id === (importResult?.protocol_id ?? selectedProtocolId));
        if (!proto?.graph?.nodes) return [];
        return proto.graph.nodes
            .filter((n: any) => n.type === 'unitOp')
            .sort((a: any, b: any) => (a.position?.x ?? 0) - (b.position?.x ?? 0))
            .map((n: any) => ({
                id: n.id,
                name: n.data?.label ?? 'Unnamed',
                paramSchema: n.data?.paramSchema ?? {},
            }));
    });

    const stepParamsGrouped = $derived.by(() => {
        const grouped = new Map<string, ValueAssignment[]>();
        for (const [, assignment] of paramAssignments) {
            if (assignment.rejected || !assignment.protocolStepId) continue;
            const list = grouped.get(assignment.protocolStepId) || [];
            list.push(assignment);
            grouped.set(assignment.protocolStepId, list);
        }
        return grouped;
    });

    const unassignedParams = $derived.by(() =>
        [...paramAssignments.values()].filter(a => !a.protocolStepId && !a.rejected)
    );

    const unreviewedLowConfidence = $derived.by(() =>
        [...paramAssignments.values()].filter(
            a => a.confidence < 0.7 && !a.accepted && !a.edited && !a.rejected
        ).length
    );

    const emptySteps = $derived.by(() =>
        protocolSteps.filter((s: ProtocolStep) => !stepParamsGrouped.has(s.id) && !naSteps.has(s.id))
    );

    const canFinalize = $derived(
        runName.trim().length > 0 &&
        unreviewedLowConfidence === 0 &&
        emptySteps.length === 0 &&
        !finalizing
    );

    const summaryText = $derived.by(() => {
        const accepted = [...paramAssignments.values()].filter(a => a.accepted && !a.rejected).length;
        const edited = [...paramAssignments.values()].filter(a => a.edited).length;
        const rejected = [...paramAssignments.values()].filter(a => a.rejected).length;
        const na = naSteps.size;
        const parts: string[] = [];
        if (accepted) parts.push(`${accepted} accepted`);
        if (edited) parts.push(`${edited} edited`);
        if (rejected) parts.push(`${rejected} rejected`);
        if (na) parts.push(`${na} N/A`);
        return parts.join(', ') || 'No values reviewed';
    });

    // ── Upload step ─────────────────────────────────────────────────

    const allowedTypes = new Set([
        'application/pdf', 'image/jpeg', 'image/png', 'image/tiff', 'image/heic',
    ]);
    const maxSize = 50 * 1024 * 1024;

    function handleFileSelect(file: File) {
        if (!allowedTypes.has(file.type)) {
            error = `Unsupported file type: ${file.type}. Use PDF, JPEG, PNG, TIFF, or HEIC.`;
            return;
        }
        if (file.size > maxSize) {
            error = `File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum is 50 MB.`;
            return;
        }
        error = null;
        selectedFile = file;
    }

    function handleDrop(e: DragEvent) {
        e.preventDefault();
        dragOver = false;
        const file = e.dataTransfer?.files?.[0];
        if (file) handleFileSelect(file);
    }

    function handleFileInput(e: Event) {
        const input = e.target as HTMLInputElement;
        const file = input.files?.[0];
        if (file) handleFileSelect(file);
        // Don't reset input.value — it causes spurious change events
        // that can interfere with other UI interactions
    }

    async function startImport() {
        if (!selectedFile || !selectedProtocolId) return;
        error = null;
        uploading = true;
        wizardStep = 'processing';

        try {
            const result = await api.uploadWithFields<BatchRecordImportResponse>(
                '/science/batch-record-imports',
                selectedFile,
                { project_id: projectId, protocol_id: selectedProtocolId },
            );
            importResult = result;
            startPolling();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Upload failed';
            wizardStep = 'upload';
        } finally {
            uploading = false;
        }
    }

    // ── Processing step (polling) ───────────────────────────────────

    function startPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(pollImportStatus, 2000);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    async function pollImportStatus() {
        if (!importResult) return;
        try {
            const result = await api.get<BatchRecordImportResponse>(
                `/science/batch-record-imports/${importResult.import_id}`,
            );
            importResult = result;

            if (result.status === 'REVIEW') {
                stopPolling();
                initializeReviewState(result);
                wizardStep = 'review';
            } else if (result.status === 'FAILED') {
                stopPolling();
                error = result.error_message || 'Extraction failed';
            }
        } catch {
            stopPolling();
            error = 'Failed to check import status';
        }
    }

    // ── Review step initialization ──────────────────────────────────

    function initializeReviewState(result: BatchRecordImportResponse) {
        paramAssignments = new Map();
        naSteps = new Map();
        expandedSteps = new Set();

        if (!result.extraction || !result.step_mappings) return;

        // Build assignments from LLM mappings
        for (const mapping of result.step_mappings) {
            const extractedStep = result.extraction.steps[mapping.extracted_step_index];
            if (!extractedStep) continue;

            for (const pm of mapping.param_mappings) {
                const extractedParam = extractedStep.parameters[pm.extracted_param_index];
                if (!extractedParam) continue;

                const key = `${mapping.extracted_step_index}-${pm.extracted_param_index}`;
                paramAssignments.set(key, {
                    paramKey: key,
                    protocolStepId: mapping.protocol_step_id,
                    schemaFieldKey: pm.schema_field_key,
                    value: extractedParam.value,
                    originalValue: extractedParam.value,
                    extractedLabel: extractedParam.field_label,
                    extractedUnit: extractedParam.unit,
                    confidence: extractedParam.confidence,
                    accepted: extractedParam.confidence >= 0.7,
                    edited: false,
                    rejected: false,
                });
            }

            // Add unmapped params from this extracted step
            const mappedIndices = new Set(mapping.param_mappings.map(pm => pm.extracted_param_index));
            for (let pi = 0; pi < extractedStep.parameters.length; pi++) {
                if (mappedIndices.has(pi)) continue;
                const param = extractedStep.parameters[pi];
                const key = `${mapping.extracted_step_index}-${pi}`;
                paramAssignments.set(key, {
                    paramKey: key,
                    protocolStepId: '',
                    schemaFieldKey: '',
                    value: param.value,
                    originalValue: param.value,
                    extractedLabel: param.field_label,
                    extractedUnit: param.unit,
                    confidence: param.confidence,
                    accepted: false,
                    edited: false,
                    rejected: false,
                });
            }
        }

        // Add params from unmapped extracted steps
        const mappedStepIndices = new Set(result.step_mappings.map(m => m.extracted_step_index));
        for (let si = 0; si < result.extraction.steps.length; si++) {
            if (mappedStepIndices.has(si)) continue;
            const step = result.extraction.steps[si];
            for (let pi = 0; pi < step.parameters.length; pi++) {
                const param = step.parameters[pi];
                const key = `${si}-${pi}`;
                paramAssignments.set(key, {
                    paramKey: key,
                    protocolStepId: '',
                    schemaFieldKey: '',
                    value: param.value,
                    originalValue: param.value,
                    extractedLabel: param.field_label,
                    extractedUnit: param.unit,
                    confidence: param.confidence,
                    accepted: false,
                    edited: false,
                    rejected: false,
                });
            }
        }

        // Expand steps with low-confidence or unmatched data
        for (const step of protocolSteps) {
            const params = stepParamsGrouped.get(step.id);
            if (!params || params.some(p => p.confidence < 0.7)) {
                expandedSteps.add(step.id);
            }
        }

        // Auto-suggest run name
        if (result.extraction.batch_id) {
            runName = `Import — ${result.extraction.batch_id}`;
        } else if (result.extraction.document_title) {
            runName = `Import — ${result.extraction.document_title}`;
        } else {
            runName = `Import — ${result.original_filename}`;
        }
    }

    // ── Review actions ──────────────────────────────────────────────

    function acceptParam(key: string) {
        const a = paramAssignments.get(key);
        if (a) {
            a.accepted = true;
            a.rejected = false;
            paramAssignments = new Map(paramAssignments);
        }
    }

    function rejectParam(key: string) {
        const a = paramAssignments.get(key);
        if (a) {
            a.rejected = true;
            a.accepted = false;
            paramAssignments = new Map(paramAssignments);
        }
    }

    function editParam(key: string, newValue: unknown) {
        const a = paramAssignments.get(key);
        if (a) {
            a.value = newValue;
            a.edited = true;
            a.accepted = true;
            a.rejected = false;
            paramAssignments = new Map(paramAssignments);
        }
    }

    function moveParam(key: string, targetStepId: string, targetFieldKey: string) {
        const a = paramAssignments.get(key);
        if (a) {
            a.protocolStepId = targetStepId;
            a.schemaFieldKey = targetFieldKey;
            a.accepted = true;
            a.rejected = false;
            paramAssignments = new Map(paramAssignments);
        }
    }

    function markStepNA(stepId: string, reason: string) {
        naSteps.set(stepId, reason);
        naSteps = new Map(naSteps);
    }

    function unmarkStepNA(stepId: string) {
        naSteps.delete(stepId);
        naSteps = new Map(naSteps);
    }

    function toggleStep(stepId: string) {
        if (expandedSteps.has(stepId)) {
            expandedSteps.delete(stepId);
        } else {
            expandedSteps.add(stepId);
        }
        expandedSteps = new Set(expandedSteps);
    }

    function getStepFields(stepId: string): { key: string; label: string }[] {
        const step = protocolSteps.find(s => s.id === stepId);
        if (!step?.paramSchema?.properties) return [];
        return Object.entries(step.paramSchema.properties).map(([k, v]: [string, any]) => ({
            key: k,
            label: v.title || k,
        }));
    }

    function getAssignedFieldKey(stepId: string, fieldKey: string): ValueAssignment | undefined {
        for (const [, a] of paramAssignments) {
            if (a.protocolStepId === stepId && a.schemaFieldKey === fieldKey && !a.rejected) {
                return a;
            }
        }
        return undefined;
    }

    // ── Finalize ────────────────────────────────────────────────────

    async function handleFinalize() {
        if (!importResult || !canFinalize) return;
        finalizing = true;

        try {
            const stepMappings = protocolSteps.map(step => {
                if (naSteps.has(step.id)) {
                    return {
                        protocol_step_id: step.id,
                        na: true,
                        na_reason: naSteps.get(step.id) || '',
                        values: [],
                    };
                }

                const params = stepParamsGrouped.get(step.id) || [];
                return {
                    protocol_step_id: step.id,
                    values: params.map(p => ({
                        schema_field_key: p.schemaFieldKey,
                        value: p.value,
                        accepted: p.accepted,
                        edited: p.edited,
                        original_value: p.originalValue,
                        original_confidence: p.confidence,
                    })),
                    notes: params
                        .filter(p => p.schemaFieldKey === '__notes__')
                        .map(p => `${p.extractedLabel}: ${p.value}`)
                        .join('; '),
                };
            });

            const result = await api.post<{ run_id: string; run_name: string }>(
                `/science/batch-record-imports/${importResult.import_id}/finalize`,
                {
                    protocol_id: importResult.protocol_id,
                    run_name: runName.trim(),
                    step_mappings: stepMappings,
                },
            );

            toast.success(`Run "${result.run_name}" created from batch record import`);
            open = false;
            resetState();
            onSuccess?.(result.run_id);
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to create run';
        } finally {
            finalizing = false;
        }
    }

    // ── Lifecycle ───────────────────────────────────────────────────

    function resetState() {
        wizardStep = 'upload';
        selectedFile = null;
        selectedProtocolId = '';
        importResult = null;
        runName = '';
        error = null;
        uploading = false;
        finalizing = false;
        dragOver = false;
        paramAssignments = new Map();
        naSteps = new Map();
        expandedSteps = new Set();
        stopPolling();
    }

    let discardConfirmOpen = $state(false);

    function handleClose() {
        if (wizardStep !== 'upload' && (importResult || uploading)) {
            discardConfirmOpen = true;
            return;
        }
        resetState();
        open = false;
    }

    function confirmDiscardImport() {
        discardConfirmOpen = false;
        resetState();
        open = false;
    }

    $effect(() => {
        return () => stopPolling();
    });
</script>

<FullScreenModal bind:open title="Import Batch Record" onClose={handleClose}>

    <!-- Step 1: Upload -->
    {#if wizardStep === 'upload'}
        <div class="h-full flex items-center justify-center p-8">
            <div class="max-w-lg w-full space-y-6">
                <div class="text-center mb-6">
                    <h2 class="text-xl font-semibold mb-2">Import a Paper Batch Record</h2>
                    <p class="text-sm text-muted-foreground">Upload a scanned PDF or photo of a completed batch record. AI will extract the recorded values and map them to a protocol.</p>
                </div>

                {#if error}
                    <div class="bg-destructive/10 text-destructive text-sm p-3 rounded-md">{error}</div>
                {/if}

                <!-- File drop zone -->
                <div
                    class="border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors {dragOver ? 'border-primary bg-primary/5' : 'border-muted-foreground/25 hover:border-primary/50'}"
                    role="button"
                    tabindex="0"
                    ondragover={(e) => { e.preventDefault(); dragOver = true; }}
                    ondragleave={() => { dragOver = false; }}
                    ondrop={handleDrop}
                    onclick={() => document.getElementById('batch-file-input')?.click()}
                    onkeydown={(e) => { if (e.key === 'Enter') document.getElementById('batch-file-input')?.click(); }}
                >
                    {#if selectedFile}
                        <div class="space-y-1">
                            <p class="text-sm font-medium">{selectedFile.name}</p>
                            <p class="text-xs text-muted-foreground">{(selectedFile.size / 1024 / 1024).toFixed(1)} MB</p>
                            <Button variant="link" size="sm" class="h-auto p-0 text-xs" onclick={(e: MouseEvent) => { e.stopPropagation(); selectedFile = null; }}>
                                Remove
                            </Button>
                        </div>
                    {:else}
                        <div class="space-y-2">
                            <svg class="w-10 h-10 mx-auto text-muted-foreground/50" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                                <path d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m6.75 12l-3-3m0 0l-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                            </svg>
                            <p class="text-sm text-muted-foreground">Drop a file here or click to browse</p>
                            <p class="text-xs text-muted-foreground">PDF, JPEG, PNG, TIFF, HEIC (max 50 MB)</p>
                        </div>
                    {/if}
                    <input id="batch-file-input" type="file" accept=".pdf,.jpg,.jpeg,.png,.tiff,.tif,.heic" class="hidden" onchange={handleFileInput} />
                </div>

                <!-- Protocol selector -->
                <div>
                    <label for="import-protocol-select" class="block text-sm font-medium text-foreground mb-1">
                        Protocol
                    </label>
                    <select
                        id="import-protocol-select"
                        bind:value={selectedProtocolId}
                        class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-background"
                    >
                        <option value="">Select a protocol to map against</option>
                        {#each nonArchivedProtocols as proto}
                            <option value={proto.id}>{proto.name}</option>
                        {/each}
                    </select>
                    {#if nonArchivedProtocols.length === 0}
                        <p class="text-xs text-muted-foreground mt-1">No protocols in this project. Create one first.</p>
                    {/if}
                </div>

                <!-- Start button -->
                <Button
                    class="w-full"
                    disabled={!selectedFile || !selectedProtocolId || uploading}
                    onclick={startImport}
                >
                    {uploading ? 'Uploading...' : 'Start Import'}
                </Button>
            </div>
        </div>

    <!-- Step 2: Processing -->
    {:else if wizardStep === 'processing'}
        <div class="h-full flex items-center justify-center p-8">
            <div class="text-center space-y-4 max-w-md">
                {#if error}
                    <div class="space-y-4">
                        <svg class="w-12 h-12 mx-auto text-destructive" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                            <path d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                        </svg>
                        <p class="text-sm font-medium text-destructive">{error}</p>
                        <Button
                            variant="secondary"
                            onclick={() => { error = null; wizardStep = 'upload'; }}
                        >
                            Try Again
                        </Button>
                    </div>
                {:else}
                    <!-- Spinner -->
                    <div class="w-12 h-12 mx-auto border-4 border-muted border-t-primary rounded-full animate-spin"></div>
                    <p class="text-sm font-medium">Analyzing batch record...</p>
                    {#if importResult?.progress}
                        <p class="text-xs text-muted-foreground">{importResult.progress.stage_label}</p>
                        {#if importResult.progress.total > 0}
                            <div class="w-full bg-muted rounded-full h-2">
                                <div class="bg-primary h-2 rounded-full transition-all" style="width: {importResult.progress.percent}%"></div>
                            </div>
                            <p class="text-xs text-muted-foreground">{importResult.progress.current} / {importResult.progress.total}</p>
                        {/if}
                    {:else}
                        <p class="text-xs text-muted-foreground">This may take a minute for multi-page documents...</p>
                    {/if}
                {/if}
            </div>
        </div>

    <!-- Step 3: Review & Resolve -->
    {:else if wizardStep === 'review'}
        <div class="h-full flex flex-col">
            <!-- Scrollable content -->
            <div class="flex-1 overflow-y-auto p-6 space-y-4">
                {#if error}
                    <div class="bg-destructive/10 text-destructive text-sm p-3 rounded-md">{error}</div>
                {/if}

                <!-- Extraction summary -->
                {#if importResult?.extraction}
                    <div class="text-sm text-muted-foreground">
                        {#if importResult.extraction.document_title}
                            <span class="font-medium text-foreground">{importResult.extraction.document_title}</span> —
                        {/if}
                        {importResult.extraction.steps.length} steps extracted,
                        overall confidence {Math.round(importResult.extraction.overall_confidence * 100)}%
                        {#if importResult.page_count}
                            ({importResult.page_count} pages)
                        {/if}
                    </div>
                {/if}

                <!-- Protocol steps accordion -->
                {#each protocolSteps as step}
                    {@const params = stepParamsGrouped.get(step.id) || []}
                    {@const isNA = naSteps.has(step.id)}
                    {@const isExpanded = expandedSteps.has(step.id)}
                    {@const avgConfidence = params.length > 0 ? params.reduce((sum, p) => sum + p.confidence, 0) / params.length : 0}
                    {@const hasLowConfidence = params.some(p => p.confidence < 0.7 && !p.accepted && !p.edited && !p.rejected)}

                    <div class="border rounded-lg {isNA ? 'border-yellow-300 bg-yellow-50/50' : hasLowConfidence ? 'border-amber-300' : params.length > 0 ? 'border-green-200' : 'border-red-200'}">
                        <!-- Step header -->
                        <Button
                            variant="ghost"
                            class="w-full justify-between px-4 py-3 h-auto rounded-none font-normal hover:bg-muted/30"
                            onclick={() => toggleStep(step.id)}
                        >
                            <div class="flex items-center gap-3">
                                <svg class="w-4 h-4 text-muted-foreground transition-transform {isExpanded ? 'rotate-90' : ''}" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                    <path d="M9 5l7 7-7 7" />
                                </svg>
                                <span class="font-medium text-sm">{step.name}</span>
                            </div>
                            <div class="flex items-center gap-2 text-xs text-muted-foreground">
                                {#if isNA}
                                    <span class="text-yellow-700 font-medium">N/A</span>
                                {:else if params.length > 0}
                                    <span>{params.length} values</span>
                                    <ConfidenceBadge confidence={avgConfidence} />
                                {:else}
                                    <span class="text-red-600 font-medium">No data</span>
                                {/if}
                            </div>
                        </Button>

                        <!-- Step content (expanded) -->
                        {#if isExpanded}
                            <div class="border-t px-4 py-3 space-y-2">
                                {#if isNA}
                                    <div class="flex items-center gap-2">
                                        <span class="text-sm text-yellow-700">Marked N/A:</span>
                                        <span class="text-sm">{naSteps.get(step.id)}</span>
                                        <Button variant="link" size="sm" class="h-auto p-0 text-xs" onclick={() => unmarkStepNA(step.id)}>
                                            Undo
                                        </Button>
                                    </div>
                                {:else if params.length > 0}
                                    <!-- Parameter rows -->
                                    <table class="w-full text-sm">
                                        <thead>
                                            <tr class="text-xs text-muted-foreground border-b">
                                                <th class="text-left py-1 font-medium">Parameter</th>
                                                <th class="text-left py-1 font-medium">Value</th>
                                                <th class="text-left py-1 font-medium">Conf.</th>
                                                <th class="text-left py-1 font-medium">Field</th>
                                                <th class="text-right py-1 font-medium">Actions</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {#each params as param}
                                                <tr class="border-b last:border-0 {param.rejected ? 'opacity-40 line-through' : ''} {param.confidence < 0.7 && !param.accepted && !param.edited ? 'bg-amber-50' : ''}">
                                                    <td class="py-2 pr-2">
                                                        <span class="text-muted-foreground">{param.extractedLabel}</span>
                                                        {#if param.extractedUnit}
                                                            <span class="text-xs text-muted-foreground/70">({param.extractedUnit})</span>
                                                        {/if}
                                                    </td>
                                                    <td class="py-2 pr-2">
                                                        {#if param.edited}
                                                            <span class="font-medium">{param.value}</span>
                                                            <span class="text-xs text-muted-foreground ml-1">(was: {param.originalValue})</span>
                                                        {:else}
                                                            <span>{param.value}</span>
                                                        {/if}
                                                    </td>
                                                    <td class="py-2 pr-2">
                                                        <ConfidenceBadge confidence={param.confidence} />
                                                    </td>
                                                    <td class="py-2 pr-2 text-xs text-muted-foreground">
                                                        {param.schemaFieldKey}
                                                    </td>
                                                    <td class="py-2 text-right space-x-1">
                                                        {#if !param.accepted && !param.rejected}
                                                            <Button size="sm" class="h-6 px-2 text-xs bg-green-100 text-green-800 hover:bg-green-200 shadow-none" onclick={() => acceptParam(param.paramKey)}>Accept</Button>
                                                        {/if}
                                                        {#if !param.rejected}
                                                            <Button size="sm" class="h-6 px-2 text-xs bg-red-100 text-red-800 hover:bg-red-200 shadow-none" onclick={() => rejectParam(param.paramKey)}>Reject</Button>
                                                        {:else}
                                                            <Button variant="secondary" size="sm" class="h-6 px-2 text-xs" onclick={() => acceptParam(param.paramKey)}>Restore</Button>
                                                        {/if}
                                                        <!-- Move dropdown -->
                                                        <select
                                                            class="text-xs border rounded px-1 py-0.5"
                                                            value=""
                                                            onchange={(e) => {
                                                                const val = (e.target as HTMLSelectElement).value;
                                                                if (val) {
                                                                    const [stepId, fieldKey] = val.split('::');
                                                                    moveParam(param.paramKey, stepId, fieldKey);
                                                                }
                                                            }}
                                                        >
                                                            <option value="">Move to...</option>
                                                            {#each protocolSteps.filter(s => s.id !== step.id) as targetStep}
                                                                <optgroup label={targetStep.name}>
                                                                    {#each getStepFields(targetStep.id) as field}
                                                                        {@const existing = getAssignedFieldKey(targetStep.id, field.key)}
                                                                        <option value="{targetStep.id}::{field.key}">
                                                                            {field.label}{existing ? ` (current: ${existing.value})` : ''}
                                                                        </option>
                                                                    {/each}
                                                                    <option value="{targetStep.id}::__notes__">Add to notes</option>
                                                                </optgroup>
                                                            {/each}
                                                        </select>
                                                    </td>
                                                </tr>
                                            {/each}
                                        </tbody>
                                    </table>
                                {:else}
                                    <!-- No data - offer N/A -->
                                    <div class="space-y-2">
                                        <p class="text-sm text-muted-foreground">No extracted data matched this step.</p>
                                        <div class="flex items-center gap-2">
                                            <input
                                                type="text"
                                                placeholder="Reason (required)"
                                                class="flex-1 px-2 py-1.5 text-sm border rounded-md"
                                                id="na-reason-{step.id}"
                                            />
                                            <Button
                                                size="sm"
                                                class="bg-yellow-100 text-yellow-800 hover:bg-yellow-200 shadow-none"
                                                onclick={() => {
                                                    const input = document.getElementById(`na-reason-${step.id}`) as HTMLInputElement;
                                                    if (input?.value.trim()) {
                                                        markStepNA(step.id, input.value.trim());
                                                    }
                                                }}
                                            >
                                                Mark N/A
                                            </Button>
                                        </div>
                                    </div>
                                {/if}
                            </div>
                        {/if}
                    </div>
                {/each}

                <!-- Unassigned extracted data -->
                {#if unassignedParams.length > 0}
                    <div class="border border-orange-200 rounded-lg">
                        <div class="px-4 py-3 bg-orange-50/50 border-b border-orange-200">
                            <h3 class="text-sm font-medium text-orange-800">
                                Unassigned Extracted Data ({unassignedParams.length} values)
                            </h3>
                            <p class="text-xs text-orange-600 mt-0.5">
                                These values couldn't be matched to any protocol step. Assign them or skip.
                            </p>
                        </div>
                        <div class="px-4 py-3 space-y-2">
                            {#each unassignedParams as param}
                                <div class="flex items-center gap-3 py-1.5 border-b last:border-0">
                                    <span class="text-sm flex-shrink-0">{param.extractedLabel}: <strong>{param.value}</strong> {param.extractedUnit || ''}</span>
                                    <ConfidenceBadge confidence={param.confidence} />
                                    <select
                                        class="text-xs border rounded px-1 py-0.5 flex-1 max-w-xs"
                                        value=""
                                        onchange={(e) => {
                                            const val = (e.target as HTMLSelectElement).value;
                                            if (val === '__skip__') {
                                                rejectParam(param.paramKey);
                                            } else if (val) {
                                                const [stepId, fieldKey] = val.split('::');
                                                moveParam(param.paramKey, stepId, fieldKey);
                                            }
                                        }}
                                    >
                                        <option value="">Assign to...</option>
                                        {#each protocolSteps as targetStep}
                                            <optgroup label={targetStep.name}>
                                                {#each getStepFields(targetStep.id) as field}
                                                    {@const existing = getAssignedFieldKey(targetStep.id, field.key)}
                                                    <option value="{targetStep.id}::{field.key}">
                                                        {field.label}{existing ? ` (current: ${existing.value})` : ''}
                                                    </option>
                                                {/each}
                                                <option value="{targetStep.id}::__notes__">Add to notes</option>
                                            </optgroup>
                                        {/each}
                                        <option value="__skip__">Skip (add to run notes)</option>
                                    </select>
                                </div>
                            {/each}
                        </div>
                    </div>
                {/if}

                <!-- Extracted metadata (collapsed) -->
                {#if importResult?.extraction}
                    {@const ext = importResult.extraction}
                    {@const hasMetadata = ext.steps.some(s => s.timestamps.length > 0 || s.signatures.length > 0 || s.deviations.length > 0)}
                    {#if hasMetadata}
                        <details class="border rounded-lg">
                            <summary class="px-4 py-3 text-sm font-medium text-muted-foreground cursor-pointer hover:text-foreground">
                                Extracted Metadata (timestamps, signatures, deviations)
                            </summary>
                            <div class="px-4 py-3 border-t text-xs text-muted-foreground space-y-2">
                                {#each ext.steps as step}
                                    {#if step.timestamps.length > 0 || step.signatures.length > 0 || step.deviations.length > 0}
                                        <div>
                                            <span class="font-medium text-foreground">{step.step_name}:</span>
                                            {#each step.timestamps as ts}
                                                <span class="ml-2">{ts.label}: {ts.value}</span>
                                            {/each}
                                            {#each step.signatures as sig}
                                                <span class="ml-2">Signed: {sig.initials_or_name}{sig.role ? ` (${sig.role})` : ''}</span>
                                            {/each}
                                            {#each step.deviations as dev}
                                                <span class="ml-2 text-amber-700">Deviation: {dev.description}</span>
                                            {/each}
                                        </div>
                                    {/if}
                                {/each}
                            </div>
                        </details>
                    {/if}
                {/if}
            </div>

            <!-- Footer -->
            <div class="border-t px-6 py-4 shrink-0 flex items-center justify-between gap-4 bg-background">
                <div class="flex-1">
                    <input
                        type="text"
                        bind:value={runName}
                        placeholder="Run name (required)"
                        class="w-full max-w-sm px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                </div>
                <div class="flex items-center gap-4">
                    <span class="text-xs text-muted-foreground">{summaryText}</span>
                    {#if !canFinalize}
                        <span class="text-xs text-amber-600">
                            {#if runName.trim().length === 0}
                                Run name required
                            {:else if unreviewedLowConfidence > 0}
                                {unreviewedLowConfidence} low-confidence values need review
                            {:else if emptySteps.length > 0}
                                {emptySteps.length} steps need values or N/A
                            {/if}
                        </span>
                    {/if}
                    <Button
                        disabled={!canFinalize}
                        onclick={handleFinalize}
                    >
                        {finalizing ? 'Creating...' : 'Create Completed Run'}
                    </Button>
                </div>
            </div>
        </div>
    {/if}

</FullScreenModal>

<ConfirmDialog
    bind:open={discardConfirmOpen}
    title="Discard import?"
    message="You'll lose your import progress. Are you sure?"
    confirmLabel="Discard"
    confirmVariant="danger"
    onConfirm={confirmDiscardImport}
    onCancel={() => (discardConfirmOpen = false)}
/>
