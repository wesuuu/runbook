/**
 * Drift test: T2 REOPEN_NOT_AUTHORIZED — frontend preflight.
 *
 * Companion to the pytest integration test
 * (backend/tests/integration/glp/test_reopen_not_authorized_drift.py).
 *
 * The backend predicate ``assert_can_reopen`` (services/runs/validation.py)
 * authorises reopen under three tiered conditions:
 *   1. user is the active STUDY_DIRECTOR signer on the run's protocol, OR
 *   2. user has the ADMIN role in the run's org, OR
 *   3. user has ADMIN-level permission on the run's project.
 *
 * The frontend mirror must hide / disable the "Reopen with reason" button
 * unless one of those tiers is satisfied so that unauthorised users never
 * see the entry point.  Today the predicate is enforced server-side only
 * (the button shows for any user when ``activeSignoffs.length > 0``);
 * this test specifies the rule a future preflight must follow.
 */

import { describe, it, expect } from 'vitest';

interface ReopenAuthContext {
    userId: string;
    orgRoles: string[];
    isProtocolStudyDirectorSigner: boolean;
    hasProjectAdminPermission: boolean;
}

function canReopen(ctx: ReopenAuthContext): boolean {
    if (ctx.orgRoles.includes('ADMIN')) return true;
    if (ctx.isProtocolStudyDirectorSigner) return true;
    if (ctx.hasProjectAdminPermission) return true;
    return false;
}

describe('GLP drift: REOPEN_NOT_AUTHORIZED preflight', () => {
    it('rejects a plain MEMBER with no protocol/project privileges', () => {
        expect(
            canReopen({
                userId: 'u-op',
                orgRoles: ['MEMBER'],
                isProtocolStudyDirectorSigner: false,
                hasProjectAdminPermission: false,
            }),
        ).toBe(false);
    });

    it('accepts an org ADMIN', () => {
        expect(
            canReopen({
                userId: 'u-admin',
                orgRoles: ['MEMBER', 'ADMIN'],
                isProtocolStudyDirectorSigner: false,
                hasProjectAdminPermission: false,
            }),
        ).toBe(true);
    });

    it('accepts the active Study Director signer of the protocol', () => {
        expect(
            canReopen({
                userId: 'u-sd',
                orgRoles: ['MEMBER'],
                isProtocolStudyDirectorSigner: true,
                hasProjectAdminPermission: false,
            }),
        ).toBe(true);
    });

    it('accepts a user with ADMIN permission on the project', () => {
        expect(
            canReopen({
                userId: 'u-lead',
                orgRoles: ['MEMBER'],
                isProtocolStudyDirectorSigner: false,
                hasProjectAdminPermission: true,
            }),
        ).toBe(true);
    });

    it('rejects when none of the three tiers match', () => {
        expect(
            canReopen({
                userId: 'u-random',
                orgRoles: ['MEMBER', 'BILLING'],
                isProtocolStudyDirectorSigner: false,
                hasProjectAdminPermission: false,
            }),
        ).toBe(false);
    });
});
