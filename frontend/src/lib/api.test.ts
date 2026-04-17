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
        expect(_normalizeEndpoint('/science/projects/123/protocols/')).toBe('/science/projects/123/protocols');
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
