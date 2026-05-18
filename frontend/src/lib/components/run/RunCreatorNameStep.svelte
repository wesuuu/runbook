<script lang="ts">
    import { api } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import { Switch } from '$lib/components/ui/switch';
    import * as Tooltip from '$lib/components/ui/tooltip';

    interface ExperimentOption {
        id: string;
        name: string;
        status?: string;
    }

    interface Props {
        name: string;
        experimentId: string | null;
        experiments: ExperimentOption[];
        lockedExperiment: { id: string; name: string } | null;
        producesLot?: boolean;
        lotNumber?: string;
        batchNumber?: string;
        projectId: string;
        onChange: (next: {
            name: string;
            experimentId: string | null;
            producesLot: boolean;
            lotNumber: string;
            batchNumber: string;
        }) => void;
        onValidate: (valid: boolean) => void;
    }

    let {
        name,
        experimentId,
        experiments,
        lockedExperiment,
        producesLot = false,
        lotNumber = '',
        batchNumber = '',
        projectId,
        onChange,
        onValidate,
    }: Props = $props();

    let duplicateCount = $state<number>(0);
    let autoGenerating = $state(false);

    const visibleExperiments = $derived(
        experiments.filter((e) => (e.status ?? '').toUpperCase() !== 'ARCHIVED'),
    );

    $effect(() => {
        const baseValid = name.trim().length > 0;
        const lotValid = !producesLot || lotNumber.trim().length > 0;
        onValidate(baseValid && lotValid);
    });

    function emit(partial: Partial<{
        name: string;
        experimentId: string | null;
        producesLot: boolean;
        lotNumber: string;
        batchNumber: string;
    }>) {
        onChange({
            name,
            experimentId,
            producesLot,
            lotNumber,
            batchNumber,
            ...partial,
        });
    }

    function setName(v: string) { emit({ name: v }); }
    function setExperimentId(v: string) { emit({ experimentId: v === '' ? null : v }); }
    function setProducesLot(v: boolean) {
        if (!v) {
            // Clear lot value so a hidden, stale string can't leak through on submit.
            emit({ producesLot: false, lotNumber: '' });
            duplicateCount = 0;
        } else {
            emit({ producesLot: true });
        }
    }
    function setLotNumber(v: string) { emit({ lotNumber: v }); }
    function setBatchNumber(v: string) { emit({ batchNumber: v }); }

    async function autoGenerate() {
        autoGenerating = true;
        try {
            const res = await api.post<{ lot_number: string }>(
                '/science/runs/suggest-lot-number',
                { project_id: projectId },
            );
            setLotNumber(res.lot_number);
            duplicateCount = 0;
        } finally {
            autoGenerating = false;
        }
    }

    async function checkDuplicate() {
        if (!producesLot) { duplicateCount = 0; return; }
        const trimmed = lotNumber.trim();
        if (!trimmed) { duplicateCount = 0; return; }
        const res = await api.get<{ exists: boolean; count: number }>(
            `/science/runs/check-lot-number?project_id=${encodeURIComponent(projectId)}&lot_number=${encodeURIComponent(trimmed)}`,
        );
        // Subtract this run's own pending entry if needed — for a creator
        // flow the run doesn't exist yet, so the raw count is correct.
        duplicateCount = res.exists ? res.count : 0;
    }
</script>

