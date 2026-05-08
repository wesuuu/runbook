<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

    type ConfirmPayload = {
        description: string | undefined;
        change_summary: string | undefined;
    };

    interface Props {
        open: boolean;
        versionNumber: number;
        onConfirm: (payload: ConfirmPayload) => void;
        onCancel?: () => void;
    }

    let {
        open = $bindable(false),
        versionNumber,
        onConfirm,
        onCancel,
    }: Props = $props();

    let description = $state('');
    let changeSummary = $state('');

    function reset() {
        description = '';
        changeSummary = '';
    }

    function handleCancel() {
        reset();
        open = false;
        onCancel?.();
    }

    function handlePublish() {
        const trimmedDesc = description.trim();
        const trimmedSummary = changeSummary.trim();
        onConfirm({
            description: trimmedDesc || undefined,
            change_summary: trimmedSummary || undefined,
        });
        reset();
        open = false;
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>Publish version {versionNumber}</Dialog.Title>
            <Dialog.Description>
                Optional metadata so future-you (and your team) know what changed.
            </Dialog.Description>
        </Dialog.Header>

        <div class="space-y-3">
            <div>
                <label
                    for="version-description"
                    class="block text-sm font-medium text-foreground mb-1"
                >
                    Description <span class="text-muted-foreground font-normal">(optional)</span>
                </label>
                <textarea
                    id="version-description"
                    bind:value={description}
                    rows="3"
                    placeholder="What changed in this version?"
                    class="w-full px-3 py-2 border border-border rounded-md text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent resize-y"
                ></textarea>
            </div>

            <div>
                <label
                    for="version-change-summary"
                    class="block text-sm font-medium text-foreground mb-1"
                >
                    Change summary <span class="text-muted-foreground font-normal">(one line, optional)</span>
                </label>
                <input
                    id="version-change-summary"
                    type="text"
                    bind:value={changeSummary}
                    placeholder="e.g. Reduced agitation cap from 100 → 80 rpm"
                    class="w-full px-3 py-2 border border-border rounded-md text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
                />
            </div>
        </div>

        <Dialog.Footer>
            <Button variant="secondary" onclick={handleCancel}>Cancel</Button>
            <Button onclick={handlePublish}>Publish</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
