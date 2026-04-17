<script lang="ts">
	import { ContextMenu as ContextMenuPrimitive } from "bits-ui";
	import { cn, type WithoutChildrenOrChild } from "$lib/utils.js";
	import type { Snippet } from "svelte";

	let {
		ref = $bindable(null),
		class: className,
		children,
		...restProps
	}: WithoutChildrenOrChild<ContextMenuPrimitive.SubContentProps> & {
		children: Snippet;
	} = $props();
</script>

<ContextMenuPrimitive.Portal>
	<ContextMenuPrimitive.SubContent
		bind:ref
		data-slot="context-menu-sub-content"
		class={cn(
			"bg-white z-50 min-w-[180px] overflow-hidden rounded-lg border border-slate-200 py-2 shadow-lg",
			className,
		)}
		{...restProps}
	>
		{@render children?.()}
	</ContextMenuPrimitive.SubContent>
</ContextMenuPrimitive.Portal>