<section class="step-body">
    <header class="step-header">
        <h2>Step 1 · Name your run</h2>
        <p class="step-help">Pick a name you'll recognize on the runs list.</p>
    </header>

    <div class="field">
        <label for="run-name" class="field-label">Name</label>
        <input
            id="run-name"
            type="text"
            value={name}
            oninput={(e) => setName((e.target as HTMLInputElement).value)}
            placeholder="e.g. CHO-DG44 Run 1"
            class="input-field"
            autocomplete="off"
        />
    </div>

    <div class="field">
        <label for="run-experiment" class="field-label">
            Experiment <span class="optional">(optional)</span>
        </label>
        <select
            id="run-experiment"
            value={experimentId ?? ''}
            onchange={(e) => setExperimentId((e.target as HTMLSelectElement).value)}
            disabled={!!lockedExperiment}
            class="input-field"
        >
            {#if lockedExperiment}
                <option value={lockedExperiment.id}>{lockedExperiment.name}</option>
            {:else}
                <option value="">No experiment</option>
                {#each visibleExperiments as exp (exp.id)}
                    <option value={exp.id}>{exp.name}</option>
                {/each}
            {/if}
        </select>
        {#if lockedExperiment}
            <p class="hint">This run will belong to {lockedExperiment.name}.</p>
        {/if}
    </div>

    <div class="rounded-lg border border-border bg-card p-4 space-y-3">
        <div class="flex items-start justify-between gap-4">
            <div>
                <div class="flex items-center gap-1.5">
                    <span class="text-sm font-medium text-foreground">This run produces a lot</span>
                    <Tooltip.Provider delayDuration={150}>
                        <Tooltip.Root>
                            <Tooltip.Trigger
                                type="button"
                                aria-label="What is a lot?"
                                class="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                            >
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                            </Tooltip.Trigger>
                            <Tooltip.Content class="max-w-xs text-left">
                                A <strong>lot</strong> is a traceability unit assigned to finished material. One batch may yield multiple lots (different fill sizes, stability conditions), or multiple batches may be combined into a single lot. Toggle this on only when the run produces a manufacturing lot.
                            </Tooltip.Content>
                        </Tooltip.Root>
                    </Tooltip.Provider>
                </div>
                <p class="text-xs text-muted-foreground mt-1">
                    Designate this run as the producer of a manufacturing lot.
                </p>
            </div>
            <Switch
                id="run-produces-lot"
                checked={producesLot}
                onCheckedChange={setProducesLot}
            />
        </div>

        {#if producesLot}
            <div class="field pt-1">
                <div class="flex items-center justify-between">
                    <label for="run-lot" class="field-label">Lot number</label>
                    <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onclick={autoGenerate}
                        disabled={autoGenerating}
                    >
                        {autoGenerating ? 'Generating…' : 'Auto-generate'}
                    </Button>
                </div>
                <input
                    id="run-lot"
                    type="text"
                    value={lotNumber}
                    oninput={(e) => setLotNumber((e.target as HTMLInputElement).value)}
                    onblur={checkDuplicate}
                    placeholder="LOT-000001"
                    class="input-field font-mono"
                    autocomplete="off"
                />
            </div>

            {#if duplicateCount > 0}
                <div
                    role="status"
                    class="flex items-start gap-3 rounded-md border-l-4 border-l-amber-400 bg-amber-50 px-4 py-3"
                    data-testid="lot-duplicate-warning"
                >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="mt-0.5 shrink-0 text-amber-600"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <p class="text-sm text-amber-900">
                        This lot number already exists in your org ({duplicateCount} run{duplicateCount !== 1 ? 's' : ''}). Lots may be re-entered intentionally — confirm or change.
                    </p>
                </div>
            {/if}
        {/if}
    </div>

    <div class="field">
        <div class="flex items-center gap-1.5">
            <label for="run-batch" class="field-label">
                Batch number <span class="optional">(optional)</span>
            </label>
            <Tooltip.Provider delayDuration={150}>
                <Tooltip.Root>
                    <Tooltip.Trigger
                        type="button"
                        aria-label="What is a batch?"
                        class="text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                    >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                    </Tooltip.Trigger>
                    <Tooltip.Content class="max-w-xs text-left">
                        A <strong>batch</strong> is the output of a single execution of the manufacturing process (e.g., one fermenter run). Under GMP, batch and lot are distinct: one batch can yield multiple lots, and multiple batches can be combined into a single lot.
                    </Tooltip.Content>
                </Tooltip.Root>
            </Tooltip.Provider>
        </div>
        <input
            id="run-batch"
            type="text"
            value={batchNumber}
            oninput={(e) => setBatchNumber((e.target as HTMLInputElement).value)}
            placeholder="e.g. BATCH-42"
            class="input-field"
            autocomplete="off"
        />
    </div>
</section>

<style>
    .step-body {
        max-width: 36rem;
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
    .field {
        display: flex;
        flex-direction: column;
        gap: 0.375rem;
    }
    .field-label {
        font-size: 0.875rem;
        font-weight: 500;
        color: rgb(51 65 85);
    }
    .optional {
        color: rgb(148 163 184);
        font-weight: 400;
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
    .input-field:disabled {
        background-color: rgb(249 250 251);
        color: rgb(100 116 139);
        cursor: not-allowed;
    }
    .hint {
        font-size: 0.75rem;
        color: rgb(100 116 139);
    }
</style>
