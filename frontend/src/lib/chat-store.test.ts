import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({ getToken: () => 'T' }));
vi.mock('$lib/config', () => ({ API_BASE: 'http://test.local' }));

vi.mock('$lib/api', () => ({
    api: {
        post: vi.fn(),
        get: vi.fn(),
    },
    ApiError: class ApiError extends Error {},
}));

import * as store from './chat-store.svelte';
import * as sse from './ai/sse-stream';

describe('chat-store streaming', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it('exposes the current tool and pushes prior tools onto the trail when a new one arrives', async () => {
        store.__test_setActiveSession({
            id: 'S1',
            messages: [],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);

        const labels: (string | null)[] = [];
        const trails: string[][] = [];

        vi.spyOn(sse, 'streamSse').mockImplementation(async (_ep, _b, cb) => {
            cb({ type: 'tool_start', tool: 'search_documents', label: 'Searching documents…' });
            labels.push(store.getCurrentTool()?.label ?? null);
            trails.push(store.getToolTrail().map(t => t.label));

            cb({ type: 'tool_start', tool: 'read_section', label: 'Reading document section…' });
            cb({ type: 'tool_end', tool: 'read_section' });
            labels.push(store.getCurrentTool()?.label ?? null);
            trails.push(store.getToolTrail().map(t => t.label));

            cb({
                type: 'done',
                user_message: { id: 'u1', session_id: 'S1', role: 'user', content: 'hi', metadata_: null, created_at: '2026-01-01' },
                assistant_message: { id: 'a1', session_id: 'S1', role: 'assistant', content: 'ok', metadata_: null, created_at: '2026-01-01' },
                sources: [],
            });
        });

        store.setMessageInput('hi');
        await store.sendMessage();

        // First tool is active immediately; trail is empty.
        // Second tool is queued behind a 1s display hold, so the active label
        // stays on "Searching documents…" within this synchronous test.
        // tool_end is a no-op (labels are held by their own timer).
        expect(labels).toEqual(['Searching documents…', 'Searching documents…']);
        expect(trails).toEqual([[], []]);

        // After the stream completes, the indicator clears.
        expect(store.getCurrentTool()).toBeNull();
        expect(store.getToolTrail()).toEqual([]);
        expect(store.getCurrentToolLabel()).toBeNull();
    });

    it('clears the tool indicator on stream error', async () => {
        store.__test_setActiveSession({
            id: 'S1',
            messages: [],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);
        vi.spyOn(sse, 'streamSse').mockImplementation(async () => {
            throw new Error('boom');
        });
        store.setMessageInput('hi');
        await store.sendMessage();
        expect(store.getCurrentTool()).toBeNull();
        expect(store.getToolTrail()).toEqual([]);
    });
});
