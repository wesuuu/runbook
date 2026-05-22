import { describe, expect, it } from 'vitest';
import {
    eventIcon,
    eventTone,
    notificationHref,
    BELL_LIMIT,
    HISTORY_PAGE_SIZE,
} from './notifications';

const UUID = '33333333-3333-3333-3333-333333333333';

describe('notificationHref', () => {
    it('maps known entity types to their routes', () => {
        expect(notificationHref('run', UUID)).toBe(`/runs/${UUID}`);
        expect(notificationHref('protocol', UUID)).toBe(`/protocols/${UUID}`);
        expect(notificationHref('experiment', UUID)).toBe(`/experiments/${UUID}`);
        expect(notificationHref('project', UUID)).toBe(`/projects/${UUID}`);
    });

    it('returns null for an unknown entity type', () => {
        expect(notificationHref('widget', UUID)).toBeNull();
    });

    it('returns null for a falsy or malformed entity id', () => {
        expect(notificationHref('run', '')).toBeNull();
        expect(notificationHref('run', 'not-a-uuid')).toBeNull();
    });
});

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
