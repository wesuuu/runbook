<script lang="ts">
    type StepNum = 1 | 2 | 3;
    interface Props {
        currentStep: StepNum;
        highestVisited: StepNum;
        onJump: (step: StepNum) => void;
    }

    let { currentStep, highestVisited, onJump }: Props = $props();
    const steps = [
        { n: 1 as const, label: 'Destination' },
        { n: 2 as const, label: 'Review moves' },
        { n: 3 as const, label: 'Confirm & archive' },
    ];
</script>

<nav class="stepper" aria-label="Archive site steps">
    {#each steps as s, i (s.n)}
        <button
            type="button"
            class="step-pill cursor-pointer transition-all duration-150"
            class:active={s.n === currentStep}
            class:visited={s.n < currentStep}
            disabled={s.n > highestVisited}
            onclick={() => { if (s.n <= highestVisited) onJump(s.n); }}
        >
            <span class="step-num">{s.n < currentStep ? '✓' : s.n}</span>
            <span class="step-label">{s.label}</span>
        </button>
        {#if i < steps.length - 1}
            <span class="step-sep" aria-hidden="true">›</span>
        {/if}
    {/each}
</nav>

<style>
    .stepper { display: flex; align-items: center; gap: .25rem; font-size: .875rem; }
    .step-pill { display: inline-flex; align-items: center; gap: .5rem; padding: .375rem .75rem; border-radius: .375rem; color: hsl(215 15% 50%); border: 1px solid transparent; background: transparent; }
    .step-pill:hover:not(:disabled) { background: hsl(var(--muted)); }
    .step-pill:disabled { opacity: .4; cursor: not-allowed; }
    .step-pill.visited { color: hsl(215 25% 27%); }
    .step-pill.active { background: hsl(195 85% 22% / .08); border-color: hsl(195 85% 22% / .30); color: hsl(var(--primary)); }
    .step-num { display: inline-flex; align-items: center; justify-content: center; width: 1.25rem; height: 1.25rem; border-radius: 9999px; background: hsl(205 22% 87%); color: hsl(215 25% 35%); font-size: .75rem; font-weight: 600; }
    .step-pill.active .step-num { background: hsl(var(--primary)); color: white; }
    .step-pill.visited:not(.active) .step-num { background: hsl(var(--accent)); color: white; }
    .step-sep { color: hsl(205 22% 75%); padding: 0 .125rem; }
</style>
