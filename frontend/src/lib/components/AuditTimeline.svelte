<script lang="ts">
    /**
     * Shared audit timeline component used by:
     * - RunHistory (History tab on run detail page)
     * - ActivityTab (Activity tab on project detail page)
     *
     * Renders a vertical timeline with avatars, action descriptions,
     * timestamps, and structured detail lines.
     */
    import { Button } from '$lib/components/ui/button';

    export interface AuditEntry {
        id: string;
        action: string;
        actor_name: string;
        actor_email?: string;
        entity_type?: string;
        entity_name?: string;
        created_at: string;
        changes?: Record<string, any>;
    }

    export interface DetailLine {
        label: string;
        value: string;
        oldValue?: string;
    }

    interface Props {
        entries: AuditEntry[];
        total?: number;
        offset?: number;
        limit?: number;
        loading?: boolean;
        getActionLabel?: (entry: AuditEntry) => string;
        getDetails?: (entry: AuditEntry) => DetailLine[];
        showEntityBadge?: boolean;
        onPageChange?: (offset: number) => void;
    }

    let {
        entries,
        total = 0,
        offset = 0,
        limit = 50,
        loading = false,
        getActionLabel = defaultActionLabel,
        getDetails = () => [],
        showEntityBadge = false,
        onPageChange,
    }: Props = $props();

    let container: HTMLDivElement;

    const hasPagination = $derived(total > limit);
    const showingFrom = $derived(offset + 1);
    const showingTo = $derived(Math.min(offset + limit, total));
    const canPrev = $derived(offset > 0);
    const canNext = $derived(offset + limit < total);

    function handlePageChange(newOffset: number) {
        if (onPageChange) {
            window.scrollTo({ top: 0 });
            onPageChange(newOffset);
        }
    }

    // --- Avatar helpers ---

    function initials(name: string | null, email: string | null): string {
        if (name && name !== 'Unknown') {
            const parts = name.trim().split(/\s+/);
            if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
            return parts[0].substring(0, 2).toUpperCase();
        }
        if (email) return email.substring(0, 2).toUpperCase();
        return '??';
    }

    const avatarColors = [
        '#2563eb', '#059669', '#7c3aed', '#d97706',
        '#e11d48', '#0891b2', '#4f46e5', '#0d9488',
    ];

    function avatarBg(name: string | null, email: string | null): string {
        const str = name || email || 'System';
        let hash = 0;
        for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
        return avatarColors[Math.abs(hash) % avatarColors.length];
    }

    // --- Formatting helpers ---

    function formatDate(dateStr: string): string {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffMin = Math.floor(diffMs / 60000);
        const diffHr = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHr / 24);

        if (diffMin < 1) return 'Just now';
        if (diffMin < 60) return `${diffMin}m ago`;
        if (diffHr < 24) return `${diffHr}h ago`;
        if (diffDay === 1) return 'Yesterday';
        if (diffDay < 7) return `${diffDay}d ago`;
        const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' };
        if (date.getFullYear() < now.getFullYear()) opts.year = 'numeric';
        return date.toLocaleDateString('en-US', opts);
    }

    function defaultActionLabel(entry: AuditEntry): string {
        const labels: Record<string, string> = {
            CREATE: 'created',
            UPDATE: 'updated',
            DELETE: 'deleted',
            ARCHIVE: 'archived',
            STEP_COMPLETE: 'completed step in',
            STEP_UNCOMPLETE: 'uncompleted step in',
            STEP_EDIT: 'edited',
            NOTE_ADDED: 'added a note to',
            ATTACHMENT_UPLOADED: 'uploaded a file to',
            ATTACHMENT_DELETED: 'removed a file from',
            ATTACHMENT_RESTORED: 'restored a file in',
        };
        return labels[entry.action] ?? entry.action.toLowerCase();
    }

    function entityBadgeClasses(entityType: string): string {
        switch (entityType) {
            case 'Project': return 'bg-purple-50 text-purple-600 border-purple-200';
            case 'Protocol': return 'bg-sky-50 text-sky-600 border-sky-200';
            case 'Run': return 'bg-amber-50 text-amber-600 border-amber-200';
            default: return 'bg-slate-50 text-slate-600 border-slate-200';
        }
    }
