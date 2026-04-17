<script lang="ts">
    import RoleWizard from "$lib/components/RoleWizard.svelte";

    interface Props {
        runId: string;
        runName: string;
        protocolName: string | null;
        steps: any[];
        editExecutionData: Record<string, any>;
        savingEdits: boolean;
        error: string | null;
        reEdit?: boolean;
        onDataUpdate: (data: Record<string, any>) => void;
        onSave: () => void;
        onCancel: () => void;
    }

    let {
        runId,
        runName,
        protocolName,
        steps,
        editExecutionData,
        savingEdits,
        error,
        reEdit = false,
        onDataUpdate,
        onSave,
        onCancel,
    }: Props = $props();
</script>

<div class="mb-8">
    <div class="flex items-center justify-between mb-2">
        <div>
            <h1 class="text-3xl font-bold text-foreground">
                {runName}
            </h1>
            {#if protocolName}
                <p class="text-sm text-muted-foreground mt-1">
                    Protocol: {protocolName}
                </p>
            {/if}
        </div>
        <span class="inline-block text-xs font-semibold px-3 py-1 bg-amber-100 text-amber-700 rounded-full">
            Editing
        </span>
    </div>
    <div class="mt-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
        <p class="text-sm text-amber-700">
            {#if reEdit}
                You are editing this run again. Changes will not be saved until you click "Save Edits".
            {:else}
                You are editing a completed run. Changes will not be saved until you click "Save Edits". Original values will be preserved for GMP audit trail.
            {/if}
        </p>
    </div>
</div>

<div class="bg-white rounded-lg border border-border p-2 sm:p-8 mb-8">
    <RoleWizard
        {steps}
        {runId}
        executionData={editExecutionData}
        draftMode={true}
        {onDataUpdate}
    />
</div>

{#if error}
    <div class="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-base">
        {error}
    </div>
{/if}

<div class="flex justify-between items-center">
    <button
        onclick={onCancel}
        class="px-6 py-2 bg-muted text-foreground/80 rounded-lg font-medium hover:bg-muted transition-colors"
    >
        Cancel
    </button>
    <button
        onclick={onSave}
        disabled={savingEdits}
        class="px-6 py-2 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 transition-colors disabled:bg-muted disabled:cursor-not-allowed"
    >
        {savingEdits ? 'Saving...' : 'Save Edits'}
    </button>
</div>
