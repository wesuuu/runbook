<script lang="ts">
    import type { ChatSkill } from '$lib/schemas/chat';
    import {
        FlaskConical, Sparkles, FileSearch, GitCompare,
        Wrench, BookOpen, BarChart3, Bug,
    } from 'lucide-svelte';

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
            <button
                class="flex-shrink-0 flex items-center gap-2 px-4 py-2 rounded-full
                    border border-border/60 bg-card hover:bg-muted cursor-pointer
                    transition-colors text-sm font-medium text-foreground
                    active:scale-95"
                onclick={() => handleSkillClick(skill)}
                title={skill.description}
            >
                <Icon class="w-4 h-4 text-primary" />
                {skill.name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
            </button>
        {/each}
    </div>
{:else}
    <!-- Dropdown (tools menu in active chat) -->
    <div class="relative">
        <button
            class="p-2 rounded-lg border border-border/60 bg-background
                hover:bg-muted/70 transition-colors text-muted-foreground
                hover:text-foreground"
            onclick={() => (dropdownOpen = !dropdownOpen)}
            title="Tools"
            aria-label="Chat tools"
        >
            <Wrench class="w-4 h-4" />
        </button>

        {#if dropdownOpen}
            <!-- Backdrop -->
            <button
                class="fixed inset-0 z-30"
                onclick={() => (dropdownOpen = false)}
                aria-label="Close menu"
                tabindex="-1"
            ></button>

            <!-- Menu -->
            <div class="absolute bottom-full left-0 mb-2 z-40 w-64 rounded-lg border border-border/60
                bg-popover shadow-lg py-1 animate-in fade-in-0 zoom-in-95">
                {#each skills as skill (skill.name)}
                    {@const Icon = getIcon(skill.icon)}
                    <button
                        class="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-left
                            hover:bg-muted/70 transition-colors"
                        onclick={() => handleSkillClick(skill)}
                    >
                        <Icon class="w-4 h-4 text-primary flex-shrink-0" />
                        <div class="min-w-0 flex-1">
                            <p class="font-medium text-foreground truncate">
                                {skill.name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                            </p>
                            <p class="text-xs text-muted-foreground truncate">{skill.description}</p>
                        </div>
                    </button>
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
