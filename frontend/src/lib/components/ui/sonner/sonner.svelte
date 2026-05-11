<script lang="ts">
	import { Toaster as SonnerToaster, type ToasterProps } from 'svelte-sonner';

	let {
		class: className,
		...restProps
	}: ToasterProps & { class?: string } = $props();

	// Stamp every toast with a wall-clock timestamp the moment it mounts, so the
	// mono "lab printout" header strip (rendered via CSS ::before) can read it
	// via attr(data-time). svelte-sonner doesn't expose a per-toast hook AND
	// only mounts [data-sonner-toaster] when toasts.length > 0, so we observe
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
/>

<style>
	/*
	 * Sonner renders toasts inside a portal Tailwind v4's scanner does not
	 * reliably reach, so size + layout overrides live here as global CSS keyed
	 * off sonner's own data-attributes. The mono "lab printout" header strip
	 * (::before) reads data-type (sonner-set) and data-time (set by the
	 * MutationObserver in <script> above).
	 */
	:global([data-sonner-toaster]) {
		--width: 26rem;
	}

	:global([data-sonner-toaster] [data-sonner-toast]) {
		--type-color: var(--muted-fg);
		--type-tint: var(--muted);
		position: relative;
		padding: 44px 18px 18px;
		min-height: 5rem;
		gap: 14px;
	}

	:global([data-sonner-toaster] [data-sonner-toast])::before {
		content: attr(data-type) " · " attr(data-time);
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 32px;
		padding: 0 18px;
		display: flex;
		align-items: center;
		font-family: 'DM Mono', ui-monospace, monospace;
		font-size: 0.6875rem;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		font-weight: 500;
		color: var(--type-color);
		background: var(--type-tint);
		border-bottom: 1px solid var(--type-color);
		border-radius: var(--radius) var(--radius) 0 0;
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
		top: 38px;
	}
	:global([data-sonner-toaster] [data-sonner-toast] [data-icon]) {
		width: 1.25rem;
		height: 1.25rem;
	}
</style>
