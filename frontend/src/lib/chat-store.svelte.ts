import { tick } from 'svelte';
import { api, ApiError } from '$lib/api';
import { toast } from 'svelte-sonner';
import type {
    ChatSession,
    ChatSessionDetail,
    ChatMessage,
    ChatSourceReference,
    ChatSkill,
    ChatConfig,
    ExternalProtocolPayloadPreview,
    ExternalProtocolStepPreview,
} from '$lib/schemas/chat';
import {
    ChatSessionSchema,
    ChatSessionDetailSchema,
    ChatSessionListResponseSchema,
    ChatSkillListResponseSchema,
    ChatConfigSchema,
} from '$lib/schemas/chat';
import { streamSse, type SseEvent } from '$lib/ai/sse-stream';

// ─── Module-level state (survives navigations) ───

let sessions = $state<ChatSession[]>([]);
let activeSession = $state<ChatSessionDetail | null>(null);
let panelState = $state<'collapsed' | 'open'>('collapsed');
let messageInput = $state('');
let loading = $state(false);
let sending = $state(false);
let creatingSession = $state(false);
let sidebarCollapsed = $state(false);
let sourcePanelOpen = $state(false);
let activeSources = $state<ChatSourceReference[]>([]);
let initialized = $state(false);
let skills = $state<ChatSkill[]>([]);
let skillsLoaded = $state(false);
let chatConfig = $state<ChatConfig | null>(null);
let messageError = $state<string | null>(null);

// F-0084: external-protocol approval handoff. When the agent emits an
// `approval_required` SSE event, the stream closes and we hold the preview
// here until the user approves or rejects via `submitApproval`. Survives
// reload — `selectSession` rehydrates from the placeholder message's
// `metadata_.pending_approval`.
export interface PendingApproval {
    tool_call_id: string;
    tool_name: string;
    title: string;
    source_url: string;
    payload_preview: ExternalProtocolPayloadPreview;
    assistant_message_id: string;
}
let pendingApproval = $state<PendingApproval | null>(null);
let submittingApproval = $state(false);

// F-0089: sticky skill activation. Clicking a skill chip arms the next
// message; the user types their prompt and `sendMessage` attaches the
// `skill_id` to the request body. Cleared after the agent emits `done`
// and when the active session changes.
let activeSkill = $state<ChatSkill | null>(null);

// Scroll callback — set by the component that owns the DOM ref
let scrollFn: (() => void) | null = null;

// Poll handle for the "awaiting assistant reply" recovery loop.
// When a session is loaded and its trailing turn is a user message with no
// assistant reply yet (typically after a page refresh during a slow LLM call),
// we keep `sending = true` and re-fetch the session every few seconds until
// the assistant message lands. After STALE_POLL_MS without resolution we
// surface a retry affordance — the original request may have been orphaned
// (backend restart, crash, or a cancellation we can't detect from the client).
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let staleTimer: ReturnType<typeof setTimeout> | null = null;
let pollSessionId: string | null = null;
let stalePendingMessage = $state<ChatMessage | null>(null);

// Live tool indicator for the chat thinking row (F-0083). Tool events stream
// in faster than humans can read, so each tool is held for at least
// MIN_LABEL_DISPLAY_MS — incoming tool_start events queue up and advance after
// the current one has been shown long enough. When the active tool advances
// out, it's pushed onto `toolTrail` (most-recent first) so the UI can render a
// stacked stream of recently-completed tools.
export interface ToolEvent {
    id: number;
    name: string;
    label: string;
}

const MIN_LABEL_DISPLAY_MS = 1000;
const TRAIL_CAP = 6;
let nextToolId = 0;
let currentTool = $state<ToolEvent | null>(null);
let toolTrail = $state<ToolEvent[]>([]);
let labelQueue: ToolEvent[] = [];
let labelShownAt: number = 0;
let labelTimer: ReturnType<typeof setTimeout> | null = null;

