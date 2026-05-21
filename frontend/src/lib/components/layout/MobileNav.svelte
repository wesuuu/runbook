<script lang="ts">
    import { slide, fade } from 'svelte/transition';
    import { Button } from '$lib/components/ui/button';
    import Logo from '$lib/components/layout/Logo.svelte';

    let { open = $bindable(false), currentPath = '' } = $props();

    function close() {
        open = false;
    }

    const links = [
        { href: '/', label: 'Dashboard' },
        { href: '/library', label: 'Library' },
        { href: '/reviews', label: 'Reviews' },
        { href: '/chat', label: 'AI Chat' },
        { href: '/projects', label: 'Projects' },
        { href: '/settings', label: 'Settings' },
    ];

    function isActive(href: string): boolean {
        if (href === '/') return currentPath === '/';
        return currentPath.startsWith(href);
    }
</script>

{#if open}
    <!-- Backdrop -->
    <div
        class="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm cursor-pointer"
        transition:fade={{ duration: 200 }}
        onclick={close}
        onkeydown={(e) => e.key === 'Escape' && close()}
        role="button"
        tabindex="-1"
    ></div>

    <!-- Drawer -->
    <nav
        class="fixed top-0 left-0 bottom-0 z-50 w-72 bg-white border-r border-border shadow-xl flex flex-col"
        transition:slide={{ axis: 'x', duration: 250 }}
    >
        <!-- Header -->
        <div class="flex items-center justify-between px-5 py-4 border-b border-border">
            <a href="/" class="flex items-center gap-2.5" onclick={close}>
                <div class="shadow-sm shadow-primary/20 rounded-md">
                    <Logo size="sm" />
                </div>
                <span class="text-[15px] font-semibold text-foreground tracking-tight">Batchrite</span>
            </a>
            <Button
                variant="ghost"
                size="icon"
                class="min-h-11 min-w-11 text-muted-foreground hover:text-foreground"
                onclick={close}
                aria-label="Close menu"
            >
                <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                    <path d="M18 6 6 18M6 6l12 12" />
                </svg>
            </Button>
        </div>

        <!-- Links -->
        <div class="flex-1 py-3 px-3">
            {#each links as link}
                <a
                    href={link.href}
                    class="flex items-center gap-3 min-h-11 px-3 rounded-lg text-sm font-medium transition-colors {isActive(link.href) ? 'bg-primary/10 text-primary font-semibold' : 'text-muted-foreground hover:text-foreground hover:bg-muted'}"
                    onclick={close}
                >
                    {link.label}
                </a>
            {/each}
        </div>
    </nav>
{/if}
