import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('./legal-api', () => ({
    acceptTos: vi.fn(),
}));

vi.mock('./api', () => ({
    api: { get: vi.fn(), post: vi.fn() },
    ApiError: class extends Error {
        status: number;
        constructor(status: number, message: string) {
            super(message);
            this.status = status;
        }
    },
}));

import { acceptTos as apiAcceptTos } from './legal-api';
import {
    isTosCurrent,
    acceptTos,
    switchOrg,
    pickCurrentOrg,
    getCurrentOrg,
    getToken,
    __setUserForTest,
    __setOrgStateForTest,
    type Org,
} from './auth.svelte';

describe('isTosCurrent', () => {
    it('returns true when user.tos_current is true', () => {
        __setUserForTest({ tos_current: true } as any);
        expect(isTosCurrent()).toBe(true);
    });

    it('returns false when user.tos_current is false', () => {
        __setUserForTest({ tos_current: false } as any);
        expect(isTosCurrent()).toBe(false);
    });

    it('returns false when no user is loaded', () => {
        __setUserForTest(null);
        expect(isTosCurrent()).toBe(false);
    });
});

describe('acceptTos', () => {
    beforeEach(() => vi.clearAllMocks());

    it('calls the API and updates user state', async () => {
        vi.mocked(apiAcceptTos).mockResolvedValueOnce({
            tos_current: true,
            tos_version: '2026-04-27',
            tos_accepted_at: '2026-04-27T00:00:00Z',
        });
        __setUserForTest({ tos_current: false } as any);
        await acceptTos();
        expect(apiAcceptTos).toHaveBeenCalled();
        expect(isTosCurrent()).toBe(true);
    });
});

describe('switchOrg', () => {
    const orgA = { id: 'org-a', name: 'Org A' } as Org;
    const orgB = { id: 'org-b', name: 'Org B' } as Org;

    const fetchResponse = (status: number, body: unknown) => ({
        ok: status >= 200 && status < 300,
        status,
        json: async () => body,
    });

    beforeEach(() => {
        vi.clearAllMocks();
        localStorage.clear();
        __setUserForTest({ id: 'u1' } as any);
        __setOrgStateForTest({
            token: 'tok-a',
            currentOrg: orgA,
            orgs: [orgA, orgB],
        });
    });

    it('keeps the current org unchanged when /auth/switch-org fails', async () => {
        // The desync bug: mutating currentOrg here would leave the UI on
        // orgB while the token still scopes to orgA.
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => fetchResponse(500, { detail: 'boom' })),
        );

        await expect(switchOrg(orgB)).rejects.toThrow();

        expect(getCurrentOrg()).toEqual(orgA);
        expect(getToken()).toBe('tok-a');
        expect(localStorage.getItem('current_org_id')).not.toBe('org-b');
    });

    it('switches org and stores the new token on success', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async (url: string) =>
                String(url).includes('/auth/switch-org')
                    ? fetchResponse(200, { access_token: 'tok-b' })
                    : fetchResponse(200, []),
            ),
        );

        await switchOrg(orgB);

        expect(getCurrentOrg()).toEqual(orgB);
        expect(getToken()).toBe('tok-b');
        expect(localStorage.getItem('current_org_id')).toBe('org-b');
    });
});

describe('pickCurrentOrg', () => {
    const orgA = { id: 'org-a', name: 'Org A' } as Org;
    const orgB = { id: 'org-b', name: 'Org B' } as Org;

    /** Build an unsigned JWT carrying the given payload claims. */
    function makeToken(payload: Record<string, unknown>): string {
        const body = btoa(JSON.stringify(payload))
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=/g, '');
        return `header.${body}.signature`;
    }

    it('picks the org named by the JWT org_id claim, not the first membership', () => {
        // The desync bug: the backend scopes every API call to the token's
        // org_id, so a UI showing orgA while the token carries orgB strands
        // every by-slug lookup (F-0091) against the wrong org.
        const token = makeToken({ sub: 'u1', org_id: 'org-b' });
        expect(pickCurrentOrg([orgA, orgB], token, null)).toEqual(orgB);
    });

    it('lets the JWT org_id claim override a stale saved org id', () => {
        const token = makeToken({ sub: 'u1', org_id: 'org-b' });
        expect(pickCurrentOrg([orgA, orgB], token, 'org-a')).toEqual(orgB);
    });

    it('falls back to the saved org when the token carries no org_id claim', () => {
        const token = makeToken({ sub: 'u1' });
        expect(pickCurrentOrg([orgA, orgB], token, 'org-b')).toEqual(orgB);
    });

    it('falls back to the first org when neither claim nor saved id matches', () => {
        const token = makeToken({ sub: 'u1', org_id: 'org-gone' });
        expect(pickCurrentOrg([orgA, orgB], token, null)).toEqual(orgA);
    });

    it('tolerates a malformed token and falls back to the saved org', () => {
        expect(pickCurrentOrg([orgA, orgB], 'not-a-jwt', 'org-b')).toEqual(orgB);
    });

    it('returns null when the user has no memberships', () => {
        expect(pickCurrentOrg([], makeToken({ org_id: 'org-a' }), null)).toBeNull();
    });
});
