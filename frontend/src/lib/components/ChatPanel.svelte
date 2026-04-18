<script lang="ts">
    import { tick } from 'svelte';
    import { marked } from 'marked';
    import DOMPurify from 'dompurify';
    import ChatSkillButtons from '$lib/components/ChatSkillButtons.svelte';
    import { Button } from '$lib/components/ui/button';
    import { scale } from 'svelte/transition';
    import {
        getPanelState, getActiveSession, getMessageInput, isSending,
        getMessageSources, getSkills,
        openPanel, closePanel, togglePanel,
        setMessageInput, sendMessage, clearConversation,
        registerScrollFn, activateSkill,
    } from '$lib/chat-store.svelte';

    let { showFab = true } = $props();

    let messagesEndEl = $state<HTMLDivElement>(undefined!);
    let inputEl = $state<HTMLTextAreaElement>(undefined!);
    let isMobile = $state(false);

    // Responsive detection
    if (typeof window !== 'undefined') {
        const mq = window.matchMedia('(max-width: 767px)');
        isMobile = mq.matches;
        mq.addEventListener('change', (e) => { isMobile = e.matches; });
    }

    // Derived state from store
    const panelState = $derived(getPanelState());
    const activeSession = $derived(getActiveSession());
    const messageInput = $derived(getMessageInput());
    const sending = $derived(isSending());
    const skills = $derived(getSkills());

    const hasMessages = $derived(
        activeSession !== null && activeSession.messages.length > 0
    );

    // Register scroll function with the store
    $effect(() => {
        if (panelState === 'open') {
            registerScrollFn(() => {
                messagesEndEl?.scrollIntoView({ behavior: 'smooth' });
            });
        }
    });

    // Focus input when panel opens
    $effect(() => {
        if (panelState === 'open') {
            tick().then(() => inputEl?.focus());
        }
    });

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    function handleGlobalKeydown(e: KeyboardEvent) {
        if ((e.metaKey || e.ctrlKey) && e.key === 'j') {
            e.preventDefault();
            togglePanel();
        }
    }

    function renderMarkdown(content: string): string {
        return DOMPurify.sanitize(
            marked.parse(content, { gfm: true, breaks: true }) as string
        );
    }

    function formatTime(iso: string): string {
        return new Date(iso).toLocaleTimeString([], {
            hour: '2-digit', minute: '2-digit',
        });
    }

    const shortcutLabel = typeof navigator !== 'undefined' && navigator.platform?.includes('Mac') ? 'Cmd' : 'Ctrl';
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

