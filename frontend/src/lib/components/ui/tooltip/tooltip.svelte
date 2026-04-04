<script lang="ts">
	import { Tooltip as TooltipPrimitive } from "bits-ui";
	import type { Snippet } from "svelte";

	let {
		children,
		...restProps
	}: Omit<TooltipPrimitive.RootProps, 'children'> & { children?: Snippet } = $props();
</script>

<TooltipPrimitive.Root {...restProps}>
	{@render children?.()}
</TooltipPrimitive.Root>
