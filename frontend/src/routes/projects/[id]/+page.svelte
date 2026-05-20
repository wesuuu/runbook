<script lang="ts">
    import { page } from "$app/stores";
    import { goto } from "$app/navigation";
    import { api } from "$lib/api";
    import { getCurrentOrg } from "$lib/auth.svelte";
    import * as Dialog from "$lib/components/ui/dialog";
    import { Button } from "$lib/components/ui/button";
    import { Input } from "$lib/components/ui/input";
    import { Label } from "$lib/components/ui/label";
    import { Textarea } from "$lib/components/ui/textarea";
    import {
        Card,
        CardContent,
        CardDescription,
        CardFooter,
        CardHeader,
        CardTitle,
    } from "$lib/components/ui/card";
    import ProtocolsTab from "$lib/components/project/ProtocolsTab.svelte";
    import ExperimentsTab from "$lib/components/project/ExperimentsTab.svelte";
    import RunsTab from "$lib/components/project/RunsTab.svelte";
    import ActivityTab from "$lib/components/project/ActivityTab.svelte";
    import SettingsTab from "$lib/components/project/SettingsTab.svelte";
    import ProtocolImportModal from "$lib/components/modals/ProtocolImportModal.svelte";
    import RunCreatorWizardModal from "$lib/components/run/RunCreatorWizardModal.svelte";
    import BatchRecordImportModal from "$lib/components/modals/BatchRecordImportModal.svelte";
    import { HelpMenu, TourModal, runProjectTour } from "$lib/onboarding";
    import { shouldShowDot, markDismissed, isCompleted, isDismissed, isHydrated } from "$lib/onboarding/tourStore.svelte";
    import { fade } from "svelte/transition";
    import { blockDuration } from "$lib/transitions";

    const id = $derived($page.params.id ?? "");

    let project = $state<any>(null);
    let protocols = $state<any[]>([]);
    let runs = $state<any[]>([]);
    let experiments = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);

    // -- Tab State (derived from URL ?tab= param) --
    type TabName = "protocols" | "experiments" | "runs" | "activity" | "settings";
    const validTabs: TabName[] = ["protocols", "experiments", "runs", "activity", "settings"];

    const activeTab: TabName = $derived.by(() => {
        const t = $page.url.searchParams.get("tab");
        if (t && validTabs.includes(t as TabName)) return t as TabName;
        return "protocols";
    });

    function setTab(tab: TabName) {
        if (tab === activeTab) return;
        goto(`?tab=${tab}`, { replaceState: false, keepFocus: true, noScroll: true });
    }

    // -- Import Modal --
    let showImportModal = $state(false);

    // -- Batch Record Import --
    let showBatchImportModal = $state(false);

    // -- Run Modal --
    let showRunModal = $state(false);

    // -- Experiment Modal --
    let showExperimentModal = $state(false);
    let newExperimentName = $state("");
    let newExperimentDescription = $state("");

    // -- Form State for "New Project" mode --
    let form = $state({ name: "", description: "", organization_id: "" });
    let organizations = $state<any[]>([]);

    // -- Onboarding Tour --
    let projectTourModalOpen = $state(false);
    let projectTourAutoStarted = $state(false);

    function openProjectTourModal() {
        projectTourModalOpen = true;
    }

    function startProjectTour() {
        projectTourModalOpen = false;
        runProjectTour(() => {});
    }

    async function dismissProjectTour() {
        projectTourModalOpen = false;
        await markDismissed('project');
    }

    $effect(() => {
        const tour = $page.url.searchParams.get('tour');
        if (
            tour === 'project' &&
            !projectTourAutoStarted &&
            isHydrated() &&
            !isCompleted('project') &&
            !isDismissed('project')
        ) {
            projectTourAutoStarted = true;
            setTimeout(() => runProjectTour(() => {}), 300);
            // Strip the ?tour param so refreshing doesn't re-trigger the tour
            const url = new URL($page.url);
            url.searchParams.delete('tour');
            goto(url.pathname + url.search, {
                replaceState: true,
                keepFocus: true,
                noScroll: true,
            });
        } else if (tour === 'project' && isHydrated() && (isCompleted('project') || isDismissed('project'))) {
            // Already toured — clean up stale URL param without starting again
            const url = new URL($page.url);
            url.searchParams.delete('tour');
            goto(url.pathname + url.search, {
                replaceState: true,
                keepFocus: true,
                noScroll: true,
            });
        }
    });

    // -- Derived --
    const shortProjectId = $derived(
        project?.id ? "PRJ-" + project.id.slice(0, 6).toUpperCase() : "",
    );

    // Reload data whenever the project id changes
    $effect(() => {
        const currentId = id;
        project = null;
        protocols = [];
        runs = [];
        experiments = [];
        error = null;

        if (currentId === "new") {
            loadCreateData();
        } else {
            loadData();
        }
    });

    async function loadData() {
        loading = true;
        try {
            if (id === "new") return;

            const [p, protos, projectRuns, projectExperiments] = await Promise.all([
                api.get(`/projects/${id}`),
                api.get(`/projects/${id}/protocols`),
                api.get(`/projects/${id}/runs`),
                api.get(`/projects/${id}/experiments`),
            ]);

            project = p;
            protocols = protos as any[];
            runs = projectRuns as any[];
            experiments = projectExperiments as any[];
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            loading = false;
        }
    }

    async function reloadProtocols(showArchived: boolean) {
        try {
            const protocolsUrl = showArchived
                ? `/projects/${id}/protocols?include_archived=true`
                : `/projects/${id}/protocols`;
            const result = await api.get(protocolsUrl);
            protocols = result as any[];
        } catch (e: unknown) {
            console.error('Failed to reload protocols:', e instanceof Error ? e.message : e);
        }
    }

    async function createProtocol() {
        try {
            const existingNames = protocols.map((p: any) => p.name);
            let name = "Untitled Protocol";
            if (existingNames.includes(name)) {
                let i = 2;
                while (existingNames.includes(`Untitled Protocol ${i}`)) {
                    i++;
                }
                name = `Untitled Protocol ${i}`;
            }

            const newProto: any = await api.post("/protocols", {
                name,
                project_id: project.id,
                description: "",
            });
            goto(`/protocols/${newProto.id}`);
        } catch (e: unknown) {
            console.error(e instanceof Error ? e.message : e);
        }
    }

    async function createExperiment() {
        if (!newExperimentName) return;

        try {
            const newExp: any = await api.post("/experiments", {
                name: newExperimentName,
                project_id: project.id,
                description: newExperimentDescription || null,
            });
            showExperimentModal = false;
            newExperimentName = "";
            newExperimentDescription = "";
            goto(`/experiments/${newExp.id}`);
        } catch (e: unknown) {
            console.error(e instanceof Error ? e.message : e);
        }
    }

    async function loadCreateData() {
        const org = getCurrentOrg();
        organizations = await api.get("/iam/organizations");
        if (org) {
            form.organization_id = org.id;
        } else if (organizations.length > 0) {
            form.organization_id = organizations[0].id;
        }
        loading = false;
    }

    async function saveNewProject() {
        try {
            await api.post("/projects", form);
            goto("/projects");
        } catch (e: unknown) {
            console.error(e instanceof Error ? e.message : e);
        }
    }
