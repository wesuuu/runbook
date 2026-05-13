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

    it('captures pendingApproval and pauses on approval_required (F-0084)', async () => {
        store.__test_setActiveSession({
            id: 'S1',
            messages: [],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);

        vi.spyOn(sse, 'streamSse').mockImplementation(async (_ep, _b, cb) => {
            cb({
                type: 'approval_required',
                tool_call_id: 'call_abc',
                tool_name: 'create_protocol_from_external_source',
                title: 'Heat-shock transformation',
                source_url: 'https://openwetware.org/wiki/X',
                payload_preview: {
                    title: 'Heat-shock transformation',
                    source_url: 'https://openwetware.org/wiki/X',
                    step_count: 7,
                    license: 'CC BY-SA 3.0',
                    deviations: [],
                },
                assistant_message_id: 'a1b2c3d4-e5f6-4789-8abc-0123456789ab',
            });
        });

        store.setMessageInput('convert that one');
        await store.sendMessage();

        const pending = store.getPendingApproval();
        expect(pending).not.toBeNull();
        expect(pending?.tool_call_id).toBe('call_abc');
        expect(pending?.title).toBe('Heat-shock transformation');
        expect(pending?.payload_preview.step_count).toBe(7);
        // sending must clear so the input isn't stuck in a spinner
        expect(store.isSending()).toBe(false);
    });

    it('submitApproval(true) resumes via /approve and merges done payload (F-0084)', async () => {
        store.__test_setActiveSession({
            id: 'S1',
            messages: [
                {
                    id: 'a1b2c3d4-e5f6-4789-8abc-0123456789ab',
                    session_id: 'S1',
                    role: 'assistant',
                    content: '',
                    metadata_: {
                        pending_approval: {
                            tool_call_id: 'call_abc',
                            tool_name: 'create_protocol_from_external_source',
                        },
                    },
                    created_at: '2026-01-01',
                },
            ],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);

        // Seed pendingApproval first via a stream
        vi.spyOn(sse, 'streamSse').mockImplementationOnce(async (_ep, _b, cb) => {
            cb({
                type: 'approval_required',
                tool_call_id: 'call_abc',
                tool_name: 'create_protocol_from_external_source',
                title: 'Heat-shock transformation',
                source_url: 'https://openwetware.org/wiki/X',
                payload_preview: {
                    title: 'Heat-shock transformation',
                    source_url: 'https://openwetware.org/wiki/X',
                    step_count: 7,
                    license: 'CC BY-SA 3.0',
                    deviations: [],
                },
                assistant_message_id: 'a1b2c3d4-e5f6-4789-8abc-0123456789ab',
            });
        });
        store.setMessageInput('go');
        await store.sendMessage();
        expect(store.getPendingApproval()).not.toBeNull();

        const endpoints: string[] = [];
        const bodies: unknown[] = [];
        vi.spyOn(sse, 'streamSse').mockImplementationOnce(async (ep, body, cb) => {
            endpoints.push(ep);
            bodies.push(body);
            cb({
                type: 'done',
                user_message: {
                    id: 'u2', session_id: 'S1', role: 'user',
                    content: 'Approved external protocol conversion.',
                    metadata_: null, created_at: '2026-01-01',
                },
                assistant_message: {
                    id: 'a1b2c3d4-e5f6-4789-8abc-0123456789ab',
                    session_id: 'S1', role: 'assistant',
                    content: 'Drafted Heat-shock transformation.',
                    metadata_: null, created_at: '2026-01-01',
                },
                sources: [],
            });
        });

        await store.submitApproval(true);

        expect(endpoints[0]).toBe('/chat/sessions/S1/messages/approve');
        expect(bodies[0]).toEqual({ tool_call_id: 'call_abc', approved: true });
        expect(store.getPendingApproval()).toBeNull();

        const msgs = store.getActiveSession()?.messages ?? [];
        const placeholderStillEmpty = msgs.find(
            m => m.id === 'a1b2c3d4-e5f6-4789-8abc-0123456789ab' && m.content === '',
        );
        expect(placeholderStillEmpty).toBeUndefined();
        const drafted = msgs.find(m => m.content?.startsWith('Drafted'));
        expect(drafted).toBeDefined();
    });

    it('submitApproval(false) sends approved:false and clears pendingApproval (F-0084)', async () => {
        store.__test_setActiveSession({
            id: 'S2',
            messages: [],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);
        vi.spyOn(sse, 'streamSse').mockImplementationOnce(async (_ep, _b, cb) => {
            cb({
                type: 'approval_required',
                tool_call_id: 'call_xyz',
                tool_name: 'create_protocol_from_external_source',
                title: 'X',
                source_url: 'https://openwetware.org/wiki/X',
                payload_preview: {
                    title: 'X',
                    source_url: 'https://openwetware.org/wiki/X',
                    step_count: 3,
                    license: 'CC BY-SA 3.0',
                    deviations: [],
                },
                assistant_message_id: 'a1b2c3d4-e5f6-4789-8abc-0123456789ab',
            });
        });
        store.setMessageInput('go');
        await store.sendMessage();

        const bodies: unknown[] = [];
        vi.spyOn(sse, 'streamSse').mockImplementationOnce(async (_ep, body, cb) => {
            bodies.push(body);
            cb({
                type: 'done',
                user_message: {
                    id: 'u3', session_id: 'S2', role: 'user',
                    content: 'Rejected the external protocol conversion.',
                    metadata_: null, created_at: '2026-01-01',
                },
                assistant_message: {
                    id: 'a1b2c3d4-e5f6-4789-8abc-0123456789ab',
                    session_id: 'S2', role: 'assistant',
                    content: "Skipped the import.",
                    metadata_: null, created_at: '2026-01-01',
                },
                sources: [],
            });
        });

        await store.submitApproval(false);

        expect(bodies[0]).toEqual({ tool_call_id: 'call_xyz', approved: false });
        expect(store.getPendingApproval()).toBeNull();
    });

    it('submitApproval(true, {editedSteps, deviations}) sends them in the approve body (F-0084)', async () => {
        store.__test_setActiveSession({
            id: 'S3',
            messages: [],
            title: 'New Chat',
            created_at: '2026-01-01',
            user_id: 'U1',
            org_id: 'O1',
            ai_message_history: null,
        } as never);
        vi.spyOn(sse, 'streamSse').mockImplementationOnce(async (_ep, _b, cb) => {
            cb({
                type: 'approval_required',
                tool_call_id: 'call_edit',
                tool_name: 'create_protocol_from_external_source',
                title: 'X',
                source_url: 'https://openwetware.org/wiki/X',
                payload_preview: {
                    title: 'X',
                    source_url: 'https://openwetware.org/wiki/X',
                    step_count: 3,
                    license: 'CC BY-SA 3.0',
                    deviations: [],
                },
                assistant_message_id: 'a1b2c3d4-e5f6-4789-8abc-0123456789ab',
            });
        });
        store.setMessageInput('go');
        await store.sendMessage();

        const bodies: unknown[] = [];
        vi.spyOn(sse, 'streamSse').mockImplementationOnce(async (_ep, body, cb) => {
            bodies.push(body);
            cb({
                type: 'done',
                user_message: {
                    id: 'u4', session_id: 'S3', role: 'user',
                    content: 'Approved with edits.',
                    metadata_: null, created_at: '2026-01-01',
                },
                assistant_message: {
                    id: 'a1b2c3d4-e5f6-4789-8abc-0123456789ab',
                    session_id: 'S3', role: 'assistant',
                    content: 'Drafted.',
                    metadata_: null, created_at: '2026-01-01',
                },
                sources: [],
            });
        });

        await store.submitApproval(true, {
            editedSteps: [
                { text: 'Step A', duration_min: null },
                { text: 'Step B edited', duration_min: 5 },
            ],
            deviations: ['Edited step: ~~Step B~~ Step B edited'],
        });

        expect(bodies[0]).toEqual({
            tool_call_id: 'call_edit',
            approved: true,
            edited_steps: [
                { text: 'Step A', duration_min: null },
                { text: 'Step B edited', duration_min: 5 },
            ],
            deviations: ['Edited step: ~~Step B~~ Step B edited'],
        });
        expect(store.getPendingApproval()).toBeNull();
    });

    it('rehydrates pendingApproval from placeholder metadata on session reload (F-0084)', async () => {
        const api = (await import('$lib/api')).api as unknown as {
            get: ReturnType<typeof vi.fn>;
        };
        const placeholderId = 'a1b2c3d4-e5f6-4789-8abc-0123456789ab';
        api.get.mockResolvedValueOnce({
            id: 'S-reload',
            user_id: 'U1',
            org_id: 'O1',
            title: 'New Chat',
            status: 'ACTIVE',
            context_document_ids: null,
            created_at: '2026-01-01',
            updated_at: '2026-01-01',
            messages: [
                {
                    id: 'u1', session_id: 'S-reload', role: 'user',
                    content: 'find a protocol for DNA electrophoresis',
                    metadata_: null, created_at: '2026-05-12T20:00:00Z',
                },
                {
                    id: placeholderId,
                    session_id: 'S-reload',
                    role: 'assistant',
                    content: 'Awaiting your approval to draft the selected protocol.',
                    metadata_: {
                        pending_approval: {
                            tool_call_id: 'functions.create_protocol_from_external_source:1',
                            tool_name: 'create_protocol_from_external_source',
                            title: 'Alm:Agarose gel electrophoresis',
                            source_url: 'https://openwetware.org/wiki/Alm:Agarose_gel_electrophoresis',
                            payload_preview: {
                                title: 'Alm:Agarose gel electrophoresis',
                                source_url: 'https://openwetware.org/wiki/Alm:Agarose_gel_electrophoresis',
                                step_count: 13,
                                duration_min_total: 5,
                                license: 'CC BY-SA 3.0',
                                deviations: [],
                            },
                        },
                    },
                    created_at: '2026-05-12T20:01:00Z',
                },
            ],
        });

        await store.selectSession('S-reload');

        const pending = store.getPendingApproval();
        expect(pending).not.toBeNull();
        expect(pending?.assistant_message_id).toBe(placeholderId);
        expect(pending?.tool_call_id).toBe(
            'functions.create_protocol_from_external_source:1',
        );
        expect(pending?.title).toBe('Alm:Agarose gel electrophoresis');
        expect(pending?.payload_preview.step_count).toBe(13);
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
