<script lang="ts">
    import { onMount } from 'svelte';
    import { fade } from 'svelte/transition';
    import { goto } from '$app/navigation';
    import Logo from '$lib/components/layout/Logo.svelte';
    import LegalDocument from '$lib/components/legal/LegalDocument.svelte';
    import AcceptForm from '$lib/components/legal/AcceptForm.svelte';
    import { acceptTos, isTosCurrent } from '$lib/auth.svelte';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();

    let activeTab = $state<'terms' | 'privacy'>('terms');

    onMount(() => {
        if (isTosCurrent()) {
            goto('/');
        }
    });

    async function handleAccept() {
        await acceptTos();
        goto('/');
    }
</script>

<div class="min-h-screen bg-background pb-32 md:pb-12" in:fade={{ duration: 200 }}>
    <main class="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
        <!-- Anchor logo (nav is hidden on this route) -->
        <div class="flex justify-center mb-8">
            <Logo size="md" />
        </div>

        <!-- Hero copy -->
        <header class="mb-8">
            <h1 class="text-2xl sm:text-3xl font-semibold text-foreground tracking-tight">
                Please review and accept our terms
            </h1>
            <p class="text-sm sm:text-base text-muted-foreground mt-2 leading-relaxed">
                Before you can use Batchrite, take a moment to review the
                Terms of Service and Privacy Policy. Both apply to every
                user account.
            </p>
        </header>

        <!-- "At a glance" callout — surfaces material terms before the full document -->
        <aside
            class="mb-8 rounded-md border border-border/60 bg-muted/40 border-l-4 border-l-primary p-5"
            aria-label="Summary of material terms"
        >
            <h2 class="text-sm font-semibold text-foreground tracking-wide uppercase mb-3">
                At a glance
            </h2>
            <ul class="space-y-2 text-sm text-foreground leading-relaxed">
                <li class="flex gap-2">
                    <span class="text-primary mt-0.5" aria-hidden="true">•</span>
                    <span>
                        Batchrite is for <strong>research use only</strong> — not
                        validated for cGMP, GLP, or clinical use.
                    </span>
                </li>
                <li class="flex gap-2">
                    <span class="text-primary mt-0.5" aria-hidden="true">•</span>
                    <span>
                        You may not upload <strong>Protected Health Information</strong>
                        (HIPAA PHI).
                    </span>
                </li>
                <li class="flex gap-2">
                    <span class="text-primary mt-0.5" aria-hidden="true">•</span>
                    <span>
                        We don't sell your data and don't use it
                        to <strong>train AI models</strong>.
                    </span>
                </li>
            </ul>
        </aside>

        <!-- Tabs -->
        <div class="border-b border-border" role="tablist" aria-label="Legal documents">
            <button
                class="px-4 py-2 -mb-px cursor-pointer transition-all duration-150 {activeTab === 'terms' ? 'border-b-2 border-primary text-foreground font-medium' : 'text-muted-foreground hover:text-foreground'}"
                type="button"
                role="tab"
                aria-selected={activeTab === 'terms'}
                onclick={() => (activeTab = 'terms')}
            >Terms of Service</button>
            <button
                class="px-4 py-2 -mb-px cursor-pointer transition-all duration-150 {activeTab === 'privacy' ? 'border-b-2 border-primary text-foreground font-medium' : 'text-muted-foreground hover:text-foreground'}"
                type="button"
                role="tab"
                aria-selected={activeTab === 'privacy'}
                onclick={() => (activeTab = 'privacy')}
            >Privacy Policy</button>
        </div>

        <!-- Document panel -->
        <div class="max-h-[60vh] overflow-y-auto border border-border border-t-0 rounded-b-md p-6 sm:p-8 bg-card">
            {#if activeTab === 'terms'}
                <LegalDocument
                    markdown={data.terms.markdown}
                    version={data.terms.version}
                    effectiveDate={data.terms.effective_date}
                />
            {:else}
                <LegalDocument
                    markdown={data.privacy.markdown}
                    version={data.privacy.version}
                    effectiveDate={data.privacy.effective_date}
                />
            {/if}
        </div>

        <!-- Hairline separator (desktop only — sticky bar replaces this on mobile) -->
        <hr class="hidden md:block border-border my-8" />

        <!-- Accept form: inline on desktop, sticky bottom bar on mobile/tablet -->
        <div
            class="md:static fixed bottom-0 left-0 right-0 md:bottom-auto md:left-auto md:right-auto bg-background/95 md:bg-transparent backdrop-blur md:backdrop-blur-none border-t md:border-t-0 border-border px-4 sm:px-6 md:px-0 py-4 md:py-0 z-10"
        >
            <div class="max-w-3xl mx-auto md:mx-0">
                <AcceptForm onAccept={handleAccept} />
            </div>
        </div>
    </main>
</div>
