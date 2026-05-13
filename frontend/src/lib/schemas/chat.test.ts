import { describe, it, expect } from 'vitest';
import {
    ApprovalRequiredEventSchema,
    ExternalProtocolPayloadPreviewSchema,
    ApprovalRequestSchema,
} from '$lib/schemas/chat';

describe('approval schemas (F-0084)', () => {
    it('validates an approval_required event', () => {
        const ev = ApprovalRequiredEventSchema.parse({
            type: 'approval_required',
            tool_call_id: 'call_abc',
            tool_name: 'create_protocol_from_external_source',
            title: 'X',
            source_url: 'https://openwetware.org/wiki/X',
            assistant_message_id: 'a1b2c3d4-e5f6-4789-8abc-0123456789ab',
            payload_preview: {
                title: 'X',
                source_url: 'https://openwetware.org/wiki/X',
                step_count: 7,
                license: 'CC BY-SA 3.0',
            },
        });
        expect(ev.tool_call_id).toBe('call_abc');
    });

    it('rejects malformed payload_preview', () => {
        expect(() =>
            ExternalProtocolPayloadPreviewSchema.parse({ title: 'X' }),
        ).toThrow();
    });

    it('validates an approval request', () => {
        const req = ApprovalRequestSchema.parse({
            tool_call_id: 'call_abc',
            approved: true,
        });
        expect(req.approved).toBe(true);
    });
});
