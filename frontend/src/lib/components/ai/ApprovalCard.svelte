<script lang="ts">
    import { fly, slide } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import Check from '@lucide/svelte/icons/check';
    import X from '@lucide/svelte/icons/x';
    import Plus from '@lucide/svelte/icons/plus';
    import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
    import AlertTriangle from '@lucide/svelte/icons/triangle-alert';
    import ChevronDown from '@lucide/svelte/icons/chevron-down';
    import { Button } from '$lib/components/ui/button';
    import type { ExternalProtocolStepPreview } from '$lib/schemas/chat';
    import { computeDeviations } from './approval-diff';

    type StepPreview = ExternalProtocolStepPreview;

    interface PayloadPreview {
        title: string;
        source_url: string;
        project_name?: string | null;
        step_count: number;
        duration_min_total?: number | null;
        license: string;
        deviations: string[];
        steps?: StepPreview[];
    }

    export interface ApprovalSubmission {
        editedSteps: StepPreview[];
        deviations: string[];
    }

    interface Props {
        toolCallId: string;
        toolName: string;
        title: string;
        sourceUrl: string;
        payloadPreview: PayloadPreview;
        pending?: boolean;
        onApprove: (toolCallId: string, submission?: ApprovalSubmission) => void;
        onReject: (toolCallId: string) => void;
    }

    let {
        toolCallId,
        title,
        sourceUrl,
        payloadPreview,
        pending = false,
        onApprove,
        onReject,
    }: Props = $props();

    const originalSteps = $derived<StepPreview[]>(payloadPreview.steps ?? []);
    let editedSteps = $state<StepPreview[]>(
        (payloadPreview.steps ?? []).map(s => ({ ...s })),
    );
    let stepsOpen = $state(false);

    const isDirty = $derived.by(() => {
        if (editedSteps.length !== originalSteps.length) return true;
        for (let i = 0; i < editedSteps.length; i++) {
            const a = editedSteps[i];
            const b = originalSteps[i];
            if (a.text !== b.text) return true;
            if ((a.duration_min ?? null) !== (b.duration_min ?? null)) return true;
        }
        return false;
    });
    const hasSteps = $derived(editedSteps.length > 0 || originalSteps.length > 0);

    const sourceHost = $derived.by(() => {
        try {
            return new URL(sourceUrl).host;
        } catch {
            return sourceUrl;
        }
    });

    function pad2(n: number): string {
        return n < 10 ? `0${n}` : `${n}`;
    }

    function updateStepText(index: number, text: string): void {
        if (editedSteps[index]?.text === text) return;
        editedSteps = editedSteps.map((s, i) =>
            i === index ? { ...s, text } : s,
        );
    }

    function updateStepDuration(index: number, raw: string): void {
        const trimmed = raw.trim();
        const parsed = trimmed === '' ? null : Number(trimmed);
        const duration_min =
            parsed === null || Number.isNaN(parsed)
                ? null
                : Math.max(0, Math.round(parsed));
        if ((editedSteps[index]?.duration_min ?? null) === duration_min) return;
        editedSteps = editedSteps.map((s, i) =>
            i === index ? { ...s, duration_min } : s,
        );
    }

    function removeStep(index: number): void {
        editedSteps = editedSteps.filter((_, i) => i !== index);
    }

    function addStep(): void {
        editedSteps = [...editedSteps, { text: '', duration_min: null }];
        stepsOpen = true;
    }

    function resetSteps(): void {
        editedSteps = originalSteps.map(s => ({ ...s }));
    }

    function handleApprove(): void {
        const cleaned = editedSteps
            .map(s => ({ ...s, text: s.text.trim() }))
            .filter(s => s.text.length > 0);
        const deviations = computeDeviations(originalSteps, cleaned);
        const changed = deviations.length > 0;
        onApprove(
            toolCallId,
            changed ? { editedSteps: cleaned, deviations } : undefined,
        );
    }

    function handleReject(): void {
        onReject(toolCallId);
    }
</script>

<div
    in:fly={{ y: 6, duration: 220 }}
    class="approval-card overflow-hidden rounded-xl"
