<!-- frontend/src/lib/components/sites/SiteArchiveWizardModal.svelte -->
<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import SitePicker from './SitePicker.svelte';
    import SiteArchiveStepper from './SiteArchiveStepper.svelte';
    import type { Site, SiteArchiveRequest } from '$lib/schemas/sites';
    import type { Equipment } from '$lib/schemas/science';

    interface Props {
        open: boolean;
        site: Site;
        otherSites: Site[];
        equipment: Equipment[];
        onClose: () => void;
        onSubmit: (payload: SiteArchiveRequest) => Promise<void>;
    }

    let { open, site, otherSites, equipment, onClose, onSubmit }: Props = $props();

    type StepNum = 1 | 2 | 3;
    let step = $state<StepNum>(1);
    let highest = $state<StepNum>(1);

    let defaultTo = $state<string>(otherSites[0]?.id ?? '');
    let overrides = $state<Record<string, string>>({});
    let filter = $state('');
    let reason = $state('');
    let ack = $state(false);
    let submitting = $state(false);

    function jump(n: StepNum) {
        step = n;
    }
    function next() {
        step = (step + 1) as StepNum;
        highest = Math.max(highest, step) as StepNum;
    }
    function back() {
        step = (step - 1) as StepNum;
    }

    const filtered = $derived(
        equipment.filter(
            (e) =>
                !filter ||
                e.name.toLowerCase().includes(filter.toLowerCase()) ||
                (e.room ?? '').toLowerCase().includes(filter.toLowerCase()),
        ),
    );

    const overrideCount = $derived(Object.keys(overrides).length);
    const countsByDest = $derived.by(() => {
        const out: Record<string, number> = {};
        for (const e of equipment) {
            const dest = overrides[e.id] ?? defaultTo;
            out[dest] = (out[dest] ?? 0) + 1;
        }
        return out;
    });

    function siteName(id: string): string {
        return otherSites.find((s) => s.id === id)?.name ?? id;
    }

    async function submit() {
        if (!ack || !reason.trim()) return;
        submitting = true;
        try {
            await onSubmit({ default_move_to: defaultTo, overrides, reason });
            onClose();
        } finally {
            submitting = false;
        }
    }
</script>

