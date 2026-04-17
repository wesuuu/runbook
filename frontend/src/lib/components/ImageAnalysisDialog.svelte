<script lang="ts">
    import { api } from '$lib/api';
    import { API_BASE } from '$lib/config';
    import * as Dialog from '$lib/components/ui/dialog';

    interface ExtractedValue {
        field_key: string;
        field_label: string;
        value: number | string;
        unit?: string;
        confidence: number;
    }

    interface ConversationMessage {
        role: string;
        content: string;
    }

    interface AnalysisResponse {
        conversation: {
            id: string;
            image_id: string;
            messages: ConversationMessage[];
            extracted_values: Record<string, any>;
            status: string;
        };
        message: string;
        extracted_values: ExtractedValue[];
        needs_clarification: boolean;
    }

    let {
        open = $bindable(false),
        runId,
        stepId,
        imageId,
        imagePath,
        onConfirm,
    }: {
        open: boolean;
        runId: string;
        stepId: string;
        imageId: string;
        imagePath: string;
        onConfirm?: (values: Record<string, any>) => void;
    } = $props();

    let analyzing = $state(false);
    let conversing = $state(false);
    let confirming = $state(false);
    let errorMsg = $state<string | null>(null);
    let analysisAttempted = $state(false);

    let messages = $state<ConversationMessage[]>([]);
    let extractedValues = $state<ExtractedValue[]>([]);
    let needsClarification = $state(false);
    let conversationStatus = $state<string>('pending');
    let userReply = $state('');

    // Track which values user has edited/rejected
    let editedValues = $state<Record<string, string>>({});
    let rejectedKeys = $state<Set<string>>(new Set());

    // Auto-analyze when dialog opens with an image
    $effect(() => {
        if (open && imageId && !analysisAttempted && !analyzing) {
            startAnalysis();
        }
    });

    async function startAnalysis() {
        analyzing = true;
        analysisAttempted = true;
        errorMsg = null;
        try {
            const resp = await api.post<AnalysisResponse>(
                `/ai/runs/${runId}/images/${imageId}/analyze`,
                {}
            );
            messages = resp.conversation.messages;
            extractedValues = resp.extracted_values;
            needsClarification = resp.needs_clarification;
            conversationStatus = resp.conversation.status;
        } catch (e: unknown) {
            errorMsg = e instanceof Error ? e.message : 'AI analysis failed';
        } finally {
            analyzing = false;
        }
    }

    async function sendReply() {
        if (!userReply.trim()) return;
        const reply = userReply.trim();
        userReply = '';
        conversing = true;
        errorMsg = null;

        // Optimistically add user message
        messages = [...messages, { role: 'user', content: reply }];

        try {
            const resp = await api.post<AnalysisResponse>(
                `/ai/runs/${runId}/images/${imageId}/converse`,
                { message: reply }
            );
            messages = resp.conversation.messages;
            extractedValues = resp.extracted_values;
            needsClarification = resp.needs_clarification;
            conversationStatus = resp.conversation.status;
        } catch (e: unknown) {
            errorMsg = e instanceof Error ? e.message : 'Failed to send message';
        } finally {
            conversing = false;
        }
    }

    async function confirmValues() {
        confirming = true;
        errorMsg = null;

        // Build values map: use edited values where available, skip rejected
        const values: Record<string, any> = {};
        for (const ev of extractedValues) {
            if (rejectedKeys.has(ev.field_key)) continue;
            if (editedValues[ev.field_key] !== undefined) {
                const raw = editedValues[ev.field_key];
                values[ev.field_key] = isNaN(Number(raw)) ? raw : Number(raw);
            } else {
                values[ev.field_key] = ev.value;
            }
        }

        if (Object.keys(values).length === 0) {
            errorMsg = 'No values to confirm. Accept at least one extracted value.';
            confirming = false;
            return;
        }

        try {
            await api.post(
                `/ai/runs/${runId}/images/${imageId}/confirm`,
                { values }
            );
            onConfirm?.(values);
            resetAndClose();
        } catch (e: unknown) {
            errorMsg = e instanceof Error ? e.message : 'Failed to confirm values';
        } finally {
            confirming = false;
        }
    }

    function resetAndClose() {
        open = false;
        messages = [];
        extractedValues = [];
        needsClarification = false;
        conversationStatus = 'pending';
        userReply = '';
        editedValues = {};
        rejectedKeys = new Set();
        errorMsg = null;
        analysisAttempted = false;
    }

    function toggleReject(key: string) {
        const next = new Set(rejectedKeys);
        if (next.has(key)) {
            next.delete(key);
        } else {
            next.add(key);
        }
        rejectedKeys = next;
    }

    function getConfidenceColor(confidence: number): string {
        if (confidence >= 0.9) return 'text-emerald-600';
        if (confidence >= 0.7) return 'text-amber-600';
        return 'text-red-600';
    }

    function getConfidenceLabel(confidence: number): string {
        if (confidence >= 0.9) return 'High';
        if (confidence >= 0.7) return 'Medium';
        return 'Low';
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendReply();
        }
    }

    function handleOpenChange(value: boolean) {
        if (!value) resetAndClose();
    }
