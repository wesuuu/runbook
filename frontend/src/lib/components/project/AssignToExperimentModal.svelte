<script lang="ts">
    import { api } from "$lib/api";
    import { toast } from "$lib/toast";
    import * as Dialog from "$lib/components/ui/dialog";
    import { Button } from "$lib/components/ui/button";

    interface Props {
        open: boolean;
        runId: string;
        runName: string;
        experiments: any[];
        onAssigned?: () => void;
    }

    let {
        open = $bindable(false),
        runId,
        runName,
        experiments,
        onAssigned,
    }: Props = $props();

    let selectedExpId = $state<string | null>(null);
    let submitting = $state(false);
    let error = $state<string | null>(null);

    const availableExperiments = $derived(
        experiments.filter((e: any) => e.status?.toUpperCase() !== 'ARCHIVED')
    );

    async function assign() {
        if (!selectedExpId) return;
        submitting = true;
        error = null;
        try {
            await api.post(`/science/experiments/${selectedExpId}/runs`, {
                run_id: runId,
            });
            const expName = availableExperiments.find((e: any) => e.id === selectedExpId)?.name ?? 'experiment';
            toast.success(`"${runName}" assigned to ${expName}`);
            open = false;
            selectedExpId = null;
            onAssigned?.();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to assign run';
        } finally {
            submitting = false;
        }
    }

    function close() {
        open = false;
        selectedExpId = null;
        error = null;
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="min-w-[420px] sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>Assign to Experiment</Dialog.Title>
            <Dialog.Description>
                Move <strong>{runName}</strong> into an experiment.
            </Dialog.Description>
        </Dialog.Header>
        <div class="space-y-3">
            {#if availableExperiments.length > 0}
                <div>
                    <label
                        for="assign-exp-select"
                        class="block text-sm font-medium text-gray-700 mb-1"
                    >Experiment</label>
                    <select
                        id="assign-exp-select"
                        bind:value={selectedExpId}
                        class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent bg-white"
                    >
                        <option value="">Select an experiment</option>
                        {#each availableExperiments as exp}
                            <option value={exp.id}>{exp.name}</option>
                        {/each}
                    </select>
                </div>
            {:else}
                <p class="text-sm text-slate-500 py-2">
                    No experiments available. Create an experiment first.
                </p>
            {/if}
            {#if error}
                <p class="text-sm text-red-600">{error}</p>
            {/if}
        </div>
        <Dialog.Footer>
            <Button variant="secondary" onclick={close}>
                Cancel
            </Button>
            <Button
                onclick={assign}
                disabled={!selectedExpId || submitting}
            >
                {submitting ? 'Assigning...' : 'Assign'}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
