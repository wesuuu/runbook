<script lang="ts">
	import type { Snippet } from "svelte";
	import { fade } from "svelte/transition";
	import { cn } from "$lib/utils";
	import { Button } from "$lib/components/ui/button";

	interface Props {
		icon?: Snippet;
		title: string;
		description?: string;
		actionLabel?: string;
		onAction?: () => void;
		secondaryActionLabel?: string;
		secondaryOnAction?: () => void;
		class?: string;
	}

	let {
		icon,
		title,
		description,
		actionLabel,
		onAction,
		secondaryActionLabel,
		secondaryOnAction,
		class: className,
	}: Props = $props();
</script>

<div
	class={cn("flex flex-col items-center text-center py-10", className)}
	transition:fade={{ duration: 200 }}
>
	{#if icon}
		<div
			class="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mb-4 text-muted-foreground/40"
		>
			{@render icon()}
		</div>
	{/if}
	<p class="font-semibold text-foreground">{title}</p>
	{#if description}
		<p class="text-sm text-muted-foreground mt-1 max-w-md">{description}</p>
	{/if}
	{#if actionLabel}
		<Button
			variant="outline"
			size="sm"
			class="mt-4"
			onclick={onAction}
		>
			{actionLabel}
		</Button>
	{/if}
	{#if secondaryActionLabel}
		<Button
			variant="ghost"
			size="sm"
			class="mt-2 text-muted-foreground"
			onclick={secondaryOnAction}
		>
			{secondaryActionLabel}
		</Button>
	{/if}
</div>
