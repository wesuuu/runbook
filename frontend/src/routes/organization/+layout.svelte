<script lang="ts">
    import { page } from '$app/stores';
    let { children } = $props();
</script>

<div class="grid grid-cols-12 min-h-screen">
    <aside class="col-span-2 border-r border-border bg-muted/30 p-4">
        <h2 class="text-xs uppercase tracking-wide text-muted-foreground font-medium mb-3">Organization</h2>
        <nav>
            <a
                href="/organization/sites"
                class="block px-2 py-1.5 rounded hover:bg-muted cursor-pointer transition-all duration-150"
                class:bg-muted={$page.url.pathname.startsWith('/organization/sites')}
            >
                Sites &amp; Equipment
            </a>
        </nav>
    </aside>
    <main class="col-span-10">
        {@render children?.()}
    </main>
</div>
