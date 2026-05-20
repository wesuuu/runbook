<script lang="ts">
    import { api } from '$lib/api';
    import { toast } from '$lib/toast';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import * as Dialog from '$lib/components/ui/dialog';
    import ConfirmDialog from '$lib/components/ui/confirm-dialog.svelte';
    import { formatFileSize } from '$lib/utils/document-utils';
    import { API_BASE } from '$lib/config';
    import { getToken } from '$lib/auth.svelte';

    interface ConvertWarning {
        type: string;
        variable: string;
        description: string;
    }

    interface ConvertResponse {
        conversion_id: string;
        preview_url: string;
        template_download_url: string;
        warnings: ConvertWarning[];
        variables_detected: string[];
    }

    interface ToolActivity {
        tool: string;
        sequence: number;
        status: 'running' | 'success' | 'error';
        summary?: string;
    }

    interface Props {
        open: boolean;
        projectId?: string;
        onSuccess?: () => void;
    }

    let { open = $bindable(false), projectId, onSuccess }: Props = $props();

    // --- State ---
    let step = $state<'upload' | 'processing' | 'review'>('upload');

    // Upload state
    let selectedFile = $state<File | null>(null);
    let templateType = $state<'SOP' | 'BATCH_RECORD'>('SOP');
    let dragOver = $state(false);
    let error = $state<string | null>(null);

    // SSE activity tracking
    let activities = $state<ToolActivity[]>([]);
    let sseCleanup = $state<(() => void) | null>(null);
    let sseActive = $state(false);

    // Conversion result
    let previewMode = $state<'rendered' | 'template' | 'original'>('rendered');
    let templateBlobUrl = $state<string | null>(null);
    let originalBlobUrl = $state<string | null>(null);
    let conversionId = $state<string | null>(null);
    let previewBlobUrl = $state<string | null>(null);
    let templateDownloadUrl = $state<string | null>(null);
    let warnings = $state<ConvertWarning[]>([]);
    let variablesDetected = $state<string[]>([]);

    // Chat refinement
    let chatMessages = $state<Array<{ role: 'user' | 'assistant'; content: string }>>([]);
    let chatInput = $state('');
    let refining = $state(false);

    // Save state
    let showSaveDialog = $state(false);
    let saveName = $state('');
    let saveDescription = $state('');
    let saving = $state(false);

    const allowedTypes = new Set([
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ]);

    function toolLabel(tool: string): string {
        switch (tool) {
            case 'apply_substitutions': return 'Applying substitutions';
            case 'add_table_loop': return 'Adding table loop';
            case 'modify_table': return 'Modifying table';
            case 'remove_section': return 'Removing section';
            case 'add_content': return 'Adding content';
            case 'validate': return 'Validating';
            case 'compare_to_original': return 'Comparing to original';
            default: return tool;
        }
    }

    function stopSSE() {
        sseCleanup?.();
        sseCleanup = null;
        sseActive = false;
    }

    function resetState() {
        stopSSE();
        step = 'upload';
        selectedFile = null;
        templateType = 'SOP';
        dragOver = false;
        error = null;
        activities = [];
        conversionId = null;
        if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
        previewBlobUrl = null;
        if (templateBlobUrl) URL.revokeObjectURL(templateBlobUrl);
        templateBlobUrl = null;
        if (originalBlobUrl) URL.revokeObjectURL(originalBlobUrl);
        originalBlobUrl = null;
        previewMode = 'rendered';
        templateDownloadUrl = null;
        warnings = [];
        variablesDetected = [];
        chatMessages = [];
        chatInput = '';
        refining = false;
        showSaveDialog = false;
        saveName = '';
        saveDescription = '';
        saving = false;
    }

    // --- File handling ---
    function handleFileSelect(file: File) {
        error = null;
        if (!allowedTypes.has(file.type)) {
            error = 'Unsupported file type. Only .docx files are accepted.';
            return;
        }
        if (file.size > 20 * 1024 * 1024) {
            error = `File too large: ${formatFileSize(file.size)}. Maximum: 20 MB`;
            return;
        }
        selectedFile = file;
    }

    function handleInputChange(e: Event) {
        const input = e.target as HTMLInputElement;
        if (input.files?.[0]) handleFileSelect(input.files[0]);
    }

    function handleDrop(e: DragEvent) {
        e.preventDefault();
        dragOver = false;
        const file = e.dataTransfer?.files?.[0];
        if (file) handleFileSelect(file);
    }

    async function fetchPreview(url: string) {
        const token = getToken();
        const cacheBust = `_t=${Date.now()}`;
        const separator = url.includes('?') ? '&' : '?';
        const resp = await fetch(`${API_BASE}${url}${separator}${cacheBust}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            cache: 'no-store',
        });
        if (resp.ok) {
            const blob = await resp.blob();
            if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
            previewBlobUrl = URL.createObjectURL(blob);
        }
    }

    async function fetchOriginalPreview() {
        if (!conversionId || originalBlobUrl) return;
        const token = getToken();
        const url = `/templates/conversions/${conversionId}/original.pdf`;
        const resp = await fetch(`${API_BASE}${url}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (resp.ok) {
            const blob = await resp.blob();
            originalBlobUrl = URL.createObjectURL(blob);
        }
    }

    async function fetchTemplatePreview() {
        if (!conversionId) return;
        const token = getToken();
        const url = `/templates/conversions/${conversionId}/template.pdf`;
        const cacheBust = `_t=${Date.now()}`;
        const resp = await fetch(
            `${API_BASE}${url}?${cacheBust}`,
            {
                headers: token ? { Authorization: `Bearer ${token}` } : {},
                cache: 'no-store',
            },
        );
        if (resp.ok) {
            const blob = await resp.blob();
            if (templateBlobUrl) URL.revokeObjectURL(templateBlobUrl);
            templateBlobUrl = URL.createObjectURL(blob);
        }
    }

    // --- Convert ---
    async function handleConvert() {
        if (!selectedFile) return;
        step = 'processing';
        error = null;
        activities = [];

        try {
            const startResult = await api.uploadWithFields<{ conversion_id: string; status: string }>(
                '/templates/convert',
                selectedFile,
                { template_type: templateType },
            );
            conversionId = startResult.conversion_id;
            saveName = selectedFile.name.replace(/\.[^.]+$/, '') + ' Template';

            startSSE(startResult.conversion_id);
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to start conversion';
            step = 'upload';
        }
    }

    function startSSE(id: string) {
        stopSSE();
        sseActive = true;
        sseCleanup = api.connectSSE(
            `/templates/conversions/${id}/events`,
            {
                onToolCall(data) {
                    activities = [...activities, {
                        tool: data.tool,
                        sequence: data.sequence,
                        status: 'running',
                    }];
                },
                onToolResult(data) {
                    activities = activities.map(a =>
                        a.sequence === data.sequence
                            ? { ...a, status: data.status as 'success' | 'error', summary: data.summary }
                            : a
                    );
                },
                async onComplete(data) {
                    sseActive = false;
                    templateDownloadUrl = data.template_url;
                    warnings = data.warnings as ConvertWarning[];
                    variablesDetected = data.variables;

                    chatMessages = [{
                        role: 'assistant',
                        content: `Converted "${selectedFile?.name}" into a template with ${data.variables.length} variables.`,
                    }];

                    if (data.preview_url) await fetchPreview(data.preview_url);
                    step = 'review';
                },
                onError(data) {
                    sseActive = false;
                    error = data.message || 'Conversion failed';
                    step = 'upload';
                },
            },
        );
    }

    // --- Chat refinement ---
    async function handleChatSend() {
        if (!chatInput.trim() || !conversionId || refining) return;

        const instruction = chatInput.trim();
        chatInput = '';
        chatMessages = [...chatMessages, { role: 'user', content: instruction }];
        refining = true;

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5 * 60 * 1000);

        try {
            const result = await api.post<ConvertResponse>(
                `/templates/conversions/${conversionId}/refine`,
                { instruction },
            );

            templateDownloadUrl = result.template_download_url;
            warnings = result.warnings;
            variablesDetected = result.variables_detected;

            if (result.preview_url) await fetchPreview(result.preview_url);
            // Re-fetch template preview if currently viewing it
            if (templateBlobUrl) URL.revokeObjectURL(templateBlobUrl);
            templateBlobUrl = null;
            if (previewMode === 'template') await fetchTemplatePreview();
            chatMessages = [...chatMessages, {
                role: 'assistant',
                content: `Template updated with ${result.variables_detected.length} variables. Check the preview.`,
            }];
        } catch (e: unknown) {
            const msg = controller.signal.aborted
                ? 'Refinement timed out after 5 minutes. Try a simpler instruction.'
                : `Failed to refine: ${e instanceof Error ? e.message : 'Unknown error'}. Try rephrasing.`;
            chatMessages = [...chatMessages, { role: 'assistant', content: msg }];
        } finally {
            clearTimeout(timeout);
            refining = false;
        }
    }

    function handleChatKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleChatSend();
        }
    }

    // --- Re-upload ---
    async function handleReupload(e: Event) {
        const input = e.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file || !conversionId) return;

        refining = true;
        try {
            const result = await api.uploadWithFields<ConvertResponse>(
                `/templates/conversions/${conversionId}/reupload`,
                file,
                {},
            );

            templateDownloadUrl = result.template_download_url;
            warnings = result.warnings;
            variablesDetected = result.variables_detected;

            if (result.preview_url) await fetchPreview(result.preview_url);
            if (templateBlobUrl) URL.revokeObjectURL(templateBlobUrl);
            templateBlobUrl = null;
            if (previewMode === 'template') await fetchTemplatePreview();
            chatMessages = [...chatMessages, {
                role: 'assistant',
                content: 'Re-uploaded template processed. Check the updated preview.',
            }];
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Re-upload failed');
        } finally {
            refining = false;
        }
    }

    // --- Save to library ---
    async function handleSave() {
        if (!conversionId || saving) return;
        saving = true;

        try {
            await api.post(
                `/templates/conversions/${conversionId}/save`,
                {
                    name: saveName,
                    template_type: templateType,
                    description: saveDescription,
                    ...(projectId ? { project_id: projectId } : {}),
                },
            );
            toast.success('Template saved to library');
            open = false;
            resetState();
            onSuccess?.();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to save');
        } finally {
            saving = false;
        }
    }

    // --- Download template ---
    async function downloadTemplate() {
        if (!templateDownloadUrl) return;
        const token = getToken();
        const resp = await fetch(`${API_BASE}${templateDownloadUrl}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!resp.ok) {
            toast.error('Failed to download template');
            return;
        }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'template.docx';
        link.click();
        URL.revokeObjectURL(url);
    }

    let discardConfirmOpen = $state(false);

    function handleClose() {
        if (conversionId && !showSaveDialog) {
            discardConfirmOpen = true;
            return;
        }
        open = false;
        resetState();
    }

    function confirmDiscardConversion() {
        discardConfirmOpen = false;
        open = false;
        resetState();
    }

    const criticalWarnings = $derived(warnings.filter(w => w.type === 'critical_missing'));
    const missingVarWarnings = $derived(warnings.filter(w => w.type === 'missing_variable'));
    const otherWarnings = $derived(warnings.filter(w => w.type !== 'missing_variable' && w.type !== 'critical_missing'));

    // Resizable split pane
    let chatWidth = $state(400);
    let resizing = $state(false);
    let resizeStartX = $state(0);
    let resizeStartWidth = $state(0);

    function handleResizePointerDown(e: PointerEvent) {
        const target = e.currentTarget as HTMLElement;
        target.setPointerCapture(e.pointerId);
        resizing = true;
        resizeStartX = e.clientX;
        resizeStartWidth = chatWidth;
    }

    function handleResizePointerMove(e: PointerEvent) {
        if (!resizing) return;
        const delta = resizeStartX - e.clientX;
        chatWidth = Math.max(280, Math.min(700, resizeStartWidth + delta));
    }

    function handleResizePointerUp() {
        resizing = false;
    }

    // Prevent navigation while conversion is running
    $effect(() => {
        if (!sseActive) return;
        function onBeforeUnload(e: BeforeUnloadEvent) {
            e.preventDefault();
            e.returnValue = '';
        }
        window.addEventListener('beforeunload', onBeforeUnload);
        return () => window.removeEventListener('beforeunload', onBeforeUnload);
    });
</script>

<Dialog.Root open={open}>
    <Dialog.Content
        class="w-screen h-screen max-w-none sm:max-w-none max-h-none overflow-y-visible rounded-none border-0 p-0 gap-0 bg-background flex flex-col overflow-hidden"
        style="top: 0; left: 0; translate: none"
        showCloseButton={false}
        onEscapeKeydown={(e) => { e.preventDefault(); handleClose(); }}
        interactOutsideBehavior="ignore"
    >
    <!-- Header -->
    <div class="flex items-center justify-between border-b border-border px-6 py-3 shrink-0">
        <div class="flex items-center gap-6">
            <Dialog.Title class="text-lg font-semibold">Convert Document to Template</Dialog.Title>
            <Dialog.Description class="sr-only">
                Upload a completed document and convert it into a reusable template.
            </Dialog.Description>
            {#if step === 'review'}
                <span class="text-sm text-muted-foreground">
                    {variablesDetected.length} variables detected
                </span>
            {/if}
        </div>
        <Button
            variant="ghost"
            size="icon-sm"
            onclick={handleClose}
            aria-label="Close"
        >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path d="M6 18L18 6M6 6l12 12" />
            </svg>
        </Button>
    </div>

    <!-- Content -->
    <div class="flex-1 overflow-hidden">
    <div class="h-full flex flex-col">
        {#if step === 'upload'}
            <!-- Upload step -->
            <div class="flex-1 flex items-center justify-center p-8">
                <div class="max-w-lg w-full space-y-6">
                    <div class="text-center mb-6">
                        <h2 class="text-xl font-semibold mb-2">Upload a Completed Document</h2>
                        <p class="text-sm text-muted-foreground">
                            Upload a filled SOP, batch record, or other document. The AI will
                            convert it into a reusable template with variable placeholders.
                        </p>
                    </div>

                    {#if error}
                        <div class="bg-destructive/10 text-destructive text-sm p-3 rounded-md">{error}</div>
                    {/if}

                    <!-- Template type selector -->
                    <div>
                        <Label>Template Type</Label>
                        <div class="flex gap-2 mt-1">
                            <Button
                                variant="outline"
                                class="flex-1 {templateType === 'SOP' ? 'border-primary bg-primary/10 text-primary hover:bg-primary/15' : ''}"
                                onclick={() => (templateType = 'SOP')}
                            >
                                Protocol
                            </Button>
                            <Button
                                variant="outline"
                                class="flex-1 {templateType === 'BATCH_RECORD' ? 'border-primary bg-primary/10 text-primary hover:bg-primary/15' : ''}"
                                onclick={() => (templateType = 'BATCH_RECORD')}
                            >
                                Batch Record
                            </Button>
                        </div>
                    </div>

                    <!-- Drop zone -->
                    <div
                        class="border-2 border-dashed rounded-lg p-10 text-center transition-colors cursor-pointer
                            {dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'}"
                        ondrop={handleDrop}
                        ondragover={(e) => { e.preventDefault(); dragOver = true; }}
                        ondragleave={() => (dragOver = false)}
                        onclick={() => document.getElementById('convert-file-input')?.click()}
                        onkeydown={(e) => e.key === 'Enter' && document.getElementById('convert-file-input')?.click()}
                        role="button"
                        tabindex="0"
                    >
                        {#if selectedFile}
                            <div>
                                <p class="font-medium text-sm">{selectedFile.name}</p>
                                <p class="text-xs text-muted-foreground mt-1">{formatFileSize(selectedFile.size)}</p>
                                <p class="text-xs text-primary mt-2">Click to change file</p>
                            </div>
                        {:else}
                            <div>
                                <svg class="w-10 h-10 mx-auto mb-3 text-muted-foreground" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                                    <path d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
                                </svg>
                                <p class="text-sm text-muted-foreground">Drag and drop a file here, or click to browse</p>
                                <p class="text-xs text-muted-foreground mt-1">DOCX files only (max 20 MB)</p>
                            </div>
                        {/if}
                        <input
                            id="convert-file-input"
                            type="file"
                            class="hidden"
                            accept=".docx"
                            onchange={handleInputChange}
                        />
                    </div>

                    <Button
                        onclick={handleConvert}
                        disabled={!selectedFile}
                        class="w-full"
                    >
                        Convert to Template
                    </Button>
                </div>
            </div>

        {:else if step === 'processing'}
            <!-- Processing: dynamic tool-call activity log -->
            <div class="flex-1 flex items-center justify-center">
                <div class="w-full max-w-md px-8">
                    <p class="text-sm font-medium text-center mb-4">Converting document...</p>

                    <div class="space-y-2">
                        {#each activities as activity}
                            <div class="flex items-center gap-2 text-xs">
                                {#if activity.status === 'running'}
                                    <div class="w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full animate-spin shrink-0"></div>
                                {:else if activity.status === 'success'}
                                    <svg class="w-3.5 h-3.5 text-emerald-500 shrink-0" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>
                                {:else}
                                    <svg class="w-3.5 h-3.5 text-destructive shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M6 18L18 6M6 6l12 12"/></svg>
                                {/if}
                                <span class="{activity.status === 'running' ? 'text-primary font-medium' : ''}">
                                    {toolLabel(activity.tool)}
                                    {#if activity.summary}
                                        <span class="text-muted-foreground ml-1">— {activity.summary}</span>
                                    {/if}
                                </span>
                            </div>
                        {/each}

                        {#if activities.length === 0 && sseActive}
                            <div class="flex items-center gap-2 text-xs text-muted-foreground">
                                <div class="w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full animate-spin shrink-0"></div>
                                <span>Starting AI agent...</span>
                            </div>
                        {:else if sseActive && !activities.some(a => a.status === 'running')}
                            <div class="flex items-center gap-2 text-xs text-muted-foreground mt-1">
                                <div class="w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full animate-spin shrink-0"></div>
                                <span>Thinking...</span>
                            </div>
                        {/if}
                    </div>
                </div>
            </div>

        {:else if step === 'review'}
            <!-- Review: split pane -->
            <div class="flex-1 flex overflow-hidden" style={resizing ? 'user-select: none' : ''}>
                <!-- Left: preview with toggle -->
                <div class="flex-1 overflow-hidden flex flex-col min-w-0">
                    <div class="px-4 py-2 border-b border-border bg-muted/30 flex items-center justify-between">
                        <div class="flex gap-1 bg-muted rounded-md p-0.5">
                            <Button
                                variant="ghost"
                                size="sm"
                                class="h-7 px-3 text-xs {previewMode === 'original' ? 'bg-background text-foreground shadow-sm hover:bg-background' : 'text-muted-foreground'}"
                                onclick={async () => { previewMode = 'original'; await fetchOriginalPreview(); }}
                            >
                                Original
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                class="h-7 px-3 text-xs {previewMode === 'rendered' ? 'bg-background text-foreground shadow-sm hover:bg-background' : 'text-muted-foreground'}"
                                onclick={() => (previewMode = 'rendered')}
                            >
                                Rendered
                            </Button>
                            <Button
                                variant="ghost"
                                size="sm"
                                class="h-7 px-3 text-xs {previewMode === 'template' ? 'bg-background text-foreground shadow-sm hover:bg-background' : 'text-muted-foreground'}"
                                onclick={async () => { previewMode = 'template'; if (!templateBlobUrl) await fetchTemplatePreview(); }}
                            >
                                Template
                            </Button>
                        </div>
                    </div>
                    <div class="flex-1 overflow-auto bg-muted/10">
                        {#if previewMode === 'original'}
                            {#if originalBlobUrl}
                                <iframe
                                    src="{originalBlobUrl}"
                                    class="w-full h-full"
                                    title="Original Document"
                                ></iframe>
                            {:else}
                                <div class="flex items-center justify-center h-full text-muted-foreground text-sm">
                                    Loading original...
                                </div>
                            {/if}
                        {:else if previewMode === 'rendered'}
                            {#if previewBlobUrl}
                                <iframe
                                    src="{previewBlobUrl}"
                                    class="w-full h-full"
                                    title="Rendered Preview"
                                ></iframe>
                            {:else}
                                <div class="flex items-center justify-center h-full text-muted-foreground text-sm">
                                    No preview available
                                </div>
                            {/if}
                        {:else}
                            {#if templateBlobUrl}
                                <iframe
                                    src="{templateBlobUrl}"
                                    class="w-full h-full"
                                    title="Template Preview"
                                ></iframe>
                            {:else}
                                <div class="flex items-center justify-center h-full text-muted-foreground text-sm">
                                    Loading template...
                                </div>
                            {/if}
                        {/if}
                    </div>
                </div>

                <!-- Resize handle -->
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <div
                    class="w-2 shrink-0 cursor-col-resize bg-border hover:bg-primary/30 active:bg-primary/40 transition-colors {resizing ? 'bg-primary/40' : ''}"
                    onpointerdown={handleResizePointerDown}
                    onpointermove={handleResizePointerMove}
                    onpointerup={handleResizePointerUp}
                    style="touch-action: none"
                ></div>

                <!-- Right: warnings + chat -->
                <div class="flex flex-col shrink-0" style="width: {chatWidth}px">
                    <!-- Warnings -->
                    {#if warnings.length > 0}
                        <div class="px-4 py-3 border-b border-border space-y-2 max-h-48 overflow-y-auto">
                            {#if criticalWarnings.length > 0}
                                {#each criticalWarnings as w}
                                    <div class="bg-destructive/10 text-destructive text-xs p-2 rounded font-medium">
                                        {w.description}
                                    </div>
                                {/each}
                            {/if}
                            {#if otherWarnings.length > 0}
                                {#each otherWarnings as w}
                                    <div class="bg-amber-500/10 text-amber-700 text-xs p-2 rounded">
                                        {w.description}
                                    </div>
                                {/each}
                            {/if}
                            {#if missingVarWarnings.length > 0}
                                <details class="text-xs">
                                    <summary class="cursor-pointer text-muted-foreground hover:text-foreground">
                                        {missingVarWarnings.length} optional variables not used
                                    </summary>
                                    <ul class="mt-1 space-y-1 pl-4">
                                        {#each missingVarWarnings as w}
                                            <li class="text-muted-foreground">
                                                <code class="text-xs">{w.variable}</code>
                                            </li>
                                        {/each}
                                    </ul>
                                </details>
                            {/if}
                        </div>
                    {/if}

                    <!-- Chat messages -->
                    <div class="flex-1 overflow-y-auto p-4 space-y-3">
                        {#each chatMessages as msg}
                            <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
                                <div class="max-w-[90%] px-3 py-2 rounded-lg text-sm {msg.role === 'user'
                                    ? 'bg-primary text-primary-foreground'
                                    : 'bg-muted text-foreground'}">
                                    {msg.content}
                                </div>
                            </div>
                        {/each}
                        {#if refining}
                            <div class="flex justify-start">
                                <div class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm bg-muted text-muted-foreground">
                                    <div class="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin shrink-0"></div>
                                    <span class="italic">Updating template...</span>
                                </div>
                            </div>
                        {/if}
                    </div>

                    <!-- Chat input -->
                    <div class="border-t border-border p-3">
                        <div class="flex gap-2">
                            <textarea
                                bind:value={chatInput}
                                onkeydown={handleChatKeydown}
                                placeholder="Ask the AI to adjust the template..."
                                class="flex-1 px-3 py-2 border border-border rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring"
                                rows="2"
                                disabled={refining}
                            ></textarea>
                            <Button
                                onclick={handleChatSend}
                                disabled={!chatInput.trim() || refining}
                                class="self-end"
                                size="sm"
                            >
                                Send
                            </Button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Bottom bar -->
            <div class="border-t border-border px-6 py-3 flex items-center justify-between shrink-0">
                <div class="flex gap-2">
                    <Button variant="outline" size="sm" onclick={downloadTemplate}>
                        Download Template (.docx)
                    </Button>
                    <label class="inline-flex">
                        <Button variant="outline" size="sm" onclick={() => document.getElementById('reupload-input')?.click()}>
                            Re-upload Edited Template
                        </Button>
                        <input
                            id="reupload-input"
                            type="file"
                            class="hidden"
                            accept=".docx"
                            onchange={handleReupload}
                        />
                    </label>
                </div>
                <div class="flex gap-2">
                    <Button variant="outline" onclick={handleClose}>Cancel</Button>
                    <Button onclick={() => (showSaveDialog = true)}>Save to Library</Button>
                </div>
            </div>

            <Dialog.Root bind:open={showSaveDialog}>
                <Dialog.Content class="max-w-md space-y-4">
                    <Dialog.Header>
                        <Dialog.Title class="text-lg font-semibold">Save Template to Library</Dialog.Title>
                    </Dialog.Header>
                    <div>
                        <Label for="save-name">Template Name</Label>
                        <Input id="save-name" bind:value={saveName} class="mt-1" />
                    </div>
                    <div>
                        <Label for="save-desc">Description (optional)</Label>
                        <Input id="save-desc" bind:value={saveDescription} class="mt-1" />
                    </div>
                    <div>
                        <Label>Type</Label>
                        <p class="text-sm text-muted-foreground mt-1">
                            {templateType === 'SOP' ? 'Protocol' : 'Batch Record'}
                        </p>
                    </div>
                    <div class="flex justify-end gap-2">
                        <Button variant="outline" onclick={() => (showSaveDialog = false)}>Cancel</Button>
                        <Button onclick={handleSave} disabled={!saveName.trim() || saving}>
                            {saving ? 'Saving...' : 'Save'}
                        </Button>
                    </div>
                </Dialog.Content>
            </Dialog.Root>
        {/if}
    </div>
    </div>
    </Dialog.Content>
</Dialog.Root>

<ConfirmDialog
    bind:open={discardConfirmOpen}
    title="Discard conversion?"
    message="You'll lose your conversion progress. Are you sure?"
    confirmLabel="Discard"
    confirmVariant="danger"
    onConfirm={confirmDiscardConversion}
    onCancel={() => (discardConfirmOpen = false)}
/>
