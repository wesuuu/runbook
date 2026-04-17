<script lang="ts">
	import * as Dialog from "./dialog/index.js";
	import type { Snippet } from "svelte";

	interface Props {
		open: boolean;
		title: string;
		message?: string;
		confirmLabel?: string;
		cancelLabel?: string;
		confirmVariant?: "primary" | "danger" | "warning" | "success";
		loading?: boolean;
		onConfirm: () => void;
		onCancel: () => void;
		warning?: Snippet;
	}

	let {
		open = $bindable(false),
		title,
		message,
		confirmLabel = "Confirm",
		cancelLabel = "Cancel",
		confirmVariant = "primary",
		loading = false,
		onConfirm,
		onCancel,
		warning,
	}: Props = $props();

	const variantClasses: Record<string, string> = {
		primary:
			"bg-primary text-primary-foreground hover:bg-primary/90",
		danger:
			"bg-destructive text-white hover:bg-destructive/90",
		warning:
			"bg-accent text-accent-foreground hover:bg-accent/90",
		success:
			"bg-emerald-600 text-white hover:bg-emerald-700",
	};

	function handleOpenChange(value: boolean) {
		if (!value) {
			onCancel();
		}
	}
</script>

<Dialog.Root bind:open onOpenChange={handleOpenChange}>
	<Dialog.Content class="sm:max-w-sm">
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			{#if message}
				<Dialog.Description>{message}</Dialog.Description>
			{/if}
		</Dialog.Header>

		{#if warning}
			{@render warning()}
		{/if}

		<Dialog.Footer>
			<button
				onclick={onCancel}
				class="px-4 py-2 bg-muted text-foreground/80 rounded-lg font-medium hover:bg-muted/80 transition-colors"
			>
				{cancelLabel}
			</button>
			<button
				onclick={onConfirm}
				disabled={loading}
				class="px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed {variantClasses[confirmVariant]}"
			>
				{loading ? "..." : confirmLabel}
			</button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