</script>

<Dialog.Root bind:open onOpenChange={handleOpenChange}>
    <Dialog.Content class="sm:max-w-2xl max-h-[90vh] flex flex-col p-0 gap-0">
        <!-- Header -->
        <div class="px-6 py-4 border-b border-border shrink-0">
            <h2 class="text-lg font-semibold text-foreground">AI Image Analysis</h2>
            <p class="text-sm text-muted-foreground">Extracting measurement values from your image</p>
        </div>

        <!-- Scrollable Content -->
        <div class="flex-1 overflow-y-auto px-6 py-4 space-y-4 min-h-0">
            <!-- Image Preview -->
            <div class="flex justify-center bg-muted/50 rounded-lg p-2">
                <img
                    src="{API_BASE}/uploads/images/{imagePath}"
                    alt="Captured measurement"
                    class="max-h-48 rounded object-contain"
                />
            </div>

            <!-- Loading State -->
            {#if analyzing}
                <div class="flex items-center justify-center py-8">
                    <div class="text-center">
                        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto mb-3"></div>
                        <p class="text-sm text-muted-foreground">Analyzing image...</p>
                    </div>
                </div>
            {/if}

            <!-- Error -->
            {#if errorMsg}
                <div class="p-3 bg-red-50 border border-red-200 rounded-lg text-sm">
                    <p class="text-red-700">{errorMsg}</p>
                    <button
                        onclick={() => { analysisAttempted = false; }}
                        class="mt-2 text-xs text-red-600 underline hover:text-red-800"
                    >
                        Retry analysis
                    </button>
                </div>
            {/if}

            <!-- Conversation Messages -->
            {#if messages.length > 0}
                <div class="space-y-3">
                    {#each messages as msg}
                        {#if msg.role === 'assistant'}
                            <div class="flex gap-2">
                                <div class="shrink-0 w-7 h-7 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center text-xs font-bold">
                                    AI
                                </div>
                                <div class="bg-muted/50 rounded-lg p-3 text-sm text-foreground/80 max-w-[85%]">
                                    {msg.content}
                                </div>
                            </div>
                        {:else if msg.role === 'user'}
                            <div class="flex gap-2 justify-end">
                                <div class="bg-teal-50 rounded-lg p-3 text-sm text-teal-800 max-w-[85%]">
                                    {msg.content}
                                </div>
                                <div class="shrink-0 w-7 h-7 rounded-full bg-muted text-muted-foreground flex items-center justify-center text-xs font-bold">
                                    You
                                </div>
                            </div>
                        {/if}
                    {/each}
                </div>
            {/if}

            <!-- Extracted Values -->
            {#if extractedValues.length > 0}
                <div class="border border-border rounded-lg">
                    <div class="px-4 py-2.5 bg-muted/50 border-b border-border rounded-t-lg">
                        <h4 class="text-sm font-semibold text-foreground/80">Extracted Values</h4>
                    </div>
                    <div class="divide-y divide-border/60">
                        {#each extractedValues as ev}
                            {@const isRejected = rejectedKeys.has(ev.field_key)}
                            <div class="px-4 py-3 flex items-center gap-3 {isRejected ? 'opacity-40' : ''}">
                                <div class="flex-1 min-w-0">
                                    <div class="text-sm font-medium text-foreground/80">
                                        {ev.field_label}
                                    </div>
                                    <div class="flex items-center gap-2 mt-1">
                                        {#if editedValues[ev.field_key] !== undefined && !isRejected}
                                            <input
                                                type="text"
                                                bind:value={editedValues[ev.field_key]}
                                                class="w-32 px-2 py-1 border border-teal-300 rounded text-sm font-mono focus:outline-none focus:ring-1 focus:ring-teal-500"
                                            />
                                        {:else}
                                            <span class="text-sm font-mono font-medium text-foreground">
                                                {ev.value}
                                            </span>
                                        {/if}
                                        {#if ev.unit}
                                            <span class="text-xs text-muted-foreground">{ev.unit}</span>
                                        {/if}
                                        <span class="text-xs {getConfidenceColor(ev.confidence)}">
                                            {getConfidenceLabel(ev.confidence)} ({Math.round(ev.confidence * 100)}%)
                                        </span>
                                    </div>
                                </div>
                                <div class="flex gap-1.5 shrink-0">
                                    {#if !isRejected}
                                        <button
                                            onclick={() => {
                                                if (editedValues[ev.field_key] !== undefined) {
                                                    const { [ev.field_key]: _, ...rest } = editedValues;
                                                    editedValues = rest;
                                                } else {
                                                    editedValues = { ...editedValues, [ev.field_key]: String(ev.value) };
                                                }
                                            }}
                                            class="px-2 py-1 text-xs rounded border {editedValues[ev.field_key] !== undefined ? 'bg-teal-50 border-teal-300 text-teal-700' : 'border-border text-muted-foreground hover:bg-muted'}"
                                        >
                                            {editedValues[ev.field_key] !== undefined ? 'Done' : 'Edit'}
                                        </button>
                                    {/if}
                                    <button
                                        onclick={() => toggleReject(ev.field_key)}
                                        class="px-2 py-1 text-xs rounded border {isRejected ? 'bg-red-50 border-red-300 text-red-700' : 'border-border text-muted-foreground hover:bg-muted'}"
                                    >
                                        {isRejected ? 'Undo' : 'Reject'}
                                    </button>
                                </div>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}

            <!-- Chat Input -->
            {#if conversationStatus !== 'pending' && conversationStatus !== 'confirmed'}
                <div class="flex gap-2">
                    <input
                        type="text"
                        bind:value={userReply}
                        onkeydown={handleKeydown}
                        placeholder="Ask the AI to clarify or re-check..."
                        disabled={conversing}
                        class="flex-1 px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent disabled:opacity-50"
                    />
                    <button
                        onclick={sendReply}
                        disabled={conversing || !userReply.trim()}
                        class="px-4 py-2 bg-teal-600 text-white rounded-lg text-sm font-medium hover:bg-teal-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {conversing ? '...' : 'Send'}
                    </button>
                </div>
            {/if}
        </div>

        <!-- Footer Actions -->
        {#if extractedValues.length > 0 && conversationStatus !== 'confirmed'}
            <div class="flex justify-end gap-3 px-6 py-4 border-t border-border shrink-0">
                <button
                    onclick={resetAndClose}
                    class="px-4 py-2 bg-muted text-foreground/80 rounded-lg text-sm font-medium hover:bg-muted/80 transition-colors"
                >
                    Dismiss
                </button>
                <button
                    onclick={confirmValues}
                    disabled={confirming}
                    class="px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-medium hover:bg-emerald-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {confirming ? 'Confirming...' : 'Confirm Values'}
                </button>
            </div>
        {/if}
    </Dialog.Content>
</Dialog.Root>
