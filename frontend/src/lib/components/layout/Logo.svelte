<script lang="ts">
	import LogoMark from './LogoMark.svelte';

	interface Props {
		/** Drives the mark px and the wordmark px. */
		size?: 'sm' | 'md' | 'lg';
		/** Forwarded to LogoMark. */
		variant?: 'full' | 'simple';
		/** Forwarded to LogoMark. */
		animated?: boolean;
		/** `horizontal` = mark beside wordmark; `stacked` = mark above it. */
		orientation?: 'horizontal' | 'stacked';
		class?: string;
	}

	let {
		size = 'md',
		variant = 'simple',
		animated = false,
		orientation = 'horizontal',
		class: cls = '',
	}: Props = $props();

	// Mark px and wordmark px are decoupled — the nav wants a ~30px mark but
	// only ~16px text. `gap` is tuned per size to keep the lockup balanced.
	// `lg` is the stacked hero treatment (login + loading screens), so its
	// mark is sized as a height against the cropped `full` variant.
	const sizeMap = {
		sm: { mark: 24, wordmark: 14, gap: 4 },
		md: { mark: 30, wordmark: 16, gap: 5 },
		lg: { mark: 92, wordmark: 33, gap: 14 },
	};

	const dims = $derived(sizeMap[size]);
</script>

<span
	class="batchrite-lockup {cls}"
	class:stacked={orientation === 'stacked'}
	style="gap: {dims.gap}px;"
>
	<LogoMark {variant} {animated} size={dims.mark} />
	<span class="batchrite-wordmark" style="font-size: {dims.wordmark}px;"
		>batchrite</span
	>
</span>

<style>
	.batchrite-lockup {
		display: inline-flex;
		align-items: center;
		line-height: 1;
		white-space: nowrap;
	}
	.batchrite-lockup.stacked {
		flex-direction: column;
	}
	.batchrite-wordmark {
		font-family: 'DM Sans', system-ui, sans-serif;
		font-weight: 600;
		letter-spacing: -0.035em;
		color: #0a4c5c;
		font-feature-settings: 'cv11', 'ss01';
		line-height: 1;
	}
</style>
