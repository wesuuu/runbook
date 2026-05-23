<script lang="ts">
    import { api } from "$lib/api";
    import { getUser } from "$lib/auth.svelte";
    import {
        firstError,
        type FieldErrors,
    } from "$lib/validation";
    import BarcodeScanner from "$lib/components/media/BarcodeScanner.svelte";
    import * as Dialog from '$lib/components/ui/dialog';
    import ImageAnalysisDialog from "$lib/components/modals/ImageAnalysisDialog.svelte";
    import ImageGallery from "$lib/components/media/ImageGallery.svelte";
    import { Button } from "$lib/components/ui/button";
    import { renderTemplate } from "$lib/utils/template";
    import {
        stepProgressPercent,
        areStepFieldsLocked,
        barcodeScanApplies,
    } from "./roleWizardState";

    interface SchemaProperty {
        type?: string;
        title?: string;
        unit?: string;
        enum?: string[];
        default?: any;
        "x-ref-type"?: string;
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
        status: "pending" | "in_progress" | "completed" | "skipped";
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
        readonly = false,
        draftMode = false,
        onDataUpdate,
        onAllStepsComplete,
    }: {
        steps: Step[];
        runId: string;
        executionData: Record<string, any>;
        readonly?: boolean;
        draftMode?: boolean;
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
    let uploading = $state(false);
    let showAnalysisDialog = $state(false);
    let showTagSelector = $state(false);
    let activeImageId = $state('');
    let activeImagePath = $state('');
    let selectedTags = $state<string[]>([]);
    const selectedTagSet = $derived(new Set(selectedTags));
    let savingTags = $state(false);
    interface StepImage {
        id: string;
        run_id: string;
        step_id: string;
        file_path: string;
        original_filename: string;
        mime_type: string;
        created_at: string;
        parameter_tags?: string[];
        conversation?: { status: string };
    }
    let stepImages = $state<Record<string, StepImage[]>>({});
    let confirmedImageIds = $state<Set<string>>(new Set());
    let imageStatuses = $state<Record<string, string>>({});
    let aiFilledFields = $state<Set<string>>(new Set());

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
            newStepData[step.id] = executionData[step.id] || {
                status: "pending",
            };
        });
        stepData = newStepData;
    });

    const currentStep = $derived(steps[currentStepIdx]);
    const currentData = $derived(stepData[currentStep?.id] || {});

    // Filter out x-ref-type fields (node references, not recordable values)
    const editableFields = $derived(
        currentStep?.paramSchema?.properties
            ? Object.entries(currentStep.paramSchema.properties).filter(
                  ([_, prop]) => !prop["x-ref-type"],
              )
            : [],
    );
    const hasSchema = $derived(editableFields.length > 0);

    const completed = $derived(
        Object.values(stepData).filter((s) => s.status === "completed").length,
    );
    const progress = $derived({
        current: currentStepIdx + 1,
        total: steps.length,
        // Driven by completed steps, not the viewed step index (#24).
        percent: stepProgressPercent(completed, steps.length),
    });
    const allComplete = $derived(
        steps.length > 0 && completed === steps.length,
    );
    // A completed step's recordable fields are locked until it is reopened;
    // observer (read-only) mode locks them too (#23).
    const fieldsLocked = $derived(
        areStepFieldsLocked(readonly, currentData.status),
    );

    async function saveStepData() {
        if (!currentStep) return;

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

            if (draftMode) {
                // In draft mode, only update local state — no API call
                onDataUpdate?.(updatedExecutionData);
            } else {
                await api.put(`/runs/${runId}`, {
                    execution_data: updatedExecutionData,
                });
                onDataUpdate?.(updatedExecutionData);
            }
        } catch (e: unknown) {
            saveError = e instanceof Error ? e.message : "Failed to save step data";
            console.error("Save error:", e instanceof Error ? e.message : e);
        } finally {
            saving = false;
        }
    }

    function nextStep() {
        if (currentStepIdx < steps.length - 1) {
            currentStepIdx++;
            saveError = null;
            fieldErrors = {};
            aiFilledFields = new Set();
        }
    }

    function prevStep() {
        if (currentStepIdx > 0) {
            currentStepIdx--;
            saveError = null;
            fieldErrors = {};
            aiFilledFields = new Set();
        }
    }

    function toggleStepComplete() {
        if (!currentStep) return;

        if (currentData.status === "completed") {
            currentData.status = "in_progress";
            currentData.timestamp = new Date().toISOString();
            saveStepData();
            return;
        }

        if (hasSchema) {
            const results = currentData.results || {};
            const errors: FieldErrors = {};

            // Validate each editable field is filled in
            for (const [key, prop] of editableFields) {
                const val = results[key];
                const label = prop.title || key;

                if (val === undefined || val === null || val === "") {
                    errors[key] = [`${label} is required`];
                } else if (
                    (prop.type === "number" || prop.type === "integer") &&
                    typeof val === "number" &&
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
                fieldErrors = {
                    value: ["A value or measurement is required"],
                };
                return;
            }
        }

        fieldErrors = {};
        currentData.status = "completed";
        currentData.timestamp = new Date().toISOString();
        const user = getUser();
        if (user?.id) {
            currentData.completed_by_user_id = user.id;
        }
        saveStepData();
    }

    function updateResultField(key: string, raw: string, type?: string) {
        if (!currentStep) return;
        if (!currentData.results) currentData.results = {};

        if (type === "number" || type === "integer") {
            currentData.results[key] = raw === "" ? undefined : parseFloat(raw);
        } else {
            currentData.results[key] = raw;
        }

        if (fieldErrors[key]) {
            const { [key]: _, ...rest } = fieldErrors;
            fieldErrors = rest;
        }

        if (!currentData.status || currentData.status === "pending") {
            currentData.status = "in_progress";
        }
    }

    function updateLegacyValue(value: string) {
        if (!currentStep) return;
        currentData.value = value;
        if (value.trim() && fieldErrors.value) {
            const { value: _, ...rest } = fieldErrors;
            fieldErrors = rest;
        }
        if (!currentData.status || currentData.status === "pending") {
            currentData.status = "in_progress";
        }
    }

    function updateNotes(notes: string) {
        if (currentStep) {
            currentData.notes = notes;
            if (!currentData.status || currentData.status === "pending") {
                currentData.status = "in_progress";
            }
        }
    }

    // Load images for the current step
    async function loadStepImages(stepId: string) {
        try {
            const resp = await api.get<{ items: any[] }>(`/ai/runs/${runId}/images`);
            const all = resp.items || [];
            // Group by step_id
            const grouped: Record<string, any[]> = {};
            for (const img of all) {
                if (!grouped[img.step_id]) grouped[img.step_id] = [];
                grouped[img.step_id].push(img);
            }
            stepImages = grouped;

            // Fetch conversation status for each image
            const confirmed = new Set<string>();
            const statuses: Record<string, string> = {};
            for (const img of all) {
                try {
                    const detail = await api.get<{ conversation?: { status: string } }>(
                        `/ai/runs/${runId}/images/${img.id}`
                    );
                    if (detail.conversation) {
                        statuses[img.id] = detail.conversation.status;
                        if (detail.conversation.status === 'confirmed') {
                            confirmed.add(img.id);
                        }
                    } else {
                        statuses[img.id] = 'captured';
                    }
                } catch {
                    statuses[img.id] = 'captured';
                }
            }
            confirmedImageIds = confirmed;
            imageStatuses = statuses;
        } catch {
            // Non-critical — gallery just won't show
        }
    }

    // Load images when step changes
    $effect(() => {
        if (currentStep?.id && runId && !draftMode) {
            loadStepImages(currentStep.id);
        }
    });

    function triggerCapture() {
        fileInput?.click();
    }

    async function handleFileCapture(e: Event) {
        const input = e.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file || !currentStep) return;

        uploading = true;
        saveError = null;
        try {
            const resp = await api.uploadFile<{
                id: string;
                file_path: string;
                step_id: string;
            }>(`/ai/runs/${runId}/steps/${currentStep.id}/images`, file);

            activeImageId = resp.id;
            activeImagePath = resp.file_path;
            selectedTags = [];
            showTagSelector = true;

            // Refresh gallery
            await loadStepImages(currentStep.id);
        } catch (e: unknown) {
            saveError = e instanceof Error ? e.message : 'Failed to upload image';
        } finally {
            uploading = false;
            // Reset input so the same file can be re-selected
            input.value = '';
        }
    }

    function toggleTag(key: string) {
        if (selectedTags.includes(key)) {
            selectedTags = selectedTags.filter(t => t !== key);
        } else {
            selectedTags = [...selectedTags, key];
        }
    }

    async function saveTagsAndClose() {
        if (!activeImageId) return;
        savingTags = true;
        try {
            await api.put(`/ai/runs/${runId}/images/${activeImageId}/tag`, {
                parameter_tags: selectedTags,
            });
        } catch {
            // Non-critical — tags are optional
        } finally {
            savingTags = false;
            showTagSelector = false;
        }
    }


    function handleConfirmValues(values: Record<string, any>) {
        if (!currentStep) return;
        // Populate form fields with confirmed values
        if (!currentData.results) currentData.results = {};
        const newAiFields = new Set(aiFilledFields);
        for (const [key, value] of Object.entries(values)) {
            currentData.results[key] = value;
            newAiFields.add(key);
        }
        aiFilledFields = newAiFields;
        if (!currentData.status || currentData.status === 'pending') {
            currentData.status = 'in_progress';
        }
        // Clear any field errors for confirmed keys
        for (const key of Object.keys(values)) {
            if (fieldErrors[key]) {
                const { [key]: _, ...rest } = fieldErrors;
                fieldErrors = rest;
            }
        }
        // Mark image as confirmed
        if (activeImageId) {
            confirmedImageIds = new Set([...confirmedImageIds, activeImageId]);
        }
        saveStepData();
    }

    function handleGalleryImageClick(image: any) {
        activeImageId = image.id;
        activeImagePath = image.file_path;
        showAnalysisDialog = true;
    }

    function getCategoryColor(category?: string): string {
        switch (category?.toLowerCase()) {
            case "media prep":
                return "bg-blue-50 text-blue-700 border-blue-200";
            case "cell culture":
                return "bg-green-50 text-green-700 border-green-200";
            case "reaction":
                return "bg-purple-50 text-purple-700 border-purple-200";
            case "analysis":
                return "bg-orange-50 text-orange-700 border-orange-200";
            case "general":
            default:
                return "bg-slate-50 text-slate-700 border-slate-200";
        }
    }

    function getStatusColor(status?: string): string {
        switch (status) {
            case "completed":
                return "bg-emerald-100 text-emerald-700";
            case "in_progress":
                return "bg-blue-100 text-blue-700";
            case "skipped":
                return "bg-slate-100 text-slate-600";
            case "pending":
            default:
                return "bg-slate-50 text-slate-600";
        }
    }

    function getResultFieldValue(key: string): string {
        const val = currentData.results?.[key];
        if (val === undefined || val === null) return "";
        return String(val);
    }
