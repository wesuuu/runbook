<script lang="ts">
	import { Toaster as SonnerToaster, type ToasterProps } from 'svelte-sonner';

	let {
		class: className,
		...restProps
	}: ToasterProps & { class?: string } = $props();
</script>

<SonnerToaster
	class={className}
	toastOptions={{
		classes: {
			toast:
				'group toast group-[.toaster]:bg-card group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg group-[.toaster]:rounded-[var(--radius)] group-[.toaster]:font-sans',
			title: 'group-[.toast]:text-foreground group-[.toast]:font-medium',
			description: 'group-[.toast]:text-muted-foreground group-[.toast]:text-sm',
			actionButton:
				'group-[.toast]:bg-primary group-[.toast]:text-primary-foreground group-[.toast]:rounded-md group-[.toast]:text-sm group-[.toast]:font-medium',
			cancelButton:
				'group-[.toast]:bg-muted group-[.toast]:text-muted-foreground group-[.toast]:rounded-md group-[.toast]:text-sm group-[.toast]:font-medium',
			closeButton:
				'group-[.toast]:bg-card group-[.toast]:text-foreground group-[.toast]:border-border',
			success:
				'group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-primary/30',
			error:
				'group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-destructive/30',
			warning:
				'group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-accent/30',
			info:
				'group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-primary/30',
		},
	}}
	{...restProps}
/>
