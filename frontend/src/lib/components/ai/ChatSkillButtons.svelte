<script lang="ts">
    import type { ChatSkill } from '$lib/schemas/chat';
    import {
        FlaskConical, Sparkles, FileSearch, GitCompare,
        Wrench, BookOpen, BarChart3, Bug,
    } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';

    let {
        skills = [],
        mode = 'chips',
        onactivate,
    }: {
        skills: ChatSkill[];
        mode: 'chips' | 'dropdown';
        onactivate: (skill: ChatSkill) => void;
    } = $props();

    let dropdownOpen = $state(false);

    const iconMap: Record<string, typeof FlaskConical> = {
        'flask-conical': FlaskConical,
        'sparkles': Sparkles,
        'file-search': FileSearch,
        'git-compare': GitCompare,
        'wrench': Wrench,
        'book-open': BookOpen,
        'bar-chart-3': BarChart3,
        'bug': Bug,
    };

    function getIcon(name: string) {
        return iconMap[name] ?? Sparkles;
    }

    function handleSkillClick(skill: ChatSkill) {
        dropdownOpen = false;
        onactivate(skill);
    }
</script>

{#if skills.length === 0}
    <!-- nothing to render -->
{:else if mode === 'chips'}
    <!-- Horizontal scrollable chip row (empty state / conversation starters) -->
    <div class="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
        {#each skills as skill (skill.name)}
            {@const Icon = getIcon(skill.icon)}
            <Button
                variant="outline"
                rounded="full"
                class="h-auto px-4 py-2 bg-card text-foreground active:scale-95"
                onclick={() => handleSkillClick(skill)}
                title={skill.description}
            >
                <Icon class="w-4 h-4 text-primary" />
                {skill.name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
            </Button>
        {/each}
    </div>
{:else}
    <!-- Dropdown (tools menu in active chat) -->
    <div class="relative">
        <Button
            variant="outline"
            size="icon-sm"
            class="size-9 p-2 text-muted-foreground hover:text-foreground hover:bg-muted/70"
            onclick={() => (dropdownOpen = !dropdownOpen)}
            title="Tools"
            aria-label="Chat tools"
        >
            <Wrench class="w-4 h-4" />
        </Button>

        {#if dropdownOpen}
            <!-- Backdrop -->
            <Button
                variant="ghost"
                class="fixed inset-0 z-30 h-auto w-auto rounded-none p-0 shadow-none hover:bg-transparent"
                onclick={() => (dropdownOpen = false)}
                aria-label="Close menu"
                tabindex={-1}
            ></Button>

            <!-- Menu -->
            <div class="absolute bottom-full left-0 mb-2 z-40 w-64 rounded-lg border border-border/60
                bg-popover shadow-lg py-1 animate-in fade-in-0 zoom-in-95">
                {#each skills as skill (skill.name)}
                    {@const Icon = getIcon(skill.icon)}
                    <Button
                        variant="ghost"
                        class="w-full h-auto justify-start gap-3 px-3 py-2.5 text-sm text-left rounded-none"
                        onclick={() => handleSkillClick(skill)}
                    >
                        <Icon class="w-4 h-4 text-primary flex-shrink-0" />
                        <div class="min-w-0 flex-1">
                            <p class="font-medium text-foreground truncate">
                                {skill.name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                            </p>
                            <p class="text-xs text-muted-foreground truncate">{skill.description}</p>
                        </div>
                    </Button>
                {/each}
            </div>
        {/if}
    </div>
{/if}

<style>
    .scrollbar-none {
        -ms-overflow-style: none;
        scrollbar-width: none;
    }
    .scrollbar-none::-webkit-scrollbar {
        display: none;
    }
</style>