function advanceLabel(): void {
    if (labelTimer) {
        clearTimeout(labelTimer);
        labelTimer = null;
    }
    if (currentTool !== null) {
        toolTrail = [currentTool, ...toolTrail].slice(0, TRAIL_CAP);
    }
    const next = labelQueue.shift() ?? null;
    currentTool = next;
    labelShownAt = next === null ? 0 : Date.now();
    if (next !== null && labelQueue.length > 0) {
        labelTimer = setTimeout(advanceLabel, MIN_LABEL_DISPLAY_MS);
    }
}

function enqueueLabel(name: string, label: string): void {
    const ev: ToolEvent = { id: nextToolId++, name, label };
    if (currentTool === null) {
        currentTool = ev;
        labelShownAt = Date.now();
        return;
    }
    labelQueue.push(ev);
    if (labelTimer !== null) return;
    const elapsed = Date.now() - labelShownAt;
    const wait = Math.max(0, MIN_LABEL_DISPLAY_MS - elapsed);
    labelTimer = setTimeout(advanceLabel, wait);
}

function resetLabelQueue(): void {
    if (labelTimer) {
        clearTimeout(labelTimer);
        labelTimer = null;
    }
    labelQueue = [];
    currentTool = null;
    toolTrail = [];
    labelShownAt = 0;
}

export function getCurrentTool(): ToolEvent | null {
    return currentTool;
}

export function getToolTrail(): ToolEvent[] {
    return toolTrail;
}

// Backwards-compat getter — preserved for callers that only need the label
// string (e.g. tests, simple consumers).
export function getCurrentToolLabel(): string | null {
    return currentTool?.label ?? null;
}

const STALE_POLL_MS = 90_000;

function trailingUserMessage(detail: ChatSessionDetail | null): ChatMessage | null {
    if (!detail || detail.messages.length === 0) return null;
    for (let i = detail.messages.length - 1; i >= 0; i--) {
        const msg = detail.messages[i];
        if (msg.role === 'summary') continue;
        return msg.role === 'user' ? msg : null;
    }
    return null;
}

function clearPoll(): void {
    if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
    }
    if (staleTimer) {
        clearTimeout(staleTimer);
        staleTimer = null;
    }
    pollSessionId = null;
    stalePendingMessage = null;
}

async function pollForAssistantReply(sessionId: string): Promise<void> {
    if (pollSessionId !== sessionId) return;
    try {
        const detail = await api.get(`/chat/sessions/${sessionId}`, {
            schema: ChatSessionDetailSchema,
        });
        if (pollSessionId !== sessionId) return;
        const pending = trailingUserMessage(detail);
        if (pending) {
            pollTimer = setTimeout(() => pollForAssistantReply(sessionId), 2500);
            return;
        }
        activeSession = detail;
        sending = false;
        clearPoll();
        await tick();
        scrollFn?.();
        void loadSessions();
    } catch {
        pollTimer = setTimeout(() => pollForAssistantReply(sessionId), 5000);
    }
}

function rehydratePendingApproval(detail: ChatSessionDetail): void {
    // The placeholder assistant message persisted by send_message_streaming
    // carries the approval preview in `metadata_.pending_approval`. After a
    // reload (or moving between sessions) we re-surface the approval card
    // from that record.
    pendingApproval = null;
    if (!detail.messages.length) return;
    const last = detail.messages[detail.messages.length - 1];
    if (last.role !== 'assistant') return;
    const meta = last.metadata_ as Record<string, unknown> | null;
    const raw = meta?.pending_approval as Record<string, unknown> | undefined;
    if (!raw) return;
    pendingApproval = {
        tool_call_id: String(raw.tool_call_id ?? ''),
        tool_name: String(raw.tool_name ?? ''),
        title: String(raw.title ?? ''),
        source_url: String(raw.source_url ?? ''),
        payload_preview:
            (raw.payload_preview as ExternalProtocolPayloadPreview) ?? {
                title: '',
                source_url: '',
                step_count: 0,
                license: 'CC BY-SA 3.0',
                deviations: [],
            },
        assistant_message_id: last.id,
    };
}

