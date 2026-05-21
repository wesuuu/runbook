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
 * F-0080 (decision C1): Study Director and QAU review happen
 * *asynchronously after* the run reaches COMPLETED — auto-generated
 * `GlpSignoffRequest` rows surfaced in the `/reviews` queue. They no
 * longer gate closure; only the OPERATOR sign-off does. This must mirror
 * the backend predicate exactly, otherwise the preflight blocks
 * completion before the request reaches the server and the async review
 * queue is never populated.
 *
 * `settings` is retained in the signature for call-site stability but is
 * no longer read — SD/QAU requirements are enforced post-completion by
 * the backend signoff-request generator.
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
    // run/settings are part of the signature for call-site stability and
    // to mirror the backend predicate's argument list exactly.
    void run;
    void settings;
    return { ok: missing.length === 0, missing };
}
