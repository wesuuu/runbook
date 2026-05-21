<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { fade } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { blockDuration, listDuration } from '$lib/transitions';
    import { api } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import { paths } from '$lib/paths';
    import { Button } from '$lib/components/ui/button';
    import * as Table from '$lib/components/ui/table';
    import * as Dialog from '$lib/components/ui/dialog';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import { Textarea } from '$lib/components/ui/textarea';
    import {
        Card,
        CardContent,
        CardHeader,
        CardTitle,
        CardDescription,
    } from '$lib/components/ui/card';
    import { Plus } from 'lucide-svelte';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import ErrorAlert from '$lib/components/ui/error-alert.svelte';
    import { ProjectListSchema, ProjectSchema, type Project } from '$lib/schemas';
    import { EmptyState } from '$lib/components/ui/empty-state';
    import TourModal from '$lib/onboarding/TourModal.svelte';
    import { markAllDismissed } from '$lib/onboarding/tourStore.svelte';

    let projects = $state<Project[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let welcomeOpen = $state(false);

    // -- New Project dialog --
    let showCreateModal = $state(false);
    let newProjectName = $state('');
    let newProjectDescription = $state('');
    let creating = $state(false);
    let createError = $state<string | null>(null);

    async function loadProjects() {
        loading = true;
        try {
            const org = getCurrentOrg();
            const query = org ? `?organization_id=${org.id}` : '';
            const res = await api.get(`/projects${query}`, { schema: ProjectListSchema });
            projects = Array.isArray(res) ? res : [];
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            loading = false;
        }
    }

    async function createProject() {
        if (!newProjectName.trim()) return;
        creating = true;
        createError = null;
        try {
            const org = getCurrentOrg();
            const created = await api.post(
                '/projects',
                {
                    name: newProjectName.trim(),
                    description: newProjectDescription.trim() || null,
                    organization_id: org?.id,
                },
                { schema: ProjectSchema },
            );
            showCreateModal = false;
            newProjectName = '';
            newProjectDescription = '';
            goto(paths.project(created.slug));
        } catch (e: unknown) {
            createError = e instanceof Error ? e.message : 'An error occurred';
        } finally {
            creating = false;
        }
    }

    async function startProjectTourFromWelcome() {
        welcomeOpen = false;
        const { project_id } = await api.post<{ project_id: string }>(
            '/onboarding/tour/project/start', {},
        );
        const created = await api.get(`/projects/${project_id}`, { schema: ProjectSchema });
        goto(`${paths.project(created.slug)}?tour=project`);
    }

    async function dismissWelcome() {
        welcomeOpen = false;
        await markAllDismissed();
    }

    onMount(loadProjects);

    // Open the create dialog when arrived here via "New Project" elsewhere
    // (e.g. the ProjectsDropdown). The ?new param is stripped immediately so
    // a refresh or back-nav doesn't re-open the dialog (F-0091 L2).
    $effect(() => {
        if ($page.url.searchParams.get('new') !== null) {
            showCreateModal = true;
            const url = new URL($page.url);
            url.searchParams.delete('new');
            goto(url.pathname + url.search, {
                replaceState: true,
                keepFocus: true,
                noScroll: true,
            });
        }
    });
</script>

<div class="max-w-5xl mx-auto space-y-6">
    <div class="flex items-center justify-between">
        <div>
            <h1 class="text-3xl font-bold tracking-tight">Projects</h1>
            <p class="text-muted-foreground">
                Manage your scientific projects.
            </p>
        </div>
        <Button onclick={() => (showCreateModal = true)}>
            <Plus class="mr-2 h-4 w-4" /> New Project
        </Button>
    </div>

    {#if loading}
        <div in:fade={{ duration: blockDuration() }}>
            <LoadingSpinner message="Loading projects..." />
        </div>
    {:else if error}
        <div in:fade={{ duration: blockDuration() }}>
            <ErrorAlert message="Error: {error}" />
        </div>
    {:else}
        <div in:fade={{ duration: blockDuration() }}>
        <Card>
            <CardHeader>
                <CardTitle>All Projects</CardTitle>
                <CardDescription>A list of all projects in your organization.</CardDescription>
            </CardHeader>
            <CardContent>
                {#if projects.length === 0}
                    <EmptyState
                        title="No projects found"
                        description="Create one to get started."
                        secondaryActionLabel="Take the tour"
                        secondaryOnAction={() => (welcomeOpen = true)}
                    />
                {:else}
                    <!-- Mobile card layout -->
                    <div class="sm:hidden divide-y divide-border">
                        {#each projects as project (project.id)}
                            <a href={paths.project(project.slug)} class="block py-3 px-1 min-h-11" animate:flip={{ duration: listDuration() }} in:fade={{ duration: listDuration() }}>
                                <div class="font-semibold text-sm text-primary">{project.name}</div>
                                {#if project.description}
                                    <div class="text-xs text-muted-foreground mt-1 line-clamp-2">{project.description}</div>
                                {/if}
                            </a>
                        {/each}
                    </div>
                    <!-- Desktop table -->
                    <div class="hidden sm:block">
                        <Table.Root>
                            <Table.Caption>All projects in your organization.</Table.Caption>
                            <Table.Header>
                                <Table.Row>
                                    <Table.Head>Name</Table.Head>
                                    <Table.Head class="hidden md:table-cell">Description</Table.Head>
                                    <Table.Head class="text-right">Actions</Table.Head>
                                </Table.Row>
                            </Table.Header>
                            <Table.Body>
                                {#each projects as project (project.id)}
                                    <Table.Row>
                                        <Table.Cell class="font-medium">
                                            <a
                                                href={paths.project(project.slug)}
                                                class="font-semibold text-primary hover:underline"
                                            >
                                                {project.name}
                                            </a>
                                        </Table.Cell>
                                        <Table.Cell class="hidden md:table-cell">{project.description || '-'}</Table.Cell>
                                        <Table.Cell class="text-right">
                                            <a href={paths.project(project.slug)}>
                                                <Button variant="ghost" size="sm">View</Button>
                                            </a>
                                        </Table.Cell>
                                    </Table.Row>
                                {/each}
                            </Table.Body>
                        </Table.Root>
                    </div>
                {/if}
            </CardContent>
        </Card>
        </div>
    {/if}
</div>

<!-- NEW PROJECT MODAL -->
<Dialog.Root bind:open={showCreateModal}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>New Project</Dialog.Title>
            <Dialog.Description>Create a new project to organize your work.</Dialog.Description>
        </Dialog.Header>
        <div class="space-y-4">
            <div class="space-y-2">
                <Label for="new-project-name">Name</Label>
                <Input
                    id="new-project-name"
                    bind:value={newProjectName}
                    placeholder="My Project"
                />
            </div>
            <div class="space-y-2">
                <Label for="new-project-desc">Description</Label>
                <Textarea
                    id="new-project-desc"
                    bind:value={newProjectDescription}
                    placeholder="Describe the project..."
                />
            </div>
            {#if createError}
                <p class="text-sm text-red-600">{createError}</p>
            {/if}
        </div>
        <Dialog.Footer>
            <Button
                variant="secondary"
                onclick={() => {
                    showCreateModal = false;
                    newProjectName = '';
                    newProjectDescription = '';
                    createError = null;
                }}
            >
                Cancel
            </Button>
            <Button onclick={createProject} disabled={!newProjectName.trim() || creating}>
                {creating ? 'Creating...' : 'Create Project'}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<TourModal
    bind:open={welcomeOpen}
    title="Welcome to Batchrite"
    description="Want a quick tour of your workspace? Start with how projects are laid out."
    primaryLabel="Check out how projects are laid out"
    secondaryLabel="Dismiss"
    onPrimary={startProjectTourFromWelcome}
    onSecondary={dismissWelcome}
/>