</script>

<div class="flex flex-col h-full">
    <!-- Progress Bar -->
    <div class="mb-4 sm:mb-8">
        <div class="flex justify-between items-center mb-3">
            <span class="text-base font-semibold text-slate-800">
                Step {progress.current} of {progress.total}
            </span>
            <span class="text-base text-slate-600">
                {completed} completed
            </span>
        </div>
        <div class="w-full bg-slate-200 rounded-full h-3">
            <div
                class="bg-teal-600 h-3 rounded-full transition-all duration-300"
                style="width: {progress.percent}%"
            ></div>
        </div>
        <!-- Step dots -->
        <div class="flex gap-1.5 mt-3 justify-center flex-wrap">
            {#each steps as step, i}
                <Button
                    variant="ghost"
                    rounded="full"
                    onclick={() => {
                        currentStepIdx = i;
                        saveError = null;
                        fieldErrors = {};
                        aiFilledFields = new Set();
                    }}
                    class="size-3 p-0 shadow-none hover:bg-transparent {i === currentStepIdx
                        ? 'bg-teal-600 scale-125 hover:bg-teal-600'
                        : stepData[step.id]?.status === 'completed'
                            ? 'bg-emerald-400 hover:bg-emerald-400'
                            : 'bg-slate-300 hover:bg-slate-300'}"
                    aria-label="Go to step {i + 1}"
                ></Button>
            {/each}
        </div>
    </div>

    <!-- Step Card -->
    {#if currentStep}
        <div
            class="flex-1 bg-white rounded-xl border border-slate-200 p-3 sm:p-6 md:p-10 mb-8 flex flex-col shadow-sm"
        >
            <!-- Step Header -->
            <div class="mb-8">
                <div class="flex items-start justify-between gap-4 mb-4">
                    <div class="flex-1">
                        <h2 class="text-2xl sm:text-3xl font-bold text-slate-900">
                            {currentStep.name}
                        </h2>
                        {#if currentStep.category}
                            <div class="mt-3">
                                <span
                                    class="inline-block text-sm font-semibold px-3 py-1.5 rounded-lg border {getCategoryColor(
                                        currentStep.category,
                                    )}"
                                >
                                    {currentStep.category}
                                </span>
                            </div>
                        {/if}
                    </div>
                    <span
                        class="inline-block text-sm font-semibold px-4 py-2 rounded-lg shrink-0 {getStatusColor(
                            currentData.status,
                        )}"
                    >
                        {currentData.status?.replace(/_/g, " ").toUpperCase() ||
                            "PENDING"}
                    </span>
                </div>

                {#if currentStep.description}
                    <!-- Substitute {{param}} placeholders so the operator
                         sees concrete values, not raw template tokens (#21). -->
                    <p class="text-slate-600 text-base leading-relaxed">
                        {renderTemplate(currentStep.description, currentStep.params)}
                    </p>
                {/if}

                {#if currentStep.duration_min}
                    <p class="text-slate-500 text-sm mt-3">
                        Estimated duration: {currentStep.duration_min} minutes
                    </p>
                {/if}
            </div>

            <!-- Form Fields -->
            <div class="flex-1 space-y-6 mb-8">
                {#if hasSchema}
                    <!-- Schema-driven fields from paramSchema -->
                    {#each editableFields as [key, prop]}
                        {@const expected = currentStep.params?.[key]}
                        {@const isAiFilled = aiFilledFields.has(key)}
                        <div>
                            <div class="flex items-center gap-2 mb-1">
                                <label
                                    for="result-{key}"
                                    class="block text-base font-medium text-slate-700"
                                >
                                    {prop.title || key}
                                    <span class="text-red-400">*</span>
                                </label>
                                {#if isAiFilled}
                                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-teal-100 text-teal-700 text-xs font-semibold">
                                        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                                            <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
                                        </svg>
                                        AI filled
                                    </span>
                                {/if}
                            </div>
                            {#if expected !== undefined && expected !== null && expected !== ""}
                                <p class="text-sm text-slate-400 mb-2">
                                    Expected: <span class="font-mono font-medium text-slate-500">{expected}</span>
                                </p>
                            {/if}
                            {#if prop.enum}
                                <select
                                    id="result-{key}"
                                    value={getResultFieldValue(key)}
                                    onchange={(e) =>
                                        updateResultField(
                                            key,
                                            e.currentTarget.value,
                                            prop.type,
                                        )}
                                    onblur={saveStepData}
                                    disabled={fieldsLocked}
                                    class="w-full px-4 py-3.5 border rounded-xl text-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 {firstError(fieldErrors, key) ? 'border-red-400' : isAiFilled ? 'border-teal-400 bg-teal-50/50' : 'border-slate-300'}"
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
                                        type={prop.type === "number" || prop.type === "integer" ? "number" : "text"}
                                        step={prop.type === "integer" ? "1" : "any"}
                                        value={getResultFieldValue(key)}
                                        onchange={(e) =>
                                            updateResultField(
                                                key,
                                                e.currentTarget.value,
                                                prop.type,
                                            )}
                                        onblur={saveStepData}
                                        disabled={fieldsLocked}
                                        placeholder={expected !== undefined ? `Expected: ${expected}` : `Enter ${(prop.title || key).toLowerCase()}`}
                                        class="flex-1 px-4 py-3.5 border rounded-xl text-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 {firstError(fieldErrors, key) ? 'border-red-400' : isAiFilled ? 'border-teal-400 bg-teal-50/50' : 'border-slate-300'}"
                                    />
                                    {#if !fieldsLocked && barcodeScanApplies(prop.type)}
                                        <Button
                                            variant="outline"
                                            size="icon"
                                            title="Scan barcode"
                                            aria-label="Scan barcode"
                                            onclick={() => (scanningField = { key, type: prop.type })}
                                            class="size-12 rounded-xl text-slate-500 hover:text-teal-700 hover:border-teal-400 hover:bg-teal-50"
                                        >
                                            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                                                <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 013.75 9.375v-4.5zM3.75 14.625c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5a1.125 1.125 0 01-1.125-1.125v-4.5zM13.5 4.875c0-.621.504-1.125 1.125-1.125h4.5c.621 0 1.125.504 1.125 1.125v4.5c0 .621-.504 1.125-1.125 1.125h-4.5A1.125 1.125 0 0113.5 9.375v-4.5z" />
                                                <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 6.75h.75v.75h-.75v-.75zM6.75 16.5h.75v.75h-.75v-.75zM16.5 6.75h.75v.75H16.5v-.75zM13.5 13.5h.75v.75h-.75v-.75zM13.5 19.5h.75v.75h-.75v-.75zM19.5 13.5h.75v.75h-.75v-.75zM19.5 19.5h.75v.75h-.75v-.75zM16.5 16.5h.75v.75H16.5v-.75z" />
                                            </svg>
                                        </Button>
                                    {/if}
                                </div>
                            {/if}
                            {#if firstError(fieldErrors, key)}
                                <p class="mt-1.5 text-sm text-red-600">
                                    {firstError(fieldErrors, key)}
                                </p>
                            {/if}
                        </div>
                    {/each}
                {:else}
                    <!-- Legacy fallback for steps without paramSchema -->
                    <div>
                        <label
                            for="step-value-input"
                            class="block text-base font-medium text-slate-700 mb-2"
                        >
                            Value / Measurement
                            <span class="text-red-400">*</span>
                        </label>
                        <input
                            id="step-value-input"
                            type="text"
                            value={currentData.value || ""}
                            onchange={(e) =>
                                updateLegacyValue(e.currentTarget.value)}
                            onblur={saveStepData}
                            disabled={fieldsLocked}
                            placeholder="Enter result or measurement"
                            class="w-full px-4 py-3.5 border rounded-xl text-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 {firstError(fieldErrors, 'value') ? 'border-red-400' : 'border-slate-300'}"
                        />
                        {#if firstError(fieldErrors, "value")}
                            <p class="mt-1.5 text-sm text-red-600">
                                {firstError(fieldErrors, "value")}
                            </p>
                        {/if}
                    </div>
                {/if}

                <!-- Notes -->
                <div>
                    <label
                        for="step-notes-input"
                        class="block text-base font-medium text-slate-700 mb-2"
                    >
                        Notes & Observations
                    </label>
                    <textarea
                        id="step-notes-input"
                        value={currentData.notes || ""}
                        onchange={(e) => updateNotes(e.currentTarget.value)}
                        onblur={saveStepData}
                        disabled={fieldsLocked}
                        placeholder="Enter any notes or observations"
                        rows="5"
                        class="w-full px-4 py-3.5 border border-slate-300 rounded-xl text-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
                    ></textarea>
                </div>

                <!-- Media Input Buttons -->
                {#if !fieldsLocked && !draftMode}
                    <div class="pt-2">
                        <p class="text-sm text-slate-500 mb-3 font-medium">
                            Capture data
                        </p>
                        <div class="flex flex-col sm:flex-row gap-3">
                            <Button
                                variant="outline"
                                disabled
                                title="Voice input coming soon"
                                class="gap-2.5 px-5 py-3 rounded-xl text-base text-slate-600 min-h-11 h-auto"
                            >
                                <span class="text-xl">🎤</span>
                                <span>Voice Memo</span>
                                <!-- Visible "coming soon" marker — the title
                                     tooltip never appears on a tablet, so the
                                     disabled state looked broken (#27). -->
                                <span class="ml-1 px-1.5 py-0.5 rounded-full bg-slate-200 text-slate-500 text-xs font-semibold uppercase tracking-wide">
                                    Soon
                                </span>
                            </Button>
                            <Button
                                variant="outline"
                                onclick={triggerCapture}
                                disabled={uploading}
                                class="gap-2.5 px-5 py-3 rounded-xl text-base text-teal-700 border-teal-300 bg-teal-50 hover:bg-teal-100 hover:text-teal-700 min-h-11 h-auto"
                            >
                                {#if uploading}
                                    <span class="animate-spin text-xl">...</span>
                                    <span>Uploading...</span>
                                {:else}
                                    <span class="text-xl">📷</span>
                                    <span>Take Photo</span>
                                {/if}
                            </Button>
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

                    <!-- Image Gallery for Current Step -->
                    {#if currentStep && stepImages[currentStep.id]?.length}
                        <ImageGallery
                            images={stepImages[currentStep.id]}
                            {confirmedImageIds}
                            {imageStatuses}
                            onImageClick={handleGalleryImageClick}
                            onAnalyzeClick={handleGalleryImageClick}
                        />
                    {/if}
                {/if}
            </div>

            <!-- Error Message -->
            {#if saveError}
                <div
                    class="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-base"
                >
                    {saveError}
                </div>
            {/if}

            <!-- Complete Button -->
            {#if !readonly}
                <Button
                    variant={currentData.status === "completed" ? "secondary" : "default"}
                    onclick={toggleStepComplete}
                    disabled={saving}
                    class="w-full h-auto py-4 rounded-xl font-semibold text-lg {currentData.status ===
                    'completed'
                        ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200 ring-2 ring-emerald-300'
                        : 'bg-teal-600 text-white hover:bg-teal-700 active:bg-teal-800'}"
                >
                    {#if saving}
                        Saving...
                    {:else if currentData.status === "completed"}
                        ✓ Step Completed
                    {:else}
                        Mark Step Complete
                    {/if}
                </Button>
            {/if}
        </div>
    {/if}

    <!-- Navigation -->
    <div class="flex justify-between items-center gap-4">
        <Button
            variant="secondary"
            onclick={prevStep}
            disabled={currentStepIdx === 0}
            class="flex-1 h-auto py-4 rounded-xl font-semibold text-lg bg-slate-100 text-slate-700 hover:bg-slate-200 active:bg-slate-300"
        >
            ← Previous
        </Button>

        <div class="text-base font-medium text-slate-500 shrink-0 px-2">
            {progress.current} / {progress.total}
        </div>

        <Button
            variant="default"
            onclick={nextStep}
            disabled={currentStepIdx === steps.length - 1}
            class="flex-1 h-auto py-4 rounded-xl font-semibold text-lg bg-teal-600 text-white hover:bg-teal-700 active:bg-teal-800"
        >
            Next →
        </Button>
    </div>

    <!-- All Steps Complete Summary -->
    {#if allComplete && !readonly}
        <div class="mt-8 p-6 bg-emerald-50 border border-emerald-200 rounded-xl text-center">
            <p class="text-lg font-semibold text-emerald-800 mb-2">
                All {steps.length} steps completed
            </p>
            <p class="text-sm text-emerald-600 mb-4">
                You have finished all steps for your role. You can review any step above, or finalize the run.
            </p>
            {#if onAllStepsComplete}
                <Button
                    variant="default"
                    onclick={onAllStepsComplete}
                    class="h-auto px-8 py-3 rounded-xl font-semibold text-lg bg-emerald-600 text-white hover:bg-emerald-700"
                >
                    Finalize Run
                </Button>
            {/if}
        </div>
    {/if}

    <!-- Parameter Tag Selector (shown after image capture) -->
    {#if currentStep}
        <Dialog.Root bind:open={showTagSelector}>
            <Dialog.Content
                class="w-[95%] max-w-md max-h-[90vh] p-0 flex flex-col overflow-hidden"
            >
                <!-- Header -->
                <div class="flex items-center justify-between px-6 py-4 border-b border-slate-200">
                    <div>
                        <Dialog.Title class="text-lg font-semibold text-slate-900">Tag Image Parameters</Dialog.Title>
                        <Dialog.Description class="text-sm text-slate-500">Select which parameters this image captures</Dialog.Description>
                    </div>
                </div>
                <!-- Body -->
                <div class="px-6 py-4 overflow-y-auto">
                    {#if editableFields.length > 0}
                        <div class="space-y-2">
                            {#each editableFields as [key, prop] (key)}
                                {@const isSelected = selectedTagSet.has(key)}
                                <Button
                                    variant="outline"
                                    onclick={() => toggleTag(key)}
                                    class="w-full h-auto justify-start gap-3 px-4 py-3 rounded-lg border-2 text-left {isSelected ? 'border-emerald-500 bg-emerald-50 ring-2 ring-emerald-200 text-emerald-900 hover:bg-emerald-50 hover:text-emerald-900' : 'border-slate-200 hover:border-slate-300 text-slate-700'}"
                                >
                                    <span class="flex-shrink-0 w-6 h-6 rounded border-2 flex items-center justify-center transition-colors {isSelected ? 'border-emerald-500 bg-emerald-500' : 'border-slate-300 bg-white'}">
                                        {#if isSelected}
                                            <svg class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                                                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                                            </svg>
                                        {/if}
                                    </span>
                                    <span class="font-medium">{prop.title || key}</span>
                                    {#if prop.unit}
                                        <span class="text-slate-400 text-sm">({prop.unit})</span>
                                    {/if}
                                </Button>
                            {/each}
                        </div>
                        {#if selectedTagSet.size === 0}
                            <p class="mt-3 text-sm text-amber-600">Select at least one parameter to continue.</p>
                        {/if}
                    {:else}
                        <p class="text-sm text-slate-400">No parameters defined for this step.</p>
                    {/if}
                </div>
                <!-- Footer -->
                <div class="px-6 py-4 border-t border-slate-200">
                    <Button
                        variant="default"
                        onclick={saveTagsAndClose}
                        disabled={savingTags || (editableFields.length > 0 && selectedTagSet.size === 0)}
                        class="w-full h-auto py-3 rounded-lg bg-emerald-600 text-white font-medium hover:bg-emerald-700"
                    >
                        {savingTags ? 'Saving...' : `Tag ${selectedTagSet.size > 0 ? `(${selectedTagSet.size})` : ''}`}
                    </Button>
                </div>
            </Dialog.Content>
        </Dialog.Root>
    {/if}

    <!-- AI Analysis Dialog -->
    {#if currentStep}
        <ImageAnalysisDialog
            bind:open={showAnalysisDialog}
            runId={runId}
            stepId={currentStep.id}
            imageId={activeImageId}
            imagePath={activeImagePath}
            onConfirm={handleConfirmValues}
        />
    {/if}

    <!-- Barcode Scanner -->
    <BarcodeScanner
        open={scanningField !== null}
        onScan={handleBarcodeScan}
        onClose={() => (scanningField = null)}
    />
</div>
