<script lang="ts">
    import { api } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Textarea } from '$lib/components/ui/textarea';
    import { Label } from '$lib/components/ui/label';
    import * as Dialog from '$lib/components/ui/dialog';
    import { ExperimentSchema, type Experiment } from '$lib/schemas/experiments';

    interface Props {
        open: boolean;
        projectId: string;
        /** Called with the created experiment on success. */
        onCreated: (experiment: Experiment) => void;
    }

    let { open = $bindable(), projectId, onCreated }: Props = $props();

    let name = $state('');
    let objective = $state('');
    let description = $state('');
    let error = $state<string | null>(null);
    let saving = $state(false);

    function reset() {
        name = '';
        objective = '';
        description = '';
        error = null;
    }

    async function submit() {
        if (!name.trim() || saving) return;
        saving = true;
        error = null;
        try {
            const created = await api.post<Experiment>('/experiments', {
                name: name.trim(),
                project_id: projectId,
                objective: objective.trim() || null,
                description: description.trim() || null,
            }, { schema: ExperimentSchema });
            open = false;
            reset();
            onCreated(created);
        } catch (e) {
            error = e instanceof Error ? e.message : 'Failed to create experiment.';
        } finally {
            saving = false;
        }
    }
</script>

<Dialog.Root bind:open onOpenChange={(v) => !v && reset()}>
    <Dialog.Content class="sm:max-w-lg">
        <Dialog.Header>
            <Dialog.Title>New experiment</Dialog.Title>
            <Dialog.Description>
                An experiment is an investigation — give it a question to answer.
            </Dialog.Description>
        </Dialog.Header>

        <div class="space-y-4 py-2">
            <div class="space-y-1.5">
                <Label for="exp-name">Name</Label>
                <Input id="exp-name" bind:value={name} placeholder="Experiment name" />
            </div>

            <div class="space-y-1.5">
                <Label for="exp-objective">Objective</Label>
                <Textarea
                    id="exp-objective"
                    bind:value={objective}
                    placeholder="What question are you investigating?"
                    rows={3}
                />
                <p class="text-xs text-muted-foreground">
                    Tip: phrase it as a testable hypothesis, e.g. "Does raising the
                    glucose setpoint increase day-12 titer?"
                </p>
            </div>

            <div class="space-y-1.5">
                <Label for="exp-description">Description <span class="text-muted-foreground">(optional)</span></Label>
                <Textarea id="exp-description" bind:value={description} rows={2} />
                <p class="text-xs text-muted-foreground">
                    Background or scope — distinct from the objective question above.
                </p>
            </div>

            {#if error}
                <p class="text-sm text-destructive">{error}</p>
            {/if}
        </div>

        <Dialog.Footer>
            <Button
                variant="ghost"
                onclick={() => {
                    open = false;
                    reset();
                }}
            >
                Cancel
            </Button>
            <Button onclick={submit} disabled={!name.trim() || saving}>
                {saving ? 'Creating…' : 'Create experiment'}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
