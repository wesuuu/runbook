import { tick } from 'svelte';
import { api } from '$lib/api';
import { toast } from 'svelte-sonner';
import type { ChatSession, ChatSessionDetail, ChatMessage, ChatSourceReference, ChatSkill, ChatConfig } from '$lib/schemas/chat';
import {
    ChatSessionSchema,
    ChatSessionDetailSchema,
    ChatSessionListResponseSchema,
    ChatCompletionResponseSchema,
    ChatSkillListResponseSchema,
    ChatConfigSchema,
} from '$lib/schemas/chat';

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

// Scroll callback — set by the component that owns the DOM ref
let scrollFn: (() => void) | null = null;

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
    try {
        const detail = await api.get(`/chat/sessions/${sessionId}`, {
            schema: ChatSessionDetailSchema,
        });
        activeSession = detail;
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
        toast.success('Conversation cleared');
    } catch {
        toast.error('Failed to clear conversation');
    }
}

export async function sendMessage(skillId?: string): Promise<void> {
    const content = messageInput.trim();
    if (!content || sending) return;

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

    try {
        const body: Record<string, string> = { content };
        if (skillId) {
            body.skill_id = skillId;
        }

        const res = await api.post(
            `/chat/sessions/${activeSession.id}/messages`,
            body,
            { schema: ChatCompletionResponseSchema },
        );

        // Replace temp message with real one + assistant response
        activeSession.messages = [
            ...activeSession.messages.filter(m => m.id !== tempUserMsg.id),
            res.user_message,
            res.assistant_message,
        ];

        // Show sources if any
        if (res.sources && res.sources.length > 0) {
            activeSources = res.sources;
            sourcePanelOpen = true;
        }

        // Update session title in sidebar list
        const idx = sessions.findIndex(s => s.id === activeSession!.id);
        if (idx !== -1 && sessions[idx].title === 'New Chat') {
            sessions[idx] = { ...sessions[idx], title: content.slice(0, 100) };
            sessions = [...sessions];
        }

        await tick();
        scrollFn?.();
    } catch {
        activeSession.messages = activeSession.messages.filter(
            m => m.id !== tempUserMsg.id,
        );
        toast.error('Failed to send message');
    } finally {
        sending = false;
    }
}

export function activateSkill(skill: ChatSkill): void {
    const label = skill.name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    messageInput = label;
    sendMessage(skill.name);
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
    scrollFn = null;
}
