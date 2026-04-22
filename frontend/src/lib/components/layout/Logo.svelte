<script lang="ts">
	interface Props {
		size?: 'sm' | 'md' | 'lg';
		class?: string;
	}

	let { size = 'md', class: cls = '' } = $props();

	const sizeMap = {
		sm: 'w-7 h-7',      // 28px
		md: 'w-8 h-8',      // 32px
		lg: 'w-12 h-12',    // 48px
	};
</script>

<img
	src="/logo.png"
	alt="Batchrite"
	class="{sizeMap[size]} object-cover {cls}"
/>