function maybeStartAwaitingPoll(detail: ChatSessionDetail): void {
    const pending = trailingUserMessage(detail);
    if (!pending) {
        clearPoll();
        return;
    }
    clearPoll();
    sending = true;
    pollSessionId = detail.id;
    pollTimer = setTimeout(() => pollForAssistantReply(detail.id), 2500);

    // Use the orphan message's age — if it was sent before this page even
    // opened (e.g. backend was restarted while a request was in flight) we
    // want to surface the retry option immediately, not 90s from now.
    const ageMs = Math.max(0, Date.now() - new Date(pending.created_at).getTime());
    const remaining = Math.max(0, STALE_POLL_MS - ageMs);
    staleTimer = setTimeout(() => {
        if (pollSessionId !== detail.id) return;
        stalePendingMessage = pending;
    }, remaining);
}

export function getStalePendingMessage(): ChatMessage | null {
    return stalePendingMessage;
}

export async function retryStalePending(): Promise<void> {
    const orphan = stalePendingMessage;
    if (!orphan) return;
    const content = orphan.content;
    clearPoll();
    sending = false;
    messageInput = content;
    await sendMessage();
}

export function dismissStalePending(): void {
    // "Keep waiting" — hide the retry banner but leave the poll running so a
    // late reply still resolves the dots. Won't reappear unless the session
    // is reloaded.
    if (staleTimer) {
        clearTimeout(staleTimer);
        staleTimer = null;
    }
    stalePendingMessage = null;
}

// ─── Getters (reactive reads) ───

export function getChatSessions(): ChatSession[] { return sessions; }
export function getActiveSession(): ChatSessionDetail | null { return activeSession; }
export function getPanelState(): 'collapsed' | 'open' { return panelState; }
export function getMessageInput(): string { return messageInput; }
export function isSending(): boolean { return sending; }
export function isLoading(): boolean { return loading; }
export function isCreatingSession(): boolean { return creatingSession; }
export function isChatInitialized(): boolean { return initialized; }
export function isSidebarCollapsed(): boolean { return sidebarCollapsed; }
export function isSourcePanelOpen(): boolean { return sourcePanelOpen; }
export function getActiveSources(): ChatSourceReference[] { return activeSources; }
export function getSkills(): ChatSkill[] { return skills; }
export function getChatConfig(): ChatConfig | null { return chatConfig; }
export function getMessageError(): string | null { return messageError; }
export function getPendingApproval(): PendingApproval | null { return pendingApproval; }
export function isSubmittingApproval(): boolean { return submittingApproval; }
export function getActiveSkill(): ChatSkill | null { return activeSkill; }
export function clearActiveSkill(): void { activeSkill = null; }

// ─── Panel state actions ───

export function openPanel(): void { panelState = 'open'; }
export function closePanel(): void { panelState = 'collapsed'; }
export function togglePanel(): void {
    panelState = panelState === 'collapsed' ? 'open' : 'collapsed';
}

// ─── Input / UI actions ───

export function setMessageInput(value: string): void {
    messageInput = value;
    const maxLen = chatConfig?.max_message_length ?? 10000;
    if (value.length > maxLen) {
        messageError = `Message too long (${value.length.toLocaleString()} / ${maxLen.toLocaleString()} characters)`;
    } else {
        messageError = null;
    }
}
export function setSidebarCollapsed(value: boolean): void { sidebarCollapsed = value; }
export function setSourcePanelOpen(open: boolean): void { sourcePanelOpen = open; }
export function registerScrollFn(fn: () => void): void { scrollFn = fn; }

// ─── Skills ───

export async function fetchSkills(): Promise<void> {
    if (skillsLoaded) return;
    try {
        const res = await api.get('/chat/skills', {
            schema: ChatSkillListResponseSchema,
        });
        skills = res.skills;
        skillsLoaded = true;
    } catch {
        // Skills are non-critical — silently fail
    }
}

