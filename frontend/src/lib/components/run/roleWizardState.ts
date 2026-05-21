/**
 * Pure state helpers for the run RoleWizard. Extracted so the progress and
 * field-locking rules are unit-testable without rendering the full wizard.
 */

/** A run step's execution status as stored in `stepData`. */
export type StepStatus =
    | 'pending'
    | 'in_progress'
    | 'completed'
    | 'skipped'
    | undefined;

/**
 * Percent for the wizard progress bar — driven by how many steps are
 * actually COMPLETED, not by which step is currently being viewed.
 *
 * The bar previously tracked `currentStepIdx`, so it sat at ~50% even when
 * every step of a two-step run was completed (QA issue #24).
 *
 * @param completed Number of steps whose status is "completed".
 * @param total Total number of steps in the run.
 * @returns A percentage in the range [0, 100].
 */
export function stepProgressPercent(completed: number, total: number): number {
    if (total <= 0) return 0;
    const pct = (completed / total) * 100;
    if (pct < 0) return 0;
    if (pct > 100) return 100;
    return pct;
}

/**
 * Whether a step's recordable fields (results, notes, capture) should be
 * locked against editing.
 *
 * A step is locked when the wizard is in read-only (observer) mode, or once
 * the step has been marked complete — a completed step must be explicitly
 * reopened before its recorded values can change (QA issue #23).
 *
 * @param readonly Whether the wizard is rendered in observer/read-only mode.
 * @param stepStatus The current step's execution status.
 */
export function areStepFieldsLocked(
    readonly: boolean,
    stepStatus: StepStatus,
): boolean {
    return readonly || stepStatus === 'completed';
}

/**
 * Whether the barcode-scan affordance should be offered for a recordable
 * field of the given JSON-schema type.
 *
 * Barcodes encode text identifiers (lot numbers, sample IDs). Offering a
 * scanner next to a numeric process parameter — RPM, duration, temperature —
 * makes no sense, so the affordance is shown only for text fields (QA
 * issue #26).
 *
 * @param fieldType The field's JSON-schema `type` (e.g. "string", "number").
 */
export function barcodeScanApplies(fieldType: string | undefined): boolean {
    return fieldType !== 'number' && fieldType !== 'integer';
}
