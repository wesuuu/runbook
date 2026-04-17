<script lang="ts">
    import { api } from '$lib/api';
    import { getUser } from '$lib/auth.svelte';
    import type { RunNote } from '$lib/schemas';

    let {
        runId,
        notes = $bindable([]),
    }: {
        runId: string;
        notes: RunNote[];
    } = $props();

    let newNote = $state('');
    let isAnomaly = $state(false);
    let submitting = $state(false);
    let error = $state<string | null>(null);

    async function addNote() {
        const content = newNote.trim();
        if (!content) return;
        submitting = true;
        error = null;
        try {
            const note = await api.post<RunNote>(`/science/runs/${runId}/notes`, {
                content,
                flags: isAnomaly ? ['anomaly'] : [],
            });
            notes = [...notes, note as RunNote];
            newNote = '';
            isAnomaly = false;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to add note';
        } finally {
            submitting = false;
        }
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            addNote();
        }
    }
</script>

<div class="max-w-3xl mx-auto py-6 space-y-4">
    {#if notes.length === 0}
        <div class="text-center py-12 text-muted-foreground">
            <p class="text-lg font-medium mb-1">No notes yet</p>
            <p class="text-sm">Add observations, comments, or flag anomalies below.</p>
        </div>
    {/if}

    <!-- Note list -->
    {#each notes as note}
        <div class="bg-white rounded-lg border border-border p-4
            {note.flags?.includes('anomaly') ? 'border-l-4 border-l-amber-400' : ''}">
            <p class="text-foreground whitespace-pre-wrap">{note.content}</p>
            <div class="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
                <span>{note.author_name}</span>
                <span>{new Date(note.created_at).toLocaleString()}</span>
                <span class="px-1.5 py-0.5 bg-muted rounded text-[10px] font-medium">
                    {note.run_status}
                </span>
                {#if note.flags?.includes('anomaly')}
                    <span class="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-[10px] font-semibold">
                        ANOMALY
                    </span>
                {/if}
            </div>
        </div>
    {/each}

    <!-- Error -->
    {#if error}
        <div class="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
        </div>
    {/if}

    <!-- Add note input -->
    <div class="bg-white rounded-lg border border-border p-4">
        <textarea
            bind:value={newNote}
            onkeydown={handleKeydown}
            placeholder="Add a note..."
            rows="3"
            class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent resize-y"
        ></textarea>
        <div class="flex items-center justify-between mt-2">
            <label class="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
                <input type="checkbox" bind:checked={isAnomaly}
                    class="rounded border-slate-300" />
                Flag as anomaly
            </label>
            <div class="flex items-center gap-2">
                <span class="text-xs text-muted-foreground hidden sm:inline">
                    {navigator.platform?.includes('Mac') ? 'Cmd' : 'Ctrl'}+Enter to submit
                </span>
                <button
                    onclick={addNote}
                    disabled={!newNote.trim() || submitting}
                    class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {submitting ? 'Adding...' : 'Add Note'}
                </button>
            </div>
        </div>
    </div>
</div>
