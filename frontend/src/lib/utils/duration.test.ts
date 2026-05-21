import { describe, it, expect } from 'vitest';
import {
    clampDuration,
    MIN_DURATION_MIN,
    MIN_DURATION_MIN_TIMELINE,
} from './duration';

describe('clampDuration', () => {
    it('passes through a valid positive duration', () => {
        expect(clampDuration(30, false)).toBe(30);
    });

    it('allows a value exactly at the minimum', () => {
        expect(clampDuration(MIN_DURATION_MIN, false)).toBe(MIN_DURATION_MIN);
    });

    it('clamps a negative duration to the minimum', () => {
        expect(clampDuration(-9999, false)).toBe(MIN_DURATION_MIN);
    });

    it('clamps zero to the minimum', () => {
        expect(clampDuration(0, false)).toBe(MIN_DURATION_MIN);
    });

    it('clamps NaN to the minimum', () => {
        expect(clampDuration(NaN, false)).toBe(MIN_DURATION_MIN);
    });

    it('clamps null (a cleared number input) to the minimum', () => {
        expect(clampDuration(null, false)).toBe(MIN_DURATION_MIN);
    });

    it('clamps undefined to the minimum', () => {
        expect(clampDuration(undefined, false)).toBe(MIN_DURATION_MIN);
    });

    it('clamps Infinity to the minimum', () => {
        expect(clampDuration(Infinity, false)).toBe(MIN_DURATION_MIN);
    });

    it('uses the 5-minute floor when the timeline is enabled', () => {
        expect(clampDuration(2, true)).toBe(MIN_DURATION_MIN_TIMELINE);
    });

    it('allows a value at the timeline floor', () => {
        expect(clampDuration(MIN_DURATION_MIN_TIMELINE, true)).toBe(
            MIN_DURATION_MIN_TIMELINE,
        );
    });

    it('passes through a large valid duration when the timeline is on', () => {
        expect(clampDuration(120, true)).toBe(120);
    });
});