</script>

{#if id === "new"}
    <!-- CREATE MODE -->
    <div class="max-w-4xl mx-auto py-8 px-4">
        <div class="max-w-xl mx-auto">
            <h1 class="text-3xl font-bold text-slate-900 mb-6">New Project</h1>
            <Card>
                <CardHeader>
                    <CardTitle>Project Details</CardTitle>
                    <CardDescription
                        >Create a new project to organize your work.</CardDescription
                    >
                </CardHeader>
                <CardContent class="space-y-4">
                    <div class="space-y-2">
                        <Label for="name">Name</Label>
                        <Input
                            id="name"
                            bind:value={form.name}
                            placeholder="My Project"
                        />
                    </div>
                    <div class="space-y-2">
                        <Label for="desc">Description</Label>
                        <Textarea
                            id="desc"
                            bind:value={form.description}
                            placeholder="Describe the project..."
                        />
                    </div>
                    <div class="space-y-2">
                        <Label for="org">Organization</Label>
                        <select
                            id="org"
                            bind:value={form.organization_id}
                            class="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {#each organizations as org}
                                <option value={org.id}>{org.name}</option>
                            {/each}
                        </select>
                    </div>
                </CardContent>
                <CardFooter>
                    <Button onclick={saveNewProject} class="w-full"
                        >Create Project</Button
                    >
                </CardFooter>
            </Card>
        </div>
    </div>
{:else if loading}
    <div
        in:fade={{ duration: blockDuration() }}
        class="flex items-center justify-center min-h-[calc(100vh-57px)] bg-gray-100 text-sm text-slate-400"
    >
        Loading project...
    </div>
{:else if error}
    <div
        in:fade={{ duration: blockDuration() }}
        class="max-w-xl mx-auto mt-8 p-4 bg-red-50 text-red-600 rounded-lg text-sm"
    >
        Error: {error}
    </div>
{:else if project}
    <!-- DASHBOARD MODE -->
    <div
        in:fade={{ duration: blockDuration() }}
        class="min-h-[calc(100vh-57px)] w-full mx-auto bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden"
    >
        <!-- Header -->
        <div class="flex justify-between items-start pt-5 sm:pt-7 px-4 sm:px-8">
            <div class="flex-1 min-w-0">
                <!-- Breadcrumb -->
                <nav class="flex items-center gap-2 mb-2.5 text-[13px]">
                    <a
                        href="/projects"
                        class="text-teal-600 font-medium hover:underline"
                        >Projects</a
                    >
                    <span class="text-slate-400">&rsaquo;</span>
                    <span class="text-slate-600 font-mono font-medium"
                        >{shortProjectId}</span
                    >
                </nav>

                <!-- Title + Badge -->
                <div class="flex items-center gap-3.5 mb-1.5">
                    <h1
                        class="text-[26px] font-bold text-slate-900 leading-tight"
                    >
                        {project.name}
                    </h1>
                    <span
                        class="text-xs font-semibold px-3 py-0.5 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-200 whitespace-nowrap"
                        >Active</span
                    >
                </div>

                <!-- Description -->
                {#if project.description}
                    <p class="text-sm text-slate-500 mb-3 leading-relaxed">
                        {project.description}
                    </p>
                {/if}

                <!-- Stats -->
                <div class="flex items-center gap-3 pb-5">
                    <div
                        class="flex items-center gap-1.5 text-[13px] text-slate-500 font-medium"
                    >
                        <svg
                            class="w-4 h-4 text-slate-400"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.5"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            ><path
                                d="M9.75 3.104v5.714a2.25 2.25 0 0 1-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 0 1 4.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0 1 12 15a9.065 9.065 0 0 0-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0 1 12 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5"
                            /></svg
                        >
                        <span
                            >{runs.length} Active Run{runs.length !== 1
                                ? "s"
                                : ""}</span
                        >
                    </div>
                    <span class="w-[3px] h-[3px] rounded-full bg-slate-300"
                    ></span>
                    <div
                        class="flex items-center gap-1.5 text-[13px] text-slate-500 font-medium"
                    >
                        <svg
                            class="w-4 h-4 text-slate-400"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.5"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            ><path
                                d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
                            /></svg
                        >
                        <span
                            >{protocols.length} Published Protocol{protocols.length !==
                            1
                                ? "s"
                                : ""}</span
                        >
                    </div>
                </div>
            </div>

            <!-- Action buttons -->
            <div class="shrink-0 flex gap-2.5 items-start pt-6">
                {#if activeTab === "experiments"}
                    <Button
                        size="sm"
                        onclick={() => (showExperimentModal = true)}
                    >
                        + New Experiment
                    </Button>
                {:else if activeTab === "runs"}
                    <Button
                        size="sm"
                        onclick={() => (showBatchImportModal = true)}
                    >
                        Import Batch Record
                    </Button>
                    <Button
                        size="sm"
                        onclick={() => (showRunModal = true)}
                    >
                        + New Run
                    </Button>
                {:else if activeTab === "protocols"}
                    <Button
                        size="sm"
                        onclick={() => (showImportModal = true)}
                    >
                        Import Protocol
                    </Button>
                    <Button
                        size="sm"
                        onclick={createProtocol}
                    >
                        + New Protocol
                    </Button>
                {/if}
                <HelpMenu dotVisible={shouldShowDot('project')} onTakeTour={openProjectTourModal} />
            </div>
        </div>

        <!-- Tab Navigation -->
        <nav class="flex px-4 sm:px-8 border-b border-gray-200 overflow-x-auto">
            {#each validTabs as tab}
                <Button
                    variant="tab"
                    data-active={activeTab === tab}
                    data-tour={`project-tab-${tab}`}
                    onclick={() => setTab(tab)}
                    class="px-5 py-3 -mb-px"
                >
                    {tab === "protocols" ? "Protocols" : tab === "experiments" ? "Experiments" : tab === "runs" ? "All Runs" : tab === "activity" ? "Activity" : "Settings"}
                </Button>
            {/each}
        </nav>

        <!-- Tab Content -->
        <div class="min-h-[300px]">
            {#if activeTab === "experiments"}
                <ExperimentsTab {experiments} {runs} {protocols} projectId={id} />
            {:else if activeTab === "runs"}
                <RunsTab {runs} {protocols} {experiments} onDataChanged={loadData} />
            {:else if activeTab === "protocols"}
                <ProtocolsTab
                    projectId={id}
                    {protocols}
                    onReloadProtocols={reloadProtocols}
                    onCreateProtocol={createProtocol}
                    onImportProtocol={() => (showImportModal = true)}
                />
            {:else if activeTab === "activity"}
                <ActivityTab projectId={id} />
            {:else if activeTab === "settings"}
                <SettingsTab
                    projectId={id}
                    {project}
                    onProjectUpdated={(updated) => { project = updated; }}
                />
            {/if}
        </div>
    </div>
{/if}

<!-- BATCH RECORD IMPORT MODAL -->
<BatchRecordImportModal
    bind:open={showBatchImportModal}
    projectId={id}
    {protocols}
    onSuccess={(runId) => {
        loadData();
        goto(`/runs/${runId}`);
    }}
/>

<!-- IMPORT PROTOCOL MODAL -->
<ProtocolImportModal
    bind:open={showImportModal}
    preselectedProjectId={id !== 'new' ? id : undefined}
    onSuccess={(protocolId) => {
        loadData();
        goto(`/protocols/${protocolId}`);
    }}
/>

<!-- RUN MODAL -->
<RunCreatorWizardModal
    bind:open={showRunModal}
    projectId={id}
    {protocols}
    {experiments}
/>

<!-- EXPERIMENT MODAL -->
<Dialog.Root bind:open={showExperimentModal}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>New Experiment</Dialog.Title>
            <Dialog.Description>Create an experiment to organize related runs.</Dialog.Description>
        </Dialog.Header>
        <div class="space-y-3">
            <div>
                <label
                    for="experiment-name"
                    class="block text-sm font-medium text-gray-700 mb-1">Name</label
                >
                <input
                    id="experiment-name"
                    type="text"
                    bind:value={newExperimentName}
                    placeholder="e.g. Effect of MOI on transduction"
                    class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                />
            </div>
            <div>
                <label
                    for="experiment-desc"
                    class="block text-sm font-medium text-gray-700 mb-1"
                    >Description <span class="text-slate-400 font-normal">(optional)</span></label
                >
                <textarea
                    id="experiment-desc"
                    bind:value={newExperimentDescription}
                    placeholder="Brief description of what you're investigating..."
                    rows={3}
                    class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent resize-none"
                ></textarea>
            </div>
        </div>
        <Dialog.Footer>
            <Button
                variant="secondary"
                onclick={() => {
                    showExperimentModal = false;
                    newExperimentName = "";
                    newExperimentDescription = "";
                }}
            >
                Cancel
            </Button>
            <Button
                onclick={createExperiment}
                disabled={!newExperimentName}
            >
                Create
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<!-- PROJECT TOUR MODAL -->
<TourModal
    bind:open={projectTourModalOpen}
    title="Tour: how projects are laid out"
    description="A quick 5-step walkthrough of the project tabs."
    primaryLabel="Take tour"
    secondaryLabel="Dismiss"
    onPrimary={startProjectTour}
    onSecondary={dismissProjectTour}
/>
