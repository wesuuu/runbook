<script lang="ts">
    import { goto } from "$app/navigation";
    import { api } from "$lib/api";
    import * as Dialog from "$lib/components/ui/dialog";

    interface Props {
        open: boolean;
        projectId: string;
        protocols: any[];
        experiments?: any[];
        /** When set, locks the experiment field and shows it in the title */
        forExperiment?: { id: string; name: string } | null;
        onCreated?: () => void;
    }

    let {
        open = $bindable(false),
        projectId,
        protocols,
        experiments = [],
        forExperiment = null,
        onCreated,
    }: Props = $props();

    let runName = $state("");
    let protocolId = $state<string | null>(null);
    let experimentId = $state<string | null>(null);

    // Sync forExperiment into experimentId when it changes
    $effect(() => {
        if (forExperiment) {
            experimentId = forExperiment.id;
        }
    });

    const title = $derived(
        forExperiment
            ? `New Run for ${forExperiment.name}`
            : "New Run"
    );

    const description = $derived(
        forExperiment
            ? "Create a run within this experiment."
            : "Start a new run from a protocol."
    );

    let error = $state<string | null>(null);

    async function createRun() {
        if (!runName || !protocolId) return;
        error = null;

        try {
            const payload: Record<string, unknown> = {
                name: runName,
                project_id: projectId,
                protocol_id: protocolId,
                experiment_id: experimentId ?? undefined,
            };
            const newRun: any = await api.post("/science/runs", payload);
            close();
            if (onCreated) onCreated();
            goto(`/runs/${newRun.id}`);
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to create run';
        }
    }

    function close() {
        open = false;
        runName = "";
        error = null;
        protocolId = null;
        if (!forExperiment) {
            experimentId = null;
        }
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Description>{description}</Dialog.Description>
        </Dialog.Header>
        <div class="space-y-3">
            <div>
                <label
                    for="run-name"
                    class="block text-sm font-medium text-gray-700 mb-1">Name</label
                >
                <input
                    id="run-name"
                    type="text"
                    bind:value={runName}
                    placeholder="e.g. CHO-DG44 Run 1"
                    class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                />
            </div>
            <div>
                <label
                    for="run-protocol-select"
                    class="block text-sm font-medium text-gray-700 mb-1"
                    >Protocol</label
                >
                <select
                    id="run-protocol-select"
                    bind:value={protocolId}
                    class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent bg-white"
                >
                    <option value="">Select a protocol</option>
                    {#each protocols.filter((p: any) => p.status?.toUpperCase() !== 'ARCHIVED') as proto}
                        <option value={proto.id}>{proto.name}</option>
                    {/each}
                </select>
            </div>
            {#if !forExperiment}
                <div>
                    <label
                        for="run-experiment-select"
                        class="block text-sm font-medium text-gray-700 mb-1"
                        >Experiment <span class="text-slate-400 font-normal">(optional)</span></label
                    >
                    <select
                        id="run-experiment-select"
                        bind:value={experimentId}
                        class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent bg-white"
                    >
                        <option value="">No experiment</option>
                        {#each experiments.filter((e: any) => e.status?.toUpperCase() !== 'ARCHIVED') as exp}
                            <option value={exp.id}>{exp.name}</option>
                        {/each}
                    </select>
                </div>
            {/if}
            {#if error}
                <p class="text-sm text-red-600">{error}</p>
            {/if}
        </div>
        <Dialog.Footer>
            <button
                onclick={close}
                class="px-4 py-2 text-sm font-medium text-foreground/80 bg-muted rounded-lg hover:bg-muted/80 transition-colors"
            >
                Cancel
            </button>
            <button
                onclick={createRun}
                disabled={!runName || !protocolId}
                class="px-4 py-2 text-sm font-medium text-white bg-teal-600 rounded-lg hover:bg-teal-700 transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
                Create
            </button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
