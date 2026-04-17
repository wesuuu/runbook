<script lang="ts">
	import * as Dialog from "./dialog/index.js";
	import { Button } from "$lib/components/ui/button";
	import type { ButtonVariant } from "$lib/components/ui/button";
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

	const buttonVariantFor: Record<NonNullable<Props["confirmVariant"]>, ButtonVariant> = {
		primary: "default",
		danger: "destructive",
		warning: "default",
		success: "default",
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
			<Button variant="secondary" onclick={onCancel}>
				{cancelLabel}
			</Button>
			<Button
				variant={buttonVariantFor[confirmVariant]}
				onclick={onConfirm}
				disabled={loading}
			>
				{loading ? "..." : confirmLabel}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
