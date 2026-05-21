import { describe, it, expect, vi } from 'vitest';
import { normalizeEndpoint as _normalizeEndpoint } from './normalizeEndpoint';
import { z } from 'zod';

describe('_normalizeEndpoint', () => {
    it('removes trailing slash from path', () => {
        expect(_normalizeEndpoint('/projects/')).toBe('/projects');
    });

    it('removes multiple trailing slashes', () => {
        expect(_normalizeEndpoint('/projects///')).toBe('/projects');
    });

    it('preserves path without trailing slash', () => {
        expect(_normalizeEndpoint('/projects')).toBe('/projects');
    });

    it('removes trailing slash before query params', () => {
        expect(_normalizeEndpoint('/projects/?organization_id=abc')).toBe('/projects?organization_id=abc');
    });

    it('preserves query params without trailing slash', () => {
        expect(_normalizeEndpoint('/projects?organization_id=abc')).toBe('/projects?organization_id=abc');
    });

    it('handles nested paths with trailing slash', () => {
        expect(_normalizeEndpoint('/projects/123/protocols/')).toBe('/projects/123/protocols');
    });

    it('handles root path', () => {
        expect(_normalizeEndpoint('/')).toBe('');
    });

    it('handles empty string', () => {
        expect(_normalizeEndpoint('')).toBe('');
    });
});

describe('_validateResponse', () => {
    const TestSchema = z.object({
        id: z.string(),
        name: z.string(),
    }).passthrough();

    it('returns parsed data when response matches schema', async () => {
        const { _validateResponse } = await import('./apiValidation');
        const data = { id: '123', name: 'Test' };
        const result = _validateResponse(data, TestSchema, '/test');
        expect(result).toEqual(data);
    });

    it('passes through unknown fields with passthrough schema', async () => {
        const { _validateResponse } = await import('./apiValidation');
        const data = { id: '123', name: 'Test', extra: true };
        const result = _validateResponse(data, TestSchema, '/test');
        expect(result).toEqual(data);
    });

    it('throws in dev mode when response mismatches schema', async () => {
        // import.meta.env.DEV is true in vitest by default
        const { _validateResponse } = await import('./apiValidation');
        const badData = { id: 123, name: 'Test' }; // id should be string
        expect(() => _validateResponse(badData, TestSchema, '/test')).toThrow(
            'API response validation failed',
        );
    });

    it('warns in prod mode when response mismatches schema', async () => {
        // Temporarily override DEV
        const originalDev = import.meta.env.DEV;
        import.meta.env.DEV = false;
        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

        try {
            const { _validateResponse } = await import('./apiValidation');
            const badData = { id: 123, name: 'Test' };
            const result = _validateResponse(badData, TestSchema, '/test');

            // Should return the raw data, not throw
            expect(result).toEqual(badData);
            expect(warnSpy).toHaveBeenCalledWith(
                expect.stringContaining('API response validation failed'),
            );
        } finally {
            import.meta.env.DEV = originalDev;
            warnSpy.mockRestore();
        }
    });
});

describe('_handleErrorResponse', () => {
    async function captureRejection(body: unknown, status: number, fallback: string) {
        const { _handleErrorResponse } = await import('./api');
        const res = new Response(JSON.stringify(body), { status });
        try {
            await _handleErrorResponse(res, fallback);
        } catch (e) {
            return e;
        }
        throw new Error('_handleErrorResponse did not throw');
    }

    it('uses a string detail as the error message', async () => {
        const err = await captureRejection({ detail: 'Not found' }, 404, 'fallback');
        expect((err as Error).message).toBe('Not found');
        expect((err as { status: number }).status).toBe(404);
    });

    it('extracts detail.message when detail is an object (SLUG_CONFLICT)', async () => {
        const body = {
            detail: {
                code: 'SLUG_CONFLICT',
                message:
                    "A project named 'CHO Line' already exists in this organization.",
            },
        };
        const err = await captureRejection(body, 422, 'fallback');
        // The human message is surfaced — not "[object Object]".
        expect((err as Error).message).toBe(body.detail.message);
        // The structured body is preserved so callers can match on .code.
        expect((err as { data: unknown }).data).toEqual(body);
    });

    it('falls back to the default message for a Pydantic error list', async () => {
        const body = {
            detail: [{ loc: ['body', 'name'], msg: 'field required' }],
        };
        const err = await captureRejection(body, 422, 'Request failed');
        expect((err as Error).message).toBe('Request failed');
    });
});
