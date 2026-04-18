<script lang="ts">
    interface Props {
        visible: boolean;
        ariaLabel: string;
        onClick: () => void;
        class?: string;
    }

    let { visible, ariaLabel, onClick, class: className }: Props = $props();
</script>

{#if visible}
    <button
        type="button"
        aria-label={ariaLabel}
        onclick={onClick}
        class={`absolute z-20 inline-flex h-3 w-3 cursor-pointer ${className ?? '-top-1 -right-1'}`}
    >
        <span
            class="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-500 opacity-75"
        ></span>
        <span
            class="relative inline-flex h-3 w-3 rounded-full bg-blue-500"
        ></span>
    </button>
{/if}
