import type { ExternalProtocolStepPreview } from '$lib/schemas/chat';

/**
 * Deterministic diff between two step lists for approval-card inline edits.
 *
 * Strategy: walk pairwise as far as the trimmed `text` matches; mismatches and
 * length differences become Added / Removed / Edited deviations. The user's
 * edits drive a small, hand-curated list of changes — they're not branching
 * here — so a positional walk produces strings that read as intended without
 * misclassifying e.g. a removed-then-edited pair as one big edit.
 */
export function computeDeviations(
    original: ExternalProtocolStepPreview[],
    edited: ExternalProtocolStepPreview[],
): string[] {
    const deviations: string[] = [];
    const o = original;
    const e = edited;
    const maxLen = Math.max(o.length, e.length);
    let oi = 0;
    let ei = 0;
    while (oi < maxLen || ei < maxLen) {
        const oStep = o[oi];
        const eStep = e[ei];
        if (oStep === undefined && eStep !== undefined) {
            deviations.push(`Added step: ${eStep.text.trim()}`);
            ei += 1;
            continue;
        }
        if (eStep === undefined && oStep !== undefined) {
            deviations.push(`Removed step: ${oStep.text.trim()}`);
            oi += 1;
            continue;
        }
        if (oStep === undefined || eStep === undefined) break;
        const oText = oStep.text.trim();
        const eText = eStep.text.trim();
        if (oText === eText) {
            oi += 1;
            ei += 1;
            continue;
        }
        // Heuristic: if the original step's text is found verbatim later in
        // `edited`, treat the current position as an "Added" (insert before
        // the matching step) rather than an "Edited".
        const laterMatchInEdited = e.findIndex(
            (s, idx) => idx > ei && s.text.trim() === oText,
        );
        if (laterMatchInEdited !== -1) {
            deviations.push(`Added step: ${eText}`);
            ei += 1;
            continue;
        }
        // Mirror: if the edited step matches a later original, the original
        // step here was removed.
        const laterMatchInOriginal = o.findIndex(
            (s, idx) => idx > oi && s.text.trim() === eText,
        );
        if (laterMatchInOriginal !== -1) {
            deviations.push(`Removed step: ${oText}`);
            oi += 1;
            continue;
        }
        // Otherwise it's an edit in place.
        deviations.push(`Edited step: ~~${oText}~~ ${eText}`);
        oi += 1;
        ei += 1;
    }
    return deviations;
}
