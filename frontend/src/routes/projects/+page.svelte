<script lang="ts">
    import { onMount } from 'svelte';
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

    interface Project {
        id: string;
        name: string;
        description?: string;
        organization?: { name: string };
    }

    let projects = $state<Project[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);

    async function loadProjects() {
        loading = true;
        try {
            const org = getCurrentOrg();
            const query = org ? `?organization_id=${org.id}` : '';
            const res = await api.get<any>(`/projects${query}`);
            projects = Array.isArray(res) ? res : res.projects || [];
        } catch (e: any) {
            error = e.message;
        } finally {
            loading = false;
        }
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
        <div class="text-center py-10 text-muted-foreground">
            Loading projects...
        </div>
    {:else if error}
        <div class="bg-destructive/10 text-destructive p-4 rounded-md">
            Error: {error}
        </div>
    {:else}
        <Card>
            <CardHeader>
                <CardTitle>All Projects</CardTitle>
                <CardDescription>A list of all projects in your organization.</CardDescription>
            </CardHeader>
            <CardContent>
                {#if projects.length === 0}
                    <div class="text-center py-10 text-muted-foreground">
                        No projects found. Create one to get started.
                    </div>
                {:else}
                    <Table.Root>
                        <Table.Caption>A list of your recent projects.</Table.Caption>
                        <Table.Header>
                            <Table.Row>
                                <Table.Head>Name</Table.Head>
                                <Table.Head>Description</Table.Head>
                                <Table.Head>Organization</Table.Head>
                                <Table.Head class="text-right">Actions</Table.Head>
                            </Table.Row>
                        </Table.Header>
                        <Table.Body>
                            {#each projects as project}
                                <Table.Row>
                                    <Table.Cell class="font-medium">
                                        <a
                                            href="/projects/{project.id}"
                                            class="font-semibold text-primary hover:underline"
                                        >
                                            {project.name}
                                        </a>
                                    </Table.Cell>
                                    <Table.Cell>{project.description || '-'}</Table.Cell>
                                    <Table.Cell>{project.organization?.name || 'N/A'}</Table.Cell>
                                    <Table.Cell class="text-right">
                                        <a href="/projects/{project.id}">
                                            <Button variant="ghost" size="sm">View</Button>
                                        </a>
                                    </Table.Cell>
                                </Table.Row>
                            {/each}
                        </Table.Body>
                    </Table.Root>
                {/if}
            </CardContent>
        </Card>
    {/if}
</div>
