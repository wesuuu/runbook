<script lang="ts">
	interface Props {
		message?: string;
		size?: 'sm' | 'md' | 'lg';
		fullPage?: boolean;
		class?: string;
	}

	let {
		message,
		size = 'md',
		fullPage = false,
		class: className = '',
	}: Props = $props();

	const sizeClasses = {
		sm: 'w-6 h-6 border-2',
		md: 'w-8 h-8 border-2',
		lg: 'w-12 h-12 border-2',
	};

	const containerClasses = fullPage
		? 'flex items-center justify-center min-h-[calc(100vh-57px)]'
		: 'flex items-center justify-center py-32';
</script>

<div class="{containerClasses} {className}">
	<div class="flex flex-col items-center gap-4">
		<div class="{sizeClasses[size]} border-border border-t-primary rounded-full animate-spin"></div>
		{#if message}
			<p class="text-sm text-muted-foreground tracking-wide">{message}</p>
		{/if}
	</div>
</div>
