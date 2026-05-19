import type { GlpSignoffResponse } from '$lib/schemas/glpSignoff';

export interface QauIndependentResult {
    ok: boolean;
    conflictRole?: 'OPERATOR' | 'STUDY_DIRECTOR';
}

/**
 * T2 preflight: cheap independence check for a proposed QAU signoff.
 *
 * GLP requires the QAU (Quality Assurance Unit) signer to be
 * independent from the OPERATOR and STUDY_DIRECTOR. The backend
 * predicate is the authoritative check — it considers per-step actors,
 * lane assignments, and protocol SD — which is too expensive to mirror
 * client-side. This helper only catches the obvious duplicate cases:
 *
 * - The proposed QAU signer is the run's OPERATOR signer
 * - The proposed QAU signer is the active STUDY_DIRECTOR signer
 *
 * Backend remains the source of truth.
 */
export function validateQauIndependent(
    activeSignoffs: GlpSignoffResponse[],
    proposedQauSignerId: string,
    operatorSignerId: string | null,
): QauIndependentResult {
    if (operatorSignerId && operatorSignerId === proposedQauSignerId) {
        return { ok: false, conflictRole: 'OPERATOR' };
    }
    const sd = activeSignoffs.find((s) => s.role === 'STUDY_DIRECTOR');
    if (sd && sd.signer_id === proposedQauSignerId) {
        return { ok: false, conflictRole: 'STUDY_DIRECTOR' };
    }
    return { ok: true };
}
