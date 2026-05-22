import { describe, expect, it } from 'vitest';
import {
    NotificationSchema,
    NotificationListResponseSchema,
    UnreadCountResponseSchema,
} from './notifications';

const VALID = {
    id: '11111111-1111-1111-1111-111111111111',
    user_id: '22222222-2222-2222-2222-222222222222',
    event_type: 'RUN_STARTED',
    entity_type: 'run',
    entity_id: '33333333-3333-3333-3333-333333333333',
    title: 'Run started',
    message: 'CHO-042 started',
    read_at: null,
    created_at: '2026-05-21T10:00:00Z',
};

describe('notification schemas', () => {
    it('parses a valid notification', () => {
        expect(NotificationSchema.parse(VALID).title).toBe('Run started');
    });

    it('keeps unknown fields (passthrough, forward compat)', () => {
        const parsed = NotificationSchema.parse({ ...VALID, future: 1 });
        expect((parsed as Record<string, unknown>).future).toBe(1);
    });

    it('parses a list response', () => {
        const parsed = NotificationListResponseSchema.parse({
            items: [VALID],
            total: 1,
        });
        expect(parsed.items).toHaveLength(1);
        expect(parsed.total).toBe(1);
    });

    it('parses an unread-count response', () => {
        expect(UnreadCountResponseSchema.parse({ count: 5 }).count).toBe(5);
    });

    it('rejects a notification missing required id', () => {
        const { id: _id, ...withoutId } = VALID;
        expect(() => NotificationSchema.parse(withoutId)).toThrow();
    });
});
