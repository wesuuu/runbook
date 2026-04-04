<script lang="ts">
    import { api } from "$lib/api";
    import * as Dialog from "$lib/components/ui/dialog";
    import { shortId, statusClasses, statusLabel, formatDate } from "./projectUtils";

    interface Props {
        open: boolean;
        experimentId: string;
        experimentName: string;
        runs: any[];
        onAdded?: () => void;
    }

    let {
        open = $bindable(false),
        experimentId,
        experimentName,
        runs,
        onAdded,
    }: Props = $props();

    let searchQuery = $state("");
    let submitting = $state<string | null>(null);
    let error = $state<string | null>(null);

    const standaloneRuns = $derived(
        runs.filter((r: any) => {
            if (r.experiment_id) return false;
            if (!searchQuery.trim()) return true;
            const q = searchQuery.toLowerCase();
            return r.name?.toLowerCase().includes(q) || r.status?.toLowerCase().includes(q);
        })
    );

    async function linkRun(runId: string) {
        submitting = runId;
        error = null;
        try {
            await api.post(`/science/experiments/${experimentId}/runs`, {
                run_id: runId,
            });
            onAdded?.();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to add run';
        } finally {
            submitting = null;
        }
    }

    function close() {
        open = false;
        searchQuery = "";
        error = null;
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-lg">
        <Dialog.Header>
            <Dialog.Title>Add Existing Run</Dialog.Title>
            <Dialog.Description>
                Add a standalone run to <strong>{experimentName}</strong>.
            </Dialog.Description>
        </Dialog.Header>
        <div class="space-y-3">
            <input
                type="text"
                bind:value={searchQuery}
                placeholder="Search runs..."
                class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
            />

            {#if error}
                <p class="text-sm text-red-600">{error}</p>
            {/if}

            <div class="max-h-[300px] overflow-y-auto border border-slate-200 rounded-lg divide-y divide-slate-100">
                {#each standaloneRuns as run}
                    <div class="flex items-center justify-between px-3 py-2.5 hover:bg-slate-50 transition-colors">
                        <div class="min-w-0 flex-1">
                            <div class="text-sm font-medium text-slate-800 truncate">{run.name}</div>
                            <div class="flex items-center gap-2 text-xs text-slate-400 mt-0.5">
                                <span class="font-mono">{shortId(run.id)}</span>
                                <span>&middot;</span>
                                <span class="inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded-full {statusClasses(run.status)}">
                                    {statusLabel(run.status)}
                                </span>
                                <span>&middot;</span>
                                <span>{formatDate(run.updated_at || run.created_at)}</span>
                            </div>
                        </div>
                        <button
                            onclick={() => linkRun(run.id)}
                            disabled={submitting === run.id}
                            class="ml-3 shrink-0 px-3 py-1 text-xs font-medium text-teal-600 border border-teal-200 rounded-lg hover:bg-teal-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {submitting === run.id ? '...' : 'Add'}
                        </button>
                    </div>
                {:else}
                    <div class="py-6 text-center text-sm text-slate-400">
                        {searchQuery ? 'No matching standalone runs.' : 'No standalone runs available.'}
                    </div>
                {/each}
            </div>
        </div>
        <Dialog.Footer>
            <button
                onclick={close}
                class="px-4 py-2 text-sm font-medium text-foreground/80 bg-muted rounded-lg hover:bg-muted/80 transition-colors"
            >
                Done
            </button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
