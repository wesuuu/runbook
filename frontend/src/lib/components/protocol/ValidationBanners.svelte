<script lang="ts">
    import { Button } from "$lib/components/ui/button";

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
        latestDraftVersion: number | null;
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
        latestDraftVersion,
        branchValidationErrors,
        processStartValidationErrors,
        onUnarchive,
        onRestorePreviewedVersion,
        onExitPreview,
    }: Props = $props();

    const isViewingDraft = $derived(
        previewingVersion !== null
            && latestDraftVersion !== null
            && previewingVersion === latestDraftVersion,
    );
</script>

<!-- Archive banner -->
{#if protocolStatus === 'ARCHIVED'}
    <div class="archive-banner">
        <span>This protocol is archived and cannot be edited.</span>
        <Button size="sm" onclick={onUnarchive}>Unarchive</Button>
    </div>
{/if}

<!-- Version preview banner -->
{#if previewingVersion !== null}
    <div class="preview-banner" class:preview-banner-draft={isViewingDraft}>
        {#if isViewingDraft}
            <span>Editing unpublished <strong>draft v{previewingVersion}</strong> — published v{versionNumber} is unchanged until you publish</span>
            <div class="preview-banner-actions">
                <Button size="sm" variant="outline" onclick={onExitPreview}>Back to v{versionNumber}</Button>
            </div>
        {:else}
            <span>Viewing <strong>v{previewingVersion}</strong> of {versionNumber} (read-only preview)</span>
            <div class="preview-banner-actions">
                <Button size="sm" onclick={onRestorePreviewedVersion}>Restore this version</Button>
                <Button size="sm" variant="outline" onclick={onExitPreview}>Back to current</Button>
            </div>
        {/if}
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
                    {err.targetNodeLabels.join(" & ")} —
                    {#if err.duplicateLane === null}
                        at least one branch has <em>no role assigned</em>.
                    {:else}
                        two branches share the <em>same role</em>.
                    {/if}
                    Assign distinct roles, or enable time mode and stagger them.
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

    .preview-banner.preview-banner-draft {
        background: #fffbeb;
        border-color: #f59e0b;
        color: #92400e;
        box-shadow: 0 2px 8px rgba(245, 158, 11, 0.15);
    }

    .preview-banner-actions {
        display: flex;
        gap: 6px;
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
