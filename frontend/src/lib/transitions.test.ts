import { describe, it, expect, vi, afterEach } from 'vitest';
import {
    PAGE_MS,
    BLOCK_MS,
    LIST_MS,
    prefersReducedMotion,
    pageDuration,
    blockDuration,
    listDuration,
} from './transitions';

function mockReducedMotion(matches: boolean) {
    vi.stubGlobal('matchMedia', vi.fn(() => ({ matches })));
}

describe('transitions', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('exports positive numeric constants', () => {
        expect(PAGE_MS).toBeGreaterThan(0);
        expect(BLOCK_MS).toBeGreaterThan(0);
        expect(LIST_MS).toBeGreaterThan(0);
    });

    it('prefersReducedMotion returns false when matchMedia reports false', () => {
        mockReducedMotion(false);
        expect(prefersReducedMotion()).toBe(false);
    });

    it('prefersReducedMotion returns true when matchMedia reports true', () => {
        mockReducedMotion(true);
        expect(prefersReducedMotion()).toBe(true);
    });

    it('duration helpers return constant when reduced-motion is off', () => {
        mockReducedMotion(false);
        expect(pageDuration()).toBe(PAGE_MS);
        expect(blockDuration()).toBe(BLOCK_MS);
        expect(listDuration()).toBe(LIST_MS);
    });

    it('duration helpers return 0 when reduced-motion is on', () => {
        mockReducedMotion(true);
        expect(pageDuration()).toBe(0);
        expect(blockDuration()).toBe(0);
        expect(listDuration()).toBe(0);
    });
});
