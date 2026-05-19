<script lang="ts">
    import { Textarea } from '$lib/components/ui/textarea';

    export type RunOutcome =
        | 'COMPLETED_NORMAL'
        | 'COMPLETED_WITH_DEVIATIONS'
        | 'ABORTED';

    interface Props {
        outcome: RunOutcome | null;
        outcomeNotes: string;
        onChange: (outcome: RunOutcome, notes: string) => void;
    }

    let { outcome, outcomeNotes, onChange }: Props = $props();

    interface Option {
        value: RunOutcome;
        title: string;
        description: string;
    }

    const options: Option[] = [
        {
            value: 'COMPLETED_NORMAL',
            title: 'Completed normally',
            description: 'All steps executed within specification.',
        },
        {
            value: 'COMPLETED_WITH_DEVIATIONS',
            title: 'Completed with deviations',
            description:
                'Run finished but one or more deviations were recorded.',
        },
        {
            value: 'ABORTED',
            title: 'Aborted',
            description: 'Run stopped before normal completion.',
        },
    ];

    function selectOutcome(value: RunOutcome): void {
        onChange(value, outcomeNotes);
    }

    function notesChanged(event: Event): void {
        const value = (event.target as HTMLTextAreaElement).value;
        if (outcome) {
            onChange(outcome, value);
        }
    }
</script>

<div class="space-y-4">
    <div>
        <div class="mb-2 text-sm font-semibold">Run outcome</div>
        <div class="grid gap-2">
            {#each options as opt (opt.value)}
                {@const selected = outcome === opt.value}
                <button
                    type="button"
                    class="flex w-full cursor-pointer items-start gap-3 rounded-md border px-3 py-3 text-left transition-all duration-150 hover:brightness-95"
                    class:border-primary={selected}
                    class:bg-accent={selected}
                    class:border-border={!selected}
                    onclick={() => selectOutcome(opt.value)}
                    aria-pressed={selected}
                    data-outcome={opt.value}
                >
                    <span
                        class="mt-1 inline-block h-3 w-3 shrink-0 rounded-full border"
                        class:border-primary={selected}
                        class:bg-primary={selected}
                        class:border-border={!selected}
                    ></span>
                    <span class="min-w-0">
                        <span class="block text-sm font-medium">
                            {opt.title}
                        </span>
                        <span
                            class="block text-xs text-muted-foreground"
                        >
                            {opt.description}
                        </span>
                    </span>
                </button>
            {/each}
        </div>
    </div>

    <div>
        <label
            for="run-outcome-notes"
            class="mb-1 block text-sm font-medium"
        >
            Outcome notes
        </label>
        <Textarea
            id="run-outcome-notes"
            rows={3}
            value={outcomeNotes}
            oninput={notesChanged}
            placeholder="Summarise the result, deviations, or reason for abort."
        />
    </div>
</div>
