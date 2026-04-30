<script lang="ts">
    import type { Snippet } from 'svelte';
    import { Button } from "$lib/components/ui/button";

    interface Props {
        open: boolean;
        title: string;
        onClose: () => void;
        headerActions?: Snippet;
        children: Snippet;
    }

    let { open = $bindable(false), title, onClose, headerActions, children }: Props = $props();

    // Lock body scroll while the modal is open so the underlying page's
    // scrollbar doesn't sit alongside the modal's own scrollbar.
    $effect(() => {
        if (typeof document === 'undefined') return;
        const prev = document.body.style.overflow;
        if (open) {
            document.body.style.overflow = 'hidden';
            return () => {
                document.body.style.overflow = prev;
            };
        }
    });
</script>

{#if open}
<div class="fixed inset-0 z-50 flex flex-col bg-background">
    <!-- Header -->
    <div class="flex items-center justify-between border-b border-border px-6 py-3 shrink-0">
        <div class="flex items-center gap-6">
            <h2 class="text-lg font-semibold">{title}</h2>
            {#if headerActions}
                {@render headerActions()}
            {/if}
        </div>
        <Button
            variant="ghost"
            size="icon-sm"
            onclick={onClose}
            aria-label="Close"
        >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path d="M6 18L18 6M6 6l12 12" />
            </svg>
        </Button>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-hidden">
        {@render children()}
    </div>
</div>
{/if}
