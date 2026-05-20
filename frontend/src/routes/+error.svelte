<script lang="ts">
  import { page } from '$app/stores';
</script>

<div class="flex min-h-[60vh] flex-col items-center justify-center gap-2 text-center">
  <p class="text-5xl font-semibold text-muted-foreground">{$page.status}</p>
  <p class="text-lg">
    {$page.error?.message ?? 'Page not found'}
  </p>
  <a href="/" class="mt-2 text-sm text-primary underline">Back to dashboard</a>
</div>
