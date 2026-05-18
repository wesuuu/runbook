<script lang="ts">
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
        lotNumber?: string;
        batchNumber?: string;
        onChange: (next: { name: string; experimentId: string | null; lotNumber: string; batchNumber: string }) => void;
        onValidate: (valid: boolean) => void;
    }

    let { name, experimentId, experiments, lockedExperiment, lotNumber = '', batchNumber = '', onChange, onValidate }: Props = $props();

    const visibleExperiments = $derived(
        experiments.filter((e) => (e.status ?? '').toUpperCase() !== 'ARCHIVED'),
    );

    $effect(() => {
        onValidate(name.trim().length > 0);
    });

    function setName(v: string) { onChange({ name: v, experimentId, lotNumber, batchNumber }); }
    function setExperimentId(v: string) {
        onChange({ name, experimentId: v === '' ? null : v, lotNumber, batchNumber });
    }
    function setLotNumber(v: string) { onChange({ name, experimentId, lotNumber: v, batchNumber }); }
    function setBatchNumber(v: string) { onChange({ name, experimentId, lotNumber, batchNumber: v }); }
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

    <div class="field">
        <label for="run-lot" class="field-label">
            Lot number <span class="optional">(optional)</span>
        </label>
        <input
            id="run-lot"
            type="text"
            value={lotNumber}
            oninput={(e) => setLotNumber((e.target as HTMLInputElement).value)}
            placeholder="e.g. LOT-2024-001"
            class="input-field"
            autocomplete="off"
        />
    </div>

    <div class="field">
        <label for="run-batch" class="field-label">
            Batch number <span class="optional">(optional)</span>
        </label>
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