<Dialog.Root {open} onOpenChange={(v) => { if (!v) onClose(); }}>
    <Dialog.Content class="sm:max-w-3xl p-0">
        <header class="px-6 py-4 border-b border-border">
            <h3 class="text-base font-semibold">Archive a location</h3>
            <p class="text-xs text-muted-foreground">
                <strong>{site.name}</strong> · {equipment.length} equipment
            </p>
        </header>

        <div class="px-6 py-3 border-b border-border bg-muted/50">
            <SiteArchiveStepper currentStep={step} highestVisited={highest} onJump={jump} />
        </div>

        {#if step === 1}
            <div class="px-6 py-5 space-y-4">
                <p class="text-xs text-muted-foreground">Step 1 of 3 · Choose destination</p>
                <div class="border border-amber-200 bg-amber-50 text-amber-900 rounded-md p-3 text-sm">
                    <strong>{equipment.length}</strong> pieces of equipment will move.
                    Override per-item in step 2 if needed.
                </div>
                <div>
                    <label
                        for="default-destination"
                        class="text-xs uppercase tracking-wide text-muted-foreground font-medium"
                    >
                        Default destination site
                    </label>
                    <SitePicker
                        sites={otherSites}
                        value={defaultTo}
                        onChange={(v) => (defaultTo = v)}
                    />
                </div>
            </div>
        {:else if step === 2}
            <div class="px-6 py-4 space-y-3">
                <p class="text-xs text-muted-foreground">Step 2 of 3 · Review moves</p>
                <div class="flex items-center justify-between">
                    <p class="text-sm">
                        Default: <strong>{siteName(defaultTo)}</strong>
                    </p>
                    <input
                        class="max-w-xs w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white"
                        placeholder="Filter by name or room…"
                        bind:value={filter}
                    />
                </div>
                <div class="border border-border rounded-lg bg-white max-h-60 overflow-auto">
                    {#each filtered as e (e.id)}
                        <div class="move-row">
                            <div>
                                <div class="text-sm font-medium">{e.name}</div>
                                <div class="text-xs text-muted-foreground">
                                    {e.room ?? '—'}{e.location ? ' · ' + e.location : ''}
                                </div>
                            </div>
                            <SitePicker
                                sites={otherSites}
                                value={overrides[e.id] ?? defaultTo}
                                onChange={(v) => {
                                    if (v === defaultTo) {
                                        const { [e.id]: _omit, ...rest } = overrides;
                                        overrides = rest;
                                    } else {
                                        overrides = { ...overrides, [e.id]: v };
                                    }
                                }}
                            />
                            {#if overrides[e.id]}
                                <span class="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                                    overridden
                                </span>
                            {:else}
                                <span class="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                                    default
                                </span>
                            {/if}
                        </div>
                    {/each}
                </div>
                <p class="text-xs text-muted-foreground">
                    {overrideCount} override(s) · {equipment.length - overrideCount} follow default
                </p>
            </div>
        {:else}
            <div class="px-6 py-5 space-y-4">
                <p class="text-xs text-muted-foreground">Step 3 of 3 · Confirm &amp; archive</p>
                <div class="grid grid-cols-2 gap-3">
                    <div class="border border-border rounded-lg bg-muted/50 p-3">
                        <div class="text-xs uppercase tracking-wide text-muted-foreground font-medium mb-1">
                            Moves per destination
                        </div>
                        <ul class="text-sm space-y-1">
                            {#each Object.entries(countsByDest) as [id, count] (id)}
                                <li class="flex justify-between">
                                    <span>→ {siteName(id)}</span>
                                    <span class="font-mono">{count}</span>
                                </li>
                            {/each}
                        </ul>
                    </div>
                    <div class="border border-border rounded-lg bg-muted/50 p-3">
                        <div class="text-xs uppercase tracking-wide text-muted-foreground font-medium mb-1">
                            Side effects
                        </div>
                        <ul class="text-xs space-y-1 text-muted-foreground">
                            <li>· Rooms &amp; bench notes preserved</li>
                            <li>· Site hidden from pickers</li>
                            <li>· Past runs keep their site reference</li>
                            <li>· Audit entry per item</li>
                        </ul>
                    </div>
                </div>
                <div>
                    <label
                        for="archive-reason"
                        class="text-xs uppercase tracking-wide text-muted-foreground font-medium"
                    >
                        Reason <span class="text-destructive">*</span>
                    </label>
                    <input
                        id="archive-reason"
                        class="w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white"
                        bind:value={reason}
                        placeholder="e.g. Hayward lease ended 2026-05-15 — consolidate to HQ"
                    />
                </div>
                <label class="flex items-start gap-2 text-sm">
                    <input type="checkbox" bind:checked={ack} class="mt-1" />
                    <span>
                        I understand this site will no longer accept new equipment.
                        Past runs that reference it remain intact.
                    </span>
                </label>
            </div>
        {/if}

        <footer class="px-6 py-3 border-t border-border flex items-center justify-between bg-muted/50">
            <Button variant="ghost" onclick={onClose}>Cancel</Button>
            <div class="flex gap-2">
                {#if step > 1}
                    <Button variant="outline" onclick={back}>← Back</Button>
                {/if}
                {#if step < 3}
                    <Button onclick={next} disabled={step === 1 && !defaultTo}>
                        {step === 1 ? 'Next: Review moves →' : 'Next: Confirm →'}
                    </Button>
                {:else}
                    <Button
                        variant="destructive"
                        onclick={submit}
                        disabled={!ack || !reason.trim() || submitting}
                    >
                        Archive site &amp; move {equipment.length} item{equipment.length === 1 ? '' : 's'}
                    </Button>
                {/if}
            </div>
        </footer>
    </Dialog.Content>
</Dialog.Root>

<style>
    .move-row {
        display: grid;
        grid-template-columns: 1fr 12rem auto;
        align-items: center;
        gap: 0.75rem;
        padding: 0.75rem;
        border-bottom: 1px solid hsl(var(--border));
    }
    .move-row:last-child {
        border-bottom: 0;
    }
</style>
