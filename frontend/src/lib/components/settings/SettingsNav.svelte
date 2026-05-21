<script lang="ts">
    import { cn } from '$lib/utils';
    import { Button } from '$lib/components/ui/button';
    import { Badge } from '$lib/components/ui/badge';
    import {
        SECTIONS,
        GROUP_LABELS,
        type SettingsTabId,
    } from './settingsSections';

    interface Props {
        activeTab: SettingsTabId;
        isAdmin: boolean;
        onNavigate: (id: SettingsTabId) => void;
    }
    let { activeTab, isAdmin, onNavigate }: Props = $props();

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
</script>

<nav aria-label="Settings sections" class="shrink-0 w-[232px]">
    <div class="flex flex-col gap-6">
        {#each groups as group (group.group)}
            <div class="flex flex-col gap-1">
                <span
                    class="px-3 pb-2 font-mono text-xs uppercase tracking-wider text-muted-foreground"
                >
                    {group.label}
                </span>
                {#each group.items as section (section.id)}
                    {@const isActive = section.id === activeTab}
                    {@const Icon = section.icon}
                    <Button
                        variant="ghost"
                        onclick={() => onNavigate(section.id)}
                        aria-current={isActive ? 'page' : undefined}
                        class={cn(
                            'relative w-full justify-start gap-3 min-h-11 px-3 font-normal',
                            'text-muted-foreground hover:bg-muted hover:text-foreground',
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
                        <Icon
                            class={cn(
                                'size-[17px] shrink-0',
                                isActive && 'text-primary',
                            )}
                        />
                        <span class="flex-1 truncate text-left">
                            {section.label}
                        </span>
                        {#if section.admin}
                            <Badge variant="outline">Admin</Badge>
                        {/if}
                    </Button>
                {/each}
            </div>
        {/each}
    </div>
</nav>
