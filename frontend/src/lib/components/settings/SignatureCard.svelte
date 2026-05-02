<script lang="ts">
    import { api } from '$lib/api';
    import { toast } from '$lib/toast';
    import { getUser, refreshUser, getToken } from '$lib/auth.svelte';
    import { API_BASE } from '$lib/config';
    import { Button } from '$lib/components/ui/button';
    import {
        Card,
        CardContent,
        CardHeader,
        CardTitle,
        CardDescription,
    } from '$lib/components/ui/card';
    import { SignaturePad, type SignaturePadHandle } from '$lib/components/ui/signature-pad';
    import { fade } from 'svelte/transition';
    import { blockDuration } from '$lib/transitions';

    let initialsPad: SignaturePadHandle | null = $state(null);
    let fullPad: SignaturePadHandle | null = $state(null);
    let initialsEmpty = $state(true);
    let fullEmpty = $state(true);
    let initialsBusy = $state(false);
    let fullBusy = $state(false);

    const user = $derived(getUser());

    function urlFor(suffix: 'initials' | 'full'): string | null {
        const u = user;
        if (!u) return null;
        const path = suffix === 'initials' ? u.signature_initials_url : u.signature_full_url;
        return path ? `${API_BASE}${path}?token=${getToken()}` : null;
    }

    const initialsUrl = $derived(urlFor('initials'));
    const fullUrl = $derived(urlFor('full'));

    async function save(kind: 'initials' | 'full', pad: SignaturePadHandle | null) {
        if (!pad) return;
        if (pad.isEmpty()) {
            toast.error('Please draw a signature before saving.');
            return;
        }
        const blob = await pad.toBlob();
        if (!blob) {
            toast.error('Could not export signature.');
            return;
        }
        const setBusy = (b: boolean) => (kind === 'initials' ? (initialsBusy = b) : (fullBusy = b));
        setBusy(true);
        try {
            const file = new File([blob], `${kind}.png`, { type: 'image/png' });
            await api.uploadFile(`/auth/me/signature/${kind}`, file);
            await refreshUser();
            pad.clear();
            toast.success(kind === 'initials' ? 'Initials saved.' : 'Signature saved.');
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to save signature.');
        } finally {
            setBusy(false);
        }
    }

    async function remove(kind: 'initials' | 'full') {
        const setBusy = (b: boolean) => (kind === 'initials' ? (initialsBusy = b) : (fullBusy = b));
        setBusy(true);
        try {
            await api.delete(`/auth/me/signature/${kind}`);
            await refreshUser();
            toast.success('Removed.');
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to remove signature.');
        } finally {
            setBusy(false);
        }
    }
</script>

<Card>
    <CardHeader>
        <CardTitle>Signature</CardTitle>
        <CardDescription>
            Drawn signatures replace the auto-generated cursive initials in PDF exports.
            Full signatures will be used for document approvals.
        </CardDescription>
    </CardHeader>
    <CardContent>
        <div class="grid gap-6 md:grid-cols-2">
            <!-- Initials -->
            <div class="space-y-3">
                <div class="flex items-center justify-between">
                    <h3 class="text-sm font-medium">Initials</h3>
                    {#if initialsBusy}
                        <span in:fade={{ duration: blockDuration() }} class="text-xs text-muted-foreground">Saving...</span>
                    {/if}
                </div>
                {#if initialsUrl}
                    <div class="flex items-center gap-3">
                        <img src={initialsUrl} alt="Saved initials" class="h-16 w-32 object-contain border border-dashed border-border rounded-md bg-background" />
                        <Button size="sm" variant="ghost" class="text-destructive" disabled={initialsBusy} onclick={() => remove('initials')}>
                            Delete
                        </Button>
                    </div>
                {/if}
                <SignaturePad
                    bind:this={initialsPad}
                    width={280}
                    height={120}
                    ariaLabel="Initials signature pad"
                    onChange={(empty) => (initialsEmpty = empty)}
                />
                <div class="flex items-center gap-2">
                    <Button size="sm" disabled={initialsBusy || initialsEmpty} onclick={() => save('initials', initialsPad)}>
                        Save Initials
                    </Button>
                    <Button size="sm" variant="outline" disabled={initialsBusy} onclick={() => initialsPad?.clear()}>
                        Clear
                    </Button>
                </div>
            </div>

            <!-- Full Signature -->
            <div class="space-y-3">
                <div class="flex items-center justify-between">
                    <h3 class="text-sm font-medium">Full Signature</h3>
                    {#if fullBusy}
                        <span in:fade={{ duration: blockDuration() }} class="text-xs text-muted-foreground">Saving...</span>
                    {/if}
                </div>
                {#if fullUrl}
                    <div class="flex items-center gap-3">
                        <img src={fullUrl} alt="Saved signature" class="h-16 w-56 object-contain border border-dashed border-border rounded-md bg-background" />
                        <Button size="sm" variant="ghost" class="text-destructive" disabled={fullBusy} onclick={() => remove('full')}>
                            Delete
                        </Button>
                    </div>
                {/if}
                <SignaturePad
                    bind:this={fullPad}
                    width={480}
                    height={120}
                    ariaLabel="Full signature pad"
                    onChange={(empty) => (fullEmpty = empty)}
                />
                <div class="flex items-center gap-2">
                    <Button size="sm" disabled={fullBusy || fullEmpty} onclick={() => save('full', fullPad)}>
                        Save Signature
                    </Button>
                    <Button size="sm" variant="outline" disabled={fullBusy} onclick={() => fullPad?.clear()}>
                        Clear
                    </Button>
                </div>
            </div>
        </div>
    </CardContent>
</Card>
