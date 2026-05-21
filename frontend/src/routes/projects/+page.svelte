<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { fade } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { blockDuration, listDuration } from '$lib/transitions';
    import { api } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import { Button, buttonVariants } from '$lib/components/ui/button';
    import * as Table from '$lib/components/ui/table';
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
    import { ProjectListSchema, type Project } from '$lib/schemas';
    import { EmptyState } from '$lib/components/ui/empty-state';
    import TourModal from '$lib/onboarding/TourModal.svelte';
    import { markAllDismissed } from '$lib/onboarding/tourStore.svelte';

    let projects = $state<Project[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let welcomeOpen = $state(false);

    // The list is fetched scoped to the current org, so every row belongs to
    // it — show its name rather than the project's (unpopulated) relation,
    // which rendered a blanket "N/A" (#3).
    const orgName = $derived(getCurrentOrg()?.name ?? 'N/A');

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

    async function startProjectTourFromWelcome() {
        welcomeOpen = false;
        const { project_id } = await api.post<{ project_id: string }>(
            '/onboarding/tour/project/start', {},
        );
        goto(`/projects/${project_id}?tour=project`);
    }

    async function dismissWelcome() {
        welcomeOpen = false;
        await markAllDismissed();
    }

    onMount(loadProjects);
</script>

<div class="max-w-5xl mx-auto space-y-6">
    <div class="flex items-center justify-between">
        <div>
            <h1 class="text-3xl font-bold tracking-tight">Projects</h1>
            <p class="text-muted-foreground">
                Manage your scientific projects.
            </p>
        </div>
        <a href="/projects/new" class={buttonVariants()}>
            <Plus class="mr-2 h-4 w-4" /> New Project
        </a>
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
                            <a href="/projects/{project.id}" class="block py-3 px-1 min-h-11" animate:flip={{ duration: listDuration() }} in:fade={{ duration: listDuration() }}>
                                <div class="font-semibold text-sm text-primary">{project.name}</div>
                                {#if project.description}
                                    <div class="text-xs text-muted-foreground mt-1 line-clamp-2">{project.description}</div>
                                {/if}
                                <div class="text-xs text-muted-foreground mt-1">{orgName}</div>
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
                                    <Table.Head class="hidden md:table-cell">Organization</Table.Head>
                                    <Table.Head class="text-right">Actions</Table.Head>
                                </Table.Row>
                            </Table.Header>
                            <Table.Body>
                                {#each projects as project (project.id)}
                                    <Table.Row>
                                        <Table.Cell class="font-medium">
                                            <a
                                                href="/projects/{project.id}"
                                                class="font-semibold text-primary hover:underline"
                                            >
                                                {project.name}
                                            </a>
                                        </Table.Cell>
                                        <Table.Cell class="hidden md:table-cell">{project.description || '-'}</Table.Cell>
                                        <Table.Cell class="hidden md:table-cell">{orgName}</Table.Cell>
                                        <Table.Cell class="text-right">
                                            <a href="/projects/{project.id}">
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

<TourModal
    bind:open={welcomeOpen}
    title="Welcome to Batchrite"
    description="Want a quick tour of your workspace? Start with how projects are laid out."
    primaryLabel="Check out how projects are laid out"
    secondaryLabel="Dismiss"
    onPrimary={startProjectTourFromWelcome}
    onSecondary={dismissWelcome}
/>
