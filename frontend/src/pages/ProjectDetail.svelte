<script lang="ts">
    import { onMount } from "svelte";
    import { api } from "../lib/api";
    import Link from "../lib/Link.svelte";
    import Modal from "$lib/components/Modal.svelte";
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
    import { Badge } from "$lib/components/ui/badge";

    let { params } = $props();

    let project = $state<any>(null);
    let protocols = $state<any[]>([]);
    let experiments = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);

    // -- Experiment Modal --
    let showExperimentModal = $state(false);
    let newExperimentName = $state("");

    // -- Form State for "New Project" mode --
    let form = $state({ name: "", description: "", organization_id: "" });
    let organizations = $state<any[]>([]);

    onMount(() => {
        if (params.id === "new") {
            loadCreateData();
        } else {
            loadData();
        }
    });

    async function loadData() {
        loading = true;
        try {
            if (params.id === "new") return;

            const [p, protos, exps] = await Promise.all([
                api.get(`/projects/${params.id}`),
                api.get(`/science/projects/${params.id}/protocols`),
                api.get(`/science/projects/${params.id}/experiments`),
            ]);

            project = p;
            protocols = protos as any[];
            experiments = exps as any[];
        } catch (e: any) {
            error = e.message;
        } finally {
            loading = false;
        }
    }

    async function createProtocol() {
        try {
            // Generate auto-incremented name
            const existingNames = protocols.map((p: any) => p.name);
            let name = "Untitled Protocol";
            if (existingNames.includes(name)) {
                let i = 2;
                while (existingNames.includes(`Untitled Protocol ${i}`)) {
                    i++;
                }
                name = `Untitled Protocol ${i}`;
            }

            const newProto: any = await api.post("/science/protocols", {
                name,
                project_id: project.id,
                description: "",
            });
            window.location.hash = `/protocols/${newProto.id}`;
        } catch (e: any) {
            alert(e.message);
            console.error(e);
        }
    }

    async function createExperiment() {
        if (!newExperimentName) return;

        try {
            const newExp: any = await api.post("/science/experiments", {
                name: newExperimentName,
                project_id: project.id,
            });
            showExperimentModal = false;
            newExperimentName = "";
            window.location.hash = `/experiments/${newExp.id}`;
        } catch (e: any) {
            alert(e.message);
            console.error(e);
        }
    }

    async function loadCreateData() {
        organizations = await api.get("/iam/organizations");
        if (organizations.length > 0)
            form.organization_id = organizations[0].id;
        loading = false;
    }

    async function saveNewProject() {
        try {
            await api.post("/projects", form);
            window.location.hash = "/projects";
        } catch (e: any) {
            alert(e.message);
        }
    }
</script>

<div class="max-w-5xl mx-auto py-8 px-4">
    {#if params.id === "new"}
        <!-- CREATE MODE -->
        <div class="max-w-xl mx-auto">
            <h1 class="text-3xl font-bold tracking-tight mb-6">New Project</h1>
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
    {:else if loading}
        <div class="text-center py-20 text-muted-foreground">
            Loading Dashboard...
        </div>
    {:else if error}
        <div class="bg-destructive/10 text-destructive p-4 rounded-md">
            Error: {error}
        </div>
    {:else if project}
        <!-- DASHBOARD MODE -->
        <div class="flex items-center justify-between mb-8">
            <div>
                <h1 class="text-3xl font-bold tracking-tight text-foreground">
                    {project.name}
                </h1>
                <p class="text-muted-foreground mt-1">
                    {project.description || "No description"}
                </p>
            </div>
            <div class="flex space-x-2">
                <!-- Actions -->
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <!-- PROTOCOLS -->
            <Card>
                <CardHeader
                    class="flex flex-row items-center justify-between space-y-0 pb-2"
                >
                    <div>
                        <CardTitle class="text-xl">Protocols</CardTitle>
                        <CardDescription
                            >Templates for your experiments</CardDescription
                        >
                    </div>
                    <Button
                        variant="outline"
                        size="sm"
                        onclick={createProtocol}
                    >
                        + New Protocol
                    </Button>
                </CardHeader>
                <CardContent>
                    {#if protocols.length === 0}
                        <div
                            class="text-sm text-muted-foreground italic py-4 text-center"
                        >
                            No protocols defined.
                        </div>
                    {:else}
                        <ul class="divide-y divide-border">
                            {#each protocols as proto}
                                <li
                                    class="py-3 flex justify-between items-center group"
                                >
                                    <Link
                                        to={`/protocols/${proto.id}`}
                                        class="font-medium hover:text-primary transition-colors"
                                    >
                                        {proto.name}
                                    </Link>
                                    <span class="text-xs text-muted-foreground">
                                        {new Date(
                                            proto.updated_at,
                                        ).toLocaleDateString()}
                                    </span>
                                </li>
                            {/each}
                        </ul>
                    {/if}
                </CardContent>
            </Card>

            <!-- EXPERIMENTS -->
            <Card>
                <CardHeader
                    class="flex flex-row items-center justify-between space-y-0 pb-2"
                >
                    <div>
                        <CardTitle class="text-xl">Experiments</CardTitle>
                        <CardDescription
                            >Executed runs of protocols</CardDescription
                        >
                    </div>
                    <Button
                        variant="outline"
                        size="sm"
                        onclick={() => (showExperimentModal = true)}
                    >
                        + New Experiment
                    </Button>
                </CardHeader>
                <CardContent>
                    {#if experiments.length === 0}
                        <div
                            class="text-sm text-muted-foreground italic py-4 text-center"
                        >
                            No experiments run.
                        </div>
                    {:else}
                        <ul class="divide-y divide-border">
                            {#each experiments as exp}
                                <li
                                    class="py-3 flex justify-between items-center group"
                                >
                                    <Link
                                        to={`/experiments/${exp.id}`}
                                        class="font-medium hover:text-primary transition-colors"
                                    >
                                        {exp.name}
                                    </Link>
                                    <Badge
                                        variant={exp.status === "COMPLETED"
                                            ? "default"
                                            : "secondary"}
                                    >
                                        {exp.status}
                                    </Badge>
                                </li>
                            {/each}
                        </ul>
                    {/if}
                </CardContent>
            </Card>
        </div>
    {/if}

    <!-- EXPERIMENT MODAL -->
    <Modal bind:open={showExperimentModal} title="New Experiment">
        <p class="text-sm text-gray-500 mb-4">
            Start a new experiment execution.
        </p>
        <div class="space-y-3">
            <div>
                <label
                    for="exp-name"
                    class="block text-sm font-medium text-gray-700 mb-1"
                    >Name</label
                >
                <input
                    id="exp-name"
                    type="text"
                    bind:value={newExperimentName}
                    placeholder="e.g. CHO-DG44 Run 1"
                    class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                />
            </div>
            <div class="flex justify-end gap-2 pt-2">
                <button
                    onclick={() => (showExperimentModal = false)}
                    class="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                >
                    Cancel
                </button>
                <button
                    onclick={createExperiment}
                    class="px-4 py-2 text-sm font-medium text-white bg-teal-600 rounded-lg hover:bg-teal-700 transition-colors"
                >
                    Create
                </button>
            </div>
        </div>
    </Modal>
</div>
