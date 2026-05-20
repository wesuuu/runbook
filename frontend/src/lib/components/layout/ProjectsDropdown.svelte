<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { paths } from '$lib/paths';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import { getCurrentProjectId, setCurrentProjectId } from '$lib/project-context.svelte';
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
    import { Button } from '$lib/components/ui/button';
    import { ChevronDown, Plus, FolderOpen } from 'lucide-svelte';

    interface Project {
        id: string;
        slug: string;
        name: string;
        description?: string;
    }

    let projects = $state<Project[]>([]);
    let loading = $state(true);

    const isActive = $derived($page.url.pathname.startsWith('/projects'));
    const routeProjectId = $derived.by(() => {
        const match = $page.url.pathname.match(/^\/projects\/([^/]+)/);
        const id = match ? match[1] : null;
        return id && id !== 'new' ? id : null;
    });

    // Persist the project context whenever the URL exposes one. Sticky across
    // navigation to non-project routes (protocols, runs, etc.).
    $effect(() => {
        if (routeProjectId && routeProjectId !== getCurrentProjectId()) {
            setCurrentProjectId(routeProjectId);
        }
    });

    const activeProjectId = $derived(routeProjectId ?? getCurrentProjectId());
    const currentProject = $derived(
        activeProjectId ? projects.find((p) => p.id === activeProjectId) ?? null : null
    );

    async function loadProjects() {
        loading = true;
        try {
            const org = getCurrentOrg();
            const query = org ? `?organization_id=${org.id}` : '';
            const res = await api.get<any>(`/projects${query}`);
            projects = Array.isArray(res) ? res : res.projects || [];
        } catch {
            projects = [];
        } finally {
            loading = false;
        }
    }

    onMount(loadProjects);
</script>

<DropdownMenu.Root>
    <DropdownMenu.Trigger>
        <Button
            variant="ghost"
            size="sm"
            class="h-auto px-0 py-0 gap-1.5 hover:bg-transparent hover:text-foreground {isActive ? 'text-foreground font-semibold' : 'text-muted-foreground'}"
        >
            {#if currentProject}
                <FolderOpen class="h-3.5 w-3.5 shrink-0" />
                <span class="max-w-[16ch] truncate" title={currentProject.name}>
                    {currentProject.name}
                </span>
            {:else}
                Projects
            {/if}
            <ChevronDown class="h-3.5 w-3.5 opacity-60" />
        </Button>
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end" class="w-64" style="background-color: white; z-index: 100;">
        {#if loading}
            <div class="px-3 py-4 text-center text-sm text-muted-foreground">Loading...</div>
        {:else if projects.length === 0}
            <div class="px-3 py-4 text-center text-sm text-muted-foreground">No projects yet.</div>
        {:else}
            {#each projects as project}
                <DropdownMenu.Item onclick={() => goto(paths.project(project.slug))}>
                    <span class="flex items-center gap-2 w-full">
                        <FolderOpen class="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span class="truncate">{project.name}</span>
                    </span>
                </DropdownMenu.Item>
            {/each}
        {/if}
        <DropdownMenu.Separator />
        <DropdownMenu.Item onclick={() => goto(paths.projects())}>
            <span class="text-muted-foreground">View All Projects</span>
        </DropdownMenu.Item>
        <DropdownMenu.Item onclick={() => goto(paths.projects())}>
            <span class="flex items-center gap-2">
                <Plus class="h-4 w-4" />
                New Project
            </span>
        </DropdownMenu.Item>
    </DropdownMenu.Content>
</DropdownMenu.Root>