>
    <div class="label-row flex items-center gap-2 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider">
        <AlertTriangle class="w-3.5 h-3.5" />
        External protocol · review before import
    </div>

    <div class="space-y-3 px-3.5 py-3">
        <div>
            <div class="meta-label">Title</div>
            <div class="text-[15px] font-semibold leading-tight text-foreground">
                {title}
            </div>
        </div>

        {#if payloadPreview.project_name}
            <div>
                <div class="meta-label">Destination project</div>
                <div class="text-[14px] font-medium text-foreground">
                    {payloadPreview.project_name}
                </div>
            </div>
        {/if}

        <div class="grid grid-cols-3 gap-2 text-[12px]">
            <div>
                <div class="meta-label">Steps</div>
                <div class="text-[15px] font-semibold text-foreground">
                    {editedSteps.length || payloadPreview.step_count}
                </div>
            </div>
            <div>
                <div class="meta-label">Total time</div>
                <div class="text-[15px] font-semibold text-foreground">
                    {#if payloadPreview.duration_min_total != null}
                        ~{payloadPreview.duration_min_total} min
                    {:else}
                        —
                    {/if}
                </div>
            </div>
            <div>
                <div class="meta-label">License</div>
                <div class="font-mono text-[12px] font-semibold text-foreground">
                    {payloadPreview.license}
                </div>
            </div>
        </div>

        <div>
            <div class="meta-label mb-1">Source</div>
            <a
                href={sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                class="font-mono text-[12px] text-primary underline decoration-primary/30 underline-offset-2 break-all hover:decoration-primary"
            >
                {sourceHost}
            </a>
        </div>

        <div>
            <div class="meta-label mb-1">Deviations</div>
            {#if payloadPreview.deviations.length === 0}
                <span
                    class="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-medium text-success-foreground"
                    style="background: rgba(22, 163, 74, 0.12); color: #166534;"
                >
                    <Check class="w-3 h-3" />
                    None — copied verbatim
                </span>
            {:else}
                <ul class="flex flex-col gap-1">
                    {#each payloadPreview.deviations as dev}
                        <li
                            class="rounded-md border border-dashed px-2 py-1 text-[11.5px]"
                            style="background: rgba(220, 38, 38, 0.06); color: #991b1b; border-color: rgba(220, 38, 38, 0.3);"
                        >
                            {dev}
                        </li>
                    {/each}
                </ul>
            {/if}
        </div>

        {#if hasSteps}
            <div class="procedure-block">
                <button
                    type="button"
                    class="procedure-toggle"
                    aria-expanded={stepsOpen}
                    aria-controls="approval-procedure-list"
                    onclick={() => (stepsOpen = !stepsOpen)}
                >
                    <span class="procedure-toggle-label">
                        <span class="rule" aria-hidden="true"></span>
                        <span class="text">
                            {stepsOpen ? 'Hide procedure' : 'Review & edit procedure'}
                        </span>
                        <span class="count">·&nbsp;{editedSteps.length}&nbsp;steps</span>
                        <span class="rule" aria-hidden="true"></span>
                    </span>
                    <ChevronDown
                        class="chevron w-3.5 h-3.5 {stepsOpen ? 'open' : ''}"
                    />
                </button>

                {#if stepsOpen}
                    <div
                        id="approval-procedure-list"
                        transition:slide={{ duration: 260, easing: quintOut }}
                    >
                        <ol class="procedure-list">
                            {#each editedSteps as step, i (i)}
                                <li class="procedure-item">
                                    <span class="numeral">{pad2(i + 1)}</span>
                                    <textarea
                                        class="step-text"
                                        value={step.text}
                                        rows="1"
                                        disabled={pending}
                                        aria-label={`Step ${i + 1} text`}
                                        placeholder="Step description"
                                        oninput={(e) =>
                                            updateStepText(
                                                i,
                                                (e.currentTarget as HTMLTextAreaElement).value,
                                            )}
                                    ></textarea>
                                    <input
                                        type="number"
                                        class="duration-input"
                                        min="0"
                                        step="1"
                                        value={step.duration_min ?? ''}
                                        disabled={pending}
                                        aria-label={`Step ${i + 1} duration (minutes)`}
                                        placeholder="min"
                                        oninput={(e) =>
                                            updateStepDuration(
                                                i,
                                                (e.currentTarget as HTMLInputElement).value,
                                            )}
                                    />
                                    <button
                                        type="button"
                                        class="remove-btn"
                                        disabled={pending}
                                        aria-label={`Remove step ${i + 1}`}
                                        onclick={() => removeStep(i)}
                                    >
                                        <X class="w-3 h-3" />
                                    </button>
                                </li>
                            {/each}
                            {#if editedSteps.length === 0}
                                <li class="procedure-empty">
                                    All steps removed. Add one below, or reset to restore the original.
                                </li>
                            {/if}
                        </ol>
                        <div class="procedure-actions">
                            <button
                                type="button"
                                class="action-btn"
                                disabled={pending}
                                onclick={addStep}
                                aria-label="Add step"
                            >
                                <Plus class="w-3 h-3" />
                                <span>Add step</span>
                            </button>
                            {#if isDirty}
                                <button
                                    type="button"
                                    class="action-btn"
                                    disabled={pending}
                                    onclick={resetSteps}
                                    aria-label="Reset steps to original"
                                >
                                    <RotateCcw class="w-3 h-3" />
                                    <span>Reset to original</span>
                                </button>
                            {/if}
                        </div>
                    </div>
                {/if}
            </div>
        {/if}

        <div class="flex items-center justify-end gap-2 pt-1.5">
            <Button
                variant="outline"
                size="sm"
                disabled={pending}
                onclick={handleReject}
                aria-label="Reject"
            >
                <X class="w-3.5 h-3.5 mr-1" />
                Reject
            </Button>
            <Button
                variant="default"
                size="sm"
                disabled={pending || editedSteps.length === 0}
                onclick={handleApprove}
                aria-label={isDirty ? 'Approve with edits' : 'Approve & draft'}
            >
                <Check class="w-3.5 h-3.5 mr-1" />
                {isDirty ? 'Approve with edits' : 'Approve & draft'}
            </Button>
        </div>
    </div>
</div>

<style>
    .approval-card {
        background: linear-gradient(180deg, #fffaf0 0%, #fff7e6 100%);
        border: 1px solid #fde68a;
        box-shadow:
            inset 0 0 0 1px rgba(217, 119, 6, 0.05),
            0 1px 2px rgba(217, 119, 6, 0.08);
    }
    .label-row {
        background: #fef3c7;
        border-bottom: 1px solid #fde68a;
        color: #92400e;
    }
    .meta-label {
        font-family: 'JetBrains Mono', ui-monospace, monospace;
        font-size: 10.5px;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: #92400e;
        margin-bottom: 2px;
    }
    :global(.dark) .approval-card {
        background: linear-gradient(180deg, rgba(120, 53, 15, 0.18) 0%, rgba(120, 53, 15, 0.1) 100%);
        border-color: rgba(217, 119, 6, 0.4);
    }
    :global(.dark) .label-row {
        background: rgba(217, 119, 6, 0.15);
        border-bottom-color: rgba(217, 119, 6, 0.3);
        color: #fbbf24;
    }
    :global(.dark) .meta-label {
        color: #fbbf24;
    }

    /* ── Procedure disclosure ───────────────────────────────────────────── */
    .procedure-block {
        margin-top: 2px;
    }
    .procedure-toggle {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        width: 100%;
        padding: 4px 0 2px;
        background: transparent;
        border: 0;
        cursor: pointer;
        color: #92400e;
        font-family: 'JetBrains Mono', ui-monospace, monospace;
        font-size: 10.5px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        transition: color 160ms ease;
    }
    .procedure-toggle:hover {
        color: #78350f;
    }
    .procedure-toggle-label {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 1;
    }
    .procedure-toggle-label .rule {
        flex: 1;
        height: 1px;
        background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(217, 119, 6, 0.35) 30%,
            rgba(217, 119, 6, 0.35) 70%,
            transparent 100%
        );
    }
    .procedure-toggle-label .text {
        font-weight: 600;
        white-space: nowrap;
    }
    .procedure-toggle-label .count {
        opacity: 0.7;
        white-space: nowrap;
        font-weight: 500;
    }
    .procedure-toggle :global(.chevron) {
        transition: transform 220ms cubic-bezier(0.22, 1, 0.36, 1);
        color: #b45309;
    }
    .procedure-toggle :global(.chevron.open) {
        transform: rotate(180deg);
    }

    .procedure-list {
        margin: 6px 0 0;
        padding: 4px 0;
        list-style: none;
        max-height: 360px;
        overflow-y: auto;
        border-top: 1px dashed rgba(217, 119, 6, 0.35);
        border-bottom: 1px dashed rgba(217, 119, 6, 0.35);
        background:
            linear-gradient(rgba(255, 251, 235, 0.4), rgba(255, 251, 235, 0.4));
        scrollbar-color: rgba(217, 119, 6, 0.4) transparent;
        scrollbar-width: thin;
    }
    .procedure-list::-webkit-scrollbar {
        width: 8px;
    }
    .procedure-list::-webkit-scrollbar-thumb {
        background: rgba(217, 119, 6, 0.3);
        border-radius: 4px;
    }
    .procedure-item {
        display: grid;
        grid-template-columns: auto 1fr 56px auto;
        align-items: start;
        gap: 8px;
        padding: 6px 10px;
        font-size: 12.5px;
        line-height: 1.5;
        color: #422006;
        border-top: 1px solid rgba(217, 119, 6, 0.12);
    }
    .procedure-item:first-child {
        border-top: 0;
    }
    .procedure-item .numeral {
        font-family: 'JetBrains Mono', ui-monospace, monospace;
        font-size: 10.5px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        letter-spacing: 0.04em;
        color: #b45309;
        padding-top: 6px;
        min-width: 1.6em;
    }
    .step-text {
        width: 100%;
        resize: vertical;
        min-height: 28px;
        padding: 4px 6px;
        font-family: inherit;
        font-size: 12.5px;
        line-height: 1.45;
        color: #422006;
        background: rgba(255, 255, 255, 0.6);
        border: 1px solid rgba(217, 119, 6, 0.25);
        border-radius: 4px;
        transition: border-color 140ms ease, background 140ms ease;
    }
    .step-text:focus {
        outline: none;
        border-color: rgba(180, 83, 9, 0.55);
        background: rgba(255, 255, 255, 0.95);
    }
    .step-text:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
    .duration-input {
        width: 100%;
        padding: 4px 6px;
        font-family: 'JetBrains Mono', ui-monospace, monospace;
        font-size: 11px;
        text-align: right;
        color: #92400e;
        background: rgba(255, 255, 255, 0.6);
        border: 1px solid rgba(217, 119, 6, 0.25);
        border-radius: 4px;
    }
    .duration-input:focus {
        outline: none;
        border-color: rgba(180, 83, 9, 0.55);
        background: rgba(255, 255, 255, 0.95);
    }
    .duration-input::-webkit-outer-spin-button,
    .duration-input::-webkit-inner-spin-button {
        -webkit-appearance: none;
        margin: 0;
    }
    .duration-input {
        -moz-appearance: textfield;
    }
    .remove-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 22px;
        height: 22px;
        margin-top: 3px;
        border-radius: 4px;
        background: transparent;
        border: 1px solid transparent;
        color: rgba(120, 53, 15, 0.6);
        cursor: pointer;
        transition: all 140ms ease;
    }
    .remove-btn:hover:not(:disabled) {
        background: rgba(220, 38, 38, 0.1);
        border-color: rgba(220, 38, 38, 0.35);
        color: #991b1b;
    }
    .remove-btn:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }
    .procedure-empty {
        padding: 10px 12px;
        font-size: 11.5px;
        font-style: italic;
        color: #92400e;
        opacity: 0.75;
    }
    .procedure-actions {
        display: flex;
        align-items: center;
        gap: 6px;
        margin: 6px 0 2px;
        padding: 0 4px;
    }
    .action-btn {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 8px;
        font-family: 'JetBrains Mono', ui-monospace, monospace;
        font-size: 10.5px;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: #92400e;
        background: rgba(255, 251, 235, 0.6);
        border: 1px dashed rgba(217, 119, 6, 0.4);
        border-radius: 4px;
        cursor: pointer;
        transition: all 140ms ease;
    }
    .action-btn:hover:not(:disabled) {
        background: rgba(254, 243, 199, 0.9);
        border-color: rgba(180, 83, 9, 0.6);
        color: #78350f;
    }
    .action-btn:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    :global(.dark) .procedure-toggle { color: #fbbf24; }
    :global(.dark) .procedure-toggle:hover { color: #fde68a; }
    :global(.dark) .procedure-toggle :global(.chevron) { color: #fbbf24; }
    :global(.dark) .procedure-toggle-label .rule {
        background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(251, 191, 36, 0.3) 30%,
            rgba(251, 191, 36, 0.3) 70%,
            transparent 100%
        );
    }
    :global(.dark) .procedure-list {
        border-color: rgba(251, 191, 36, 0.35);
        background: linear-gradient(rgba(120, 53, 15, 0.18), rgba(120, 53, 15, 0.18));
    }
    :global(.dark) .procedure-item {
        color: #fef3c7;
        border-top-color: rgba(251, 191, 36, 0.12);
    }
    :global(.dark) .procedure-item .numeral { color: #fbbf24; }
    :global(.dark) .step-text,
    :global(.dark) .duration-input {
        color: #fef3c7;
        background: rgba(30, 20, 10, 0.5);
        border-color: rgba(251, 191, 36, 0.3);
    }
    :global(.dark) .step-text:focus,
    :global(.dark) .duration-input:focus {
        background: rgba(30, 20, 10, 0.8);
        border-color: rgba(251, 191, 36, 0.6);
    }
    :global(.dark) .remove-btn { color: rgba(251, 191, 36, 0.7); }
    :global(.dark) .remove-btn:hover:not(:disabled) {
        background: rgba(220, 38, 38, 0.2);
        border-color: rgba(248, 113, 113, 0.5);
        color: #fca5a5;
    }
    :global(.dark) .procedure-empty { color: #fbbf24; }
    :global(.dark) .action-btn {
        color: #fbbf24;
        background: rgba(120, 53, 15, 0.3);
        border-color: rgba(251, 191, 36, 0.35);
    }
    :global(.dark) .action-btn:hover:not(:disabled) {
        background: rgba(120, 53, 15, 0.5);
        border-color: rgba(251, 191, 36, 0.6);
        color: #fde68a;
    }
</style>
