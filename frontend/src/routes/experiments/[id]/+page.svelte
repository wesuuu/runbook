<script lang="ts">
    import { page } from "$app/stores";
    import { goto } from "$app/navigation";
    import { api } from "$lib/api";
    import { Button } from "$lib/components/ui/button";
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import ErrorAlert from '$lib/components/ui/error-alert.svelte';
    import RunCreatorWizardModal from "$lib/components/run/RunCreatorWizardModal.svelte";
    import AddExistingRunModal from "$lib/components/project/AddExistingRunModal.svelte";
    import RunsTab from "$lib/components/project/RunsTab.svelte";
    import {
        shortId,
        formatDate,
        experimentStatusClasses,
        experimentStatusLabel,
    } from "$lib/components/project/projectUtils";
    import { fade } from "svelte/transition";
    import { flip } from "svelte/animate";
    import { blockDuration, listDuration } from "$lib/transitions";
    // Edra rich text editor — lazy loaded to avoid SSR issues
    let EdraEditor: any = $state(null);
    let EdraToolBar: any = $state(null);
    import { onMount } from "svelte";
    import type { Editor } from "@tiptap/core";

    onMount(async () => {
        try {
            const edra = await import("$lib/components/edra/shadcn");
            EdraEditor = edra.EdraEditor;
            EdraToolBar = edra.EdraToolBar;
        } catch (e) {
            console.warn("Edra editor failed to load:", e);
        }
    });

    const id = $derived($page.params.id ?? "");

    let experiment = $state<any>(null);
    let project = $state<any>(null);
    let protocols = $state<any[]>([]);
    let loading = $state(true);
    let saving = $state(false);
    let error = $state<string | null>(null);

    // Editable fields
    let name = $state("");
    let description = $state("");
    let status = $state("DRAFT");

    // Edra editor
    let editor = $state<Editor>();

    // Notes
    let notes = $state<any[]>([]);
    let newNote = $state("");
    let submittingNote = $state(false);

    // Run modals
    let showRunModal = $state(false);
    let showAddExistingModal = $state(false);
    let allProjectRuns = $state<any[]>([]);

    const statusOptions = ["DRAFT", "ACTIVE", "COMPLETED", "ARCHIVED"];

    $effect(() => {
        const currentId = id;
        if (currentId) loadData();
    });

    async function loadData() {
        loading = true;
        error = null;
        try {
            experiment = await api.get(`/science/experiments/${id}`);
            name = experiment.name;
            description = experiment.description ?? "";
            status = experiment.status;
            notes = experiment.notes ?? [];

            // Load project, protocols, and all runs for breadcrumb and modals
            const [proj, protos, projectRuns] = await Promise.all([
                api.get(`/projects/${experiment.project_id}`),
                api.get(`/science/projects/${experiment.project_id}/protocols`),
                api.get(`/science/projects/${experiment.project_id}/runs`),
            ]);
            project = proj;
            protocols = protos as any[];
            allProjectRuns = projectRuns as any[];
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : "Failed to load experiment";
        } finally {
            loading = false;
        }
    }

    async function save() {
        saving = true;
        try {
            const content = editor?.getJSON() ?? experiment.content ?? {};
            await api.put(`/science/experiments/${id}`, {
                name,
                description: description || null,
                content,
                status,
            });
            experiment.name = name;
            experiment.description = description;
            experiment.content = content;
            experiment.status = status;
        } catch (e: unknown) {
            console.error(e instanceof Error ? e.message : e);
        } finally {
            saving = false;
        }
    }

    async function addNote() {
        const content = newNote.trim();
        if (!content) return;
        submittingNote = true;
        try {
            const note = await api.post(
                `/science/experiments/${id}/notes`,
                { content, flags: [] },
            );
            notes = [...notes, note as any];
            newNote = "";
        } catch (e: unknown) {
            console.error(e instanceof Error ? e.message : e);
        } finally {
            submittingNote = false;
        }
    }

    function handleNoteKeydown(e: KeyboardEvent) {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            addNote();
        }
    }
</script>

