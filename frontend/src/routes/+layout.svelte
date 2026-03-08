<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { beforeNavigate } from '$app/navigation';
    import { goto } from '$app/navigation';
    import { initialize, isAuthenticated, isInitialized, getUserPreferences } from '$lib/auth.svelte';
    import UserMenu from '$lib/components/UserMenu.svelte';
    import ProjectsDropdown from '$lib/components/ProjectsDropdown.svelte';
    import '../app.css';

    let { children } = $props();

    const publicRoutes = ['/login', '/register'];

    const isPublicRoute = $derived(publicRoutes.includes($page.url.pathname));
    const showNav = $derived(!isPublicRoute && isAuthenticated());
    const isFullBleed = $derived(
        $page.url.pathname.startsWith('/protocols/') ||
        $page.url.pathname.startsWith('/export')
    );

    onMount(async () => {
        await initialize();

        // Initial redirect check
        if (!isAuthenticated() && !publicRoutes.includes($page.url.pathname)) {
            goto('/login');
        } else if (isAuthenticated() && publicRoutes.includes($page.url.pathname)) {
            goto('/');
        }
    });

    beforeNavigate(({ to, cancel }) => {
        if (!isInitialized()) return;
        const path = to?.url.pathname ?? '/';

        if (!isAuthenticated() && !publicRoutes.includes(path)) {
            cancel();
            goto('/login');
        }
    });

    // Apply user preferences to <html> element
    $effect(() => {
        if (!isInitialized() || !isAuthenticated()) return;
        const prefs = getUserPreferences();
        const html = document.documentElement;

        // Font size
        html.classList.remove('text-sm', 'text-base', 'text-lg');
        const fontMap: Record<string, string> = { small: 'text-sm', medium: 'text-base', large: 'text-lg' };
        html.classList.add(fontMap[prefs.font_size] || 'text-base');

        // Density
        html.classList.remove('density-compact', 'density-comfortable');
        if (prefs.density === 'compact') html.classList.add('density-compact');
        else html.classList.add('density-comfortable');
    });
</script>

{#if !isInitialized()}
    <div class="min-h-screen flex items-center justify-center bg-muted/40">
        <div class="flex flex-col items-center gap-3">
            <div class="w-7 h-7 border-3 border-muted-foreground/20 border-t-primary rounded-full animate-spin"></div>
            <p class="text-sm text-muted-foreground">Loading...</p>
        </div>
    </div>
{:else}
    <div class="min-h-screen bg-muted/40 text-foreground font-sans antialiased">
        {#if showNav}
            <nav
                class="bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-b border-border px-6 py-3 flex items-center justify-between sticky top-0 z-50"
            >
                <div class="flex items-center space-x-2">
                    <div
                        class="w-8 h-8 bg-primary rounded-lg flex items-center justify-center text-primary-foreground font-bold shadow-sm"
                    >
                        R
                    </div>
                    <span class="text-xl font-bold tracking-tight text-foreground">Runbook</span>
                </div>
                <div class="flex items-center space-x-4 text-sm font-medium">
                    <a
                        href="/"
                        class="{$page.url.pathname === '/' ? 'text-foreground font-semibold' : 'text-muted-foreground'} hover:text-foreground transition-colors"
                    >
                        Dashboard
                    </a>
                    <ProjectsDropdown />
                    <UserMenu />
                </div>
            </nav>
        {/if}

        {#if isFullBleed || isPublicRoute}
            {@render children()}
        {:else}
            <main class="container mx-auto py-6">
                {@render children()}
            </main>
        {/if}
    </div>
{/if}
