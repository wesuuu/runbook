<script lang="ts">
	import { ContextMenu as ContextMenuPrimitive } from "bits-ui";
	import { cn } from "$lib/utils.js";
	import type { Snippet } from "svelte";

	let {
		ref = $bindable(null),
		class: className,
		children,
		...restProps
	}: ContextMenuPrimitive.TriggerProps & {
		children?: Snippet;
	} = $props();
</script>

<ContextMenuPrimitive.Trigger
	bind:ref
	data-slot="context-menu-trigger"
	class={cn("cursor-pointer", className)}
	{...restProps}
>
	<div style="cursor: pointer !important;">
		{@render children?.()}
	</div>
</ContextMenuPrimitive.Trigger>

<style>
	div {
		cursor: pointer !important;
	}
</style>
