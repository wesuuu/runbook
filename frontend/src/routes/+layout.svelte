<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { beforeNavigate } from '$app/navigation';
    import { goto } from '$app/navigation';
    import { initialize, isAuthenticated, isInitialized, getUserPreferences } from '$lib/auth.svelte';
    import { initConnectivity, destroyConnectivity } from '$lib/pwa.svelte';
    import { initFieldMode } from '$lib/field-mode.svelte';
    import { initSyncManager, destroySyncManager } from '$lib/sync-manager';
    import UserMenu from '$lib/components/UserMenu.svelte';
    import ProjectsDropdown from '$lib/components/ProjectsDropdown.svelte';
    import NotificationBell from '$lib/components/NotificationBell.svelte';
    import ConnectivityBanner from '$lib/components/ConnectivityBanner.svelte';
    import MobileNav from '$lib/components/MobileNav.svelte';
    import { Toaster } from '$lib/components/ui/sonner';
    import { onDestroy } from 'svelte';
    import '../app.css';

    let mobileNavOpen = $state(false);

    let { children } = $props();

    const publicRoutes = ['/login', '/register'];
    const fieldModeRoutes = ['/field'];

    const isPublicRoute = $derived(publicRoutes.includes($page.url.pathname));
    const isFieldMode = $derived(fieldModeRoutes.some((r) => $page.url.pathname.startsWith(r)));
    const showNav = $derived(!isPublicRoute && !isFieldMode && isAuthenticated());
    const isFullBleed = $derived(
        $page.url.pathname.startsWith('/protocols/') ||
        $page.url.pathname.startsWith('/export') ||
        isFieldMode
    );

    onMount(async () => {
        initConnectivity();
        initSyncManager();
        await initialize();
        await initFieldMode();

        // Initial redirect check
        if (!isAuthenticated() && !publicRoutes.includes($page.url.pathname)) {
            goto('/login');
        } else if (isAuthenticated() && publicRoutes.includes($page.url.pathname)) {
            goto('/');
        }
    });

    onDestroy(() => {
        destroyConnectivity();
        destroySyncManager();
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
    {#if showNav}
        <MobileNav bind:open={mobileNavOpen} currentPath={$page.url.pathname} />
    {/if}
    <div class="min-h-screen bg-background text-foreground font-sans antialiased">
        {#if showNav}
            <nav
                class="bg-card/80 backdrop-blur-xl border-b border-border/60 px-4 sm:px-6 py-3 flex items-center justify-between sticky top-0 z-50"
            >
                <div class="flex items-center gap-2.5">
                    <!-- Hamburger button (mobile only) -->
                    <button
                        class="md:hidden min-h-11 min-w-11 flex items-center justify-center -ml-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                        onclick={() => (mobileNavOpen = true)}
                        aria-label="Open menu"
                    >
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                            <path d="M4 6h16M4 12h16M4 18h16" />
                        </svg>
                    </button>
                    <a href="/" class="flex items-center gap-2.5 group">
                        <div
                            class="w-7 h-7 bg-primary rounded-md flex items-center justify-center shadow-sm shadow-primary/20 group-hover:shadow-md group-hover:shadow-primary/30 transition-all"
                        >
                            <span class="font-mono text-sm font-medium text-primary-foreground leading-none">R</span>
                        </div>
                        <span class="text-[15px] font-semibold text-foreground tracking-tight">Runbook</span>
                    </a>
                </div>
                <div class="flex items-center gap-6 text-sm font-medium">
                    <a
                        href="/"
                        class="hidden md:block relative py-1 transition-colors {$page.url.pathname === '/' ? 'nav-active' : 'text-muted-foreground hover:text-foreground'}"
                    >
                        Dashboard
                    </a>
                    <div class="hidden md:block">
                        <ProjectsDropdown />
                    </div>
                    <div class="hidden md:block w-px h-5 bg-border/60"></div>
                    <NotificationBell />
                    <UserMenu />
                </div>
            </nav>
            <ConnectivityBanner />
        {/if}

        {#if isFullBleed || isPublicRoute}
            {@render children()}
        {:else}
            <main class="container mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
                {@render children()}
            </main>
        {/if}
    </div>
    <Toaster
        position="bottom-right"
        visibleToasts={5}
        closeButton={true}
        richColors={false}
    />
{/if}
