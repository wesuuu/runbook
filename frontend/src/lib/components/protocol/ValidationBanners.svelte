<script lang="ts">
    interface BranchError {
        sourceNodeLabel: string;
        targetNodeLabels: string[];
        duplicateLane: string | null;
    }

    interface ProcessStartError {
        processStartCount: number;
        componentFirstNodeLabel: string;
    }

    interface Props {
        protocolStatus: string;
        previewingVersion: number | null;
        versionNumber: number;
        branchValidationErrors: BranchError[];
        processStartValidationErrors: ProcessStartError[];
        onUnarchive: () => void;
        onRestorePreviewedVersion: () => void;
        onExitPreview: () => void;
    }

    let {
        protocolStatus,
        previewingVersion,
        versionNumber,
        branchValidationErrors,
        processStartValidationErrors,
        onUnarchive,
        onRestorePreviewedVersion,
        onExitPreview,
    }: Props = $props();
</script>

<!-- Archive banner -->
{#if protocolStatus === 'ARCHIVED'}
    <div class="archive-banner">
        <span>This protocol is archived and cannot be edited.</span>
        <button class="preview-banner-btn restore" onclick={onUnarchive}>
            Unarchive
        </button>
    </div>
{/if}

<!-- Version preview banner -->
{#if previewingVersion !== null}
    <div class="preview-banner">
        <span>Viewing <strong>v{previewingVersion}</strong> of {versionNumber} (read-only preview)</span>
        <div class="preview-banner-actions">
            <button class="preview-banner-btn restore" onclick={onRestorePreviewedVersion}>
                Restore this version
            </button>
            <button class="preview-banner-btn exit" onclick={onExitPreview}>
                Back to current
            </button>
        </div>
    </div>
{/if}

<!-- Branch validation banner -->
{#if branchValidationErrors.length > 0}
    <div class="validation-banner">
        <span class="validation-icon">&#x26A0;</span>
        <div class="validation-content">
            {#each branchValidationErrors as err}
                <div class="validation-item">
                    <strong>{err.sourceNodeLabel}</strong> branches to
                    {err.targetNodeLabels.join(" & ")} in
                    {#if err.duplicateLane === null}
                        <em>no swimlane</em>
                    {:else}
                        the <em>same swimlane</em>
                    {/if}
                    — move each branch target to a different role.
                </div>
            {/each}
        </div>
    </div>
{/if}

<!-- Process Start validation banner -->
{#if processStartValidationErrors.length > 0}
    <div class="validation-banner process-start-warning">
        <span class="validation-icon">&#x26A0;</span>
        <div class="validation-content">
            {#each processStartValidationErrors as err}
                <div class="validation-item">
                    {#if err.processStartCount === 0}
                        Chain containing <strong>{err.componentFirstNodeLabel}</strong> has no Process Start node — add one to define a section header in the PDF.
                    {:else}
                        Chain containing <strong>{err.componentFirstNodeLabel}</strong> has {err.processStartCount} Process Start nodes — each chain should have exactly one.
                    {/if}
                </div>
            {/each}
        </div>
    </div>
{/if}

<style>
    .preview-banner {
        position: absolute;
        top: 56px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 10;
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 16px;
        background: #eff6ff;
        border: 1px solid #3b82f6;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(59, 130, 246, 0.15);
        font-size: 12px;
        color: #1e40af;
        white-space: nowrap;
    }

    .preview-banner-actions {
        display: flex;
        gap: 6px;
    }

    .preview-banner-btn {
        padding: 4px 10px;
        border-radius: 5px;
        border: none;
        font-size: 11px;
        font-weight: 600;
        cursor: pointer;
        font-family: inherit;
        transition: all 0.15s;
    }

    .archive-banner {
        position: absolute;
        top: 56px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 10;
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 16px;
        background: #f8fafc;
        border: 1px solid #94a3b8;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(100, 116, 139, 0.15);
        font-size: 12px;
        color: #475569;
        white-space: nowrap;
    }

    .preview-banner-btn.restore {
        background: hsl(173, 58%, 39%);
        color: white;
    }

    .preview-banner-btn.restore:hover {
        background: hsl(173, 58%, 33%);
    }

    .preview-banner-btn.exit {
        background: white;
        color: #475569;
        border: 1px solid #e2e8f0;
    }

    .preview-banner-btn.exit:hover {
        background: #f8fafc;
    }

    .validation-banner {
        position: absolute;
        top: 56px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 10;
        display: flex;
        align-items: flex-start;
        gap: 8px;
        padding: 8px 14px;
        background: #fffbeb;
        border: 1px solid #f59e0b;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(245, 158, 11, 0.15);
        max-width: 520px;
    }

    .validation-icon {
        font-size: 16px;
        line-height: 1.4;
        flex-shrink: 0;
    }

    .validation-content {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .validation-item {
        font-size: 12px;
        color: #92400e;
        line-height: 1.4;
    }

    .validation-item strong {
        font-weight: 700;
    }

    .validation-banner.process-start-warning {
        top: 108px;
    }

    .validation-item em {
        font-style: italic;
    }
</style>