{#if loading}
    <div in:fade={{ duration: blockDuration() }}>
        <LoadingSpinner message="Loading experiment..." fullPage />
    </div>
{:else if error}
    <div in:fade={{ duration: blockDuration() }}>
        <ErrorAlert message="Error: {error}" class="max-w-xl mx-auto mt-8" />
    </div>
{:else if experiment}
    <div
        in:fade={{ duration: blockDuration() }}
        class="min-h-[calc(100vh-57px)] w-full mx-auto bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden"
    >
        <!-- Header -->
        <div class="pt-5 sm:pt-7 px-4 sm:px-8">
            <!-- Breadcrumb -->
            <nav class="flex items-center gap-2 mb-2.5 text-[13px]">
                <a
                    href="/projects"
                    class="text-teal-600 font-medium hover:underline"
                    >Projects</a
                >
                <span class="text-slate-400">&rsaquo;</span>
                {#if project}
                    <a
                        href="/projects/{project.id}"
                        class="text-teal-600 font-medium hover:underline"
                        >{project.name}</a
                    >
                {:else}
                    <span class="text-slate-400">...</span>
                {/if}
                <span class="text-slate-400">&rsaquo;</span>
                <span class="text-slate-600 font-mono font-medium"
                    >EXP-{shortId(experiment.id)}</span
                >
            </nav>

            <!-- Name + Status + Save -->
            <div class="flex items-center gap-3.5 mb-3">
                <input
                    type="text"
                    bind:value={name}
                    class="text-[26px] font-bold text-slate-900 leading-tight bg-transparent border-none outline-none focus:ring-0 p-0 flex-1 min-w-0"
                    placeholder="Experiment name"
                />
                <select
                    bind:value={status}
                    class="text-xs font-semibold px-3 py-1 rounded-full border cursor-pointer {experimentStatusClasses(status)}"
                >
                    {#each statusOptions as opt}
                        <option value={opt}>{experimentStatusLabel(opt)}</option>
                    {/each}
                </select>
                <Button
                    onclick={save}
                    disabled={saving}
                    class="px-4 py-2 text-[13px] font-semibold"
                >
                    {saving ? "Saving..." : "Save"}
                </Button>
            </div>

            <!-- Description -->
            <div class="mb-5">
                <textarea
                    bind:value={description}
                    placeholder="Add a brief description..."
                    rows={2}
                    class="w-full text-sm text-slate-600 bg-transparent border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent resize-none"
                ></textarea>
            </div>
        </div>

        <!-- Content Editor -->
        <div class="px-4 sm:px-8 mb-6">
            <h3 class="text-sm font-semibold text-slate-700 mb-2">Content</h3>
            <div class="border border-slate-200 rounded-lg overflow-hidden">
                {#if EdraEditor}
                    {#if editor}
                        <svelte:component this={EdraToolBar} {editor} class="border-b border-slate-200" />
                    {/if}
                    <svelte:component
                        this={EdraEditor}
                        bind:editor
                        content={experiment.content && Object.keys(experiment.content).length > 0 ? experiment.content : undefined}
                        editable={true}
                        class="min-h-[200px] p-4"
                    />
                {:else}
                    <div class="p-4 text-sm text-slate-400 min-h-[200px] flex items-center justify-center">
                        Loading editor...
                    </div>
                {/if}
            </div>
        </div>

        <!-- Runs Section -->
        <div class="px-4 sm:px-8 mb-6">
            <div class="flex items-center justify-between mb-3">
                <h3 class="text-sm font-semibold text-slate-700">
                    Runs ({experiment.runs?.length ?? 0})
                </h3>
                <div class="flex gap-2">
                    <Button
                        variant="outline"
                        size="sm"
                        onclick={() => (showAddExistingModal = true)}
                    >
                        Add Existing
                    </Button>
                    <Button
                        size="sm"
                        onclick={() => (showRunModal = true)}
                    >
                        + New Run
                    </Button>
                </div>
            </div>

            <RunsTab
                runs={experiment.runs ?? []}
                {protocols}
                experiments={[]}
                hideExperimentColumn={true}
                hideExportColumn={true}
            />
        </div>

        <!-- Notes Section -->
        <div class="px-4 sm:px-8 pb-8">
            <h3 class="text-sm font-semibold text-slate-700 mb-3">
                Notes ({notes.length})
            </h3>

            {#if notes.length > 0}
                <div class="space-y-3 mb-4">
                    {#each notes as note (note.id)}
                        <div
                            class="bg-slate-50 border border-slate-200 rounded-lg p-3"
                            animate:flip={{ duration: listDuration() }}
                            in:fade={{ duration: listDuration() }}
                        >
                            <p class="text-sm text-slate-800">{note.content}</p>
                            <div
                                class="flex items-center gap-2 mt-2 text-xs text-slate-400"
                            >
                                <span class="font-medium"
                                    >{note.author_name}</span
                                >
                                <span>&middot;</span>
                                <span>{formatDate(note.created_at)}</span>
                                {#if note.flags?.length > 0}
                                    {#each note.flags as flag}
                                        <span
                                            class="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-[10px] font-medium"
                                            >{flag}</span
                                        >
                                    {/each}
                                {/if}
                            </div>
                        </div>
                    {/each}
                </div>
            {/if}

            <!-- Add note -->
            <div class="flex gap-2">
                <textarea
                    bind:value={newNote}
                    onkeydown={handleNoteKeydown}
                    placeholder="Add a note... (Cmd+Enter to submit)"
                    rows={2}
                    class="flex-1 px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent resize-none"
                ></textarea>
                <Button
                    onclick={addNote}
                    disabled={!newNote.trim() || submittingNote}
                    class="self-end"
                >
                    {submittingNote ? "..." : "Add"}
                </Button>
            </div>
        </div>
    </div>
{/if}

<!-- MODALS -->
{#if experiment}
    <RunCreatorWizardModal
        bind:open={showRunModal}
        projectId={experiment.project_id}
        {protocols}
        forExperiment={{ id: experiment.id, name: experiment.name }}
        onCreated={loadData}
    />
    <AddExistingRunModal
        bind:open={showAddExistingModal}
        experimentId={experiment.id}
        experimentName={experiment.name}
        runs={allProjectRuns}
        onAdded={loadData}
    />
{/if}
