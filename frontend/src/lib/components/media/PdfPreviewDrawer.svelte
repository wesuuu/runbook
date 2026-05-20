<script lang="ts">
    import { onDestroy, onMount } from "svelte";
    import { api } from "$lib/api";
    import { toast } from "$lib/toast";
    import { DocumentTemplateListSchema, type DocumentTemplate } from "$lib/schemas/templates";
    import { Button } from "$lib/components/ui/button";
    import { X } from "lucide-svelte";

    let {
        protocolId,
        protocolName = "Protocol",
        projectId,
        mode = "protocol",
        runId = null,
        runName = null,
        graph = null,
        onClose,
    }: {
        protocolId: string;
        protocolName: string;
        projectId: string;
        mode: "protocol" | "run";
        runId?: string | null;
        runName?: string | null;
        graph?: Record<string, any> | null;
        onClose: () => void;
    } = $props();

    // Tab state
    let activeTab = $state<"sop" | "batch-record">("sop");

    // Template state
    let templates = $state<DocumentTemplate[]>([]);
    let selectedTemplateId = $state<string | null>(null);
    let protocolSopTemplateId = $state<string | null>(null);
    let protocolBrTemplateId = $state<string | null>(null);
    let settingTemplate = $state(false);

    // Preview state
    let blobUrl = $state<string | null>(null);
    let previewLoading = $state(false);
    let previewError = $state<string | null>(null);

    const protocolTemplateId = $derived(
        activeTab === "sop" ? protocolSopTemplateId : protocolBrTemplateId,
    );

    const isNonDefault = $derived(
        selectedTemplateId !== null && selectedTemplateId !== protocolTemplateId,
    );

    onMount(async () => {
        await loadProtocolTemplates();
        await loadTemplates();
        loadPreview();
    });

    async function loadProtocolTemplates() {
        try {
            const proto: any = await api.get(`/protocols/${protocolId}`);
            protocolSopTemplateId = proto.sop_template_id || null;
            protocolBrTemplateId = proto.batch_record_template_id || null;
            selectedTemplateId =
                activeTab === "sop" ? protocolSopTemplateId : protocolBrTemplateId;
        } catch {
            /* use whatever templates list provides */
        }
    }

    async function loadTemplates() {
        try {
            const type = activeTab === "sop" ? "SOP" : "BATCH_RECORD";
            templates = await api.get(`/templates?template_type=${type}`, {
                schema: DocumentTemplateListSchema,
            });
            // If no selectedTemplateId yet, use the first template
            if (!selectedTemplateId && templates.length) {
                selectedTemplateId = templates[0].id;
            }
        } catch {
            /* fallback to empty */
        }
    }

    function buildEndpoint(): string {
        const params = new URLSearchParams({ disposition: "inline" });
        if (selectedTemplateId) {
            params.set("template_id", selectedTemplateId);
        }

        if (activeTab === "sop") {
            return mode === "run" && runId
                ? `/runs/${runId}/pdf/sop?${params}`
                : `/protocols/${protocolId}/pdf/sop?${params}`;
        }
        return mode === "run" && runId
            ? `/runs/${runId}/pdf/batch-record?${params}`
            : `/protocols/${protocolId}/pdf/batch-record?${params}`;
    }

    async function loadPreview() {
        const endpoint = buildEndpoint();
        previewLoading = true;
        previewError = null;

        if (blobUrl) {
            URL.revokeObjectURL(blobUrl);
            blobUrl = null;
        }

        try {
            if (graph && mode === "protocol") {
                blobUrl = await api.postBlobUrl(endpoint, { graph });
            } else {
                blobUrl = await api.fetchBlobUrl(endpoint);
            }
        } catch (e: unknown) {
            previewError = e instanceof Error ? e.message : "Failed to load preview";
        } finally {
            previewLoading = false;
        }
    }

    async function handleTabChange(tab: "sop" | "batch-record") {
        activeTab = tab;
        selectedTemplateId = tab === "sop" ? protocolSopTemplateId : protocolBrTemplateId;
        await loadTemplates();
        loadPreview();
    }

    function handleTemplateChange() {
        loadPreview();
    }

    async function useThisTemplate() {
        if (!selectedTemplateId) return;
        settingTemplate = true;
        try {
            const field =
                activeTab === "sop" ? "sop_template_id" : "batch_record_template_id";
            await api.put(`/protocols/${protocolId}`, {
                [field]: selectedTemplateId,
            });
            if (activeTab === "sop") {
                protocolSopTemplateId = selectedTemplateId;
            } else {
                protocolBrTemplateId = selectedTemplateId;
            }
            toast.success("Protocol template updated (new version created)");
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : "Failed to update template");
        } finally {
            settingTemplate = false;
        }
    }

    async function downloadCurrentPdf() {
        const params = new URLSearchParams({ disposition: "attachment" });
        if (selectedTemplateId) {
            params.set("template_id", selectedTemplateId);
        }
        let endpoint: string;
        let filename: string;

        if (activeTab === "sop") {
            if (mode === "run" && runId) {
                endpoint = `/runs/${runId}/pdf/sop?${params}`;
                filename = `SOP_${(runName || "Run").replace(/\s+/g, "_")}.pdf`;
            } else {
                endpoint = `/protocols/${protocolId}/pdf/sop?${params}`;
                filename = `SOP_Preview_${protocolName.replace(/\s+/g, "_")}.pdf`;
            }
        } else {
            if (mode === "run" && runId) {
                endpoint = `/runs/${runId}/pdf/batch-record?${params}`;
                filename = `BatchRecord_${(runName || "Run").replace(/\s+/g, "_")}_BLANK.pdf`;
            } else {
                endpoint = `/protocols/${protocolId}/pdf/batch-record?${params}`;
                filename = `BatchRecord_Preview_${protocolName.replace(/\s+/g, "_")}.pdf`;
            }
        }

        if (graph && mode === "protocol") {
            api.postDownloadBlob(endpoint, { graph }, filename);
        } else {
            api.downloadBlob(endpoint, filename);
        }
    }

    function handleOverlayClick(e: MouseEvent) {
        if (e.target === e.currentTarget) onClose();
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Escape") onClose();
    }

    onDestroy(() => {
        if (blobUrl) URL.revokeObjectURL(blobUrl);
    });
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="modal-backdrop" onclick={handleOverlayClick}>
    <div class="modal" data-tour="pdf-preview">
        <!-- Header -->
        <div class="modal-header">
            <div class="header-left">
                <h3>PDF Preview</h3>
                <div class="tab-bar">
                    <Button
                        variant="ghost"
                        size="sm"
                        class="h-auto px-3.5 py-1.5 text-xs font-semibold {activeTab === 'sop' ? 'bg-slate-100 text-slate-900 border border-slate-200 hover:bg-slate-100' : 'text-slate-400'}"
                        onclick={() => handleTabChange("sop")}
                    >
                        SOP
                    </Button>
                    <Button
                        variant="ghost"
                        size="sm"
                        class="h-auto px-3.5 py-1.5 text-xs font-semibold {activeTab === 'batch-record' ? 'bg-slate-100 text-slate-900 border border-slate-200 hover:bg-slate-100' : 'text-slate-400'}"
                        onclick={() => handleTabChange("batch-record")}
                    >
                        Batch Record
                    </Button>
                </div>
            </div>
            <Button variant="ghost" size="icon-sm" onclick={onClose} aria-label="Close">
                <X class="size-4" />
            </Button>
        </div>

        <!-- Template selector bar -->
        <div class="template-bar">
            <label class="template-label" for="tpl-select">Template</label>
            <select
                id="tpl-select"
                class="template-select"
                bind:value={selectedTemplateId}
                onchange={handleTemplateChange}
            >
                {#each templates as t}
                    <option value={t.id}>
                        {t.name}{t.is_system ? " (System)" : ""}
                    </option>
                {/each}
            </select>
            {#if isNonDefault}
                <Button
                    size="sm"
                    onclick={useThisTemplate}
                    disabled={settingTemplate}
                >
                    {settingTemplate ? "Saving..." : "Use This Template"}
                </Button>
            {/if}
        </div>

        <!-- Preview area (full width) -->
        <div class="preview-area">
            {#if previewLoading}
                <div class="preview-placeholder">
                    <div class="spinner"></div>
                    <span>Loading preview...</span>
                </div>
            {:else if previewError}
                <div class="preview-placeholder error">
                    <span>Failed to load preview</span>
                    <p class="error-detail">{previewError}</p>
                    <Button variant="outline" size="sm" onclick={loadPreview}>Retry</Button>
                </div>
            {:else if blobUrl}
                <iframe src={blobUrl} title="PDF Preview" class="preview-iframe"></iframe>
            {:else}
                <div class="preview-placeholder">
                    <span>Preview will appear here</span>
                </div>
            {/if}
        </div>

        <!-- Footer -->
        <div class="modal-footer">
            <Button variant="outline" onclick={onClose}>Close</Button>
            <Button onclick={downloadCurrentPdf}>Download</Button>
        </div>
    </div>
</div>

<style>
    .modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.4);
        z-index: 50;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 24px;
        cursor: pointer;
    }

    .modal-backdrop > .modal {
        cursor: default;
    }

    .modal {
        width: 90vw;
        max-width: 1000px;
        height: 85vh;
        max-height: 800px;
        background: white;
        border-radius: 12px;
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    .modal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 14px 20px;
        border-bottom: 1px solid hsl(240, 5.9%, 90%);
        flex-shrink: 0;
    }

    .header-left {
        display: flex;
        align-items: center;
        gap: 20px;
    }

    .modal-header h3 {
        font-size: 15px;
        font-weight: 700;
        color: #0f172a;
        margin: 0;
        white-space: nowrap;
    }

    .tab-bar {
        display: flex;
        gap: 2px;
    }

    /* Template selector bar */
    .template-bar {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 20px;
        border-bottom: 1px solid hsl(240, 5.9%, 90%);
        background: #fafbfc;
        flex-shrink: 0;
    }

    .template-label {
        font-size: 11px;
        font-weight: 600;
        color: #64748b;
        white-space: nowrap;
    }

    .template-select {
        flex: 1;
        padding: 6px 10px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        font-size: 12px;
        font-family: inherit;
        color: #334155;
        background: white;
        cursor: pointer;
        max-width: 400px;
    }

    .template-select:focus {
        outline: none;
        border-color: hsl(173, 58%, 39%);
        box-shadow: 0 0 0 2px hsla(173, 58%, 39%, 0.1);
    }

    /* Preview area */
    .preview-area {
        flex: 1;
        min-height: 0;
        background: #f1f5f9;
        position: relative;
    }

    .preview-iframe {
        width: 100%;
        height: 100%;
        border: none;
    }

    .preview-placeholder {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
        gap: 8px;
        color: #94a3b8;
        font-size: 13px;
    }

    .preview-placeholder.error {
        color: #ef4444;
    }

    .error-detail {
        font-size: 11px;
        color: #94a3b8;
        margin: 0;
    }

    /* Footer */
    .modal-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 20px;
        border-top: 1px solid hsl(240, 5.9%, 90%);
        flex-shrink: 0;
    }

    .spinner {
        width: 24px;
        height: 24px;
        border: 3px solid #e2e8f0;
        border-top-color: hsl(173, 58%, 39%);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
</style>
