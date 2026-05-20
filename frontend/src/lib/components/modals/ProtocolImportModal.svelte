<script lang="ts">
    import { goto } from '$app/navigation';
    import { api } from '$lib/api';
    import { getCurrentOrg, getUser } from '$lib/auth.svelte';
    import { toast } from 'svelte-sonner';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import { Textarea } from '$lib/components/ui/textarea';
    import FullScreenModal from '$lib/components/ui/FullScreenModal.svelte';
    import ConfirmDialog from '$lib/components/ui/confirm-dialog.svelte';
    import {
        isAllowedFileType,
        isFileSizeValid,
        extractTitleFromFilename,
        formatFileSize,
    } from '$lib/utils/document-utils';
    import type { ProtocolImportProposal, StepProposal } from '$lib/schemas/protocolImport';
    import ProtocolEditor from '../../../routes/[org]/protocols/[slug]/+page.svelte';

    interface Props {
        open: boolean;
        preselectedProjectId?: string;
        onSuccess?: (protocolId: string) => void;
    }

    let { open = $bindable(false), preselectedProjectId, onSuccess }: Props = $props();

    // --- State ---
    let activeTab = $state<'import' | 'editor'>('import');
    let step = $state<'upload' | 'processing' | 'chat'>('upload');

    // Upload state
    let selectedFile = $state<File | null>(null);
    let dragOver = $state(false);
    let uploading = $state(false);
    let error = $state<string | null>(null);

    // Proposal state
    let proposal = $state<ProtocolImportProposal | null>(null);
    let currentGraph = $state<Record<string, unknown> | null>(null);

    // Chat refinement state
    let chatMessages = $state<Array<{ role: 'user' | 'assistant'; content: string }>>([]);
    let chatInput = $state('');
    let refining = $state(false);

    // Project/org scope
    let projects = $state<any[]>([]);
    let selectedProjectId = $state<string>(preselectedProjectId || '');
    let isOrgScoped = $state(false);
    let isOrgAdmin = $state(false);

    // Protocol name/description (editable)
    let protocolName = $state('');
    let protocolDescription = $state('');

    // Finalization
    let creating = $state(false);

    // Editor reference
    let editorComponent: any;

    // Load projects and check admin status on open
    $effect(() => {
        if (open) {
            loadProjects();
            checkOrgAdmin();
            if (preselectedProjectId) {
                selectedProjectId = preselectedProjectId;
            }
        }
    });

    async function loadProjects() {
        try {
            projects = await api.get('/projects') as any[];
        } catch {
            projects = [];
        }
    }

    async function checkOrgAdmin() {
        const user = getUser();
        const org = getCurrentOrg();
        if (user && org) {
            try {
                const members = await api.get(`/iam/organizations/${org.id}/members`) as any[];
                const me = members.find((m: any) => m.user_id === user.id);
                isOrgAdmin = me?.role === 'admin';
            } catch {
                isOrgAdmin = false;
            }
        }
    }

    function resetState() {
        activeTab = 'import';
        step = 'upload';
        selectedFile = null;
        dragOver = false;
        uploading = false;
        error = null;
        proposal = null;
        currentGraph = null;
        chatMessages = [];
        chatInput = '';
        refining = false;
        protocolName = '';
        protocolDescription = '';
        creating = false;
        if (!preselectedProjectId) {
            selectedProjectId = '';
        }
        isOrgScoped = false;
    }

    // --- File handling ---
    const allowedTypes = new Set([
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'image/jpeg',
        'image/png',
        'image/tiff',
    ]);

    function handleFileSelect(file: File) {
        error = null;
        if (!allowedTypes.has(file.type)) {
            error = `Unsupported file type. Accepted: PDF, DOCX, JPEG, PNG, TIFF`;
            return;
        }
        if (!isFileSizeValid(file.size)) {
            error = `File too large: ${formatFileSize(file.size)}. Maximum: 50 MB`;
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

    // --- Upload & analyze ---
    async function handleUpload() {
        if (!selectedFile) return;
        step = 'processing';
        uploading = true;
        error = null;

        try {
            const result = await api.uploadFile<ProtocolImportProposal>(
                '/protocols/import',
                selectedFile,
            );
            proposal = result;
            protocolName = result.protocol_name;
            protocolDescription = result.protocol_description;

            // Build initial graph from proposal for the editor
            currentGraph = await buildGraphFromProposal(result);

            chatMessages = [{
                role: 'assistant',
                content: `Analyzed "${selectedFile.name}" and found ${result.steps.length} steps (${result.matched_count} matched, ${result.unmatched_count} new). You can refine this protocol by chatting below, or switch to the Protocol Editor tab to make manual adjustments.`,
            }];

            step = 'chat';
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Upload failed';
            step = 'upload';
        } finally {
            uploading = false;
        }
    }

    async function buildGraphFromProposal(p: ProtocolImportProposal): Promise<Record<string, unknown>> {
        // Use the finalize-import endpoint logic to build a preview graph
        // For now, build a simple graph client-side matching the backend's build_import_graph
        const nodes: any[] = [];
        const edges: any[] = [];

        const roleNames: string[] = [];
        for (const s of p.steps) {
            if (s.role && !roleNames.includes(s.role)) roleNames.push(s.role);
        }

        const roleColors = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#06b6d4', '#f97316'];
        const laneMap: Record<string, string> = {};

        for (let i = 0; i < roleNames.length; i++) {
            const laneId = `lane-${crypto.randomUUID()}`;
            laneMap[roleNames[i]] = laneId;
            nodes.push({
                id: laneId,
                type: 'swimLane',
                zIndex: -1,
                position: { x: 0, y: i * 220 },
                data: {
                    label: roleNames[i],
                    color: roleColors[i % roleColors.length],
                    roleId: laneId,
                    orientation: 'horizontal',
                },
                style: 'width: 800px; height: 200px;',
            });
        }

        const laneCounters: Record<string, number> = {};
        for (const r of roleNames) laneCounters[r] = 0;
        let noRoleCounter = 0;

        // Create processStart nodes for each role chain
        const lastNodePerChain: Record<string, string> = {};
        for (const roleName of roleNames) {
            const psId = `ps-${crypto.randomUUID()}`;
            const idx = laneCounters[roleName]++;
            nodes.push({
                id: psId,
                type: 'processStart',
                zIndex: 1,
                position: { x: 100 + idx * 300, y: 30 },
                parentId: laneMap[roleName],
                width: 220,
                data: { label: roleName, description: '' },
            });
            lastNodePerChain[roleName] = psId;
        }
        // processStart for ungrouped steps
        const hasUngrouped = p.steps.some(s => !s.role);
        if (hasUngrouped) {
            const psId = `ps-${crypto.randomUUID()}`;
            nodes.push({
                id: psId,
                type: 'processStart',
                zIndex: 1,
                position: { x: 100 + noRoleCounter * 300, y: 200 },
                width: 220,
                data: { label: 'Process', description: '' },
            });
            noRoleCounter++;
            lastNodePerChain['__ungrouped__'] = psId;
        }

        const opNodes: any[] = [];
        for (const s of p.steps) {
            const nodeId = `node-${crypto.randomUUID()}`;
            let position: { x: number; y: number };
            let parentId: string | undefined;
            const chainKey = (s.role && laneMap[s.role]) ? s.role : '__ungrouped__';

            if (s.role && laneMap[s.role]) {
                const idx = laneCounters[s.role]++;
                position = { x: 100 + idx * 300, y: 30 };
                parentId = laneMap[s.role];
            } else {
                position = { x: 100 + noRoleCounter * 300, y: 200 };
                noRoleCounter++;
            }

            const node: any = {
                id: nodeId,
                type: 'unitOp',
                position,
                data: {
                    label: s.name,
                    unitOpId: s.matched_unit_op_id,
                    category: s.category,
                    description: s.description,
                    duration_min: s.duration_min,
                    params: s.params,
                    paramSchema: s.param_schema,
                },
            };
            if (parentId) node.parentId = parentId;
            opNodes.push(node);

            // Edge from last node in this chain
            if (lastNodePerChain[chainKey]) {
                edges.push({
                    id: `edge-${crypto.randomUUID()}`,
                    source: lastNodePerChain[chainKey],
                    target: nodeId,
                });
            }
            lastNodePerChain[chainKey] = nodeId;
        }

        nodes.push(...opNodes);

        return {
            nodes,
            edges,
            layout: 'horizontal',
            handleOrientation: 'horizontal',
            timeEnabled: false,
            startTime: '08:00',
            pixelsPerHour: 150,
            _metadata: { source: 'protocol_import' },
        };
    }

    // --- Chat refinement ---
    async function handleChatSend() {
        if (!chatInput.trim() || !currentGraph || refining) return;

        const instruction = chatInput.trim();
        chatInput = '';
        chatMessages = [...chatMessages, { role: 'user', content: instruction }];
        refining = true;

        try {
            const updatedGraph = await api.post('/protocols/refine', {
                graph: currentGraph,
                instruction,
            }) as Record<string, unknown>;

            currentGraph = updatedGraph;

            // Update the editor if visible
            if (editorComponent?.updateGraph) {
                editorComponent.updateGraph(updatedGraph);
            }

            chatMessages = [...chatMessages, {
                role: 'assistant',
                content: `Updated the protocol based on your instruction. Check the Protocol Editor tab to see the changes.`,
            }];
        } catch (e: unknown) {
            chatMessages = [...chatMessages, {
                role: 'assistant',
                content: `Failed to refine: ${e instanceof Error ? e.message : 'Unknown error'}. Try rephrasing your instruction.`,
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

    // --- Finalize ---
    async function handleCreate() {
        if (!proposal || creating) return;
        if (!selectedProjectId && !isOrgScoped) {
            error = 'Please select a project or choose organization scope';
            return;
        }

        creating = true;
        error = null;

        try {
            const body: any = {
                protocol_name: protocolName || proposal.protocol_name,
                protocol_description: protocolDescription || proposal.protocol_description,
                steps: proposal.steps,
                source_filename: proposal.source_filename,
            };

            if (isOrgScoped) {
                const org = getCurrentOrg();
                body.organization_id = org?.id;
            } else {
                body.project_id = selectedProjectId;
            }

            const result: any = await api.post('/protocols/finalize-import', body);
            toast.success(`Protocol "${result.name}" created`);
            open = false;
            resetState();

            if (onSuccess) {
                onSuccess(result.id);
            } else {
                goto(`/protocols/${result.id}`);
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to create protocol';
        } finally {
            creating = false;
        }
    }

    function handleGraphChange(graph: Record<string, unknown>) {
        currentGraph = graph;
    }

    // Prevent accidental close
    let discardConfirmOpen = $state(false);

    function handleOpenChange(isOpen: boolean) {
        if (!isOpen && (proposal || uploading)) {
            discardConfirmOpen = true;
            return;
        }
        if (!isOpen) resetState();
        open = isOpen;
    }

    function confirmDiscardImport() {
        discardConfirmOpen = false;
        resetState();
        open = false;
    }
</script>

<FullScreenModal bind:open title="Import Protocol" onClose={() => handleOpenChange(false)}>
    {#snippet headerActions()}
        <div class="flex gap-1">
            <Button
                variant={activeTab === 'import' ? 'default' : 'ghost'}
                size="sm"
                onclick={() => (activeTab = 'import')}
            >
                Import
            </Button>
            <Button
                variant={activeTab === 'editor' ? 'default' : 'ghost'}
                size="sm"
                onclick={() => (activeTab = 'editor')}
                disabled={!currentGraph}
            >
                Protocol Editor
            </Button>
        </div>
    {/snippet}
            {#if activeTab === 'import'}
                <div class="h-full flex flex-col">
                    {#if step === 'upload'}
                        <!-- Upload step -->
                        <div class="flex-1 flex items-center justify-center p-8">
                            <div class="max-w-lg w-full space-y-6">
                                <div class="text-center mb-6">
                                    <h2 class="text-xl font-semibold mb-2">Upload a Protocol Document</h2>
                                    <p class="text-sm text-muted-foreground">Upload a PDF, DOCX, or photo of your protocol. The AI will extract the procedure and create a digital protocol.</p>
                                </div>

                                {#if error}
                                    <div class="bg-destructive/10 text-destructive text-sm p-3 rounded-md">{error}</div>
                                {/if}

                                <!-- Drop zone -->
                                <div
                                    class="border-2 border-dashed rounded-lg p-10 text-center transition-colors cursor-pointer
                                        {dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'}"
                                    ondrop={handleDrop}
                                    ondragover={(e) => { e.preventDefault(); dragOver = true; }}
                                    ondragleave={() => (dragOver = false)}
                                    onclick={() => document.getElementById('sop-file-input')?.click()}
                                    onkeydown={(e) => e.key === 'Enter' && document.getElementById('sop-file-input')?.click()}
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
                                            <p class="text-xs text-muted-foreground mt-1">PDF, DOCX, JPEG, PNG, TIFF (max 50 MB)</p>
                                        </div>
                                    {/if}
                                    <input
                                        id="sop-file-input"
                                        type="file"
                                        class="hidden"
                                        accept=".pdf,.docx,.jpg,.jpeg,.png,.tiff,.tif"
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

                                <Button
                                    onclick={handleUpload}
                                    disabled={!selectedFile || uploading}
                                    class="w-full"
                                >
                                    {uploading ? 'Analyzing...' : 'Analyze Protocol'}
                                </Button>
                            </div>
                        </div>

                    {:else if step === 'processing'}
                        <!-- Processing spinner -->
                        <div class="flex-1 flex items-center justify-center">
                            <div class="text-center">
                                <div class="w-12 h-12 border-4 border-primary/20 border-t-primary rounded-full animate-spin mx-auto mb-4"></div>
                                <p class="text-sm font-medium">Analyzing your protocol...</p>
                                <p class="text-xs text-muted-foreground mt-1">This usually takes 10-30 seconds</p>
                            </div>
                        </div>

                    {:else if step === 'chat'}
                        <!-- Chat + config -->
                        <div class="h-full flex flex-col">
                            <!-- Chat messages -->
                            <div class="flex-1 overflow-y-auto p-4 space-y-3">
                                {#each chatMessages as msg}
                                    <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
                                        <div class="max-w-[80%] px-4 py-2.5 rounded-lg text-sm {msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground'}">
                                            {msg.content}
                                        </div>
                                    </div>
                                {/each}
                                {#if refining}
                                    <div class="flex justify-start">
                                        <div class="px-4 py-2.5 rounded-lg text-sm bg-muted text-muted-foreground italic">
                                            Refining protocol...
                                        </div>
                                    </div>
                                {/if}
                            </div>

                            <!-- Chat input -->
                            <div class="border-t border-border p-4 space-y-4">
                                <div class="flex gap-2">
                                    <textarea
                                        bind:value={chatInput}
                                        onkeydown={handleChatKeydown}
                                        placeholder="Tell the AI how to refine the protocol..."
                                        class="flex-1 px-3 py-2 border border-border rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring"
                                        rows="2"
                                        disabled={refining}
                                    ></textarea>
                                    <Button
                                        onclick={handleChatSend}
                                        disabled={!chatInput.trim() || refining}
                                        class="self-end"
                                    >
                                        Send
                                    </Button>
                                </div>

                                {#if error}
                                    <div class="bg-destructive/10 text-destructive text-sm p-3 rounded-md">{error}</div>
                                {/if}

                                <!-- Protocol config -->
                                <div class="grid grid-cols-2 gap-4">
                                    <div>
                                        <Label for="proto-name">Protocol Name</Label>
                                        <Input id="proto-name" bind:value={protocolName} class="mt-1" />
                                    </div>
                                    <div>
                                        <Label for="proto-project">Project</Label>
                                        {#if isOrgScoped}
                                            <Input value="Organization Protocol" disabled class="mt-1" />
                                        {:else}
                                            <select
                                                id="proto-project"
                                                bind:value={selectedProjectId}
                                                class="mt-1 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                                            >
                                                <option value="">Select a project</option>
                                                {#each projects as project}
                                                    <option value={project.id}>{project.name}</option>
                                                {/each}
                                            </select>
                                        {/if}
                                    </div>
                                </div>

                                {#if isOrgAdmin}
                                    <label class="flex items-center gap-2 text-sm">
                                        <input
                                            type="checkbox"
                                            bind:checked={isOrgScoped}
                                            class="rounded border-border"
                                        />
                                        Organization Protocol (available across all projects)
                                    </label>
                                {/if}

                                <Button
                                    onclick={handleCreate}
                                    disabled={creating || (!selectedProjectId && !isOrgScoped)}
                                    class="w-full"
                                >
                                    {creating ? 'Creating...' : 'Create Protocol'}
                                </Button>
                            </div>
                        </div>
                    {/if}
                </div>

            {:else if activeTab === 'editor'}
                <!-- Protocol Editor tab -->
                {#if currentGraph}
                    <div class="h-full">
                        <ProtocolEditor
                            bind:this={editorComponent}
                            initialGraph={currentGraph}
                            embedded={true}
                            onGraphChange={handleGraphChange}
                        />
                    </div>
                {:else}
                    <div class="flex-1 flex items-center justify-center text-muted-foreground">
                        <p>Upload a protocol document first to preview it here.</p>
                    </div>
                {/if}
            {/if}
</FullScreenModal>

<ConfirmDialog
    bind:open={discardConfirmOpen}
    title="Discard import?"
    message="You'll lose your import progress. Are you sure?"
    confirmLabel="Discard"
    confirmVariant="danger"
    onConfirm={confirmDiscardImport}
    onCancel={() => (discardConfirmOpen = false)}
/>
