<script lang="ts">
    type StepNum = 1 | 2 | 3 | 4;

    interface Props {
        currentStep: StepNum;
        highestVisited: StepNum;
        onJump: (step: StepNum) => void;
    }

    let { currentStep, highestVisited, onJump }: Props = $props();

    const steps = [
        { n: 1, label: 'Name' },
        { n: 2, label: 'Protocol' },
        { n: 3, label: 'Parameters' },
        { n: 4, label: 'Review' },
    ] as const;
</script>

<nav class="stepper" aria-label="Run creation steps">
    {#each steps as s, i (s.n)}
        <button
            type="button"
            class="step-pill"
            class:active={s.n === currentStep}
            class:visited={s.n <= highestVisited}
            data-step={s.n}
            data-step-active={s.n === currentStep}
            disabled={s.n > highestVisited}
            onclick={() => { if (s.n <= highestVisited) onJump(s.n); }}
        >
            <span class="step-num">{s.n}</span>
            <span class="step-label">{s.label}</span>
        </button>
        {#if i < steps.length - 1}
            <span class="step-sep" aria-hidden="true">›</span>
        {/if}
    {/each}
</nav>

<style>
    .stepper {
        display: flex;
        align-items: center;
        gap: 0.25rem;
        font-size: 0.875rem;
    }
    .step-pill {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.375rem 0.75rem;
        border-radius: 0.375rem;
        color: rgb(100 116 139);
        border: 1px solid transparent;
        background: transparent;
        cursor: pointer;
        transition: all 150ms;
    }
    .step-pill:hover:not(:disabled) {
        background-color: rgb(241 245 249);
    }
    .step-pill:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }
    .step-pill.visited {
        color: rgb(51 65 85);
    }
    .step-pill.active {
        background-color: rgb(240 253 250);
        border-color: rgb(94 234 212);
        color: rgb(19 78 74);
    }
    .step-num {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.25rem;
        height: 1.25rem;
        border-radius: 9999px;
        background-color: rgb(226 232 240);
        font-size: 0.75rem;
        font-weight: 600;
    }
    .step-pill.active .step-num {
        background-color: rgb(20 184 166);
        color: white;
    }
    .step-label {
        font-weight: 500;
    }
    .step-sep {
        color: rgb(203 213 225);
        padding: 0 0.125rem;
    }
</style>
