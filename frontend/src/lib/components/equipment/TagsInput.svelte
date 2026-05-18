<script lang="ts">
    interface Props {
        value: string[];
        suggestions: string[];
        onChange: (next: string[]) => void;
        placeholder?: string;
    }

    let { value, suggestions, onChange, placeholder = 'Add tag…' }: Props = $props();
    let draft = $state('');

    function normalize(raw: string): string {
        return raw.trim().toLowerCase()
            .replace(/\s+/g, '-')
            .replace(/[^a-z0-9-]+/g, '-')
            .replace(/-+/g, '-')
            .replace(/^-|-$/g, '')
            .slice(0, 40);
    }

    function commit() {
        const n = normalize(draft);
        if (!n || value.includes(n) || value.length >= 20) {
            draft = '';
            return;
        }
        onChange([...value, n]);
        draft = '';
    }

    function remove(tag: string) {
        onChange(value.filter((t) => t !== tag));
    }

    const matchingSuggestions = $derived(
        draft.length === 0
            ? []
            : suggestions.filter((s) => s.includes(normalize(draft)) && !value.includes(s)).slice(0, 6)
    );
</script>

<div class="tags-input">
    <div class="tags-chips">
        {#each value as t (t)}
            <span class="tag-chip">
                {t}
                <button type="button" aria-label="Remove {t}" onclick={() => remove(t)}>×</button>
            </span>
        {/each}
        <input
            class="tag-draft"
            type="text"
            bind:value={draft}
            {placeholder}
            onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } }}
            onblur={() => { if (draft) commit(); }}
        />
    </div>
    {#if matchingSuggestions.length > 0}
        <ul class="tags-suggestions">
            {#each matchingSuggestions as s (s)}
                <li><button type="button" onclick={() => { draft = s; commit(); }}>{s}</button></li>
            {/each}
        </ul>
    {/if}
</div>

<style>
    .tags-input { position: relative; }
    .tags-chips { display: flex; flex-wrap: wrap; gap: .3rem; padding: .4rem; border: 1px solid hsl(var(--border)); border-radius: var(--radius-md); background: white; }
    .tag-chip { display: inline-flex; align-items: center; gap: .3rem; padding: .15rem .5rem; background: hsl(205 25% 95%); border: 1px solid hsl(var(--border)); border-radius: 9999px; font-size: .75rem; }
    .tag-chip button { color: hsl(var(--muted-foreground)); cursor: pointer; background: none; border: 0; }
    .tag-draft { flex: 1; min-width: 6rem; border: 0; outline: none; background: transparent; font-size: .875rem; }
    .tags-suggestions { position: absolute; top: 100%; left: 0; right: 0; margin-top: .25rem; background: white; border: 1px solid hsl(var(--border)); border-radius: var(--radius-md); padding: .25rem 0; z-index: 10; }
    .tags-suggestions li button { width: 100%; text-align: left; padding: .35rem .75rem; background: none; border: 0; cursor: pointer; }
    .tags-suggestions li button:hover { background: hsl(205 25% 96%); }
</style>
