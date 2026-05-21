<script lang="ts">
    interface Counters {
        runs_blocked: number;
        calibrations_due: number;
        signoffs_pending: number;
        active_runs: number;
    }
    interface Props {
        counters: Counters;
        onActivate: (key: string) => void;
    }
    let { counters, onActivate }: Props = $props();

    type Severity = 'danger' | 'warn' | 'neutral';
    interface Card {
        key: string;
        label: string;
        value: number;
        severity: Severity;
    }

    const cards = $derived<Card[]>([
        { key: 'runs_blocked', label: 'Runs blocked', value: counters.runs_blocked, severity: 'danger' },
        { key: 'calibrations_due', label: 'Calibrations due', value: counters.calibrations_due, severity: 'warn' },
        { key: 'signoffs_pending', label: 'Sign-offs pending', value: counters.signoffs_pending, severity: 'neutral' },
        { key: 'active_runs', label: 'Active runs', value: counters.active_runs, severity: 'neutral' },
    ]);

    function valueClass(card: Card): string {
        if (card.value === 0) return 'text-muted-foreground';
        if (card.severity === 'danger') return 'text-red-600';
        if (card.severity === 'warn') return 'text-amber-600';
        return 'text-foreground';
    }
</script>

<div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
    {#each cards as card (card.key)}
        <button
            type="button"
            data-testid="counter-{card.key}"
            class="card-warm cursor-pointer rounded-xl p-4 text-left transition-all duration-150 hover:border-primary/30 hover:shadow-md"
            onclick={() => onActivate(card.key)}
        >
            <div
                data-testid="counter-value"
                class="text-3xl font-bold tracking-tight tabular-nums {valueClass(card)}"
            >
                {card.value}
            </div>
            <div class="mt-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                {card.label}
            </div>
        </button>
    {/each}
</div>
