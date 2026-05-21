<script lang="ts">
    interface SignoffItem {
        kind: string;
        entity_id: string;
        entity_slug: string | null;
        name: string;
        project_name: string | null;
        project_slug: string | null;
        detail: string | null;
    }
    interface Props {
        items: SignoffItem[];
        cap?: number;
        onSelect: (item: SignoffItem) => void;
    }
    let { items, cap = 5, onSelect }: Props = $props();

    const shown = $derived(items.slice(0, cap));
    const overflow = $derived(items.length - shown.length);
</script>

<div id="awaiting-signoff" class="card-warm rounded-xl p-4">
    <h3 class="mb-2 text-xs font-bold uppercase tracking-widest text-muted-foreground">
        Awaiting Sign-off
    </h3>
    {#if items.length === 0}
        <p data-testid="signoff-empty" class="text-xs text-muted-foreground">
            Nothing awaiting your sign-off.
        </p>
    {:else}
        <ul class="space-y-1">
            {#each shown as item (item.kind + item.entity_id)}
                <li>
                    <button
                        type="button"
                        class="flex w-full cursor-pointer items-center justify-between gap-2 rounded-lg p-1.5 text-left text-xs transition-all duration-150 hover:bg-muted/50"
                        onclick={() => onSelect(item)}
                    >
                        <span class="min-w-0">
                            <span class="block truncate font-medium text-foreground">{item.name}</span>
                            {#if item.detail}
                                <span class="block truncate text-[10px] text-muted-foreground">{item.detail}</span>
                            {/if}
                        </span>
                        <span class="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                            {item.kind}
                        </span>
                    </button>
                </li>
            {/each}
        </ul>
        {#if overflow > 0}
            <p data-testid="signoff-more" class="mt-2 text-[11px] font-semibold text-muted-foreground">
                +{overflow} more
            </p>
        {/if}
    {/if}
</div>
