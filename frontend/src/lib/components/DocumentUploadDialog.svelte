<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import { api } from '$lib/api';
    import { toast } from 'svelte-sonner';
    import {
        isAllowedFileType,
        isFileSizeValid,
        extractTitleFromFilename,
        formatFileSize,
    } from '$lib/utils/document-utils';

    let { open = $bindable(false), onSuccess }: { open: boolean; onSuccess: () => void } = $props();

    let activeTab = $state<'upload' | 'url'>('upload');
    let uploading = $state(false);
    let error = $state<string | null>(null);

    // Upload tab state
    let selectedFile = $state<File | null>(null);
    let title = $state('');
    let dragOver = $state(false);

    // URL tab state
    let importUrl = $state('');
    let urlTitle = $state('');

    function resetState() {
        selectedFile = null;
        title = '';
        error = null;
        dragOver = false;
        importUrl = '';
        urlTitle = '';
        activeTab = 'upload';
        uploading = false;
    }

    function handleFileSelect(file: File) {
        error = null;
        if (!isAllowedFileType(file.type)) {
            error = `Unsupported file type: ${file.type || 'unknown'}. Accepted: PDF, DOCX, TXT, MD, RTF, JPEG, PNG, HEIC`;
            return;
        }
        if (!isFileSizeValid(file.size)) {
            error = `File too large: ${formatFileSize(file.size)}. Maximum: 50 MB`;
            return;
        }
        selectedFile = file;
        if (!title) {
            title = extractTitleFromFilename(file.name);
        }
    }

    function handleInputChange(e: Event) {
        const input = e.target as HTMLInputElement;
        if (input.files?.[0]) {
            handleFileSelect(input.files[0]);
        }
    }

    function handleDrop(e: DragEvent) {
        e.preventDefault();
        dragOver = false;
        const file = e.dataTransfer?.files?.[0];
        if (file) handleFileSelect(file);
    }

    function handleDragOver(e: DragEvent) {
        e.preventDefault();
        dragOver = true;
    }

    function handleDragLeave() {
        dragOver = false;
    }

    async function handleUpload() {
        if (!selectedFile || !title.trim()) return;
        uploading = true;
        error = null;
        try {
            await api.uploadWithFields('/library/documents', selectedFile, {
                title: title.trim(),
            });
            toast.success('Document uploaded successfully');
            open = false;
            resetState();
            onSuccess();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Upload failed';
        } finally {
            uploading = false;
        }
    }

    async function handleImportUrl() {
        if (!importUrl.trim()) return;
        uploading = true;
        error = null;
        try {
            const body: Record<string, string> = { url: importUrl.trim() };
            if (urlTitle.trim()) body.title = urlTitle.trim();
            await api.post('/library/documents/from-url', body);
            toast.success('Document imported successfully');
            open = false;
            resetState();
            onSuccess();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Import failed';
        } finally {
            uploading = false;
        }
    }
</script>

<Dialog.Root bind:open onOpenChange={(v) => { if (!v) resetState(); }}>
    <Dialog.Content class="sm:max-w-lg">
        <Dialog.Header>
            <Dialog.Title>Add Document</Dialog.Title>
            <Dialog.Description>Upload a file or import from a URL.</Dialog.Description>
        </Dialog.Header>

        <!-- Tab buttons -->
        <div class="flex gap-1 border-b border-border mb-4">
            <Button
                variant="tab"
                size="sm"
                class="h-auto px-4 py-2"
                data-active={activeTab === 'upload'}
                onclick={() => (activeTab = 'upload')}
            >
                Upload File
            </Button>
            <Button
                variant="tab"
                size="sm"
                class="h-auto px-4 py-2"
                data-active={activeTab === 'url'}
                onclick={() => (activeTab = 'url')}
            >
                Import from URL
            </Button>
        </div>

        {#if error}
            <div class="bg-destructive/10 text-destructive text-sm p-3 rounded-md mb-4">
                {error}
            </div>
        {/if}

        {#if activeTab === 'upload'}
            <div class="space-y-4">
                <!-- Drop zone -->
                <div
                    class="border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer
                        {dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'}"
                    ondrop={handleDrop}
                    ondragover={handleDragOver}
                    ondragleave={handleDragLeave}
                    onclick={() => document.getElementById('file-input')?.click()}
                    onkeydown={(e) => e.key === 'Enter' && document.getElementById('file-input')?.click()}
                    role="button"
                    tabindex="0"
                >
                    {#if selectedFile}
                        <div>
                            <p class="font-medium text-sm">{selectedFile.name}</p>
                            <p class="text-xs text-muted-foreground mt-1">{formatFileSize(selectedFile.size)}</p>
                        </div>
                    {:else}
                        <div>
                            <p class="text-sm text-muted-foreground">Drag and drop a file here, or click to browse</p>
                            <p class="text-xs text-muted-foreground mt-1">PDF, DOCX, TXT, MD, RTF, JPEG, PNG, HEIC (max 50 MB)</p>
                        </div>
                    {/if}
                    <input
                        id="file-input"
                        type="file"
                        class="hidden"
                        accept=".pdf,.docx,.txt,.md,.rtf,.jpg,.jpeg,.png,.heic"
                        onchange={handleInputChange}
                    />
                </div>

                <!-- Camera capture (mobile) -->
                <div class="sm:hidden">
                    <label class="block">
                        <span class="text-sm text-muted-foreground">Or take a photo:</span>
                        <input
                            type="file"
                            accept="image/*"
                            capture="environment"
                            class="mt-1 block w-full text-sm file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-primary/10 file:text-primary"
                            onchange={handleInputChange}
                        />
                    </label>
                </div>

                <!-- Title input -->
                <div>
                    <Label for="doc-title">Title</Label>
                    <Input
                        id="doc-title"
                        bind:value={title}
                        placeholder="Document title"
                        maxlength={150}
                        class="mt-1"
                    />
                    <p class="text-xs text-muted-foreground mt-1 text-right">{title.length}/150</p>
                </div>
            </div>

            <Dialog.Footer class="mt-4">
                <Button variant="outline" onclick={() => (open = false)}>Cancel</Button>
                <Button
                    onclick={handleUpload}
                    disabled={!selectedFile || !title.trim() || uploading}
                >
                    {uploading ? 'Uploading...' : 'Upload'}
                </Button>
            </Dialog.Footer>

        {:else}
            <div class="space-y-4">
                <div>
                    <Label for="import-url">URL</Label>
                    <Input
                        id="import-url"
                        type="url"
                        bind:value={importUrl}
                        placeholder="https://..."
                        class="mt-1"
                    />
                </div>

                <div>
                    <Label for="url-title">Title (optional)</Label>
                    <Input
                        id="url-title"
                        bind:value={urlTitle}
                        placeholder="Leave blank to use page title"
                        class="mt-1"
                    />
                </div>

                <p class="text-xs text-muted-foreground">
                    Only import content you have permission to use. The source URL will be stored for attribution.
                </p>
            </div>

            <Dialog.Footer class="mt-4">
                <Button variant="outline" onclick={() => (open = false)}>Cancel</Button>
                <Button
                    onclick={handleImportUrl}
                    disabled={!importUrl.trim() || uploading}
                >
                    {uploading ? 'Importing...' : 'Import'}
                </Button>
            </Dialog.Footer>
        {/if}
    </Dialog.Content>
</Dialog.Root>
