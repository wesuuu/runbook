<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { beforeNavigate } from '$app/navigation';
    import { goto } from '$app/navigation';
    import { initialize, isAuthenticated, isEmailVerified, isInitialized, getCurrentOrg, getUserPreferences, handleVerificationCallback } from '$lib/auth.svelte';
    import { initConnectivity, destroyConnectivity } from '$lib/pwa.svelte';
    import { initFieldMode } from '$lib/field-mode.svelte';
    import { initSyncManager, destroySyncManager } from '$lib/sync-manager';
    import UserMenu from '$lib/components/layout/UserMenu.svelte';
    import ProjectsDropdown from '$lib/components/layout/ProjectsDropdown.svelte';
    import NotificationBell from '$lib/components/layout/NotificationBell.svelte';
    import ConnectivityBanner from '$lib/components/ConnectivityBanner.svelte';
    import MobileNav from '$lib/components/layout/MobileNav.svelte';
    import { Toaster } from '$lib/components/ui/sonner';
    import { Button } from '$lib/components/ui/button';
    import ChatPanel from '$lib/components/ai/ChatPanel.svelte';
    import { initChat } from '$lib/chat-store.svelte';
    import { onDestroy } from 'svelte';
    import { fade } from 'svelte/transition';
    import { pageDuration } from '$lib/transitions';
    import Logo from '$lib/components/layout/Logo.svelte';
    import '../app.css';

    let mobileNavOpen = $state(false);

    let { children } = $props();

    function shouldHideChatIcon(path: string): boolean {
        return /^\/protocols\/[^/]+$/.test(path) ||
               /^\/runs\/[^/]+$/.test(path) ||
               /^\/library\/[^/]+$/.test(path) ||
               path.startsWith('/chat') ||
               path === '/export';
    }

    function isOrgPro(org: { subscription_tier?: string } | null): boolean {
        return org?.subscription_tier === 'pro';
    }

    const publicRoutes = ['/login', '/register', '/check-email'];
    const fieldModeRoutes = ['/field'];

    const isPublicRoute = $derived(publicRoutes.includes($page.url.pathname));
    const isFieldMode = $derived(fieldModeRoutes.some((r) => $page.url.pathname.startsWith(r)));
    const showNav = $derived(!isPublicRoute && !isFieldMode && isAuthenticated());
    const shouldShowChat = $derived(!shouldHideChatIcon($page.url.pathname));
    const currentOrg = $derived(getCurrentOrg());
    const canShowFab = $derived(isOrgPro(currentOrg));
    const isFullBleed = $derived(
        $page.url.pathname.startsWith('/protocols/') ||
        $page.url.pathname.startsWith('/export') ||
        $page.url.pathname.startsWith('/chat') ||
        isFieldMode
    );

    onMount(async () => {
        initConnectivity();
        initSyncManager();

        // Handle verification callback (redirect from backend verify-email)
        const urlParams = new URLSearchParams(window.location.search);
        const authToken = urlParams.get('auth_token');
        if (authToken) {
            // Remove token from URL to avoid leaking it
            window.history.replaceState({}, '', '/');
            await handleVerificationCallback(authToken);
        }

        await initialize();
        await initFieldMode();

        // Initial redirect check
        if (!isAuthenticated() && !publicRoutes.includes($page.url.pathname)) {
            goto('/login');
        } else if (isAuthenticated() && !isEmailVerified() && $page.url.pathname !== '/check-email') {
            goto('/check-email');
        } else if (isAuthenticated() && isEmailVerified() && publicRoutes.includes($page.url.pathname)) {
            goto('/');
        }

        // Initialize chat store (fire-and-forget, idempotent)
        if (isAuthenticated() && isEmailVerified()) {
            initChat();
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
        } else if (isAuthenticated() && !isEmailVerified() && path !== '/check-email' && !publicRoutes.includes(path)) {
            cancel();
            goto('/check-email');
        }
    });

    // Apply user preferences to <html> element
    $effect(() => {
        if (!isInitialized() || !isAuthenticated()) return;
        const prefs = getUserPreferences();
        const html = document.documentElement;

        // Font size — sets root font-size so all rem-based dimensions scale proportionally
        const fontSizeMap: Record<string, string> = { small: '18px', medium: '20px', large: '23px' };
        html.style.fontSize = fontSizeMap[prefs.font_size] || '16px';

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
                <Logo size="md" />
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
                    <Button
                        variant="ghost"
                        size="icon"
                        class="md:hidden min-h-11 min-w-11 -ml-2 text-muted-foreground hover:text-foreground"
                        onclick={() => (mobileNavOpen = true)}
                        aria-label="Open menu"
                    >
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                            <path d="M4 6h16M4 12h16M4 18h16" />
                        </svg>
                    </Button>
                    <a href="/" class="flex items-center gap-2.5 group">
                        <div class="shadow-sm shadow-primary/20 group-hover:shadow-md group-hover:shadow-primary/30 transition-all rounded-md">
                            <Logo size="md" />
                        </div>
                        <span class="text-[15px] font-semibold text-foreground tracking-tight">Batchrite</span>
                    </a>
                </div>
                <div class="flex items-center gap-6 text-sm font-medium">
                    <a
                        href="/"
                        class="hidden md:block relative py-1 transition-colors {$page.url.pathname === '/' ? 'nav-active' : 'text-muted-foreground hover:text-foreground'}"
                    >
                        Dashboard
                    </a>
                    <a
                        href="/library"
                        class="hidden md:block relative py-1 transition-colors {$page.url.pathname.startsWith('/library') ? 'nav-active' : 'text-muted-foreground hover:text-foreground'}"
                    >
                        Library
                    </a>
                    <a
                        href="/chat"
                        class="hidden md:block relative py-1 transition-colors {$page.url.pathname.startsWith('/chat') ? 'nav-active' : 'text-muted-foreground hover:text-foreground'}"
                    >
                        AI Chat
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
            {#key $page.url.pathname}
                <div in:fade={{ duration: pageDuration() }}>
                    {@render children()}
                </div>
            {/key}
        {:else}
            <main class="container mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8">
                {#key $page.url.pathname}
                    <div in:fade={{ duration: pageDuration() }}>
                        {@render children()}
                    </div>
                {/key}
            </main>
        {/if}
    </div>
    <Toaster
        position="top-right"
        visibleToasts={5}
        closeButton={true}
        richColors={false}
    />
    {#if showNav && canShowFab}
        <ChatPanel showFab={shouldShowChat} />
    {/if}
{/if}