// ─── Config ───

export async function fetchChatConfig(): Promise<void> {
    try {
        chatConfig = await api.get('/chat/config', {
            schema: ChatConfigSchema,
        });
    } catch {
        // Config is non-critical — use defaults
    }
}

// ─── Session actions ───

export async function initChat(): Promise<void> {
    if (initialized) return;
    loading = true;
    try {
        await Promise.all([loadSessions(), fetchSkills(), fetchChatConfig()]);
        // Auto-load most recent active session
        if (sessions.length > 0) {
            await selectSession(sessions[0].id);
        }
    } finally {
        loading = false;
        initialized = true;
    }
}

export async function loadSessions(): Promise<void> {
    try {
        const res = await api.get('/chat/sessions?limit=100', {
            schema: ChatSessionListResponseSchema,
        });
        sessions = res.items;
    } catch {
        toast.error('Failed to load chat sessions');
    }
}

export async function createSession(): Promise<void> {
    creatingSession = true;
    try {
        const session = await api.post('/chat/sessions', {}, {
            schema: ChatSessionSchema,
        });
        sessions = [session, ...sessions];
        await selectSession(session.id);
    } catch {
        toast.error('Failed to create chat session');
    } finally {
        creatingSession = false;
    }
}

export async function selectSession(sessionId: string): Promise<void> {
    clearPoll();
    sending = false;
    // F-0089: switching sessions clears the sticky skill badge.
    activeSkill = null;
    try {
        const detail = await api.get(`/chat/sessions/${sessionId}`, {
            schema: ChatSessionDetailSchema,
        });
        activeSession = detail;
        rehydratePendingApproval(detail);
        maybeStartAwaitingPoll(detail);
        await tick();
        scrollFn?.();
    } catch {
        toast.error('Failed to load chat session');
    }
}

export async function deleteSession(sessionId: string): Promise<void> {
    try {
        await api.delete(`/chat/sessions/${sessionId}`);
        sessions = sessions.filter(s => s.id !== sessionId);
        if (activeSession?.id === sessionId) {
            activeSession = null;
            clearPoll();
            sending = false;
        }
        toast.success('Chat deleted');
    } catch {
        toast.error('Failed to delete chat');
    }
}

export async function clearConversation(): Promise<void> {
    if (!activeSession) return;
    try {
        await api.delete(`/chat/sessions/${activeSession.id}`);
        sessions = sessions.filter(s => s.id !== activeSession!.id);
        activeSession = null;
        messageInput = '';
        activeSources = [];
        sourcePanelOpen = false;
        clearPoll();
        sending = false;
        toast.success('Conversation cleared');
    } catch {
        toast.error('Failed to clear conversation');
    }
}

