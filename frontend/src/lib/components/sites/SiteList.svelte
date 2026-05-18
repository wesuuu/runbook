<script lang="ts">
    import type { Site } from '$lib/schemas/sites';

    interface Props {
        sites: (Site & { equipment_count?: number })[];
        activeId: string | null;
        canEdit: boolean;
        onSelect: (id: string) => void;
        onAdd: () => void;
    }

    let { sites, activeId, canEdit, onSelect, onAdd }: Props = $props();
</script>

<aside class="site-rail">
    <header>
        <span class="text-xs uppercase tracking-wide text-muted-foreground font-medium">Sites</span>
        {#if canEdit}
            <button
                class="text-xs px-2 py-1 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-all duration-150"
                onclick={onAdd}
            >
                + New
            </button>
        {/if}
    </header>
    <ul>
        {#each sites as s (s.id)}
            <li
                role="button"
                tabindex="0"
                class="site-rail-item cursor-pointer transition-all duration-150"
                class:active={s.id === activeId}
                onclick={() => onSelect(s.id)}
                onkeydown={(e) => { if (e.key === 'Enter') onSelect(s.id); }}
            >
                <span class="site-rail-pin"></span>
                <div class="flex-1">
                    <div class="site-name">{s.name}</div>
                    <div class="text-xs text-muted-foreground">{s.equipment_count ?? 0} equipment{s.archived_at ? ' · archived' : ''}</div>
                </div>
            </li>
        {/each}
    </ul>
</aside>

<style>
    .site-rail { border-right: 1px solid hsl(var(--border)); background: hsl(205 25% 98%); }
    .site-rail header { display: flex; align-items: center; justify-content: space-between; padding: .8rem 1rem; border-bottom: 1px solid hsl(var(--border)); }
    .site-rail ul { list-style: none; padding: .5rem; margin: 0; }
    .site-rail-item { display: flex; align-items: center; gap: .65rem; padding: .6rem .85rem; border-radius: .5rem; }
    .site-rail-item:hover { background: hsl(var(--muted)); }
    .site-rail-item.active { background: hsl(195 85% 22% / 0.08); }
    .site-rail-item.active .site-name { color: hsl(var(--primary)); font-weight: 600; }
    .site-rail-pin { width: .5rem; height: .5rem; border-radius: 9999px; background: hsl(var(--border)); }
    .site-rail-item.active .site-rail-pin { background: hsl(var(--primary)); }
</style>
