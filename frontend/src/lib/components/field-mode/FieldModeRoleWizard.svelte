<script lang="ts">
    import BarcodeScanner from '$lib/components/media/BarcodeScanner.svelte';
    import * as Dialog from '$lib/components/ui/dialog';
    import { getUser } from '$lib/auth.svelte';
    import { queueAction, updateExecutionData, recordActivity } from '$lib/field-mode.svelte';
    import { firstError, type FieldErrors } from '$lib/validation';
    import { Button } from '$lib/components/ui/button';

    interface SchemaProperty {
        type?: string;
        title?: string;
        unit?: string;
        enum?: string[];
        default?: any;
        'x-ref-type'?: string;
    }

    interface ParamSchema {
        type?: string;
        properties?: Record<string, SchemaProperty>;
        required?: string[];
    }

    interface Step {
        id: string;
        name: string;
        category?: string;
        description?: string;
        params?: Record<string, any>;
        paramSchema?: ParamSchema;
        duration_min?: number;
    }

    interface StepResult {
        status: 'pending' | 'in_progress' | 'completed' | 'skipped';
        results?: Record<string, any>;
        value?: string;
        notes?: string;
        timestamp?: string;
        completed_by_user_id?: string;
    }

    let {
        steps = [],
        runId,
        executionData = {},
        onDataUpdate,
        onAllStepsComplete,
    }: {
        steps: Step[];
        runId: string;
        executionData: Record<string, any>;
        onDataUpdate?: (data: Record<string, any>) => void;
        onAllStepsComplete?: () => void;
    } = $props();

    let currentStepIdx = $state(0);
    let stepData = $state<Record<string, StepResult>>({});
    let saving = $state(false);
    let saveError = $state<string | null>(null);
    let fieldErrors = $state<FieldErrors>({});

    // Image capture state
    let fileInput: HTMLInputElement | undefined = $state();
    let capturing = $state(false);
    let showTagSelector = $state(false);
    let selectedTags = $state<string[]>([]);
    const selectedTagSet = $derived(new Set(selectedTags));
    let capturedImageCount = $state(0);

    // Barcode scanning state
    let scanningField: { key: string; type?: string } | null = $state(null);

    function handleBarcodeScan(value: string) {
        if (!scanningField) return;
        updateResultField(scanningField.key, value, scanningField.type);
        saveStepData();
        scanningField = null;
    }

    $effect(() => {
        const newStepData: Record<string, StepResult> = {};
        steps.forEach((step) => {
            newStepData[step.id] = executionData[step.id] || { status: 'pending' };
        });
        stepData = newStepData;
    });

    const currentStep = $derived(steps[currentStepIdx]);
    const currentData = $derived(stepData[currentStep?.id] || {});

    const editableFields = $derived(
        currentStep?.paramSchema?.properties
            ? Object.entries(currentStep.paramSchema.properties).filter(
                  ([_, prop]) => !prop['x-ref-type'],
              )
            : [],
    );
    const hasSchema = $derived(editableFields.length > 0);

    const progress = $derived({
        current: currentStepIdx + 1,
        total: steps.length,
        percent: steps.length > 0 ? ((currentStepIdx + 1) / steps.length) * 100 : 0,
    });
    const completed = $derived(
        Object.values(stepData).filter((s) => s.status === 'completed').length,
    );
    const allComplete = $derived(steps.length > 0 && completed === steps.length);

    async function saveStepData() {
        if (!currentStep) return;
        recordActivity();
        saving = true;
        saveError = null;

        try {
            const updatedExecutionData = {
                ...executionData,
                [currentStep.id]: {
                    ...currentData,
                    timestamp: new Date().toISOString(),
                },
            };

            // Save to encrypted IndexedDB
            await updateExecutionData(currentStep.id, {
                ...currentData,
                timestamp: new Date().toISOString(),
            });

            // Also queue manual values for sync
            if (currentData.results && Object.keys(currentData.results).length > 0) {
                await queueAction({
                    action_type: 'manual_values',
                    step_id: currentStep.id,
                    values: currentData.results,
                });
            }

            onDataUpdate?.(updatedExecutionData);
        } catch (e: unknown) {
            saveError = e instanceof Error ? e.message : 'Failed to save step data';
        } finally {
            saving = false;
        }
    }

    function nextStep() {
        recordActivity();
        if (currentStepIdx < steps.length - 1) {
            currentStepIdx++;
            saveError = null;
            fieldErrors = {};
        }
    }

    function prevStep() {
        recordActivity();
        if (currentStepIdx > 0) {
            currentStepIdx--;
            saveError = null;
            fieldErrors = {};
        }
    }

    function toggleStepComplete() {
        if (!currentStep) return;
        recordActivity();

        if (currentData.status === 'completed') {
            currentData.status = 'in_progress';
            currentData.timestamp = new Date().toISOString();
            saveStepData();
            return;
        }

        if (hasSchema) {
            const results = currentData.results || {};
            const errors: FieldErrors = {};
            for (const [key, prop] of editableFields) {
                const val = results[key];
                const label = prop.title || key;
                if (val === undefined || val === null || val === '') {
                    errors[key] = [`${label} is required`];
                } else if (
                    (prop.type === 'number' || prop.type === 'integer') &&
                    typeof val === 'number' &&
                    isNaN(val)
                ) {
                    errors[key] = [`${label} must be a valid number`];
                }
            }
            if (Object.keys(errors).length > 0) {
                fieldErrors = errors;
                return;
            }
        } else {
            if (!currentData.value?.trim()) {
                fieldErrors = { value: ['A value or measurement is required'] };
                return;
            }
        }

        fieldErrors = {};
        currentData.status = 'completed';
        currentData.timestamp = new Date().toISOString();
        const user = getUser();
        if (user?.id) currentData.completed_by_user_id = user.id;
        saveStepData();
    }

    function updateResultField(key: string, raw: string, type?: string) {
        if (!currentStep) return;
        recordActivity();
        if (!currentData.results) currentData.results = {};
        if (type === 'number' || type === 'integer') {
            currentData.results[key] = raw === '' ? undefined : parseFloat(raw);
        } else {
            currentData.results[key] = raw;
        }
        if (fieldErrors[key]) {
            const { [key]: _, ...rest } = fieldErrors;
            fieldErrors = rest;
        }
        if (!currentData.status || currentData.status === 'pending') {
            currentData.status = 'in_progress';
        }
    }

    function updateLegacyValue(value: string) {
        if (!currentStep) return;
        recordActivity();
        currentData.value = value;
        if (value.trim() && fieldErrors.value) {
            const { value: _, ...rest } = fieldErrors;
            fieldErrors = rest;
        }
        if (!currentData.status || currentData.status === 'pending') {
            currentData.status = 'in_progress';
        }
    }

    function updateNotes(notes: string) {
        if (currentStep) {
            recordActivity();
            currentData.notes = notes;
            if (!currentData.status || currentData.status === 'pending') {
                currentData.status = 'in_progress';
            }
        }
    }

    function triggerCapture() {
        recordActivity();
        fileInput?.click();
    }

    async function handleFileCapture(e: Event) {
        const input = e.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file || !currentStep) return;

        capturing = true;
        saveError = null;
        recordActivity();

        try {
            // Read file as base64
            const buffer = await file.arrayBuffer();
            const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));

            // Queue image for sync — store base64 for later upload
            selectedTags = [];
            showTagSelector = true;

            // Store the captured data temporarily
            capturedImageData = base64;
            capturedImageFilename = file.name || 'offline_capture.jpg';
        } catch (e: unknown) {
            saveError = e instanceof Error ? e.message : 'Failed to capture image';
        } finally {
            capturing = false;
            input.value = '';
        }
    }

    let capturedImageData = $state('');
    let capturedImageFilename = $state('');

    function toggleTag(key: string) {
        if (selectedTags.includes(key)) {
            selectedTags = selectedTags.filter((t) => t !== key);
        } else {
            selectedTags = [...selectedTags, key];
        }
    }

    async function saveTagsAndQueue() {
        if (!currentStep || !capturedImageData) return;
        recordActivity();

        try {
            await queueAction({
                action_type: 'image_upload',
                step_id: currentStep.id,
                image_data: capturedImageData,
                image_filename: capturedImageFilename,
                parameter_tags: selectedTags.length > 0 ? selectedTags : undefined,
            });
            capturedImageCount++;
        } catch {
            // Non-critical
        } finally {
            showTagSelector = false;
            capturedImageData = '';
            capturedImageFilename = '';
        }
    }

    function getResultFieldValue(key: string): string {
        const val = currentData.results?.[key];
        if (val === undefined || val === null) return '';
        return String(val);
    }

    function getCategoryColor(category?: string): string {
        switch (category?.toLowerCase()) {
            case 'media prep': return 'bg-blue-50 text-blue-700 border-blue-200';
            case 'cell culture': return 'bg-green-50 text-green-700 border-green-200';
            case 'reaction': return 'bg-purple-50 text-purple-700 border-purple-200';
            case 'analysis': return 'bg-orange-50 text-orange-700 border-orange-200';
            default: return 'bg-slate-50 text-slate-700 border-slate-200';
        }
    }

    function getStatusColor(status?: string): string {
        switch (status) {
            case 'completed': return 'bg-emerald-100 text-emerald-700';
            case 'in_progress': return 'bg-blue-100 text-blue-700';
            case 'skipped': return 'bg-slate-100 text-slate-600';
            default: return 'bg-slate-50 text-slate-600';
        }
    }
