<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
    import { ChevronDown, Plus, FolderOpen } from 'lucide-svelte';

    interface Project {
        id: string;
        name: string;
        description?: string;
    }

    let projects = $state<Project[]>([]);
    let loading = $state(true);

    const isActive = $derived($page.url.pathname.startsWith('/projects'));

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
        <button
            class="flex items-center gap-1 {isActive ? 'text-foreground font-semibold' : 'text-muted-foreground'} hover:text-foreground transition-colors"
        >
            Projects
            <ChevronDown class="h-3.5 w-3.5 opacity-60" />
        </button>
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end" class="w-64" style="background-color: white; z-index: 100;">
        {#if loading}
            <div class="px-3 py-4 text-center text-sm text-muted-foreground">Loading...</div>
        {:else if projects.length === 0}
            <div class="px-3 py-4 text-center text-sm text-muted-foreground">No projects yet.</div>
        {:else}
            {#each projects as project}
                <DropdownMenu.Item onclick={() => goto(`/projects/${project.id}`)}>
                    <span class="flex items-center gap-2 w-full">
                        <FolderOpen class="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span class="truncate">{project.name}</span>
                    </span>
                </DropdownMenu.Item>
            {/each}
        {/if}
        <DropdownMenu.Separator />
        <DropdownMenu.Item onclick={() => goto('/projects')}>
            <span class="text-muted-foreground">View All Projects</span>
        </DropdownMenu.Item>
        <DropdownMenu.Item onclick={() => goto('/projects/new')}>
            <span class="flex items-center gap-2">
                <Plus class="h-4 w-4" />
                New Project
            </span>
        </DropdownMenu.Item>
    </DropdownMenu.Content>
</DropdownMenu.Root>
