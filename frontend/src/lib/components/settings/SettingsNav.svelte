<script lang="ts">
    import { onMount } from 'svelte';
    import { cn } from '$lib/utils';
    import { Button } from '$lib/components/ui/button';
    import { Badge } from '$lib/components/ui/badge';
    import * as Tooltip from '$lib/components/ui/tooltip';
    import { PanelLeftOpen, PanelLeftClose } from '@lucide/svelte';
    import {
        SECTIONS,
        GROUP_LABELS,
        type SettingsSectionEntry,
        type SettingsTabId,
    } from './settingsSections';

    interface Props {
        activeTab: SettingsTabId;
        isAdmin: boolean;
        onNavigate: (id: SettingsTabId) => void;
    }
    let { activeTab, isAdmin, onNavigate }: Props = $props();

    // Collapse state — only meaningful below the lg breakpoint.
    let railExpanded = $state(false);
    // belowLg governs ONLY tooltip rendering, never rail width.
    let belowLg = $state(false);

    onMount(() => {
        // onMount never runs during SSR, so window is always defined here.
        if (typeof window.matchMedia !== 'function') return;
        const mq = window.matchMedia('(max-width: 1023px)');
        belowLg = mq.matches;
        const onChange = (e: MediaQueryListEvent) => {
            belowLg = e.matches;
            // Reset stale toggle state when returning to the desktop layout.
            if (!e.matches) railExpanded = false;
        };
        mq.addEventListener('change', onChange);
        return () => mq.removeEventListener('change', onChange);
    });

    const visibleSections = $derived(
        isAdmin ? SECTIONS : SECTIONS.filter((s) => !s.admin),
    );

    // Two ordered groups; a group with no visible items renders nothing.
    const groups = $derived(
        (['workspace', 'account'] as const)
            .map((group) => ({
                group,
                label: GROUP_LABELS[group],
                items: visibleSections.filter((s) => s.group === group),
            }))
            .filter((g) => g.items.length > 0),
    );

    // Tooltips appear only on the collapsed icon-only rail.
    const showTooltips = $derived(belowLg && !railExpanded);
</script>

{#snippet navItem(
    section: SettingsSectionEntry,
    isActive: boolean,
    triggerProps: Record<string, unknown>,
)}
    {@const Icon = section.icon}
    <Button
        variant="ghost"
        {...triggerProps}
        onclick={() => onNavigate(section.id)}
        aria-current={isActive ? 'page' : undefined}
        class={cn(
            'relative w-full justify-start gap-3 min-h-11 px-3 font-normal',
            'text-muted-foreground hover:bg-muted hover:text-foreground',
            // Collapsed icon-only rail (below lg): center the lone icon.
            !railExpanded && 'justify-center px-0 lg:justify-start lg:px-3',
            isActive &&
                'bg-card text-foreground font-semibold ring-1 ring-border',
        )}
    >
        {#if isActive}
            <span
                aria-hidden="true"
                class="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded bg-primary"
            ></span>
        {/if}
        <Icon class={cn('size-[17px] shrink-0', isActive && 'text-primary')} />
        <span
            class={cn(
                'flex-1 truncate text-left',
                !railExpanded && 'sr-only lg:not-sr-only',
            )}
        >
            {section.label}
        </span>
        {#if section.admin}
            <Badge
                variant="outline"
                class={cn(!railExpanded && 'hidden lg:inline-flex')}
            >
                Admin
            </Badge>
        {/if}
    </Button>
{/snippet}

<nav
    aria-label="Settings sections"
    class={cn(
        // Pin the rail below the app's sticky top bar so it stays visible
        // while a long settings panel scrolls.
        'sticky top-20 shrink-0 transition-[width] duration-200',
        'w-[60px]',
        railExpanded && 'w-[232px]',
        'lg:w-[232px]',
    )}
>
    <Tooltip.Provider delayDuration={150}>
        <div class="flex flex-col gap-6">
            {#each groups as group (group.group)}
                <div class="flex flex-col gap-1">
                    <span
                        class={cn(
                            'px-3 pb-2 font-mono text-xs uppercase tracking-wider text-muted-foreground',
                            !railExpanded && 'sr-only lg:not-sr-only',
                        )}
                    >
                        {group.label}
                    </span>
                    {#each group.items as section (section.id)}
                        {@const isActive = section.id === activeTab}
                        {#if showTooltips}
                            <Tooltip.Root>
                                <Tooltip.Trigger>
                                    {#snippet child({ props })}
                                        {@render navItem(
                                            section,
                                            isActive,
                                            props,
                                        )}
                                    {/snippet}
                                </Tooltip.Trigger>
                                <Tooltip.Content side="right">
                                    {section.label}
                                </Tooltip.Content>
                            </Tooltip.Root>
                        {:else}
                            {@render navItem(section, isActive, {})}
                        {/if}
                    {/each}
                </div>
            {/each}
        </div>
    </Tooltip.Provider>

    <!-- Collapse toggle — only below the lg breakpoint. -->
    <div class="mt-6 lg:hidden">
        <Button
            variant="ghost"
            onclick={() => (railExpanded = !railExpanded)}
            aria-label={railExpanded
                ? 'Collapse navigation'
                : 'Expand navigation'}
            class="w-full justify-start gap-3 min-h-11 min-w-11 px-3 text-muted-foreground"
        >
            {#if railExpanded}
                <PanelLeftClose class="size-[17px] shrink-0" />
            {:else}
                <PanelLeftOpen class="size-[17px] shrink-0" />
            {/if}
            <span class={cn('truncate', !railExpanded && 'sr-only')}>
                {railExpanded ? 'Collapse' : 'Expand'}
            </span>
        </Button>
    </div>
</nav>