export async function sendMessage(): Promise<void> {
    const content = messageInput.trim();
    if (!content || sending) return;
    // Snapshot the armed skill (if any) before any awaits so a concurrent
    // session switch / clear can't strip it from this in-flight request.
    const skillId = activeSkill?.name ?? null;

    // Lazy session creation — if no active session, create one first
    if (!activeSession) {
        creatingSession = true;
        try {
            const session = await api.post('/chat/sessions', {}, {
                schema: ChatSessionSchema,
            });
            sessions = [session, ...sessions];
            const detail = await api.get(`/chat/sessions/${session.id}`, {
                schema: ChatSessionDetailSchema,
            });
            activeSession = detail;
        } catch {
            toast.error('Failed to create chat session');
            creatingSession = false;
            return;
        } finally {
            creatingSession = false;
        }
    }

    messageInput = '';
    clearPoll();
    sending = true;

    // Optimistic: add user message immediately
    const tempUserMsg: ChatMessage = {
        id: 'temp-user-' + Date.now(),
        session_id: activeSession.id,
        role: 'user',
        content,
        metadata_: null,
        created_at: new Date().toISOString(),
    };
    activeSession.messages = [...activeSession.messages, tempUserMsg];
    await tick();
    scrollFn?.();

    let errorCode: string | null = null;

    try {
        const body: Record<string, string> = { content };
        if (skillId) {
            body.skill_id = skillId;
        }

        resetLabelQueue();

        type DonePayload = {
            user_message: ChatMessage;
            assistant_message: ChatMessage;
            sources: ChatSourceReference[];
        };
        let donePayload: DonePayload | null = null;
        let errorDetail: string | null = null;
        let captured: PendingApproval | null = null;

        await streamSse(
            `/chat/sessions/${activeSession.id}/messages/stream`,
            body,
            (event: SseEvent) => {
                if (event.type === 'tool_start') {
                    enqueueLabel(event.tool, event.label);
                } else if (event.type === 'tool_end') {
                    // No-op: labels stay on screen for at least
                    // MIN_LABEL_DISPLAY_MS so the user can read them. The
                    // queue advances on its own timer.
                } else if (event.type === 'approval_required') {
                    captured = {
                        tool_call_id: event.tool_call_id,
                        tool_name: event.tool_name,
                        title: event.title,
                        source_url: event.source_url,
                        payload_preview:
                            event.payload_preview as ExternalProtocolPayloadPreview,
                        assistant_message_id: event.assistant_message_id,
                    };
                } else if (event.type === 'done') {
                    donePayload = {
                        user_message: event.user_message as ChatMessage,
                        assistant_message: event.assistant_message as ChatMessage,
                        sources: event.sources as ChatSourceReference[],
                    };
                    // F-0089: agent finished — clear the sticky skill badge.
                    activeSkill = null;
                } else if (event.type === 'error') {
                    errorDetail = event.detail;
                    errorCode = (event as { error_code?: string }).error_code ?? null;
                }
            },
        );

        if (errorDetail) {
            throw new Error(errorDetail as string);
        }
        if (captured) {
            // HITL pause — drop the temp user message; the persisted user
            // message + placeholder assistant will arrive after the resume.
            // For now, surface the approval card and reload so the persisted
            // turn shows up in the message list.
            activeSession.messages = activeSession.messages.filter(
                m => m.id !== tempUserMsg.id,
            );
            pendingApproval = captured;
            try {
                const detail = await api.get<ChatSessionDetail>(
                    `/chat/sessions/${activeSession.id}`,
                    { schema: ChatSessionDetailSchema },
                );
                if (detail) activeSession = detail;
            } catch {
                // Non-fatal — placeholder will appear on next navigation.
            }
            await tick();
            scrollFn?.();
            return;
        }
        if (!donePayload) {
            throw new Error('Stream ended without a result');
        }
        const done = donePayload as DonePayload;

        activeSession.messages = [
            ...activeSession.messages.filter(m => m.id !== tempUserMsg.id),
            done.user_message,
            done.assistant_message,
        ];

        if (done.sources && done.sources.length > 0) {
            activeSources = done.sources;
            sourcePanelOpen = true;
        }

        const idx = sessions.findIndex(s => s.id === activeSession!.id);
        if (idx !== -1 && sessions[idx].title === 'New Chat') {
            sessions[idx] = { ...sessions[idx], title: content.slice(0, 100) };
            sessions = [...sessions];
        }

        await tick();
        scrollFn?.();
    } catch (err) {
        activeSession.messages = activeSession.messages.filter(
            m => m.id !== tempUserMsg.id,
        );
        const detail = err instanceof Error ? err.message : '';
        if (detail) {
            toast.error(detail);
        } else {
            const codeSuffix = errorCode ? ` (${errorCode})` : '';
            toast.error(`Failed to send message${codeSuffix}`);
        }
    } finally {
        resetLabelQueue();
        sending = false;
    }
}

export interface ApprovalSubmission {
    editedSteps?: ExternalProtocolStepPreview[];
    deviations?: string[];
}

