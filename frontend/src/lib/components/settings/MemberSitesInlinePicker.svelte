<script lang="ts">
    import { Badge } from '$lib/components/ui/badge';
    import type { Site } from '$lib/schemas/sites';

    interface Props {
        allSites: Site[];
        selectedSiteIds: string[];
        onChange: (next: string[]) => void;
        hasSiteManagerRole?: boolean;
    }

    let {
        allSites,
        selectedSiteIds,
        onChange,
        hasSiteManagerRole = false,
    }: Props = $props();

    let pickerOpen = $state(false);
    let search = $state('');

    const selectedSites = $derived(
        allSites.filter((s) => selectedSiteIds.includes(s.id)),
    );

    const candidates = $derived.by(() => {
        const q = search.trim().toLowerCase();
        return allSites
            .filter((s) => !s.archived_at)
            .filter((s) => !selectedSiteIds.includes(s.id))
            .filter((s) => (q ? s.name.toLowerCase().includes(q) : true));
    });

    const showInvalid = $derived(
        hasSiteManagerRole && selectedSiteIds.length === 0,
    );

    function remove(id: string) {
        onChange(selectedSiteIds.filter((sid) => sid !== id));
    }

    function add(id: string) {
        if (selectedSiteIds.includes(id)) return;
        onChange([...selectedSiteIds, id]);
        search = '';
        pickerOpen = false;
    }
</script>

<div class="space-y-2">
    {#if selectedSites.length > 0}
        <div class="flex flex-wrap items-center gap-1.5">
            {#each selectedSites as site (site.id)}
                <Badge variant="secondary" class="gap-1 pr-1">
                    <span>{site.name}</span>
                    <button
                        type="button"
                        aria-label={`Remove ${site.name}`}
                        class="ml-0.5 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full hover:bg-muted-foreground/20 cursor-pointer"
                        onclick={() => remove(site.id)}
                    >
                        <span class="text-xs leading-none">×</span>
                    </button>
                </Badge>
            {/each}
        </div>
    {/if}

    {#if showInvalid}
        <p class="text-xs text-destructive">
            Select at least one site for this manager.
        </p>
    {/if}

    {#if !pickerOpen}
        <button
            type="button"
            class="text-xs text-primary hover:underline cursor-pointer"
            onclick={() => (pickerOpen = true)}
        >
            + Add site
        </button>
    {:else}
        <div class="rounded-md border border-input bg-background p-2 space-y-1">
            <input
                type="text"
                placeholder="Search sites..."
                class="w-full rounded-sm border border-input bg-background px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                bind:value={search}
            />
            {#if candidates.length === 0}
                <p class="text-xs text-muted-foreground px-1 py-1">
                    No sites available.
                </p>
            {:else}
                <ul class="max-h-40 overflow-y-auto">
                    {#each candidates as site (site.id)}
                        <li>
                            <button
                                type="button"
                                class="w-full text-left text-xs px-2 py-1 rounded-sm hover:bg-muted cursor-pointer"
                                onclick={() => add(site.id)}
                            >
                                {site.name}
                            </button>
                        </li>
                    {/each}
                </ul>
            {/if}
            <div class="flex justify-end pt-1">
                <button
                    type="button"
                    class="text-xs text-muted-foreground hover:underline cursor-pointer"
                    onclick={() => {
                        pickerOpen = false;
                        search = '';
                    }}
                >
                    Cancel
                </button>
            </div>
        </div>
    {/if}
</div>
