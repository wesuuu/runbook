import { describe, it, expect, vi } from 'vitest';
import { normalizeEndpoint as _normalizeEndpoint } from './normalizeEndpoint';
import { extractErrorMessage } from './apiError';
import { z } from 'zod';

describe('extractErrorMessage', () => {
    it('returns a string detail directly', () => {
        expect(extractErrorMessage({ detail: 'Not found' }, 'fallback')).toBe(
            'Not found',
        );
    });

    it('extracts message from a structured object detail', () => {
        const body = {
            detail: { error: 'SIGNATURE_REQUIRED', message: 'A saved signature is required.' },
        };
        expect(extractErrorMessage(body, 'fallback')).toBe(
            'A saved signature is required.',
        );
    });

    it('falls back to the error code when an object detail has no message', () => {
        const body = { detail: { error: 'ATTESTATION_REQUIRED' } };
        expect(extractErrorMessage(body, 'fallback')).toBe('ATTESTATION_REQUIRED');
    });

    it('never returns "[object Object]" for an object detail', () => {
        const body = { detail: { error: 'ATTESTATION_REQUIRED', role: 'OPERATOR' } };
        expect(extractErrorMessage(body, 'fallback')).not.toBe('[object Object]');
    });

    it('extracts msg from a 422 validation error list', () => {
        const body = { detail: [{ loc: ['body', 'name'], msg: 'field required' }] };
        expect(extractErrorMessage(body, 'fallback')).toBe('field required');
    });

    it('uses top-level message when no detail is present', () => {
        expect(extractErrorMessage({ message: 'Boom' }, 'fallback')).toBe('Boom');
    });

    it('returns the fallback for an empty or non-object body', () => {
        expect(extractErrorMessage(null, 'fallback')).toBe('fallback');
        expect(extractErrorMessage({}, 'fallback')).toBe('fallback');
    });
});

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
