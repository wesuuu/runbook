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
 * The GLP sign-off roles a run must collect before it can be completed.
 *
 * A run is GLP iff its protocol enables a reviewer role —
 * `require_study_director` or `require_qau`. That is the same signal the
 * backend uses to gate run completion, and the one the protocol editor
 * uses to derive `protocol.requires_approval`. A basic (non-GLP)
 * protocol enables neither, so its runs need no sign-off at all and this
 * returns an empty list — no sign-off section should be shown (#18).
 *
 * For a GLP run the OPERATOR sign-off is always required; STUDY_DIRECTOR
 * and QAU are each added when their flag is set.
 */
export function resolveRequiredRoles(settings: GlpSettings): GlpRole[] {
    if (!settings.require_study_director && !settings.require_qau) {
        return [];
    }
    const roles: GlpRole[] = ['OPERATOR'];
    if (settings.require_study_director) {
        roles.push('STUDY_DIRECTOR');
    }
    if (settings.require_qau) {
        roles.push('QAU');
    }
    return roles;
}

/**
 * Frontend mirror of the backend `assert_run_can_close` predicate.
 *
 * Validates that a run has the required GLP signoffs before it can be
 * closed/completed. Backend remains the source of truth — this is a
 * preflight check to surface errors before the user submits.
 *
 * F-0080 (decision C1): Study Director and QAU review happen
 * *asynchronously after* the run reaches COMPLETED — auto-generated
 * `GlpSignoffRequest` rows surfaced in the `/reviews` queue. They no
 * longer gate closure; only the OPERATOR sign-off does. This must mirror
 * the backend predicate exactly, otherwise the preflight blocks
 * completion before the request reaches the server and the async review
 * queue is never populated.
 *
 * A basic (non-GLP) run — neither reviewer flag set — has no sign-off
 * gate at all and closes freely (#18). Only a GLP run requires the
 * OPERATOR sign-off; SD/QAU requirements are enforced post-completion by
 * the backend signoff-request generator.
 */
export function validateCanCloseRun(
    run: Run,
    settings: GlpSettings,
    activeSignoffs: GlpSignoffResponse[],
): CanCloseResult {
    // run is part of the signature for call-site stability and to mirror
    // the backend predicate's argument list exactly.
    void run;
    // Basic (non-GLP) run: no reviewer role enabled, no sign-off gate (#18).
    if (!settings.require_study_director && !settings.require_qau) {
        return { ok: true, missing: [] };
    }
    const have = new Set<GlpRole>(activeSignoffs.map((s) => s.role));
    const missing: GlpRole[] = [];
    if (!have.has('OPERATOR')) {
        missing.push('OPERATOR');
    }
    return { ok: missing.length === 0, missing };
}
