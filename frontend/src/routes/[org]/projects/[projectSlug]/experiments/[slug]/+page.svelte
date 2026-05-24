<script lang="ts">
    import { page } from "$app/stores";
    import { goto } from "$app/navigation";
    import { onMount, onDestroy } from "svelte";
    import { toast } from "svelte-sonner";
    import { api } from "$lib/api";
    import { getUser, getCurrentOrgRoles } from "$lib/auth.svelte";
    import { Button } from "$lib/components/ui/button";
    import { Input } from "$lib/components/ui/input";
    import { Textarea } from "$lib/components/ui/textarea";
    import { Trash2, X } from "lucide-svelte";

    const EXPERIMENT_NAME_MAX = 200;
    const EXPERIMENT_DESCRIPTION_MAX = 5000;
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import ErrorAlert from '$lib/components/ui/error-alert.svelte';
    import RunCreatorWizardModal from "$lib/components/run/RunCreatorWizardModal.svelte";
    import AddExistingRunModal from "$lib/components/project/AddExistingRunModal.svelte";
    import RunsTab from "$lib/components/project/RunsTab.svelte";
    import ConditionsTable from "$lib/components/experiment/ConditionsTable.svelte";
    import KeyResultsTable from "$lib/components/experiment/KeyResultsTable.svelte";
    import KeyResultsChart from "$lib/components/experiment/KeyResultsChart.svelte";
    import ConclusionCard from "$lib/components/experiment/ConclusionCard.svelte";
    import ObservationsTimeline from "$lib/components/experiment/ObservationsTimeline.svelte";
    import {
        ObservationsResponseSchema,
        type ObservationItem,
    } from "$lib/schemas/observation";
    import { ExperimentSchema } from "$lib/schemas/experiments";
    import {
        shortId,
        formatDate,
        experimentStatusClasses,
        experimentStatusLabel,
    } from "$lib/components/project/projectUtils";
    import { fade } from "svelte/transition";
    import { flip } from "svelte/animate";
    import { blockDuration, listDuration } from "$lib/transitions";
    import { paths } from "$lib/paths";

    // Route params: experiments nest under their project (F-0091). The
    // experiment is fetched by project slug + experiment slug; once loaded,
    // `id` resolves to the experiment's real UUID for sub-resource endpoints
    // and updates.
    const projectSlug = $derived($page.params.projectSlug ?? "");
    const slug = $derived($page.params.slug ?? "");

    let experiment = $state<any>(null);
    const id = $derived(experiment?.id ?? "");
    let project = $state<any>(null);
    let protocols = $state<any[]>([]);
    let loading = $state(true);
    let saving = $state(false);
    let error = $state<string | null>(null);
    let saveError = $state<string | null>(null);
    let noteError = $state<string | null>(null);

    // Editable fields
    let name = $state("");
    let description = $state("");

    // Objective block
    let objective = $state("");
    let successCriteria = $state<string[]>([]);
    let editingObjective = $state(false);
    let objectiveError = $state<string | null>(null);

    // Notes
    let notes = $state<any[]>([]);
    let newNote = $state("");
    let submittingNote = $state(false);

    // Run modals
    let showRunModal = $state(false);
    let showAddExistingModal = $state(false);
    let allProjectRuns = $state<any[]>([]);

    $effect(() => {
        const ps = projectSlug;
        const s = slug;
        if (ps && s) loadData();
    });

    async function loadData() {
        loading = true;
        error = null;
        try {
            experiment = await api.get(
                `/experiments/by-slug/${projectSlug}/${slug}`,
            );
            name = experiment.name;
            description = experiment.description ?? "";
            objective = experiment.objective ?? "";
            successCriteria = [...(experiment.success_criteria ?? [])];
            notes = experiment.notes ?? [];

            // Load project, protocols, and all runs for breadcrumb and modals
            const [proj, protos, projectRuns] = await Promise.all([
                api.get(`/projects/${experiment.project_id}`),
                api.get(`/projects/${experiment.project_id}/protocols`),
                api.get(`/projects/${experiment.project_id}/runs`),
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

    const trimmedName = $derived(name.trim());
    const nameInvalid = $derived(
        trimmedName.length === 0 || name.length > EXPERIMENT_NAME_MAX,
    );
    const descriptionInvalid = $derived(
        description.length > EXPERIMENT_DESCRIPTION_MAX,
    );
    const currentUserId = $derived(getUser()?.id ?? null);

    async function save() {
        if (nameInvalid) {
            saveError =
                trimmedName.length === 0
                    ? 'Name is required.'
                    : `Name must be ${EXPERIMENT_NAME_MAX} characters or fewer.`;
            return;
        }
        if (descriptionInvalid) {
            saveError = `Description must be ${EXPERIMENT_DESCRIPTION_MAX} characters or fewer.`;
            return;
        }
        saving = true;
        saveError = null;
        try {
            await api.put(`/experiments/${id}`, {
                name: trimmedName,
                description: description || null,
            });
            experiment.name = trimmedName;
            experiment.description = description;
            name = trimmedName;
        } catch (e: unknown) {
            saveError = e instanceof Error ? e.message : 'Failed to save changes.';
        } finally {
            saving = false;
        }
    }

    async function deleteNote(noteId: string) {
        try {
            await api.delete(`/experiments/${id}/notes/${noteId}`);
            notes = notes.filter((n) => n.id !== noteId);
        } catch (e: unknown) {
            noteError = e instanceof Error ? e.message : 'Failed to delete note.';
        }
    }

    function cancelObjectiveEdit() {
        objective = experiment?.objective ?? "";
        successCriteria = [...(experiment?.success_criteria ?? [])];
        objectiveError = null;
        editingObjective = false;
    }

    async function saveObjective() {
        saving = true;
        objectiveError = null;
        try {
            // TODO(F-0093 follow-up): type api.put return when ExperimentSchema covers lifecycle/objective fields.
            const updated: any = await api.put(`/experiments/${id}`, {
                objective: objective.trim() || null,
                success_criteria: successCriteria.map((c) => c.trim()).filter(Boolean),
            });
            // PUT returns runs=[] for performance; preserve the existing runs
            // so the Conditions table and key-results chart don't go blank.
            experiment = { ...updated, runs: experiment?.runs ?? [] };
            objective = updated.objective ?? "";
            successCriteria = [...(updated.success_criteria ?? [])];
            editingObjective = false;
        } catch (e: unknown) {
            objectiveError = e instanceof Error ? e.message : "Failed to save objective.";
        } finally {
            saving = false;
        }
    }

    async function addNote() {
        const content = newNote.trim();
        if (!content) return;
        submittingNote = true;
        noteError = null;
        try {
            const note = await api.post(
                `/experiments/${id}/notes`,
                { content, flags: [] },
            );
            notes = [...notes, note as any];
            newNote = "";
        } catch (e: unknown) {
            noteError = e instanceof Error ? e.message : 'Failed to add note.';
        } finally {
            submittingNote = false;
        }
    }

    function handleNoteKeydown(e: KeyboardEvent) {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            addNote();
        }
    }

    // F-0043: observations timeline + key-results/conclusion wiring
    let observations = $state<ObservationItem[]>([]);
    let observationsTruncated = $state(false);
    let observationsLoading = $state(true);
    let observationsError = $state<string | null>(null);

    async function loadObservations() {
        if (!id) return;
        observationsLoading = true;
        observationsError = null;
        try {
            const res = await api.get(
                `/experiments/${id}/observations`,
                { schema: ObservationsResponseSchema },
            );
            observations = res.items;
            observationsTruncated = res.truncated;
        } catch (err) {
            observationsError =
                err instanceof Error ? err.message : 'Failed to load observations';
        } finally {
            observationsLoading = false;
        }
    }

    async function refetchExperiment() {
        if (!id) return;
        try {
            experiment = await api.get(
                `/experiments/${id}`,
                { schema: ExperimentSchema },
            );
        } catch {
            // swallow background refresh errors
        }
    }

    function onVisible() {
        if (document.visibilityState === 'visible') {
            loadObservations();
            refetchExperiment();
        }
    }

    // Once `experiment` is loaded the first time, hydrate observations and
    // start listening for tab-focus refreshes.
    let observationsBooted = false;
    $effect(() => {
        if (id && !observationsBooted) {
            observationsBooted = true;
            loadObservations();
        }
    });

    onMount(() => {
        document.addEventListener('visibilitychange', onVisible);
    });
    onDestroy(() => {
        document.removeEventListener('visibilitychange', onVisible);
    });

    const runs = $derived((experiment?.runs ?? []) as any[]);
    const hasOpenRuns = $derived(
        runs.some((r: any) => ['PLANNED', 'ACTIVE', 'EDITED'].includes(r.status)),
    );
    const canAdmin = $derived(getCurrentOrgRoles().includes('ADMIN'));

    async function saveConclusion(next: string) {
        try {
            const updated = await api.put(
                `/experiments/${id}`,
                { conclusion: next },
                { schema: ExperimentSchema },
            );
            // PUT returns runs=[] for performance; preserve existing runs.
            experiment = { ...updated, runs: experiment?.runs ?? [] };
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Failed to save conclusion');
        }
    }

    async function lockConclusion() {
        try {
            const updated = await api.post(
                `/experiments/${id}/conclusion/lock`,
                {},
                { schema: ExperimentSchema },
            );
            // lock/unlock return runs=[] for performance; preserve existing runs.
            experiment = { ...updated, runs: experiment?.runs ?? [] };
            loadObservations();
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Failed to lock conclusion');
        }
    }

    async function unlockConclusion(reason: string) {
        try {
            const updated = await api.post(
                `/experiments/${id}/conclusion/unlock`,
                { reason },
                { schema: ExperimentSchema },
            );
            // lock/unlock return runs=[] for performance; preserve existing runs.
            experiment = { ...updated, runs: experiment?.runs ?? [] };
            loadObservations();
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Failed to unlock conclusion');
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
        class="min-h-[calc(100vh-57px)] w-full mx-auto bg-background rounded-xl border border-border shadow-sm overflow-hidden"
    >
        <!-- Header -->
        <div class="pt-5 sm:pt-7 px-4 sm:px-8">
            <!-- Breadcrumb -->
            <nav class="flex items-center gap-2 mb-2.5 text-[13px]">
                <a
                    href={paths.projects()}
                    class="text-primary font-medium hover:underline"
                    >Projects</a
                >
                <span class="text-muted-foreground">&rsaquo;</span>
                {#if project}
                    <a
                        href={paths.project(projectSlug)}
                        class="text-primary font-medium hover:underline"
                        >{project.name}</a
                    >
                {:else}
                    <span class="text-muted-foreground">...</span>
                {/if}
                <span class="text-muted-foreground">&rsaquo;</span>
                <span class="text-muted-foreground font-mono font-medium"
                    >EXP-{shortId(experiment.id)}</span
                >
            </nav>

            <!-- Name + Status + Save -->
            <div class="flex items-center gap-3.5 mb-3">
                <input
                    type="text"
                    bind:value={name}
                    maxlength={EXPERIMENT_NAME_MAX}
                    aria-invalid={nameInvalid}
                    class="text-[26px] font-bold text-foreground leading-tight bg-transparent border-b outline-none focus:ring-0 p-0 flex-1 min-w-0 {nameInvalid
                        ? 'border-destructive'
                        : 'border-transparent'}"
                    placeholder="Experiment name"
                />
                <span
                    class="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold cursor-help {experimentStatusClasses(
                        experiment?.lifecycle_status ?? 'DRAFT',
                    )}"
                    title="Status is derived from this experiment's runs — add or complete runs to advance it."
                >
                    {experimentStatusLabel(experiment?.lifecycle_status ?? 'DRAFT')}
                    <span class="opacity-70 font-normal">(auto)</span>
                </span>
                <Button
                    onclick={save}
                    disabled={saving || nameInvalid || descriptionInvalid}
                    class="px-4 py-2 text-[13px] font-semibold"
                >
                    {saving ? "Saving..." : "Save name & description"}
                </Button>
            </div>

            {#if saveError}
                <p class="mb-3 text-sm text-destructive">{saveError}</p>
            {/if}

            <!-- Description -->
            <div class="mb-5">
                <Textarea
                    bind:value={description}
                    placeholder="Add a brief description..."
                    rows={2}
                    maxlength={EXPERIMENT_DESCRIPTION_MAX}
                    aria-invalid={descriptionInvalid}
                    class="resize-none {descriptionInvalid ? 'border-destructive' : ''}"
                />
                {#if description.length > EXPERIMENT_DESCRIPTION_MAX * 0.9}
                    <p
                        class="mt-1 text-xs {descriptionInvalid
                            ? 'text-destructive'
                            : 'text-muted-foreground'}"
                    >
                        {description.length} / {EXPERIMENT_DESCRIPTION_MAX}
                    </p>
                {/if}
            </div>
        </div>

        <div class="experiment-grid px-4 sm:px-8 pb-8">
        <div class="main-col flex flex-col gap-6 min-w-0">
        <!-- Objective -->
        <div>
            <div class="rounded-lg border border-border bg-card p-5">
                <div class="mb-3 flex items-center justify-between">
                    <h3 class="text-sm font-semibold text-foreground">Objective</h3>
                    {#if !editingObjective}
                        <Button
                            variant="ghost"
                            size="sm"
                            class="min-h-11"
                            onclick={() => (editingObjective = true)}
                        >
                            Edit
                        </Button>
                    {/if}
                </div>

                {#if editingObjective}
                    <div class="space-y-4">
                        <div class="space-y-1.5">
                            <label class="text-xs font-medium text-muted-foreground" for="obj">
                                The question
                            </label>
                            <Textarea id="obj" bind:value={objective} rows={3} />
                        </div>
                        <div class="space-y-1.5">
                            <span class="text-xs font-medium text-muted-foreground">
                                Success criteria
                            </span>
                            {#each successCriteria as _, i}
                                <div class="flex items-center gap-2">
                                    <Input bind:value={successCriteria[i]} placeholder="Criterion" />
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        class="shrink-0"
                                        aria-label="Remove criterion"
                                        onclick={() =>
                                            (successCriteria = successCriteria.filter(
                                                (_, j) => j !== i,
                                            ))}
                                    >
                                        <X class="h-4 w-4" />
                                    </Button>
                                </div>
                            {/each}
                            <Button
                                variant="outline"
                                size="sm"
                                onclick={() => (successCriteria = [...successCriteria, ''])}
                            >
                                + Add criterion
                            </Button>
                        </div>
                        {#if objectiveError}
                            <p class="text-sm text-destructive">{objectiveError}</p>
                        {/if}
                        <div class="flex justify-end gap-2">
                            <Button variant="ghost" onclick={cancelObjectiveEdit}>Cancel</Button>
                            <Button onclick={saveObjective} disabled={saving}>
                                {saving ? 'Saving…' : 'Save objective'}
                            </Button>
                        </div>
                    </div>
                {:else if objective}
                    <div class="space-y-3">
                        <div>
                            <p class="text-xs font-medium text-muted-foreground">The question</p>
                            <p class="mt-0.5 text-sm text-foreground">{objective}</p>
                        </div>
                        {#if successCriteria.length > 0}
                            <div>
                                <p class="text-xs font-medium text-muted-foreground">
                                    Success criteria
                                </p>
                                <ul class="mt-1 list-inside list-disc space-y-0.5 text-sm text-foreground">
                                    {#each successCriteria as c}
                                        <li>{c}</li>
                                    {/each}
                                </ul>
                            </div>
                        {/if}
                    </div>
                {:else}
                    <p class="text-sm italic text-muted-foreground">
                        Objective not set yet — add an objective and the first run to begin.
                    </p>
                {/if}
            </div>
        </div>

        <!-- F-0043: Conditions matrix -->
        <ConditionsTable {runs} />

        <!-- F-0043: Key results table + chart -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <KeyResultsTable {runs} />
            <KeyResultsChart {runs} experimentId={experiment.id} />
        </div>

        <!-- F-0043: Conclusion card -->
        <ConclusionCard
            {experiment}
            {hasOpenRuns}
            {canAdmin}
            onSave={saveConclusion}
            onLock={lockConclusion}
            onUnlock={unlockConclusion}
        />

        <!-- Runs Section -->
        <div>
            <div class="flex items-center justify-between mb-3">
                <h3 class="text-sm font-semibold text-foreground">
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
        <div>
            <h3 class="text-sm font-semibold text-foreground mb-3">
                Notes ({notes.length})
            </h3>

            {#if notes.length > 0}
                <div class="space-y-3 mb-4">
                    {#each notes as note (note.id)}
                        <div
                            class="bg-muted border border-border rounded-lg p-3 group"
                            animate:flip={{ duration: listDuration() }}
                            in:fade={{ duration: listDuration() }}
                        >
                            <div class="flex items-start justify-between gap-2">
                                <p class="text-sm text-foreground flex-1 min-w-0 break-words">
                                    {note.content}
                                </p>
                                {#if currentUserId && note.author_id === currentUserId}
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        class="h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                                        aria-label="Delete note"
                                        title="Delete note"
                                        onclick={() => deleteNote(note.id)}
                                    >
                                        <Trash2 class="h-3.5 w-3.5" />
                                    </Button>
                                {/if}
                            </div>
                            <div
                                class="flex items-center gap-2 mt-2 text-xs text-muted-foreground"
                            >
                                <span class="font-medium"
                                    >{note.author_name}</span
                                >
                                <span>&middot;</span>
                                <span>{formatDate(note.created_at)}</span>
                                {#if note.flags?.length > 0}
                                    {#each note.flags as flag}
                                        <span
                                            class="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-[10px] font-medium dark:bg-amber-500/20 dark:text-amber-300"
                                            >{flag}</span
                                        >
                                    {/each}
                                {/if}
                            </div>
                        </div>
                    {/each}
                </div>
            {/if}

            {#if noteError}
                <p class="mb-2 text-sm text-destructive">{noteError}</p>
            {/if}

            <!-- Add note -->
            <div class="flex gap-2">
                <Textarea
                    bind:value={newNote}
                    onkeydown={handleNoteKeydown}
                    placeholder="Add a note... (Cmd+Enter to submit)"
                    rows={2}
                    class="flex-1 resize-none"
                />
                <Button
                    onclick={addNote}
                    disabled={!newNote.trim() || submittingNote}
                    class="self-end"
                >
                    {submittingNote ? "..." : "Add"}
                </Button>
            </div>
        </div>
        </div><!-- /main-col -->

        <aside class="observations-col min-w-0 self-start">
            {#if observationsError}
                <div class="p-3 mb-2 border rounded bg-destructive/10 text-destructive text-sm">
                    {observationsError}
                    <button class="underline ml-2" onclick={loadObservations}>Retry</button>
                </div>
            {/if}
            <ObservationsTimeline
                items={observations}
                truncated={observationsTruncated}
                loading={observationsLoading}
            />
        </aside>
        </div><!-- /experiment-grid -->
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

<style>
    .experiment-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 1rem;
    }
    @media (min-width: 1024px) {
        .experiment-grid {
            grid-template-columns: minmax(0, 1fr) 320px;
        }
    }
</style>
