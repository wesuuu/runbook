<script lang="ts">
	import { Toaster as SonnerToaster, type ToasterProps } from 'svelte-sonner';

	let {
		class: className,
		...restProps
	}: ToasterProps & { class?: string } = $props();

	// Stamp every toast with a wall-clock timestamp the moment it mounts, so the
	// "lab printout" strip (rendered via the toast li's ::after pseudo-element)
	// can read it via attr(data-time). svelte-sonner only mounts the
	// [data-sonner-toaster] container once toasts.length > 0, so observe
	// document.body and pick up the toast li no matter when the container
	// appears.
	$effect(() => {
		const formatTime = (d: Date) =>
			d.toLocaleTimeString('en-US', {
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit',
				hour12: false,
			});

		const stamp = (el: Element) => {
			if (el instanceof HTMLElement && !el.dataset.time) {
				el.dataset.time = formatTime(new Date());
			}
		};

		const observer = new MutationObserver((mutations) => {
			for (const m of mutations) {
				for (const node of m.addedNodes) {
					if (!(node instanceof Element)) continue;
					if (node.matches?.('[data-sonner-toast]')) stamp(node);
					node.querySelectorAll?.('[data-sonner-toast]').forEach(stamp);
				}
			}
		});

		observer.observe(document.body, { childList: true, subtree: true });
		document.querySelectorAll('[data-sonner-toast]').forEach(stamp);

		return () => observer.disconnect();
	});
</script>

<SonnerToaster
	class={className}
	toastOptions={{
		classes: {
			toast:
				'group toast group-[.toaster]:bg-card group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg group-[.toaster]:rounded-[var(--radius)] group-[.toaster]:font-sans',
			title: 'group-[.toast]:text-foreground group-[.toast]:font-semibold',
			description: 'group-[.toast]:text-muted-foreground',
			actionButton:
				'group-[.toast]:bg-primary group-[.toast]:text-primary-foreground group-[.toast]:rounded-md group-[.toast]:font-medium',
			cancelButton:
				'group-[.toast]:bg-muted group-[.toast]:text-muted-foreground group-[.toast]:rounded-md group-[.toast]:font-medium',
			closeButton:
				'group-[.toast]:bg-card group-[.toast]:text-foreground group-[.toast]:border-border',
			success:
				'group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-accent/30',
			error:
				'group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-destructive/30',
			warning:
				'group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-accent/30',
			info:
				'group-[.toaster]:!bg-card group-[.toaster]:!text-foreground group-[.toaster]:!border-primary/30',
		},
	}}
	{...restProps}
>
	{#snippet successIcon()}
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>
	{/snippet}
	{#snippet errorIcon()}
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>
	{/snippet}
	{#snippet warningIcon()}
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><path d="M12 9v4M12 17h.01"/></svg>
	{/snippet}
	{#snippet infoIcon()}
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
	{/snippet}
</SonnerToaster>

<style>
	/*
	 * Sonner renders toasts inside a portal Tailwind v4's scanner does not
	 * reliably reach, so size + layout overrides live here as global CSS keyed
	 * off sonner's own data-attributes. Implements Option C "Bench Tag" from
	 * the QA-0001 mocks: 32-px mono strip with [colored dot] TYPE on the left
	 * and a muted timestamp on the right, then the body below.
	 *
	 * Strip layout uses ::before (background + dot + type label) and ::after
	 * (right-aligned timestamp). data-type is set by sonner; data-time is
	 * stamped by the MutationObserver in the <script> block above.
	 */
	:global([data-sonner-toaster]) {
		--width: 26.25rem;
	}

	:global([data-sonner-toaster] [data-sonner-toast]) {
		--type-color: var(--muted-fg);
		--type-tint: var(--muted);
		position: relative;
		padding: 48px 18px 18px;
		min-height: 5rem;
		gap: 14px;
		overflow: hidden;
	}

	:global([data-sonner-toaster] [data-sonner-toast])::before {
		content: attr(data-type);
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 32px;
		padding: 0 18px 0 32px;
		display: flex;
		align-items: center;
		font-family: 'DM Mono', ui-monospace, monospace;
		font-size: 0.6875rem;
		letter-spacing: 0.16em;
		text-transform: uppercase;
		font-weight: 500;
		color: var(--type-color);
		background-color: var(--type-tint);
		background-image: radial-gradient(
			circle at 18px center,
			var(--type-color) 3px,
			transparent 3.5px
		);
		border-bottom: 1px solid var(--type-color);
		pointer-events: none;
	}

	:global([data-sonner-toaster] [data-sonner-toast])::after {
		content: attr(data-time);
		position: absolute;
		top: 0;
		right: 18px;
		height: 32px;
		display: flex;
		align-items: center;
		font-family: 'DM Mono', ui-monospace, monospace;
		font-size: 0.6875rem;
		letter-spacing: 0.1em;
		font-weight: 400;
		color: var(--muted-fg);
		pointer-events: none;
	}

	:global([data-sonner-toaster] [data-sonner-toast][data-type="success"]) {
		--type-color: hsl(155 60% 30%);
		--type-tint: hsl(155 70% 38% / 0.10);
	}
	:global([data-sonner-toaster] [data-sonner-toast][data-type="error"]) {
		--type-color: hsl(355 75% 50%);
		--type-tint: hsl(355 75% 50% / 0.08);
	}
	:global([data-sonner-toaster] [data-sonner-toast][data-type="warning"]) {
		--type-color: hsl(28 90% 38%);
		--type-tint: hsl(38 95% 50% / 0.12);
	}
	:global([data-sonner-toaster] [data-sonner-toast][data-type="info"]) {
		--type-color: hsl(195 85% 22%);
		--type-tint: hsl(195 85% 22% / 0.08);
	}

	:global([data-sonner-toaster] [data-sonner-toast] [data-title]) {
		font-size: 1rem;
		line-height: 1.35;
		letter-spacing: -0.005em;
	}
	:global([data-sonner-toaster] [data-sonner-toast] [data-description]) {
		font-size: 0.9375rem;
		line-height: 1.5;
	}
	:global([data-sonner-toaster] [data-sonner-toast] [data-button]) {
		font-size: 0.9375rem;
		padding: 0.5rem 0.875rem;
		min-height: 2.25rem;
	}
	:global([data-sonner-toaster] [data-sonner-toast] [data-close-button]) {
		width: 1.5rem;
		height: 1.5rem;
		top: 42px;
	}
	:global([data-sonner-toaster] [data-sonner-toast] [data-icon]) {
		width: 1.375rem;
		height: 1.375rem;
		color: var(--type-color);
	}
	:global([data-sonner-toaster] [data-sonner-toast] [data-icon] svg) {
		width: 100%;
		height: 100%;
	}
</style>