<!-- ─── COLLAPSED: FAB Button ─── -->
{#if panelState === 'collapsed' && showFab}
    <div transition:scale={{ duration: 200, start: 0 }} style="position:fixed;bottom:1.5rem;right:1.5rem;z-index:40;">
        <Button
            rounded="full"
            class="chat-fab shadow-lg hover:shadow-xl size-14"
            onclick={() => openPanel()}
            aria-label="Open AI Chat"
        >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                <path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
            </svg>
        </Button>
    </div>
{/if}

<!-- ─── OPEN: Floating Panel ─── -->
{#if panelState === 'open'}
    <div
        class="chat-panel flex flex-col bg-background border border-border/60 shadow-2xl overflow-hidden
            {isMobile ? 'rounded-t-2xl' : 'rounded-2xl'}"
        style="position:fixed;z-index:40;{isMobile
            ? 'left:0;right:0;bottom:0;height:85vh;'
            : 'bottom:1.5rem;right:1.5rem;width:840px;height:1200px;max-height:calc(100vh - 5rem);'}"
    >
        <!-- Header -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-border/40 bg-card/50 flex-shrink-0">
            <div class="flex items-center gap-2 min-w-0">
                <div class="w-6 h-6 rounded-md bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <svg class="w-3.5 h-3.5 text-primary" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
                    </svg>
                </div>
                <h3 class="text-sm font-semibold text-foreground truncate">
                    {activeSession?.title ?? 'Trellis AI'}
                </h3>
            </div>
            <div class="flex items-center gap-0.5">
                {#if activeSession}
                    <Button
                        variant="ghost"
                        size="icon-sm"
                        onclick={clearConversation}
                        aria-label="Clear conversation"
                        title="Clear conversation"
                    >
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                            <path d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" />
                        </svg>
                    </Button>
                {/if}
                <!-- Open in full view -->
                <a
                    href="/chat"
                    class="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                    aria-label="Open in full view"
                    title="Open in full view"
                    onclick={() => closePanel()}
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <path d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                    </svg>
                </a>
                <!-- Close -->
                <Button
                    variant="ghost"
                    size="icon-sm"
                    onclick={closePanel}
                    aria-label="Close chat panel"
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <path d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </Button>
            </div>
        </div>

        <!-- Messages -->
        <div class="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {#if !activeSession || activeSession.messages.length === 0}
                <div class="h-full flex items-center justify-center">
                    <div class="text-center px-4">
                        <div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center mx-auto mb-3">
                            <svg class="w-5 h-5 text-primary" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                                <path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z" />
                            </svg>
                        </div>
                        <p class="text-sm font-medium text-foreground mb-1">Trellis AI</p>
                        <p class="text-xs text-muted-foreground">
                            Ask about cell biology, protocols, or experiments.
                        </p>
                    </div>
                </div>
            {:else}
                {#each activeSession.messages as msg (msg.id)}
                    <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
                        <div
                            class="max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm
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
                                <!-- Inline sources as compact chips -->
                                {#if getMessageSources(msg).length > 0}
                                    <div class="flex flex-wrap gap-1.5 mt-2">
                                        {#each getMessageSources(msg) as source}
                                            <a
                                                href="/library/{source.document_id}?chunk={source.chunk_index}"
                                                class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                                                    bg-primary/10 text-primary text-[11px] font-medium
                                                    hover:bg-primary/20 transition-colors"
                                            >
                                                <span class="truncate max-w-[140px]">{source.document_title}</span>
                                                {#if source.page_number}
                                                    <span class="opacity-60">p.{source.page_number}</span>
                                                {/if}
                                            </a>
                                        {/each}
                                    </div>
                                {/if}
                            {:else}
                                <p class="whitespace-pre-wrap">{msg.content}</p>
                            {/if}
                            <p class="text-[10px] mt-1 opacity-50">{formatTime(msg.created_at)}</p>
                        </div>
                    </div>
                {/each}

                {#if sending}
                    <div class="flex justify-start">
                        <div class="bg-muted/70 rounded-xl px-3.5 py-2.5">
                            <div class="flex items-center gap-1.5">
                                <div class="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style="animation-delay: 0ms"></div>
                                <div class="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style="animation-delay: 150ms"></div>
                                <div class="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 animate-bounce" style="animation-delay: 300ms"></div>
                            </div>
                        </div>
                    </div>
                {/if}
            {/if}
            <div bind:this={messagesEndEl}></div>
        </div>

        <!-- Input -->
        <div class="border-t border-border/40 p-3 bg-card/30 flex-shrink-0">
            <div class="flex items-end gap-2">
                {#if hasMessages && skills.length > 0}
                    <ChatSkillButtons {skills} mode="dropdown" onactivate={activateSkill} />
                {/if}
                <textarea
                    bind:this={inputEl}
                    value={messageInput}
                    oninput={(e) => setMessageInput(e.currentTarget.value)}
                    onkeydown={handleKeydown}
                    placeholder="Ask a question..."
                    class="flex-1 resize-none rounded-xl border border-border/60 bg-background px-3 py-2.5 text-sm
                        placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30
                        focus:border-primary/50 min-h-[40px] max-h-[120px]"
                    rows="1"
                    disabled={sending}
                ></textarea>
                <Button
                    size="icon"
                    class="rounded-xl"
                    onclick={() => sendMessage()}
                    disabled={!messageInput.trim() || sending}
                    aria-label="Send message"
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                        <path d="M6 12L3.269 3.126A59.768 59.768 0 0 1 21.485 12 59.77 59.77 0 0 1 3.27 20.876L5.999 12Zm0 0h7.5" />
                    </svg>
                </Button>
            </div>
            {#if !hasMessages && skills.length > 0}
                <div class="mt-2">
                    <ChatSkillButtons {skills} mode="chips" onactivate={activateSkill} />
                </div>
            {/if}
            <p class="text-[10px] text-muted-foreground text-center mt-1.5">
                <kbd class="px-1 py-0.5 rounded bg-muted text-[9px] font-mono">{shortcutLabel}+J</kbd> to toggle
            </p>
        </div>
    </div>
{/if}

<style>
    @keyframes chat-panel-in {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .chat-panel { animation: chat-panel-in 0.25s ease-out both; }
    .chat-prose :global(pre) {
        background-color: hsl(var(--muted));
        border-radius: 0.375rem;
        padding: 0.5rem 0.75rem;
        overflow-x: auto;
        font-size: 0.75rem;
    }
    .chat-prose :global(code) { font-size: 0.75rem; }
    .chat-prose :global(p) { margin-top: 0.375em; margin-bottom: 0.375em; }
    .chat-prose :global(p:first-child) { margin-top: 0; }
    .chat-prose :global(p:last-child) { margin-bottom: 0; }
    .chat-prose :global(ul), .chat-prose :global(ol) {
        margin-top: 0.375em; margin-bottom: 0.375em;
    }
</style>
