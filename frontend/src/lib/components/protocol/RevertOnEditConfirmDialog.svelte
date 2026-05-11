<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

    interface Props {
        open: boolean;
        onConfirm: () => void;
        onCancel: () => void;
    }

    let { open = $bindable(false), onConfirm, onCancel }: Props = $props();

    function handleCancel() {
        open = false;
        onCancel();
    }

    function handleConfirm() {
        open = false;
        onConfirm();
    }
</script>

<Dialog.Root bind:open onOpenChange={(v) => { if (!v) onCancel(); }}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>Revert to Draft on Edit?</Dialog.Title>
        </Dialog.Header>
        <p class="text-sm text-muted-foreground">
            Editing this protocol will revert it from APPROVED to DRAFT and
            require re-approval before runs can be created. Continue?
        </p>
        <Dialog.Footer>
            <Button variant="secondary" onclick={handleCancel}>Cancel</Button>
            <Button variant="default" onclick={handleConfirm}>
                Continue editing
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