export async function submitApproval(
    approved: boolean,
    submission?: ApprovalSubmission,
): Promise<void> {
    if (!pendingApproval || !activeSession) return;
    if (submittingApproval) return;
    const session = activeSession;
    const pending = pendingApproval;

    submittingApproval = true;
    sending = true;

    type DonePayload = {
        user_message: ChatMessage;
        assistant_message: ChatMessage;
        sources: ChatSourceReference[];
    };
    let donePayload: DonePayload | null = null;
    let errorDetail: string | null = null;

    const body: {
        tool_call_id: string;
        approved: boolean;
        edited_steps?: ExternalProtocolStepPreview[];
        deviations?: string[];
    } = {
        tool_call_id: pending.tool_call_id,
        approved,
    };
    if (approved && submission?.editedSteps) {
        body.edited_steps = submission.editedSteps;
    }
    if (approved && submission?.deviations && submission.deviations.length > 0) {
        body.deviations = submission.deviations;
    }

    try {
        resetLabelQueue();
        await streamSse(
            `/chat/sessions/${session.id}/messages/approve`,
            body,
            (event: SseEvent) => {
                if (event.type === 'tool_start') {
                    enqueueLabel(event.tool, event.label);
                } else if (event.type === 'tool_end') {
                    // no-op
                } else if (event.type === 'done') {
                    donePayload = {
                        user_message: event.user_message as ChatMessage,
                        assistant_message: event.assistant_message as ChatMessage,
                        sources: event.sources as ChatSourceReference[],
                    };
                } else if (event.type === 'error') {
                    errorDetail = event.detail;
                }
            },
        );
        if (errorDetail) throw new Error(errorDetail as string);
        if (!donePayload) throw new Error('Approval stream ended without a result');
        const done = donePayload as DonePayload;

        // Replace placeholder assistant message with the resolved one, and
        // append the persisted user message describing the decision.
        activeSession.messages = [
            ...activeSession.messages.filter(
                m => m.id !== pending.assistant_message_id,
            ),
            done.user_message,
            done.assistant_message,
        ];

        if (done.sources && done.sources.length > 0) {
            activeSources = done.sources;
            sourcePanelOpen = true;
        }
        pendingApproval = null;
        await tick();
        scrollFn?.();
    } catch {
        toast.error(approved ? 'Failed to approve' : 'Failed to reject');
    } finally {
        resetLabelQueue();
        submittingApproval = false;
        sending = false;
    }
}

export function activateSkill(skill: ChatSkill): void {
    // F-0089: arm the next user message. The badge clears on the agent's
    // `done` event (success path) or when the user switches sessions.
    activeSkill = skill;
}

export function showSourcesForMessage(msg: ChatMessage): void {
    if (!msg.metadata_ || !('sources' in msg.metadata_)) return;
    const sources = msg.metadata_.sources as ChatSourceReference[];
    if (sources.length > 0) {
        activeSources = sources;
        sourcePanelOpen = true;
    }
}

export function getMessageSources(msg: ChatMessage): ChatSourceReference[] {
    if (!msg.metadata_ || !('sources' in msg.metadata_)) return [];
    return msg.metadata_.sources as ChatSourceReference[];
}

export function resetChat(): void {
    sessions = [];
    activeSession = null;
    panelState = 'collapsed';
    messageInput = '';
    messageError = null;
    loading = false;
    sending = false;
    creatingSession = false;
    sidebarCollapsed = false;
    sourcePanelOpen = false;
    activeSources = [];
    initialized = false;
    skills = [];
    skillsLoaded = false;
    chatConfig = null;
    pendingApproval = null;
    submittingApproval = false;
    activeSkill = null;
    scrollFn = null;
    clearPoll();
}

// --- Test-only export (DO NOT USE FROM APP CODE) ---
export function __test_setActiveSession(s: ChatSessionDetail | null): void {
    activeSession = s;
    // F-0089: switching sessions clears the sticky skill badge.
    activeSkill = null;
}
