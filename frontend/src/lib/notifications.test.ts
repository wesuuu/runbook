import { describe, expect, it } from 'vitest';
import {
    eventIcon,
    eventTone,
    BELL_LIMIT,
    HISTORY_PAGE_SIZE,
} from './notifications';

describe('eventIcon', () => {
    it('returns a component for a known event type', () => {
        expect(eventIcon('RUN_STARTED')).toBeTruthy();
    });

    it('returns a fallback component for an unknown event type', () => {
        expect(eventIcon('SOMETHING_NEW')).toBeTruthy();
    });
});

describe('eventTone', () => {
    it('returns a tone class for a known event type', () => {
        expect(eventTone('STEP_DEVIATION')).toContain('destructive');
    });

    it('returns the muted fallback for an unknown event type', () => {
        expect(eventTone('SOMETHING_NEW')).toBe(
            'bg-muted text-muted-foreground',
        );
    });
});

describe('constants', () => {
    it('exposes the bell and history page sizes', () => {
        expect(BELL_LIMIT).toBe(20);
        expect(HISTORY_PAGE_SIZE).toBe(25);
    });
});
