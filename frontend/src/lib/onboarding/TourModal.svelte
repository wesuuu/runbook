<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

    interface Props {
        open: boolean;
        title: string;
        description?: string;
        primaryLabel: string;
        secondaryLabel: string;
        onPrimary: () => void;
        onSecondary: () => void;
    }

    let {
        open = $bindable(),
        title,
        description,
        primaryLabel,
        secondaryLabel,
        onPrimary,
        onSecondary,
    }: Props = $props();
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>{title}</Dialog.Title>
            {#if description}
                <Dialog.Description>{description}</Dialog.Description>
            {/if}
        </Dialog.Header>
        <div class="flex justify-end gap-2 mt-4">
            <Button variant="ghost" onclick={onSecondary}>
                {secondaryLabel}
            </Button>
            <Button onclick={onPrimary}>
                {primaryLabel}
            </Button>
        </div>
    </Dialog.Content>
</Dialog.Root>
