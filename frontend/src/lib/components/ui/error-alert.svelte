<script lang="ts">
	interface Props {
		message: string;
		class?: string;
	}

	let { message, class: className = '' }: Props = $props();
</script>

<div class="bg-destructive/10 text-destructive text-sm p-4 rounded-lg border border-destructive/15 {className}">
	{message}
</div>
