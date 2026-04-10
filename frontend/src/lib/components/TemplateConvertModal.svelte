<script lang="ts">
    import { api } from '$lib/api';
    import { toast } from '$lib/toast';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
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
        verification_rounds: number;
        verification_passed: boolean;
    }

    interface Props {
        open: boolean;
        onSuccess?: () => void;
    }

    let { open = $bindable(false), onSuccess }: Props = $props();

    // --- State ---
    let step = $state<'upload' | 'processing' | 'review'>('upload');

    // Upload state
    let selectedFile = $state<File | null>(null);
    let templateType = $state<'SOP' | 'BATCH_RECORD'>('SOP');
    let dragOver = $state(false);
    let error = $state<string | null>(null);

    // Progress tracking
    let progressStep = $state('Starting...');
    let progressNumber = $state(0);
    let progressTotal = $state(6);
    let progressElapsed = $state(0);
    let pollTimer = $state<ReturnType<typeof setInterval> | null>(null);

    // Conversion result
    let conversionId = $state<string | null>(null);
    let previewBlobUrl = $state<string | null>(null);
    let templateDownloadUrl = $state<string | null>(null);
    let warnings = $state<ConvertWarning[]>([]);
    let variablesDetected = $state<string[]>([]);
    let verificationPassed = $state(false);

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
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'image/jpeg',
        'image/png',
    ]);

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function resetState() {
        stopPolling();
        step = 'upload';
        selectedFile = null;
        templateType = 'SOP';
        dragOver = false;
        error = null;
        progressStep = 'Starting...';
        progressNumber = 0;
        progressTotal = 6;
        progressElapsed = 0;
        conversionId = null;
        if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
        previewBlobUrl = null;
        templateDownloadUrl = null;
        warnings = [];
        variablesDetected = [];
        verificationPassed = false;
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
            error = 'Unsupported file type. Accepted: PDF, DOCX, XLSX, JPEG, PNG';
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
        const resp = await fetch(`${API_BASE}${url}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (resp.ok) {
            const blob = await resp.blob();
            if (previewBlobUrl) URL.revokeObjectURL(previewBlobUrl);
            previewBlobUrl = URL.createObjectURL(blob);
        }
    }

    // --- Convert ---
    async function handleConvert() {
        if (!selectedFile) return;
        step = 'processing';
        error = null;
        progressStep = 'Uploading document...';
        progressNumber = 0;
        progressTotal = 6;
        progressElapsed = 0;

        try {
            // Start async conversion — returns immediately with conversion_id
            const startResult = await api.uploadWithFields<{ conversion_id: string; status: string }>(
                '/science/templates/convert',
                selectedFile,
                { template_type: templateType },
            );
            conversionId = startResult.conversion_id;
            saveName = selectedFile.name.replace(/\.[^.]+$/, '') + ' Template';

            // Start polling for progress
            startPolling(startResult.conversion_id);
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to start conversion';
            step = 'upload';
        }
    }

    function startPolling(id: string) {
        stopPolling();
        pollTimer = setInterval(async () => {
            try {
                const status = await api.get<{
                    status: string;
                    current_step: string;
                    step_number: number;
                    total_steps: number;
                    elapsed_seconds: number;
                    error: string | null;
                    preview_url: string | null;
                    template_download_url: string | null;
                    warnings: ConvertWarning[];
                    variables_detected: string[];
                    verification_rounds: number | null;
                    verification_passed: boolean | null;
                }>(`/science/templates/conversions/${id}/status`);

                progressStep = status.current_step;
                progressNumber = status.step_number;
                progressTotal = status.total_steps;
                progressElapsed = status.elapsed_seconds;

                if (status.status === 'completed') {
                    stopPolling();
                    templateDownloadUrl = status.template_download_url;
                    warnings = status.warnings;
                    variablesDetected = status.variables_detected;
                    verificationPassed = status.verification_passed ?? false;

                    chatMessages = [{
                        role: 'assistant',
                        content: `Analyzed "${selectedFile?.name}" and generated a template with ${status.variables_detected.length} variables detected. ${status.verification_passed ? 'Verification passed.' : 'Some issues were found — check the warnings below.'}`,
                    }];

                    if (status.preview_url) await fetchPreview(status.preview_url);
                    step = 'review';
                } else if (status.status === 'failed') {
                    stopPolling();
                    error = status.error || 'Conversion failed';
                    step = 'upload';
                }
            } catch {
                // Polling failure — keep trying unless too many failures
            }
        }, 2000);
    }

    // --- Chat refinement ---
    async function handleChatSend() {
        if (!chatInput.trim() || !conversionId || refining) return;

        const instruction = chatInput.trim();
        chatInput = '';
        chatMessages = [...chatMessages, { role: 'user', content: instruction }];
        refining = true;

        try {
            const result = await api.post<ConvertResponse>(
                `/science/templates/conversions/${conversionId}/refine`,
                { instruction },
            );


            templateDownloadUrl = result.template_download_url;
            warnings = result.warnings;
            variablesDetected = result.variables_detected;
            verificationPassed = result.verification_passed;

            if (result.preview_url) await fetchPreview(result.preview_url);
            chatMessages = [...chatMessages, {
                role: 'assistant',
                content: 'Template updated. Check the preview for changes.',
            }];
        } catch (e: unknown) {
            chatMessages = [...chatMessages, {
                role: 'assistant',
                content: `Failed to refine: ${e instanceof Error ? e.message : 'Unknown error'}. Try rephrasing.`,
            }];
        } finally {
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
                `/science/templates/conversions/${conversionId}/reupload`,
                file,
                {},
            );


            templateDownloadUrl = result.template_download_url;
            warnings = result.warnings;
            variablesDetected = result.variables_detected;
            verificationPassed = result.verification_passed;

            if (result.preview_url) await fetchPreview(result.preview_url);
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
                `/science/templates/conversions/${conversionId}/save`,
                {
                    name: saveName,
                    template_type: templateType,
                    description: saveDescription,
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

    function handleClose() {
        if (conversionId && !showSaveDialog) {
            if (!confirm("You'll lose your conversion progress. Are you sure?")) {
                return;
            }
        }
        open = false;
        resetState();
    }

    const missingVarWarnings = $derived(warnings.filter(w => w.type === 'missing_variable'));
    const otherWarnings = $derived(warnings.filter(w => w.type !== 'missing_variable'));
</script>

{#if open}
<div class="fixed inset-0 z-50 flex flex-col bg-background">
    <!-- Header -->
    <div class="flex items-center justify-between border-b border-border px-6 py-3 shrink-0">
        <div class="flex items-center gap-6">
            <h2 class="text-lg font-semibold">Convert Document to Template</h2>
            {#if step === 'review'}
                <span class="text-sm text-muted-foreground">
                    {variablesDetected.length} variables detected
                    {#if !verificationPassed}
                        <span class="text-amber-500 ml-2">Verification issues found</span>
                    {/if}
                </span>
            {/if}
        </div>
        <button
            class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            onclick={handleClose}
            aria-label="Close"
        >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path d="M6 18L18 6M6 6l12 12" />
            </svg>
        </button>
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
                            <button
                                class="flex-1 px-4 py-2 text-sm font-medium rounded-md border transition-colors {templateType === 'SOP'
                                    ? 'border-primary bg-primary/10 text-primary'
                                    : 'border-border hover:border-primary/50'}"
                                onclick={() => (templateType = 'SOP')}
                            >
                                Protocol
                            </button>
                            <button
                                class="flex-1 px-4 py-2 text-sm font-medium rounded-md border transition-colors {templateType === 'BATCH_RECORD'
                                    ? 'border-primary bg-primary/10 text-primary'
                                    : 'border-border hover:border-primary/50'}"
                                onclick={() => (templateType = 'BATCH_RECORD')}
                            >
                                Batch Record
                            </button>
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
                                <p class="text-xs text-muted-foreground mt-1">PDF, DOCX, XLSX, JPEG, PNG (max 20 MB)</p>
                            </div>
                        {/if}
                        <input
                            id="convert-file-input"
                            type="file"
                            class="hidden"
                            accept=".pdf,.docx,.xlsx,.jpg,.jpeg,.png"
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
            <!-- Processing with progress bar -->
            <div class="flex-1 flex items-center justify-center">
                <div class="w-full max-w-md px-8">
                    <!-- Current step label -->
                    <p class="text-sm font-medium text-center mb-4">{progressStep}</p>

                    <!-- Progress bar -->
                    <div class="w-full bg-muted rounded-full h-2.5 mb-3">
                        <div
                            class="bg-primary h-2.5 rounded-full transition-all duration-500 ease-out"
                            style="width: {progressTotal > 0 ? (progressNumber / progressTotal) * 100 : 0}%"
                        ></div>
                    </div>

                    <!-- Step counter + elapsed time -->
                    <div class="flex justify-between text-xs text-muted-foreground mb-6">
                        <span>Step {progressNumber} of {progressTotal}</span>
                        <span>{Math.floor(progressElapsed)}s elapsed</span>
                    </div>

                    <!-- Step breakdown -->
                    <div class="space-y-2">
                        {#each [
                            'Extracting document content...',
                            'Generating template with AI...',
                            'Wrapping into DOCX...',
                            'Verifying template...',
                            'Rendering preview...',
                            'Checking variable coverage...',
                        ] as label, i}
                            <div class="flex items-center gap-2 text-xs {i + 1 < progressNumber ? 'text-foreground' : i + 1 === progressNumber ? 'text-primary font-medium' : 'text-muted-foreground/50'}">
                                {#if i + 1 < progressNumber}
                                    <svg class="w-3.5 h-3.5 text-emerald-500 shrink-0" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>
                                {:else if i + 1 === progressNumber}
                                    <div class="w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full animate-spin shrink-0"></div>
                                {:else}
                                    <div class="w-3.5 h-3.5 rounded-full border border-muted-foreground/30 shrink-0"></div>
                                {/if}
                                <span>{label}</span>
                            </div>
                        {/each}
                    </div>

                    {#if progressElapsed > 90}
                        <p class="text-xs text-amber-500 mt-4 text-center">
                            This is taking longer than usual. The AI model may be slow.
                        </p>
                    {/if}
                </div>
            </div>

        {:else if step === 'review'}
            <!-- Review: split pane -->
            <div class="flex-1 flex overflow-hidden">
                <!-- Left: PDF preview -->
                <div class="flex-1 border-r border-border overflow-hidden flex flex-col">
                    <div class="px-4 py-2 border-b border-border bg-muted/30 text-sm font-medium">
                        Rendered Preview
                    </div>
                    <div class="flex-1 overflow-auto bg-muted/10">
                        {#if previewBlobUrl}
                            <iframe
                                src="{previewBlobUrl}"
                                class="w-full h-full"
                                title="Template Preview"
                            ></iframe>
                        {:else}
                            <div class="flex items-center justify-center h-full text-muted-foreground text-sm">
                                No preview available
                            </div>
                        {/if}
                    </div>
                </div>

                <!-- Right: warnings + chat -->
                <div class="w-[400px] flex flex-col">
                    <!-- Warnings -->
                    {#if warnings.length > 0}
                        <div class="px-4 py-3 border-b border-border space-y-2 max-h-48 overflow-y-auto">
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
                                <div class="px-3 py-2 rounded-lg text-sm bg-muted text-muted-foreground italic">
                                    Updating template...
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

            <!-- Save dialog (inline) -->
            {#if showSaveDialog}
                <div class="fixed inset-0 z-[60] flex items-center justify-center bg-black/50">
                    <div class="bg-background rounded-lg border shadow-lg p-6 w-full max-w-md space-y-4">
                        <h3 class="text-lg font-semibold">Save Template to Library</h3>
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
                    </div>
                </div>
            {/if}
        {/if}
    </div>
    </div>
</div>
{/if}
