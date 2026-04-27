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
    __setUserForTest,
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
