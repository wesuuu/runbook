<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { marked } from 'marked';
    import DOMPurify from 'dompurify';
    import ChatSkillButtons from '$lib/components/ai/ChatSkillButtons.svelte';
    import ThinkingIndicator from '$lib/components/ai/ThinkingIndicator.svelte';
    import ApprovalCard from '$lib/components/ai/ApprovalCard.svelte';
    import ProtocolImportModal from '$lib/components/modals/ProtocolImportModal.svelte';
    import { Button } from '$lib/components/ui/button';
    import { EmptyState } from '$lib/components/ui/empty-state';
    import { goto } from '$app/navigation';
    import { toast } from 'svelte-sonner';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import { api } from '$lib/api';
    import {
        getChatSessions, getActiveSession, getMessageInput, isSending,
        isLoading, isCreatingSession, isSidebarCollapsed, isSourcePanelOpen,
        getActiveSources, getMessageSources, getSkills, getMessageError,
        getStalePendingMessage, getCurrentTool, getToolTrail,
        initChat, createSession, selectSession, deleteSession,
        sendMessage, setMessageInput, setSidebarCollapsed, setSourcePanelOpen,
        showSourcesForMessage, registerScrollFn, activateSkill,
        retryStalePending, dismissStalePending,
        getPendingApproval, isSubmittingApproval, submitApproval,
    } from '$lib/chat-store.svelte';
    import type { ChatMessage } from '$lib/schemas/chat';
    import { fade } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { blockDuration, listDuration } from '$lib/transitions';

    // Derived state from shared store
    const sessions = $derived(getChatSessions());
    const activeSession = $derived(getActiveSession());
    const messageInput = $derived(getMessageInput());
    const sending = $derived(isSending());
    const loading = $derived(isLoading());
    const creatingSession = $derived(isCreatingSession());
    const sidebarCollapsed = $derived(isSidebarCollapsed());
    const sourcePanelOpen = $derived(isSourcePanelOpen());
    const activeSources = $derived(getActiveSources());
    const skills = $derived(getSkills());
    const messageError = $derived(getMessageError());
    const stalePending = $derived(getStalePendingMessage());
    const currentTool = $derived(getCurrentTool());
    const toolTrail = $derived(getToolTrail());
    const pendingApproval = $derived(getPendingApproval());
    const submittingApproval = $derived(isSubmittingApproval());

    const hasMessages = $derived(
        activeSession !== null && activeSession.messages.length > 0
    );

    const currentOrg = $derived(getCurrentOrg());
    const isOrgPro = $derived(currentOrg?.subscription_tier === 'pro');

    let messagesEndEl = $state<HTMLDivElement>(undefined!);
    let inputEl = $state<HTMLTextAreaElement>(undefined!);
    let showImportModal = $state(false);
    let notifyLoading = $state(false);
    let notifyMessage = $state<string | null>(null);
    let notifyError = $state<string | null>(null);

    onMount(async () => {
        await initChat();
        registerScrollFn(() => {
            messagesEndEl?.scrollIntoView({ behavior: 'smooth' });
        });
    });

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    function renderMarkdown(content: string): string {
        return DOMPurify.sanitize(
            marked.parse(content, { gfm: true, breaks: true }) as string
        );
    }

    function formatTime(iso: string): string {
        return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function formatDate(iso: string): string {
        const d = new Date(iso);
        const today = new Date();
        if (d.toDateString() === today.toDateString()) return 'Today';
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }

    async function handleNotifyAdmin() {
        notifyLoading = true;
        notifyError = null;
        try {
            await api.post('/chat/notify-admin', {});
            notifyMessage = 'Admin notified! They\'ll get back to you soon.';
            toast.success('Notification sent to administrators');
        } catch (err: unknown) {
            if (err instanceof Error) {
                const errorMsg = err.message;
                if (errorMsg.includes('429')) {
                    notifyError = 'You\'ve already notified admins recently. Please try again later.';
                } else {
                    notifyError = errorMsg;
                }
            } else {
                notifyError = 'Failed to notify administrators';
            }
            toast.error(notifyError);
        } finally {
            notifyLoading = false;
        }
    }
</script>

<svelte:head>
    <title>Chat - Batchrite</title>
</svelte:head>

<div class="flex h-[calc(100vh-57px)] overflow-hidden">
    <!-- Sidebar -->
    <div
        class="flex-shrink-0 border-r border-border/60 bg-card/50 flex flex-col transition-all duration-200
            {sidebarCollapsed ? 'w-0 overflow-hidden' : 'w-72'}"
    >
        <div class="p-3 border-b border-border/40 flex items-center justify-between">
            <h2 class="text-sm font-semibold text-foreground">Chats</h2>
            <Button
                size="sm"
                onclick={() => createSession()}
                disabled={creatingSession}
            >
                {creatingSession ? '...' : '+ New'}
            </Button>
        </div>
        <div class="flex-1 overflow-y-auto">
            {#if sessions.length === 0 && !loading}
                <EmptyState
                    title="No chats yet"
                    description="Start a new conversation."
                    class="py-6"
                />
            {/if}
            {#each sessions as session (session.id)}
                <div
                    class="w-full text-left px-3 py-2.5 border-b border-border/20 hover:bg-muted/50 transition-colors group cursor-pointer
                        {activeSession?.id === session.id ? 'bg-muted/70' : ''}"
                    role="button"
                    tabindex="0"
                    onclick={() => selectSession(session.id)}
                    onkeydown={(e) => e.key === 'Enter' && selectSession(session.id)}
                    animate:flip={{ duration: listDuration() }}
                    in:fade={{ duration: listDuration() }}
                >
                    <div class="flex items-start justify-between gap-2">
                        <div class="min-w-0 flex-1">
                            <p class="text-sm font-medium truncate text-foreground">{session.title}</p>
                            <p class="text-xs text-muted-foreground mt-0.5">{formatDate(session.updated_at)}</p>
                        </div>
                        <Button
                            variant="ghost"
                            size="icon-sm"
                            class="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
                            onclick={(e) => { e.stopPropagation(); deleteSession(session.id); }}
                            aria-label="Delete chat"
                        >
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                <path d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </Button>
                    </div>
                </div>
            {/each}
        </div>
    </div>

    <!-- Main chat area + sources panel -->
    <div class="flex-1 flex min-w-0">
      {#if !isOrgPro}
        <!-- Non-Pro Empty State -->
        <div class="flex-1 flex items-center justify-center">
          <div class="text-center max-w-md px-6">
            <div class="w-14 h-14 rounded-2xl bg-amber-500/10 flex items-center justify-center mx-auto mb-4">
              <svg class="w-7 h-7 text-amber-600" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                <path d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
              </svg>
            </div>
            <h2 class="text-lg font-semibold text-foreground mb-2">AI Features Unavailable</h2>
            <p class="text-sm text-muted-foreground mb-6">
              Your organization doesn't have AI Chat enabled. Contact your administrator to set up Batchrite AI.
            </p>
            <Button
              onclick={handleNotifyAdmin}
              disabled={notifyLoading || notifyMessage !== null}
              variant="default"
            >
              {notifyLoading ? 'Sending...' : 'Contact Administrator'}
            </Button>
            {#if notifyMessage}
              <p in:fade={{ duration: blockDuration() }} class="text-sm text-green-600 dark:text-green-400 mt-3">
                ✓ {notifyMessage}
              </p>
            {/if}
            {#if notifyError}
              <p in:fade={{ duration: blockDuration() }} class="text-sm text-red-600 dark:text-red-400 mt-3">
                {notifyError}
              </p>
            {/if}
          </div>
        </div>
      {:else}
        <!-- Chat UI (Pro organizations) -->
        <div class="flex-1 flex flex-col min-w-0">
          {#if !activeSession}
            <!-- Empty state -->
            <div in:fade={{ duration: blockDuration() }} class="flex-1 flex items-center justify-center">
                <div class="text-center max-w-md px-6">
                    <div class="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-4">
                        <svg class="w-7 h-7 text-primary" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                            <path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
                        </svg>
                    </div>
                    <h2 class="text-lg font-semibold text-foreground mb-2">Batchrite AI Assistant</h2>
                    <p class="text-sm text-muted-foreground mb-6">
                        Ask questions about cell biology, genetics, or process development.
                        Discuss protocols, get advice on experimental procedures, or explore scientific concepts.
                    </p>
                    {#if skills.length > 0}
                        <div class="mb-4 flex justify-center">
                            <ChatSkillButtons {skills} mode="chips" onactivate={activateSkill} />
                        </div>
                    {/if}
                    <div class="flex gap-3 justify-center">
                        <Button
                            onclick={() => createSession()}
                            disabled={creatingSession}
                        >
                            Start a conversation
                        </Button>
                        <Button
                            onclick={() => (showImportModal = true)}
                        >
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                <path d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
                            </svg>
                            Upload Protocol
                        </Button>
                    </div>
                </div>
            </div>
        {:else}
            <!-- Chat header -->
            <div class="px-4 py-3 border-b border-border/40 flex items-center gap-3 bg-card/30">
                <Button
                    variant="ghost"
                    size="icon-sm"
                    class="md:hidden text-muted-foreground"
                    onclick={() => setSidebarCollapsed(!sidebarCollapsed)}
                    aria-label="Toggle sidebar"
                >
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <path d="M4 6h16M4 12h16M4 18h16" />
                    </svg>
                </Button>
                <div class="min-w-0 flex-1">
                    <h2 class="text-sm font-semibold text-foreground truncate">{activeSession.title}</h2>
                </div>
            </div>

            <!-- Messages -->
            <div class="flex-1 overflow-y-auto px-4 py-4 space-y-4 max-w-4xl mx-auto w-full">
                {#if activeSession.messages.length === 0}
                    <div in:fade={{ duration: blockDuration() }} class="text-center py-12">
                        <p class="text-sm text-muted-foreground">Send a message to start the conversation.</p>
                    </div>
                {/if}

                {#each activeSession.messages as msg (msg.id)}
                    <div animate:flip={{ duration: listDuration() }} in:fade={{ duration: listDuration() }}>
                    {#if msg.role === 'summary'}
                        <div class="flex items-center gap-3 py-2 px-4">
                            <div class="flex-1 h-px bg-border/40"></div>
                            <span class="text-xs text-muted-foreground whitespace-nowrap">
                                Earlier messages summarized for AI
                            </span>
                            <div class="flex-1 h-px bg-border/40"></div>
                        </div>
                    {:else if msg.role === 'assistant' && pendingApproval && msg.id === pendingApproval.assistant_message_id}
                        <div class="flex justify-start">
                            <div class="max-w-[88%] w-full">
                                <ApprovalCard
                                    toolCallId={pendingApproval.tool_call_id}
                                    toolName={pendingApproval.tool_name}
                                    title={pendingApproval.title}
                                    sourceUrl={pendingApproval.source_url}
                                    payloadPreview={pendingApproval.payload_preview}
                                    pending={submittingApproval}
                                    onApprove={(_id, submission) => submitApproval(true, submission)}
                                    onReject={() => submitApproval(false)}
                                />
                            </div>
                        </div>
                    {:else}
                    <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
                        <div
                            class="max-w-[80%] rounded-xl px-4 py-3
                                {msg.role === 'user'
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted/70 text-foreground'}"
                        >
                            {#if msg.role === 'assistant'}
                                {#if Array.isArray(msg.metadata_?.tool_calls)}
                                    <div class="flex flex-col gap-1 mb-2 pb-2 border-b border-border/30">
                                        {#each msg.metadata_.tool_calls as tc_raw}
                                            {@const tc = tc_raw as Record<string, unknown>}
                                            <span class="text-[11px] text-muted-foreground/70 flex items-center gap-1.5 italic">
                                                <svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                                    <path d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
                                                </svg>
                                                {#if tc.tool === 'search_documents'}
                                                    Searched documents for "{tc.query}" ({tc.results} result{tc.results !== 1 ? 's' : ''})
                                                {:else if tc.tool === 'read_document_section'}
                                                    Read document section (chunk {tc.chunk_index})
                                                {:else if tc.tool === 'list_unit_ops'}
                                                    Listed unit operations ({tc.results} available)
                                                {:else if tc.tool === 'create_unit_op'}
                                                    Created unit operation "{tc.name}"
                                                {:else if tc.tool === 'create_protocol'}
                                                    Created protocol draft
                                                {:else}
                                                    {tc.tool}
                                                {/if}
                                            </span>
                                        {/each}
                                    </div>
                                {/if}
                                <div class="prose prose-sm max-w-none dark:prose-invert chat-prose">
                                    {@html renderMarkdown(msg.content)}
                                </div>
                                {#if getMessageSources(msg).length > 0}
                                    <Button
                                        variant="link"
                                        size="sm"
                                        class="mt-2 h-auto p-0 text-xs"
                                        onclick={() => showSourcesForMessage(msg)}
                                    >
                                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                            <path d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
                                        </svg>
                                        {getMessageSources(msg).length} source{getMessageSources(msg).length > 1 ? 's' : ''}
                                    </Button>
                                {/if}
                                {#if msg.metadata_?.context_warning}
                                    <div class="mt-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30 text-xs text-amber-600 dark:text-amber-400">
                                        <span class="font-medium">Note:</span> {msg.metadata_.context_warning}
                                    </div>
                                {/if}
                            {:else}
                                <p class="text-sm whitespace-pre-wrap">{msg.content}</p>
                            {/if}
                            <p class="text-[10px] mt-1.5 opacity-60">{formatTime(msg.created_at)}</p>
                        </div>
                    </div>
                    {/if}
                    </div>
                {/each}

                {#if sending && !stalePending}
                    <div in:fade={{ duration: blockDuration() }}>
                        <ThinkingIndicator active={currentTool} trail={toolTrail} />
                    </div>
                {/if}

                {#if stalePending}
                    <div in:fade={{ duration: blockDuration() }} class="flex justify-start">
                        <div class="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 max-w-[85%] text-sm">
                            <p class="text-amber-700 dark:text-amber-300 mb-2">
                                No reply yet — the request may have been interrupted.
                            </p>
                            <div class="flex gap-3 text-xs">
                                <button
                                    type="button"
                                    class="text-amber-700 dark:text-amber-300 underline underline-offset-2 hover:brightness-125 cursor-pointer transition-all duration-150"
                                    onclick={retryStalePending}
                                >Resend</button>
                                <span class="text-amber-700/40 dark:text-amber-300/40">·</span>
                                <button
                                    type="button"
                                    class="text-amber-700/70 dark:text-amber-300/70 hover:brightness-125 cursor-pointer transition-all duration-150"
                                    onclick={dismissStalePending}
                                >Keep waiting</button>
                            </div>
                        </div>
                    </div>
                {/if}

                <div bind:this={messagesEndEl}></div>
            </div>

            <!-- Input area -->
            <div class="border-t border-border/40 p-4 bg-card/30">
                <div class="flex items-end gap-3 max-w-4xl mx-auto">
                    {#if hasMessages && skills.length > 0}
                        <ChatSkillButtons {skills} mode="dropdown" onactivate={activateSkill} />
                    {/if}
                    <textarea
                        bind:this={inputEl}
                        value={messageInput}
                        oninput={(e) => setMessageInput(e.currentTarget.value)}
                        onkeydown={handleKeydown}
                        placeholder="Ask about cell biology, protocols, experiments..."
                        class="flex-1 resize-none rounded-xl border bg-background px-4 py-3 text-sm
                            placeholder:text-muted-foreground focus:outline-none focus:ring-2
                            min-h-[44px] max-h-[200px]
                            {messageError
                                ? 'border-red-500 focus:ring-red-500/30 focus:border-red-500'
                                : 'border-border/60 focus:ring-primary/30 focus:border-primary/50'}"
                        rows="1"
                        disabled={sending}
                    ></textarea>
                    <Button
                        size="icon-lg"
                        class="flex-shrink-0 rounded-xl"
                        onclick={() => sendMessage()}
                        disabled={!messageInput.trim() || sending || !!messageError}
                        aria-label="Send message"
                    >
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                            <path d="M6 12L3.269 3.126A59.768 59.768 0 0 1 21.485 12 59.77 59.77 0 0 1 3.27 20.876L5.999 12Zm0 0h7.5" />
                        </svg>
                    </Button>
                </div>
                {#if messageError}
                    <p in:fade={{ duration: blockDuration() }} class="text-xs text-red-500 mt-1.5 max-w-4xl mx-auto">{messageError}</p>
                {/if}
                {#if !hasMessages && skills.length > 0}
                    <div class="max-w-4xl mx-auto mt-2">
                        <ChatSkillButtons {skills} mode="chips" onactivate={activateSkill} />
                    </div>
                {/if}
                <p class="text-[11px] text-muted-foreground text-center mt-2">
                    Batchrite AI can make mistakes. Verify important information.
                </p>
            </div>
        {/if}
      </div>

      <!-- Sources panel (right side) -->
      {#if sourcePanelOpen && activeSources.length > 0}
        <div in:fade={{ duration: blockDuration() }} class="w-80 flex-shrink-0 border-l border-border/60 bg-card/30 flex flex-col overflow-hidden">
            <div class="p-3 border-b border-border/40 flex items-center justify-between">
                <h3 class="text-sm font-semibold text-foreground">Sources</h3>
                <Button
                    variant="ghost"
                    size="icon-sm"
                    class="text-muted-foreground hover:text-foreground"
                    onclick={() => setSourcePanelOpen(false)}
                    aria-label="Close sources panel"
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <path d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </Button>
            </div>
            <div class="flex-1 overflow-y-auto p-3 space-y-3">
                {#each activeSources as source, i (`${source.document_id}-${source.chunk_index}`)}
                    <a
                        href="/library/{source.document_id}?chunk={source.chunk_index}"
                        class="block rounded-lg border border-border/40 p-3 hover:bg-muted/50 transition-colors group"
                        animate:flip={{ duration: listDuration() }}
                        in:fade={{ duration: listDuration() }}
                    >
                        <div class="flex items-start gap-2">
                            <span class="flex-shrink-0 w-5 h-5 rounded-full bg-primary/10 text-primary text-[10px] font-bold flex items-center justify-center mt-0.5">
                                {i + 1}
                            </span>
                            <div class="min-w-0 flex-1">
                                <p class="text-sm font-medium text-foreground group-hover:text-primary transition-colors truncate">
                                    {source.document_title}
                                </p>
                                {#if source.page_number}
                                    <p class="text-[11px] text-muted-foreground">Page {source.page_number}</p>
                                {/if}
                                <p class="text-xs text-muted-foreground mt-1.5 line-clamp-3">
                                    {source.snippet}
                                </p>
                                <div class="flex items-center gap-2 mt-1.5">
                                    <span class="text-[10px] text-muted-foreground/70">
                                        Relevance: {Math.round(source.score * 100)}%
                                    </span>
                                    <svg class="w-3 h-3 text-muted-foreground/50 group-hover:text-primary transition-colors" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                                        <path d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                                    </svg>
                                </div>
                            </div>
                        </div>
                    </a>
                {/each}
            </div>
        </div>
      {/if}
      {/if}
    </div>
</div>

<!-- IMPORT PROTOCOL MODAL -->
<ProtocolImportModal
    bind:open={showImportModal}
    onSuccess={(protocolId) => goto(`/protocols/${protocolId}`)}
/>

<style>
    .chat-prose :global(pre) {
        background-color: hsl(var(--muted));
        border-radius: 0.5rem;
        padding: 0.75rem 1rem;
        overflow-x: auto;
    }

    .chat-prose :global(code) {
        font-size: 0.8125rem;
    }

    .chat-prose :global(p) {
        margin-top: 0.5em;
        margin-bottom: 0.5em;
    }

    .chat-prose :global(p:first-child) {
        margin-top: 0;
    }

    .chat-prose :global(p:last-child) {
        margin-bottom: 0;
    }

    .chat-prose :global(ul), .chat-prose :global(ol) {
        margin-top: 0.5em;
        margin-bottom: 0.5em;
    }
</style>
