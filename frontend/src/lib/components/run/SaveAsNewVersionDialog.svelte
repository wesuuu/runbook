<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import type { Edit } from '$lib/utils/runOverrides';

    interface Props {
        open: boolean;
        edits: Edit[];
        nextVersionNumber: number;
        onCancel: () => void;
        onJustThisRun: () => void;
        onSaveAsVersion: (description: string) => void;
    }

    let {
        open = $bindable(false),
        edits,
        nextVersionNumber,
        onCancel,
        onJustThisRun,
        onSaveAsVersion,
    }: Props = $props();

    let description = $state('');

    function summary(e: Edit): string {
        if (e.kind === 'INSTRUCTION') {
            const oldStr = String(e.oldValue ?? '').slice(0, 40);
            const newStr = String(e.newValue ?? '').slice(0, 40);
            return `${oldStr}… → ${newStr}…`;
        }
        if (e.oldValue !== undefined && e.newValue !== undefined) {
            return `${String(e.oldValue)} → ${String(e.newValue)}`;
        }
        return e.fieldLabel ?? '';
    }

    function diffKey(e: Edit): string {
        return `${e.nodeId}|${e.kind}|${e.field ?? ''}`;
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-lg">
        <Dialog.Header>
            <Dialog.Title>Save as a new protocol version?</Dialog.Title>
            <Dialog.Description>
                You've made {edits.length} edit{edits.length === 1 ? '' : 's'} to the protocol.
                You can keep them just for this run, or publish them as v{nextVersionNumber} so future runs inherit them.
            </Dialog.Description>
        </Dialog.Header>

        <div class="edits-list">
            {#each edits as e (diffKey(e))}
                <div class="edit-row">
                    <span class="edit-tag tag-{e.kind.toLowerCase()}">{e.kind}</span>
                    <span class="edit-step">{e.stepName}</span>
                    <span class="edit-summary">{e.fieldLabel ?? ''} {summary(e)}</span>
                </div>
            {/each}
        </div>

        <div class="version-desc">
            <label for="save-as-desc" class="field-label">Version description (optional)</label>
            <textarea
                id="save-as-desc"
                bind:value={description}
                rows="2"
                placeholder="e.g. Reduced pH target for DOE arm 4; swapped to Bioreactor B"
                class="textarea-field"
            ></textarea>
        </div>

        <Dialog.Footer>
            <Button variant="ghost" onclick={onCancel}>Cancel</Button>
            <Button variant="secondary" onclick={() => onSaveAsVersion(description)}>
                Save as v{nextVersionNumber}
            </Button>
            <Button autofocus onclick={onJustThisRun}>
                Just for this run · continue →
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>

<style>
    .edits-list {
        display: flex;
        flex-direction: column;
        gap: 0.375rem;
        max-height: 16rem;
        overflow-y: auto;
        padding: 0.5rem 0;
    }
    .edit-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.875rem;
    }
    .edit-tag {
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.375rem;
        border-radius: 0.25rem;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
    }
    .tag-value, .tag-swap {
        background-color: rgb(209 250 229);
        color: rgb(6 95 70);
    }
    .tag-added, .tag-schema {
        background-color: rgb(254 243 199);
        color: rgb(146 64 14);
    }
    .tag-removed {
        background-color: rgb(254 226 226);
        color: rgb(153 27 27);
    }
    .tag-instruction {
        background-color: rgb(219 234 254);
        color: rgb(30 64 175);
    }
    .edit-step {
        font-weight: 500;
        color: rgb(30 41 59);
    }
    .edit-summary {
        color: rgb(100 116 139);
        font-size: 0.75rem;
    }
    .version-desc {
        margin-top: 0.75rem;
        display: flex;
        flex-direction: column;
        gap: 0.375rem;
    }
    .field-label {
        font-size: 0.875rem;
        font-weight: 500;
        color: rgb(51 65 85);
    }
    .textarea-field {
        width: 100%;
        padding: 0.5rem 0.75rem;
        border: 1px solid rgb(209 213 219);
        border-radius: 0.5rem;
        font-size: 0.875rem;
    }
    .textarea-field:focus {
        outline: none;
        box-shadow: 0 0 0 2px rgb(20 184 166);
    }
</style>
