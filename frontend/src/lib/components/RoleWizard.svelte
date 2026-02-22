<script lang="ts">
    import { api } from "$lib/api";

    interface Step {
        id: string;
        name: string;
        category?: string;
        description?: string;
        params?: Record<string, any>;
        duration_min?: number;
    }

    interface StepResult {
        status: "pending" | "in_progress" | "completed" | "skipped";
        value?: string;
        notes?: string;
        timestamp?: string;
        completed_by_user_id?: string;
        voice_memo_url?: string;
        photo_url?: string;
    }

    let {
        steps = [],
        runId,
        executionData = {},
        onDataUpdate,
    }: {
        steps: Step[];
        runId: string;
        executionData: Record<string, any>;
        onDataUpdate?: (data: Record<string, any>) => void;
    } = $props();

    let currentStepIdx = $state(0);
    let stepData = $state<Record<string, StepResult>>({});
    let saving = $state(false);
    let saveError = $state<string | null>(null);

    $effect(() => {
        // Load execution data into local state
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
    const progress = $derived({
        current: currentStepIdx + 1,
        total: steps.length,
        percent: steps.length > 0 ? ((currentStepIdx + 1) / steps.length) * 100 : 0,
    });
    const completed = $derived(
        Object.values(stepData).filter((s) => s.status === "completed").length
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

            await api.put(`/science/runs/${runId}`, {
                execution_data: updatedExecutionData,
            });

            onDataUpdate?.(updatedExecutionData);
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
        }
    }

    function prevStep() {
        if (currentStepIdx > 0) {
            currentStepIdx--;
            saveError = null;
        }
    }

    function toggleStepComplete() {
        if (currentStep) {
            currentData.status =
                currentData.status === "completed" ? "in_progress" : "completed";
            currentData.timestamp = new Date().toISOString();
            saveStepData();
        }
    }

    function updateValue(value: string) {
        if (currentStep) {
            currentData.value = value;
            if (!currentData.status || currentData.status === "pending") {
                currentData.status = "in_progress";
            }
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
</script>

<div class="flex flex-col h-full">
    <!-- Progress Bar -->
    <div class="mb-6">
        <div class="flex justify-between items-center mb-2">
            <span class="text-sm font-medium text-slate-700">
                Step {progress.current} of {progress.total}
            </span>
            <span class="text-sm text-slate-600">
                {completed} completed
            </span>
        </div>
        <div class="w-full bg-slate-200 rounded-full h-2">
            <div
                class="bg-teal-600 h-2 rounded-full transition-all duration-300"
                style="width: {progress.percent}%"
            ></div>
        </div>
    </div>

    <!-- Step Card -->
    {#if currentStep}
        <div class="flex-1 bg-white rounded-lg border border-slate-200 p-8 mb-6 flex flex-col">
            <!-- Step Header -->
            <div class="mb-6">
                <div class="flex items-start justify-between mb-3">
                    <div class="flex-1">
                        <h2 class="text-2xl font-bold text-slate-900">
                            {currentStep.name}
                        </h2>
                        {#if currentStep.category}
                            <div class="mt-2">
                                <span
                                    class="inline-block text-xs font-semibold px-2 py-1 rounded border {getCategoryColor(
                                        currentStep.category
                                    )}"
                                >
                                    {currentStep.category}
                                </span>
                            </div>
                        {/if}
                    </div>
                    <span
                        class="inline-block text-xs font-semibold px-3 py-1 rounded {getStatusColor(
                            currentData.status
                        )}"
                    >
                        {currentData.status?.replace(/_/g, " ").toUpperCase() ||
                            "PENDING"}
                    </span>
                </div>

                {#if currentStep.description}
                    <p class="text-slate-600 text-sm">
                        {currentStep.description}
                    </p>
                {/if}

                {#if currentStep.duration_min}
                    <p class="text-slate-500 text-xs mt-3">
                        Estimated duration: {currentStep.duration_min} minutes
                    </p>
                {/if}
            </div>

            <!-- Parameters Display -->
            {#if currentStep.params && Object.keys(currentStep.params).length > 0}
                <div class="mb-6 p-4 bg-slate-50 rounded-lg border border-slate-200">
                    <h3 class="text-sm font-semibold text-slate-700 mb-3">
                        Parameters
                    </h3>
                    <div class="space-y-2">
                        {#each Object.entries(currentStep.params) as [key, value]}
                            <div class="flex justify-between text-sm">
                                <span class="text-slate-600">{key}:</span>
                                <span class="font-mono text-slate-900">
                                    {value}
                                </span>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}

            <!-- Form Fields -->
            <div class="flex-1 space-y-4 mb-6">
                <!-- Value Input -->
                <div>
                    <label
                        for="step-value"
                        class="block text-sm font-medium text-slate-700 mb-2"
                    >
                        Value / Measurement
                    </label>
                    <input
                        id="step-value"
                        type="text"
                        value={currentData.value || ""}
                        onchange={(e) => updateValue(e.currentTarget.value)}
                        onblur={saveStepData}
                        placeholder="Enter result or measurement"
                        class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                    />
                </div>

                <!-- Notes -->
                <div>
                    <label
                        for="step-notes"
                        class="block text-sm font-medium text-slate-700 mb-2"
                    >
                        Notes & Observations
                    </label>
                    <textarea
                        id="step-notes"
                        value={currentData.notes || ""}
                        onchange={(e) => updateNotes(e.currentTarget.value)}
                        onblur={saveStepData}
                        placeholder="Enter any notes or observations"
                        rows="4"
                        class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                    ></textarea>
                </div>

                <!-- Media Input Buttons (Stubbed) -->
                <div class="pt-2">
                    <p class="text-xs text-slate-600 mb-3 font-medium">
                        Attach media (coming soon)
                    </p>
                    <div class="flex gap-2">
                        <button
                            disabled
                            title="Voice input coming soon"
                            class="flex items-center gap-2 px-3 py-2 border border-slate-300 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <span>🎤</span>
                            <span>Voice Memo</span>
                        </button>
                        <button
                            disabled
                            title="Photo capture coming soon"
                            class="flex items-center gap-2 px-3 py-2 border border-slate-300 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <span>📷</span>
                            <span>Take Photo</span>
                        </button>
                    </div>
                </div>
            </div>

            <!-- Error Message -->
            {#if saveError}
                <div class="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
                    {saveError}
                </div>
            {/if}

            <!-- Complete Button -->
            <div class="flex gap-2">
                <button
                    onclick={toggleStepComplete}
                    disabled={saving}
                    class="px-4 py-2 rounded-lg font-medium text-sm transition-colors {currentData.status ===
                    'completed'
                        ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
                        : 'bg-slate-100 text-slate-700 hover:bg-slate-200'} disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {currentData.status === "completed"
                        ? "✓ Completed"
                        : "Mark Complete"}
                </button>
                {#if saving}
                    <span class="text-xs text-slate-500 self-center">
                        Saving...
                    </span>
                {/if}
            </div>
        </div>
    {/if}

    <!-- Navigation -->
    <div class="flex justify-between items-center">
        <button
            onclick={prevStep}
            disabled={currentStepIdx === 0}
            class="px-4 py-2 bg-slate-100 text-slate-700 rounded-lg font-medium text-sm hover:bg-slate-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
            ← Previous
        </button>

        <div class="text-sm text-slate-600">
            {progress.current} / {progress.total}
        </div>

        <button
            onclick={nextStep}
            disabled={currentStepIdx === steps.length - 1}
            class="px-4 py-2 bg-teal-600 text-white rounded-lg font-medium text-sm hover:bg-teal-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
            Next →
        </button>
    </div>
</div>

<style>
    :global(.role-wizard) {
        display: flex;
        flex-direction: column;
    }
</style>
