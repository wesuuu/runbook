<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { paths } from '$lib/paths';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import {
        getCurrentProjectSlug,
        setCurrentProjectSlug,
        clearCurrentProjectSlug,
    } from '$lib/project-context.svelte';
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

    const isActive = $derived(/\/projects(\/|$)/.test($page.url.pathname));

    const routeProjectSlug = $derived.by(() => {
        // Match /[org]/projects/[slug] — slug is the segment after /projects/.
        const match = $page.url.pathname.match(/\/projects\/([^/]+)/);
        const slug = match ? match[1] : null;
        return slug && slug !== 'new' ? slug : null;
    });

    // Persist the project the user last drilled into so the dropdown stays
    // "sticky" on routes that aren't project-scoped (e.g. settings, dashboard).
    // The inequality guard keeps this effect from re-writing localStorage on
    // every reactive run when the slug has not actually changed.
    $effect(() => {
        if (routeProjectSlug && routeProjectSlug !== getCurrentProjectSlug()) {
            setCurrentProjectSlug(routeProjectSlug);
        }
    });

    const activeProjectSlug = $derived(routeProjectSlug ?? getCurrentProjectSlug());

    const currentProject = $derived(
        activeProjectSlug
            ? (projects.find((p) => p.slug === activeProjectSlug) ?? null)
            : null
    );

    async function loadProjects() {
        loading = true;
        try {
            const org = getCurrentOrg();
            const query = org ? `?organization_id=${org.id}` : '';
            const res = await api.get<any>(`/projects${query}`);
            projects = Array.isArray(res) ? res : res.projects || [];
            // Self-heal a stale persisted slug: if the slug saved in
            // localStorage resolves to no loaded project (e.g. the project
            // was renamed and re-slugged), drop it so the dropdown stops
            // showing a phantom selection. A slug in the URL is
            // authoritative, so only heal when not on a project route.
            const persisted = getCurrentProjectSlug();
            if (
                !routeProjectSlug &&
                persisted &&
                !projects.some((p) => p.slug === persisted)
            ) {
                clearCurrentProjectSlug();
            }
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
        <DropdownMenu.Item onclick={() => goto(`${paths.projects()}?new=1`)}>
            <span class="flex items-center gap-2">
                <Plus class="h-4 w-4" />
                New Project
            </span>
        </DropdownMenu.Item>
    </DropdownMenu.Content>
</DropdownMenu.Root>
