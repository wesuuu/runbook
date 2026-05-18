<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { SiteCreateSchema, type SiteCreate, type Site } from '$lib/schemas/sites';
    import { validate, firstError } from '$lib/validation';

    interface Props {
        open: boolean;
        initial?: Site | null;
        onClose: () => void;
        onSubmit: (payload: SiteCreate) => Promise<void>;
    }

    let { open, initial = null, onClose, onSubmit }: Props = $props();
    let name = $state(initial?.name ?? '');
    let description = $state(initial?.description ?? '');
    let saving = $state(false);
    let errors = $state<Record<string, string[]>>({});

    $effect(() => {
        if (open) {
            name = initial?.name ?? '';
            description = initial?.description ?? '';
            errors = {};
        }
    });

    async function submit() {
        const result = validate(SiteCreateSchema, {
            name,
            description: description || undefined,
        });
        if (!result.success || !result.data) {
            errors = result.errors;
            return;
        }
        saving = true;
        try {
            await onSubmit(result.data);
            onClose();
        } finally {
            saving = false;
        }
    }
</script>

<Dialog.Root {open} onOpenChange={(v) => { if (!v) onClose(); }}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>{initial ? 'Edit site' : 'New site'}</Dialog.Title>
        </Dialog.Header>
        <div class="space-y-3 py-2">
            <div>
                <label class="text-xs uppercase tracking-wide text-muted-foreground font-medium" for="site-name">Name</label>
                <Input id="site-name" bind:value={name} placeholder="e.g. South Bay HQ" />
                {#if firstError(errors, 'name')}
                    <p class="text-xs text-destructive">{firstError(errors, 'name')}</p>
                {/if}
            </div>
            <div>
                <label class="text-xs uppercase tracking-wide text-muted-foreground font-medium" for="site-description">Description</label>
                <Input id="site-description" bind:value={description} placeholder="optional" />
                {#if firstError(errors, 'description')}
                    <p class="text-xs text-destructive">{firstError(errors, 'description')}</p>
                {/if}
            </div>
        </div>
        <Dialog.Footer>
            <Button variant="outline" onclick={onClose}>Cancel</Button>
            <Button onclick={submit} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