</script>

<div class="flex flex-col h-full">
    <!-- Progress Bar -->
    <div class="mb-6">
        <div class="flex justify-between items-center mb-2">
            <span class="text-sm font-semibold text-slate-800">
                Step {progress.current} of {progress.total}
            </span>
            <span class="text-sm text-slate-600">
                {completed} completed
            </span>
        </div>
        <div class="w-full bg-slate-200 rounded-full h-2.5">
            <div
                class="bg-teal-600 h-2.5 rounded-full transition-all duration-300"
                style="width: {progress.percent}%"
            ></div>
        </div>
        <div class="flex gap-1 mt-2 justify-center flex-wrap">
            {#each steps as step, i}
                <Button
                    variant="ghost"
                    rounded="full"
                    onclick={() => { currentStepIdx = i; fieldErrors = {}; recordActivity(); }}
                    class="size-2.5 p-0 shadow-none hover:bg-transparent {i === currentStepIdx
                        ? 'bg-teal-600 scale-125 hover:bg-teal-600'
                        : stepData[step.id]?.status === 'completed'
                            ? 'bg-emerald-400 hover:bg-emerald-400'
                            : 'bg-slate-300 hover:bg-slate-300'}"
                    aria-label="Go to step {i + 1}"
                ></Button>
            {/each}
        </div>
    </div>

    {#if currentStep}
        <div class="flex-1 bg-white rounded-xl border border-slate-200 p-5 sm:p-8 mb-6 flex flex-col shadow-sm">
            <!-- Step Header -->
            <div class="mb-6">
                <div class="flex items-start justify-between gap-3 mb-3">
                    <div class="flex-1">
                        <h2 class="text-xl sm:text-2xl font-bold text-slate-900">
                            {currentStep.name}
                        </h2>
                        {#if currentStep.category}
                            <div class="mt-2">
                                <span class="inline-block text-xs font-semibold px-2.5 py-1 rounded-lg border {getCategoryColor(currentStep.category)}">
                                    {currentStep.category}
                                </span>
                            </div>
                        {/if}
                    </div>
                    <span class="inline-block text-xs font-semibold px-3 py-1.5 rounded-lg shrink-0 {getStatusColor(currentData.status)}">
                        {currentData.status?.replace(/_/g, ' ').toUpperCase() || 'PENDING'}
                    </span>
                </div>

                {#if currentStep.description}
                    <p class="text-slate-600 text-sm leading-relaxed">{currentStep.description}</p>
                {/if}
                {#if currentStep.duration_min}
                    <p class="text-slate-500 text-xs mt-2">Est. {currentStep.duration_min} min</p>
                {/if}
            </div>

            <!-- Form Fields -->
            <div class="flex-1 space-y-5 mb-6">
                {#if hasSchema}
                    {#each editableFields as [key, prop]}
                        {@const expected = currentStep.params?.[key]}
                        <div>
                            <label for="result-{key}" class="block text-sm font-medium text-slate-700 mb-1">
                                {prop.title || key}
                                <span class="text-red-400">*</span>
                            </label>
                            {#if expected !== undefined && expected !== null && expected !== ''}
                                <p class="text-xs text-slate-400 mb-1.5">
                                    Expected: <span class="font-mono font-medium text-slate-500">{expected}</span>
                                </p>
                            {/if}
                            {#if prop.enum}
                                <select
                                    id="result-{key}"
                                    value={getResultFieldValue(key)}
                                    onchange={(e) => updateResultField(key, e.currentTarget.value, prop.type)}
                                    onblur={saveStepData}
                                    class="w-full px-3 py-3 border rounded-xl text-base focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent {firstError(fieldErrors, key) ? 'border-red-400' : 'border-slate-300'}"
                                >
                                    <option value="">Select...</option>
                                    {#each prop.enum as option}
                                        <option value={option}>{option}</option>
                                    {/each}
                                </select>
                            {:else}
                                <div class="flex items-center gap-2">
                                    <input
                                        id="result-{key}"
                                        type={prop.type === 'number' || prop.type === 'integer' ? 'number' : 'text'}
                                        step={prop.type === 'integer' ? '1' : 'any'}
                                        value={getResultFieldValue(key)}
                                        onchange={(e) => updateResultField(key, e.currentTarget.value, prop.type)}
                                        onblur={saveStepData}
                                        placeholder={expected !== undefined ? `Expected: ${expected}` : `Enter ${(prop.title || key).toLowerCase()}`}
                                        class="flex-1 px-3 py-3 border rounded-xl text-base focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent {firstError(fieldErrors, key) ? 'border-red-400' : 'border-slate-300'}"
                                    />
                                    <Button
                                        variant="outline"
                                        size="icon"
                                        title="Scan barcode"
                                        aria-label="Scan barcode"
                                        onclick={() => (scanningField = { key, type: prop.type })}
                                        class="size-11 rounded-xl text-slate-500 hover:text-teal-700 hover:border-teal-400 hover:bg-teal-50"
                                    >
                                        <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                                            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 013.75 9.375v-4.5zM3.75 14.625c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5a1.125 1.125 0 01-1.125-1.125v-4.5zM13.5 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 0113.5 9.375v-4.5z" />
                                            <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 6.75h.75v.75h-.75v-.75zM6.75 16.5h.75v.75h-.75v-.75zM16.5 6.75h.75v.75H16.5v-.75zM13.5 13.5h.75v.75h-.75v-.75zM13.5 19.5h.75v.75h-.75v-.75zM19.5 13.5h.75v.75h-.75v-.75zM19.5 19.5h.75v.75h-.75v-.75zM16.5 16.5h.75v.75H16.5v-.75z" />
                                        </svg>
                                    </Button>
                                </div>
                            {/if}
                            {#if firstError(fieldErrors, key)}
                                <p class="mt-1 text-xs text-red-600">{firstError(fieldErrors, key)}</p>
                            {/if}
                        </div>
                    {/each}
                {:else}
                    <div>
                        <label for="step-value-input" class="block text-sm font-medium text-slate-700 mb-1">
                            Value / Measurement <span class="text-red-400">*</span>
                        </label>
                        <input
                            id="step-value-input"
                            type="text"
                            value={currentData.value || ''}
                            onchange={(e) => updateLegacyValue(e.currentTarget.value)}
                            onblur={saveStepData}
                            placeholder="Enter result or measurement"
                            class="w-full px-3 py-3 border rounded-xl text-base focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent {firstError(fieldErrors, 'value') ? 'border-red-400' : 'border-slate-300'}"
                        />
                        {#if firstError(fieldErrors, 'value')}
                            <p class="mt-1 text-xs text-red-600">{firstError(fieldErrors, 'value')}</p>
                        {/if}
                    </div>
                {/if}

                <!-- Notes -->
                <div>
                    <label for="step-notes-input" class="block text-sm font-medium text-slate-700 mb-1">
                        Notes
                    </label>
                    <textarea
                        id="step-notes-input"
                        value={currentData.notes || ''}
                        onchange={(e) => updateNotes(e.currentTarget.value)}
                        onblur={saveStepData}
                        placeholder="Notes or observations"
                        rows="3"
                        class="w-full px-3 py-3 border border-slate-300 rounded-xl text-base focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                    ></textarea>
                </div>

                <!-- Image Capture (offline) -->
                <div class="pt-1">
                    <p class="text-xs text-slate-500 mb-2 font-medium">Capture data</p>
                    <div class="flex gap-2">
                        <Button
                            variant="outline"
                            onclick={triggerCapture}
                            disabled={capturing}
                            class="h-auto gap-2 px-4 py-2.5 rounded-xl text-sm text-teal-700 border-teal-300 bg-teal-50 hover:bg-teal-100 hover:text-teal-700"
                        >
                            {#if capturing}
                                <span class="animate-spin">...</span>
                                <span>Capturing...</span>
                            {:else}
                                <span>📷</span>
                                <span>Take Photo</span>
                            {/if}
                        </Button>
                        {#if capturedImageCount > 0}
                            <span class="flex items-center text-xs text-slate-500 px-2">
                                {capturedImageCount} image{capturedImageCount !== 1 ? 's' : ''} queued
                            </span>
                        {/if}
                    </div>
                    <input
                        bind:this={fileInput}
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        capture="environment"
                        onchange={handleFileCapture}
                        class="hidden"
                    />
                </div>
            </div>

            {#if saveError}
                <div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
                    {saveError}
                </div>
            {/if}

            <!-- Complete Button -->
            <Button
                variant={currentData.status === 'completed' ? 'secondary' : 'default'}
                onclick={toggleStepComplete}
                disabled={saving}
                class="w-full h-auto py-3.5 rounded-xl font-semibold text-base {currentData.status === 'completed'
                    ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200 ring-2 ring-emerald-300'
                    : 'bg-teal-600 text-white hover:bg-teal-700 active:bg-teal-800'}"
            >
                {#if saving}
                    Saving...
                {:else if currentData.status === 'completed'}
                    Step Completed
                {:else}
                    Mark Step Complete
                {/if}
            </Button>
        </div>
    {/if}

    <!-- Navigation -->
    <div class="flex justify-between items-center gap-3">
        <Button
            variant="secondary"
            onclick={prevStep}
            disabled={currentStepIdx === 0}
            class="flex-1 h-auto py-3.5 rounded-xl font-semibold text-base bg-slate-100 text-slate-700 hover:bg-slate-200"
        >
            Previous
        </Button>
        <div class="text-sm font-medium text-slate-500 shrink-0 px-1">
            {progress.current}/{progress.total}
        </div>
        <Button
            variant="default"
            onclick={nextStep}
            disabled={currentStepIdx === steps.length - 1}
            class="flex-1 h-auto py-3.5 rounded-xl font-semibold text-base bg-teal-600 text-white hover:bg-teal-700"
        >
            Next
        </Button>
    </div>

    {#if allComplete}
        <div class="mt-6 p-5 bg-emerald-50 border border-emerald-200 rounded-xl text-center">
            <p class="text-base font-semibold text-emerald-800 mb-1">All {steps.length} steps completed</p>
            <p class="text-xs text-emerald-600 mb-3">
                Your data will sync automatically when you reconnect.
            </p>
            {#if onAllStepsComplete}
                <Button
                    variant="default"
                    onclick={onAllStepsComplete}
                    class="h-auto px-6 py-2.5 rounded-xl font-semibold bg-emerald-600 text-white hover:bg-emerald-700"
                >
                    Finish
                </Button>
            {/if}
        </div>
    {/if}

    <!-- Parameter Tag Selector (after capture) -->
    {#if currentStep}
        <Dialog.Root bind:open={showTagSelector}>
            <Dialog.Content
                class="w-[95%] max-w-md max-h-[90vh] p-0 flex flex-col overflow-hidden"
            >
                <div class="flex items-center justify-between px-5 py-3 border-b border-slate-200">
                    <div>
                        <Dialog.Title class="text-base font-semibold text-slate-900">Tag Image Parameters</Dialog.Title>
                        <Dialog.Description class="text-xs text-slate-500">Which parameters does this image capture?</Dialog.Description>
                    </div>
                </div>
                <div class="px-5 py-3 overflow-y-auto">
                    {#if editableFields.length > 0}
                        <div class="space-y-2">
                            {#each editableFields as [key, prop] (key)}
                                {@const isSelected = selectedTagSet.has(key)}
                                <Button
                                    variant="outline"
                                    onclick={() => toggleTag(key)}
                                    class="w-full h-auto justify-start gap-3 px-3 py-2.5 rounded-lg border-2 text-left {isSelected ? 'border-emerald-500 bg-emerald-50 ring-2 ring-emerald-200 text-emerald-900 hover:bg-emerald-50 hover:text-emerald-900' : 'border-slate-200 hover:border-slate-300 text-slate-700'}"
                                >
                                    <span class="flex-shrink-0 w-5 h-5 rounded border-2 flex items-center justify-center transition-colors {isSelected ? 'border-emerald-500 bg-emerald-500' : 'border-slate-300 bg-white'}">
                                        {#if isSelected}
                                            <svg class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                                                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                                            </svg>
                                        {/if}
                                    </span>
                                    <span class="text-sm font-medium">{prop.title || key}</span>
                                    {#if prop.unit}
                                        <span class="text-slate-400 text-xs">({prop.unit})</span>
                                    {/if}
                                </Button>
                            {/each}
                        </div>
                    {:else}
                        <p class="text-xs text-slate-400">No parameters defined.</p>
                    {/if}
                </div>
                <div class="px-5 py-3 border-t border-slate-200">
                    <Button
                        variant="default"
                        onclick={saveTagsAndQueue}
                        disabled={editableFields.length > 0 && selectedTagSet.size === 0}
                        class="w-full h-auto py-2.5 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700"
                    >
                        Queue Image {selectedTagSet.size > 0 ? `(${selectedTagSet.size} tags)` : ''}
                    </Button>
                </div>
            </Dialog.Content>
        </Dialog.Root>
    {/if}

    <!-- Barcode Scanner -->
    <BarcodeScanner
        open={scanningField !== null}
        onScan={handleBarcodeScan}
        onClose={() => (scanningField = null)}
    />
</div>