</script>

{#if entries.length === 0}
    <div class="flex flex-col items-center justify-center py-16 text-center gap-2">
        <div class="w-12 h-12 text-slate-300 mb-2">
            <svg class="w-full h-full" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>
        </div>
        <p class="text-[15px] font-semibold text-slate-600">No activity yet</p>
        <p class="text-[13px] text-slate-400">Changes will appear here.</p>
    </div>
{:else}
    <div class="relative" bind:this={container}>
        {#each entries as entry, i}
            {@const details = getDetails(entry)}
            <div class="relative flex gap-4 pb-8 last:pb-0">
                <!-- Avatar + vertical line -->
                <div class="flex flex-col items-center flex-shrink-0">
                    <div
                        class="w-9 h-9 rounded-full flex items-center justify-center text-white text-xs font-semibold shadow-sm"
                        style="background-color: {avatarBg(entry.actor_name, entry.actor_email ?? null)}; min-width: 2.25rem; min-height: 2.25rem;"
                    >
                        {initials(entry.actor_name, entry.actor_email ?? null)}
                    </div>
                    {#if i < entries.length - 1}
                        <div class="w-px flex-1 bg-slate-200 mt-2"></div>
                    {/if}
                </div>

                <!-- Content -->
                <div class="pt-1 pb-2 min-w-0">
                    <p class="text-sm text-slate-600">
                        <span class="font-semibold text-slate-800">{entry.actor_name || entry.actor_email || 'System'}</span>
                        {' '}
                        <span>{getActionLabel(entry)}</span>
                        {#if showEntityBadge && entry.entity_type}
                            {' '}
                            <span class="inline-flex items-baseline text-xs font-medium px-2 py-0.5 rounded-full border {entityBadgeClasses(entry.entity_type)}">{entry.entity_type}</span>
                        {/if}
                        {#if entry.entity_name}
                            {' '}
                            <span class="font-medium text-slate-800">{entry.entity_name}</span>
                        {/if}
                    </p>
                    <p class="mt-1 text-xs text-slate-400">
                        {formatDate(entry.created_at)}
                        {#if entry.changes?.run_status}
                            <span class="ml-1.5 px-1.5 py-0.5 bg-slate-100 rounded text-[10px] font-medium text-slate-500">
                                {entry.changes.run_status}
                            </span>
                        {/if}
                    </p>

                    {#if details.length > 0}
                        <div class="mt-2 space-y-1">
                            {#each details as detail}
                                <div class="text-xs flex items-baseline gap-1.5">
                                    <span class="text-slate-400 font-medium">{detail.label}:</span>
                                    {#if detail.oldValue !== undefined}
                                        <span class="line-through text-slate-700">{detail.oldValue}</span>
                                        <span class="text-slate-400">&rarr;</span>
                                    {/if}
                                    <span class="text-slate-700">{detail.value}</span>
                                </div>
                            {/each}
                        </div>
                    {/if}
                </div>
            </div>
        {/each}
    </div>

    {#if hasPagination && onPageChange}
        <div class="flex justify-between items-center pt-6 mt-6 border-t border-slate-100">
            <span class="text-[13px] text-slate-400 font-medium">
                Showing {showingFrom}–{showingTo} of {total}
            </span>
            <div class="flex gap-2">
                <Button
                    variant="outline"
                    size="sm"
                    class="h-auto px-3 py-1.5 text-xs font-medium text-slate-600 border-slate-200 hover:bg-slate-50 hover:border-slate-300"
                    disabled={!canPrev || loading}
                    onclick={() => handlePageChange(Math.max(0, offset - limit))}
                >
                    Previous
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    class="h-auto px-3 py-1.5 text-xs font-medium text-slate-600 border-slate-200 hover:bg-slate-50 hover:border-slate-300"
                    disabled={!canNext || loading}
                    onclick={() => handlePageChange(offset + limit)}
                >
                    Next
                </Button>
            </div>
        </div>
    {/if}
{/if}
