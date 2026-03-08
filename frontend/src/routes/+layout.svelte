<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { beforeNavigate } from '$app/navigation';
    import { goto } from '$app/navigation';
    import { initialize, isAuthenticated, isInitialized, getUserPreferences } from '$lib/auth.svelte';
    import UserMenu from '$lib/components/UserMenu.svelte';
    import ProjectsDropdown from '$lib/components/ProjectsDropdown.svelte';
    import NotificationBell from '$lib/components/NotificationBell.svelte';
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
    <div class="min-h-screen flex items-center justify-center bg-background">
        <div class="flex flex-col items-center gap-4">
            <div class="relative">
                <div class="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                    <span class="font-mono text-lg font-medium text-primary">R</span>
                </div>
                <div class="absolute inset-0 w-10 h-10 rounded-xl border-2 border-primary/20 animate-ping"></div>
            </div>
            <p class="text-sm text-muted-foreground tracking-wide">Loading...</p>
        </div>
    </div>
{:else}
    <div class="grain"></div>
    <div class="min-h-screen bg-background text-foreground font-sans antialiased">
        {#if showNav}
            <nav
                class="bg-card/80 backdrop-blur-xl border-b border-border/60 px-6 py-3 flex items-center justify-between sticky top-0 z-50"
            >
                <a href="/" class="flex items-center gap-2.5 group">
                    <div
                        class="w-7 h-7 bg-primary rounded-md flex items-center justify-center shadow-sm shadow-primary/20 group-hover:shadow-md group-hover:shadow-primary/30 transition-all"
                    >
                        <span class="font-mono text-sm font-medium text-primary-foreground leading-none">R</span>
                    </div>
                    <span class="text-[15px] font-semibold text-foreground tracking-tight">Runbook</span>
                </a>
                <div class="flex items-center gap-6 text-sm font-medium">
                    <a
                        href="/"
                        class="relative py-1 transition-colors {$page.url.pathname === '/' ? 'nav-active' : 'text-muted-foreground hover:text-foreground'}"
                    >
                        Dashboard
                    </a>
                    <ProjectsDropdown />
                    <div class="w-px h-5 bg-border/60"></div>
                    <NotificationBell />
                    <UserMenu />
                </div>
            </nav>
        {/if}

        {#if isFullBleed || isPublicRoute}
            {@render children()}
        {:else}
            <main class="container mx-auto py-8">
                {@render children()}
            </main>
        {/if}
    </div>
{/if}
