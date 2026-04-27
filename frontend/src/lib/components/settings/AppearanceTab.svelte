<script lang="ts">
    import { api } from '$lib/api';
    import { toast } from '$lib/toast';
    import { refreshUser } from '$lib/auth.svelte';
    import { getTheme, setTheme, type Theme } from '$lib/theme.svelte';
    import {
        Card,
        CardContent,
        CardHeader,
        CardTitle,
        CardDescription,
    } from '$lib/components/ui/card';

    type ThemeOption = {
        id: Theme;
        title: string;
        blurb: string;
    };

    const OPTIONS: ThemeOption[] = [
        { id: 'lab-glass',  title: 'Lab Glass',  blurb: 'Cold, clinical white-blue. The default.' },
        { id: 'blueprint',  title: 'Blueprint',  blurb: 'Drafted paper-blue with ochre accents.' },
        { id: 'apothecary', title: 'Apothecary', blurb: 'Botanical: parchment, moss, tannin rust.' },
    ];

    const selected = $derived<Theme>(getTheme());
    let saving = $state(false);

    async function persist(theme: Theme): Promise<void> {
        await api.put('/auth/me/preferences', { theme });
        await refreshUser();
    }

    async function pick(id: Theme): Promise<void> {
        if (id === selected || saving) return;
        saving = true;
        try {
            await setTheme(id, persist);
            toast.success('Theme updated');
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to save theme');
        } finally {
            saving = false;
        }
    }
</script>

<Card>
    <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>
            Pick the visual theme used across Batchrite. Choices apply to your account on every device.
        </CardDescription>
    </CardHeader>
    <CardContent>
        <div class="grid gap-4 sm:grid-cols-3">
            {#each OPTIONS as opt (opt.id)}
                <button
                    type="button"
                    onclick={() => pick(opt.id)}
                    disabled={saving}
                    aria-pressed={selected === opt.id}
                    class="group text-left rounded-lg border p-4 transition-all duration-150 cursor-pointer
                           hover:border-primary/60 disabled:opacity-60 disabled:cursor-not-allowed
                           {selected === opt.id ? 'border-primary ring-2 ring-primary/30' : 'border-border'}"
                >
                    <!-- Scoped preview swatch using its own [data-theme] -->
                    <div data-theme={opt.id} class="mb-3 rounded-md border border-border overflow-hidden">
                        <div class="bg-background p-3 flex gap-2 items-center">
                            <div class="w-8 h-8 rounded bg-primary"></div>
                            <div class="flex-1">
                                <div class="h-2 w-3/4 rounded bg-foreground/80 mb-1.5"></div>
                                <div class="h-2 w-1/2 rounded bg-muted-foreground/60"></div>
                            </div>
                            <div class="w-3 h-3 rounded-full bg-accent"></div>
                        </div>
                        <div class="bg-card px-3 py-2 border-t border-border flex gap-1.5">
                            <div class="h-1.5 flex-1 rounded bg-muted"></div>
                            <div class="h-1.5 w-6 rounded bg-accent"></div>
                            <div class="h-1.5 w-3 rounded bg-primary"></div>
                        </div>
                    </div>

                    <div class="flex items-center justify-between">
                        <p class="text-sm font-semibold">{opt.title}</p>
                        {#if selected === opt.id}
                            <span class="text-xs font-mono text-primary">SELECTED</span>
                        {/if}
                    </div>
                    <p class="text-xs text-muted-foreground mt-1">{opt.blurb}</p>
                </button>
            {/each}
        </div>
    </CardContent>
</Card>
