<script lang="ts">
    import { api } from '$lib/api';
    import { API_BASE } from '$lib/config';
    import { getToken } from '$lib/auth.svelte';
    import { toast } from '$lib/toast';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import * as Dialog from '$lib/components/ui/dialog';

    let {
        open = $bindable(false),
        onSuccess,
    }: {
        open?: boolean;
        onSuccess: () => void;
    } = $props();

    // Step 1 state
    let selectedFile = $state<File | null>(null);
    let name = $state('');
    let description = $state('');
    let templateType = $state<'SOP' | 'BATCH_RECORD'>('SOP');
    let setAsDefault = $state(false);
    let dragOver = $state(false);
    let error = $state<string | null>(null);

    // Step 2 state
    let step = $state<1 | 2>(1);
    let previewUrl = $state<string | null>(null);
    let recognizedVars = $state<string[]>([]);
    let unrecognizedVars = $state<string[]>([]);
    let previewing = $state(false);
    let uploading = $state(false);

    const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

    function handleFileSelect(file: File) {
        error = null;
        if (file.type !== DOCX_MIME) {
            error = 'Only .docx files are allowed';
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            error = 'File exceeds 10MB limit';
            return;
        }
        selectedFile = file;
        if (!name) {
            name = file.name.replace(/\.docx$/i, '').replace(/[_-]/g, ' ');
        }
    }

    function handleDrop(e: DragEvent) {
        e.preventDefault();
        dragOver = false;
        const file = e.dataTransfer?.files?.[0];
        if (file) handleFileSelect(file);
    }

    async function preview() {
        if (!selectedFile) return;
        previewing = true;
        error = null;
        try {
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('template_type', templateType);

            const headers: HeadersInit = {};
            const token = getToken();
            if (token) headers['Authorization'] = `Bearer ${token}`;

            const resp = await fetch(`${API_BASE}/templates/preview`, {
                method: 'POST',
                headers,
                body: formData,
            });
            if (!resp.ok) {
                const body = await resp.json().catch(() => ({}));
                throw new Error(body.detail || 'Preview failed');
            }

            recognizedVars = JSON.parse(
                resp.headers.get('X-Recognized-Variables') || '[]',
            );
            unrecognizedVars = JSON.parse(
                resp.headers.get('X-Unrecognized-Variables') || '[]',
            );

            const blob = await resp.blob();
            if (previewUrl) URL.revokeObjectURL(previewUrl);
            previewUrl = URL.createObjectURL(blob);
            step = 2;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Preview failed';
        } finally {
            previewing = false;
        }
    }

    async function upload() {
        if (!selectedFile) return;
        uploading = true;
        error = null;
        try {
            await api.uploadWithFields('/templates', selectedFile, {
                name: name.trim(),
                template_type: templateType,
                description: description.trim(),
                set_as_default: String(setAsDefault),
            });
            toast.success('Template uploaded successfully');
            onSuccess();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Upload failed';
        } finally {
            uploading = false;
        }
    }

    function goBack() {
        step = 1;
        if (previewUrl) {
            URL.revokeObjectURL(previewUrl);
            previewUrl = null;
        }
    }

    $effect(() => {
        return () => {
            if (previewUrl) URL.revokeObjectURL(previewUrl);
        };
    });
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="w-full max-w-5xl max-h-[85vh] p-0 flex flex-col">
        <!-- Header -->
        <div class="flex items-center justify-between px-6 py-4 border-b">
            <Dialog.Title class="text-lg font-semibold">
                {step === 1 ? 'Upload Template' : 'Preview Template'}
            </Dialog.Title>
        </div>

        <!-- Body -->
        <div class="flex-1 overflow-auto p-6">
            {#if step === 1}
                <!-- Step 1: File + Metadata -->
                <div class="max-w-lg mx-auto space-y-4">
                    <!-- Drag-drop zone -->
                    <!-- svelte-ignore a11y_no_static_element_interactions -->
                    <div
                        class="border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer
                            {dragOver
                            ? 'border-primary bg-primary/5'
                            : 'border-border hover:border-primary/50'}"
                        ondrop={handleDrop}
                        ondragover={(e) => {
                            e.preventDefault();
                            dragOver = true;
                        }}
                        ondragleave={() => (dragOver = false)}
                        onclick={() => document.getElementById('tpl-file-input')?.click()}
                        onkeydown={(e) =>
                            e.key === 'Enter' &&
                            document.getElementById('tpl-file-input')?.click()}
                        role="button"
                        tabindex="0"
                    >
                        {#if selectedFile}
                            <p class="font-medium text-sm">{selectedFile.name}</p>
                            <p class="text-xs text-muted-foreground mt-1">
                                {(selectedFile.size / 1024).toFixed(0)} KB
                            </p>
                        {:else}
                            <p class="text-sm text-muted-foreground">
                                Drag and drop a .docx file here, or click to browse
                            </p>
                            <p class="text-xs text-muted-foreground mt-1">Max 10 MB</p>
                        {/if}
                        <input
                            id="tpl-file-input"
                            type="file"
                            class="hidden"
                            accept=".docx"
                            onchange={(e) => {
                                const target = e.currentTarget as HTMLInputElement;
                                const file = target.files?.[0];
                                if (file) handleFileSelect(file);
                            }}
                        />
                    </div>

                    <!-- Name -->
                    <div>
                        <Label for="tpl-name">Template Name</Label>
                        <Input
                            id="tpl-name"
                            bind:value={name}
                            placeholder="e.g., Our Lab SOP Format"
                        />
                    </div>

                    <!-- Type -->
                    <div>
                        <Label for="tpl-type">Template Type</Label>
                        <select
                            id="tpl-type"
                            class="w-full border rounded-md px-3 py-2 text-sm bg-background"
                            bind:value={templateType}
                        >
                            <option value="SOP">SOP</option>
                            <option value="BATCH_RECORD">Batch Record</option>
                        </select>
                    </div>

                    <!-- Description -->
                    <div>
                        <Label for="tpl-desc">Description (optional)</Label>
                        <Input
                            id="tpl-desc"
                            bind:value={description}
                            placeholder="Brief description of this template..."
                        />
                    </div>

                    <!-- Set as default -->
                    <label class="flex items-center gap-2 text-sm cursor-pointer">
                        <input type="checkbox" bind:checked={setAsDefault} class="rounded" />
                        Set as default for {templateType === 'SOP' ? 'SOP' : 'Batch Record'} exports
                    </label>

                    {#if error}
                        <p class="text-sm text-destructive">{error}</p>
                    {/if}
                </div>
            {:else}
                <!-- Step 2: Preview + Variables -->
                <div class="flex gap-4 h-[60vh]">
                    <!-- PDF Preview -->
                    <div class="flex-1 border rounded-lg overflow-hidden bg-muted/30">
                        {#if previewUrl}
                            <iframe
                                src={previewUrl}
                                class="w-full h-full"
                                title="Template Preview"
                            ></iframe>
                        {/if}
                    </div>
                    <!-- Variable Report -->
                    <div class="w-64 shrink-0 border rounded-lg p-4 overflow-auto">
                        <h3 class="text-sm font-semibold mb-3">Variables Found</h3>
                        {#if recognizedVars.length}
                            <div class="mb-4">
                                <p class="text-xs font-medium text-green-600 mb-1">
                                    Recognized ({recognizedVars.length})
                                </p>
                                {#each recognizedVars as v}
                                    <div class="flex items-center gap-1.5 text-xs py-0.5">
                                        <span class="text-green-500">✓</span>
                                        <code class="text-muted-foreground">{v}</code>
                                    </div>
                                {/each}
                            </div>
                        {/if}
                        {#if unrecognizedVars.length}
                            <div>
                                <p class="text-xs font-medium text-amber-600 mb-1">
                                    Unrecognized ({unrecognizedVars.length})
                                </p>
                                {#each unrecognizedVars as v}
                                    <div class="flex items-center gap-1.5 text-xs py-0.5">
                                        <span class="text-amber-500">⚠</span>
                                        <code class="text-muted-foreground">{v}</code>
                                    </div>
                                {/each}
                            </div>
                        {/if}
                        {#if !recognizedVars.length && !unrecognizedVars.length}
                            <p class="text-xs text-muted-foreground">No template variables found.</p>
                        {/if}
                    </div>
                </div>
            {/if}
        </div>

        <!-- Footer -->
        <div class="flex items-center justify-between px-6 py-4 border-t">
            {#if step === 1}
                <Button variant="outline" onclick={() => (open = false)}>Cancel</Button>
                <Button onclick={preview} disabled={!selectedFile || !name.trim() || previewing}>
                    {previewing ? 'Generating Preview...' : 'Preview'}
                </Button>
            {:else}
                <Button variant="outline" onclick={goBack}>Back</Button>
                <div class="flex gap-2">
                    {#if error}
                        <p class="text-sm text-destructive self-center mr-2">{error}</p>
                    {/if}
                    <Button onclick={upload} disabled={uploading}>
                        {uploading ? 'Uploading...' : 'Upload Template'}
                    </Button>
                </div>
            {/if}
        </div>
    </Dialog.Content>
</Dialog.Root>
