<script lang="ts">
    import { api } from "$lib/api";
    import { getUser } from "$lib/auth.svelte";
    import {
        firstError,
        type FieldErrors,
    } from "$lib/validation";

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

    const progress = $derived({
        current: currentStepIdx + 1,
        total: steps.length,
        percent:
            steps.length > 0
                ? ((currentStepIdx + 1) / steps.length) * 100
                : 0,
    });
    const completed = $derived(
        Object.values(stepData).filter((s) => s.status === "completed").length,
    );
    const allComplete = $derived(
        steps.length > 0 && completed === steps.length,
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
                await api.put(`/science/runs/${runId}`, {
                    execution_data: updatedExecutionData,
                });
                onDataUpdate?.(updatedExecutionData);
            }
        } catch (e: any) {
            saveError = e.message || "Failed to save step data";
            console.error("Save error:", e);
        } finally {
            saving = false;
        }
    }

    function nextStep() {
        if (currentStepIdx < steps.length - 1) {
            currentStepIdx++;
            saveError = null;
            fieldErrors = {};
        }
    }

    function prevStep() {
        if (currentStepIdx > 0) {
            currentStepIdx--;
            saveError = null;
            fieldErrors = {};
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
    <div class="mb-8">
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
                <button
                    onclick={() => {
                        currentStepIdx = i;
                        saveError = null;
                        fieldErrors = {};
                    }}
                    class="w-3 h-3 rounded-full transition-all {i === currentStepIdx
                        ? 'bg-teal-600 scale-125'
                        : stepData[step.id]?.status === 'completed'
                            ? 'bg-emerald-400'
                            : 'bg-slate-300'}"
                    aria-label="Go to step {i + 1}"
                ></button>
            {/each}
        </div>
    </div>

    <!-- Step Card -->
    {#if currentStep}
        <div
            class="flex-1 bg-white rounded-xl border border-slate-200 p-6 sm:p-10 mb-8 flex flex-col shadow-sm"
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
                    <p class="text-slate-600 text-base leading-relaxed">
                        {currentStep.description}
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
                        <div>
                            <label
                                for="result-{key}"
                                class="block text-base font-medium text-slate-700 mb-1"
                            >
                                {prop.title || key}
                                <span class="text-red-400">*</span>
                            </label>
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
                                    class="w-full px-4 py-3.5 border rounded-xl text-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent {firstError(fieldErrors, key) ? 'border-red-400' : 'border-slate-300'}"
                                >
                                    <option value="">Select...</option>
                                    {#each prop.enum as option}
                                        <option value={option}>{option}</option>
                                    {/each}
                                </select>
                            {:else}
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
                                    placeholder={expected !== undefined ? `Expected: ${expected}` : `Enter ${(prop.title || key).toLowerCase()}`}
                                    class="w-full px-4 py-3.5 border rounded-xl text-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent {firstError(fieldErrors, key) ? 'border-red-400' : 'border-slate-300'}"
                                />
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
                            for="step-value"
                            class="block text-base font-medium text-slate-700 mb-2"
                        >
                            Value / Measurement
                            <span class="text-red-400">*</span>
                        </label>
                        <input
                            id="step-value"
                            type="text"
                            value={currentData.value || ""}
                            onchange={(e) =>
                                updateLegacyValue(e.currentTarget.value)}
                            onblur={saveStepData}
                            placeholder="Enter result or measurement"
                            class="w-full px-4 py-3.5 border rounded-xl text-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent {firstError(fieldErrors, 'value') ? 'border-red-400' : 'border-slate-300'}"
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
                        for="step-notes"
                        class="block text-base font-medium text-slate-700 mb-2"
                    >
                        Notes & Observations
                    </label>
                    <textarea
                        id="step-notes"
                        value={currentData.notes || ""}
                        onchange={(e) => updateNotes(e.currentTarget.value)}
                        onblur={saveStepData}
                        placeholder="Enter any notes or observations"
                        rows="5"
                        class="w-full px-4 py-3.5 border border-slate-300 rounded-xl text-lg focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                    ></textarea>
                </div>

                <!-- Media Input Buttons (Stubbed) -->
                <div class="pt-2">
                    <p class="text-sm text-slate-500 mb-3 font-medium">
                        Attach media (coming soon)
                    </p>
                    <div class="flex gap-3">
                        <button
                            disabled
                            title="Voice input coming soon"
                            class="flex items-center gap-2.5 px-5 py-3 border border-slate-300 rounded-xl text-base text-slate-600 hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <span class="text-xl">🎤</span>
                            <span>Voice Memo</span>
                        </button>
                        <button
                            disabled
                            title="Photo capture coming soon"
                            class="flex items-center gap-2.5 px-5 py-3 border border-slate-300 rounded-xl text-base text-slate-600 hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <span class="text-xl">📷</span>
                            <span>Take Photo</span>
                        </button>
                    </div>
                </div>
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
                <button
                    onclick={toggleStepComplete}
                    disabled={saving}
                    class="w-full py-4 rounded-xl font-semibold text-lg transition-colors {currentData.status ===
                    'completed'
                        ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200 ring-2 ring-emerald-300'
                        : 'bg-teal-600 text-white hover:bg-teal-700 active:bg-teal-800'} disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {#if saving}
                        Saving...
                    {:else if currentData.status === "completed"}
                        ✓ Step Completed
                    {:else}
                        Mark Step Complete
                    {/if}
                </button>
            {/if}
        </div>
    {/if}

    <!-- Navigation -->
    <div class="flex justify-between items-center gap-4">
        <button
            onclick={prevStep}
            disabled={currentStepIdx === 0}
            class="flex-1 py-4 bg-slate-100 text-slate-700 rounded-xl font-semibold text-lg hover:bg-slate-200 active:bg-slate-300 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
            ← Previous
        </button>

        <div class="text-base font-medium text-slate-500 shrink-0 px-2">
            {progress.current} / {progress.total}
        </div>

        <button
            onclick={nextStep}
            disabled={currentStepIdx === steps.length - 1}
            class="flex-1 py-4 bg-teal-600 text-white rounded-xl font-semibold text-lg hover:bg-teal-700 active:bg-teal-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
            Next →
        </button>
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
                <button
                    onclick={onAllStepsComplete}
                    class="px-8 py-3 bg-emerald-600 text-white rounded-xl font-semibold text-lg hover:bg-emerald-700 transition-colors"
                >
                    Finalize Run
                </button>
            {/if}
        </div>
    {/if}
</div>
