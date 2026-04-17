<script lang="ts">
    import { timeAgo } from '$lib/utils';
    import { X } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';

    interface Version {
        id: string;
        version_number: number;
        name: string;
        change_summary: string | null;
        created_by_name: string | null;
        created_at: string;
    }

    let {
        versions = [],
        currentVersion = 0,
        loading = false,
        onRevert,
        onClose,
    }: {
        versions: Version[];
        currentVersion: number;
        loading: boolean;
        onRevert: (versionNumber: number) => void;
        onClose: () => void;
    } = $props();

</script>

<div class="drawer-overlay" onclick={onClose} role="presentation"></div>
<aside class="drawer">
    <div class="drawer-header">
        <h3>Version History</h3>
        <Button variant="ghost" size="icon-sm" onclick={onClose} aria-label="Close">
            <X class="size-4" />
        </Button>
    </div>

    <div class="drawer-body">
        {#if loading}
            <div class="loading">Loading versions...</div>
        {:else if versions.length === 0}
            <div class="empty">
                <p class="empty-title">No versions yet</p>
                <p class="empty-desc">Versions are created automatically each time you save.</p>
            </div>
        {:else}
            <div class="version-list">
                {#each versions as version}
                    <div
                        class="version-item"
                        class:current={version.version_number === currentVersion}
                    >
                        <div class="version-header">
                            <span class="version-badge">v{version.version_number}</span>
                            {#if version.version_number === currentVersion}
                                <span class="current-badge">Current</span>
                            {/if}
                        </div>
                        <div class="version-meta">
                            {#if version.change_summary}
                                <p class="change-summary">{version.change_summary}</p>
                            {/if}
                            <p class="version-info">
                                {#if version.created_by_name}
                                    <span class="author">{version.created_by_name}</span>
                                    &middot;
                                {/if}
                                <span class="timestamp">{timeAgo(version.created_at)}</span>
                            </p>
                        </div>
                        {#if version.version_number !== currentVersion}
                            <Button
                                variant="outline"
                                size="sm"
                                class="w-full h-auto py-1.5 text-[11px] font-semibold text-slate-600 hover:border-teal-600 hover:text-teal-700"
                                onclick={() => onRevert(version.version_number)}
                            >
                                Revert to this version
                            </Button>
                        {/if}
                    </div>
                {/each}
            </div>
        {/if}
    </div>
</aside>

<style>
    .drawer-overlay {
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.15);
        z-index: 40;
    }

    .drawer {
        position: fixed;
        top: 57px;
        right: 0;
        bottom: 0;
        width: 340px;
        background: white;
        border-left: 1px solid hsl(240, 5.9%, 90%);
        box-shadow: -4px 0 20px rgba(0, 0, 0, 0.08);
        z-index: 50;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    .drawer-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 20px;
        border-bottom: 1px solid hsl(240, 5.9%, 90%);
    }

    .drawer-header h3 {
        font-size: 15px;
        font-weight: 700;
        color: #0f172a;
        margin: 0;
    }

    .drawer-body {
        flex: 1;
        overflow-y: auto;
        padding: 12px;
    }

    .loading {
        padding: 40px 20px;
        text-align: center;
        color: #94a3b8;
        font-size: 13px;
    }

    .empty {
        padding: 40px 20px;
        text-align: center;
    }

    .empty-title {
        font-size: 14px;
        font-weight: 600;
        color: #475569;
        margin: 0 0 4px;
    }

    .empty-desc {
        font-size: 12px;
        color: #94a3b8;
        margin: 0;
    }

    .version-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .version-item {
        padding: 12px 14px;
        border: 1px solid #f1f5f9;
        border-radius: 8px;
        background: white;
        transition: border-color 0.15s;
    }

    .version-item:hover {
        border-color: #e2e8f0;
    }

    .version-item.current {
        border-color: hsl(173, 58%, 39%);
        background: hsl(173, 58%, 97%);
    }

    .version-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 6px;
    }

    .version-badge {
        font-size: 12px;
        font-weight: 700;
        color: #334155;
        background: #f1f5f9;
        padding: 2px 8px;
        border-radius: 4px;
        font-family: monospace;
    }

    .current-badge {
        font-size: 10px;
        font-weight: 600;
        color: hsl(173, 58%, 39%);
        background: hsl(173, 58%, 92%);
        padding: 2px 8px;
        border-radius: 4px;
    }

    .version-meta {
        margin-bottom: 6px;
    }

    .change-summary {
        font-size: 12px;
        font-weight: 500;
        color: #475569;
        margin: 0 0 4px;
    }

    .version-info {
        font-size: 11px;
        color: #94a3b8;
        margin: 0;
    }

    .author {
        font-weight: 500;
    }

</style>
