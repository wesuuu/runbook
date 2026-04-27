import { describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({
    api: {
        get: vi.fn(),
        post: vi.fn(),
    },
}));

import { api } from './api';
import {
    fetchCurrentLegalVersion,
    fetchLegalDocument,
    acceptTos,
} from './legal-api';

describe('fetchCurrentLegalVersion', () => {
    it('calls GET /legal/current', async () => {
        vi.mocked(api.get).mockResolvedValueOnce({
            version: '2026-04-27',
            effective_date: '2026-04-27',
        });
        const result = await fetchCurrentLegalVersion();
        expect(api.get).toHaveBeenCalledWith(
            '/legal/current',
            expect.objectContaining({ schema: expect.anything() }),
        );
        expect(result).toEqual({
            version: '2026-04-27',
            effective_date: '2026-04-27',
        });
    });
});

describe('fetchLegalDocument', () => {
    it('calls GET /legal/versions/{version}/terms', async () => {
        vi.mocked(api.get).mockResolvedValueOnce({
            version: '2026-04-27',
            effective_date: '2026-04-27',
            markdown: '# Terms',
        });
        const result = await fetchLegalDocument('2026-04-27', 'terms');
        expect(api.get).toHaveBeenCalledWith(
            '/legal/versions/2026-04-27/terms',
            expect.objectContaining({ schema: expect.anything() }),
        );
        expect(result.markdown).toBe('# Terms');
    });

    it('calls GET /legal/versions/{version}/privacy', async () => {
        vi.mocked(api.get).mockResolvedValueOnce({
            version: '2026-04-27',
            effective_date: '2026-04-27',
            markdown: '# Privacy',
        });
        await fetchLegalDocument('2026-04-27', 'privacy');
        expect(api.get).toHaveBeenCalledWith(
            '/legal/versions/2026-04-27/privacy',
            expect.objectContaining({ schema: expect.anything() }),
        );
    });
});

describe('acceptTos', () => {
    it('calls POST /auth/accept-tos', async () => {
        vi.mocked(api.post).mockResolvedValueOnce({ tos_current: true });
        const result = await acceptTos();
        expect(api.post).toHaveBeenCalledWith('/auth/accept-tos', undefined);
        expect(result).toEqual({ tos_current: true });
    });
});
