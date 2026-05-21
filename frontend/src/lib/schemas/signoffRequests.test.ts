import { describe, expect, it } from 'vitest';
import { SignoffRequestItemSchema, SignoffRequestListSchema } from './signoffRequests';

describe('SignoffRequestItemSchema', () => {
    it('parses a run queue item', () => {
        const item = SignoffRequestItemSchema.parse({
            type: 'run',
            request_id: '11111111-1111-1111-1111-111111111111',
            target_id: '22222222-2222-2222-2222-222222222222',
            target_name: 'Run 7',
            role: 'QAU',
            assigned: false,
            created_at: '2026-05-20T10:00:00Z',
        });
        expect(item.type).toBe('run');
        expect(item.assigned).toBe(false);
    });

    it('parses a list', () => {
        expect(SignoffRequestListSchema.parse([])).toEqual([]);
    });
});
