import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({ getToken: () => 'TEST_TOKEN' }));
vi.mock('$lib/config', () => ({ API_BASE: 'http://test.local' }));

import { streamSse } from './sse-stream';

function makeReadableStream(chunks: string[]): ReadableStream<Uint8Array> {
    const enc = new TextEncoder();
    let i = 0;
    return new ReadableStream({
        pull(ctrl) {
            if (i >= chunks.length) {
                ctrl.close();
                return;
            }
            ctrl.enqueue(enc.encode(chunks[i++]));
        },
    });
}

describe('streamSse', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it('parses single SSE event split across two chunks', async () => {
        const fetchMock = vi.fn(async () => ({
            ok: true,
            status: 200,
            body: makeReadableStream([
                'data: {"type":"tool_st',
                'art","tool":"x","label":"X…"}\n\n',
            ]),
        }) as unknown as Response);
        vi.stubGlobal('fetch', fetchMock);

        const events: unknown[] = [];
        await streamSse('/chat/test', { content: 'hi' }, (e) => events.push(e));

        expect(events).toEqual([
            { type: 'tool_start', tool: 'x', label: 'X…' },
        ]);
    });

    it('parses three events in one chunk', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true,
            status: 200,
            body: makeReadableStream([
                'data: {"type":"tool_start","tool":"a","label":"A…"}\n\n' +
                'data: {"type":"tool_end","tool":"a"}\n\n' +
                'data: {"type":"done"}\n\n',
            ]),
        }) as unknown as Response));

        const events: unknown[] = [];
        await streamSse('/chat/test', {}, (e) => events.push(e));

        expect((events as { type: string }[]).map((e) => e.type)).toEqual([
            'tool_start', 'tool_end', 'done',
        ]);
    });

    it('throws on non-ok response', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: false,
            status: 500,
            statusText: 'Server Error',
            text: async () => 'boom',
            body: null,
        }) as unknown as Response));

        await expect(
            streamSse('/chat/test', {}, () => {}),
        ).rejects.toThrow(/500/);
    });
});
