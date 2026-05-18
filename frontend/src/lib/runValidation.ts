import type {
    GlpRole,
    GlpSettings,
    GlpSignoffResponse,
} from '$lib/schemas/glpSignoff';
import type { Run } from '$lib/schemas/runs';

export interface CanCloseResult {
    ok: boolean;
    missing: GlpRole[];
}

/**
 * Frontend mirror of the backend `assert_run_can_close` predicate.
 *
 * Validates that a run has the required GLP signoffs before it can be
 * closed/completed. Backend remains the source of truth — this is a
 * preflight check to surface errors before the user submits.
 *
 * A run requires:
 * - An OPERATOR signoff (always)
 * - A STUDY_DIRECTOR signoff if `require_study_director` is set
 * - A QAU signoff if `require_qau` is set
 */
export function validateCanCloseRun(
    run: Run,
    settings: GlpSettings,
    activeSignoffs: GlpSignoffResponse[],
): CanCloseResult {
    const have = new Set<GlpRole>(activeSignoffs.map((s) => s.role));
    const missing: GlpRole[] = [];
    if (!have.has('OPERATOR')) {
        missing.push('OPERATOR');
    }
    if (settings.require_study_director && !have.has('STUDY_DIRECTOR')) {
        missing.push('STUDY_DIRECTOR');
    }
    if (settings.require_qau && !have.has('QAU')) {
        missing.push('QAU');
    }
    // run is part of the signature for future expansion (per-step checks)
    // and to mirror the backend predicate exactly.
    void run;
    return { ok: missing.length === 0, missing };
}
