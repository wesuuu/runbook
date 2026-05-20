<script lang="ts">
    import { api } from '$lib/api';
    import AuditTimeline from '$lib/components/analytics/AuditTimeline.svelte';
    import type { AuditEntry, DetailLine } from '$lib/components/analytics/AuditTimeline.svelte';

    let { runId }: { runId: string } = $props();

    let entries = $state<AuditEntry[]>([]);
    let total = $state(0);
    let offset = $state(0);
    let loading = $state(true);
    let error = $state<string | null>(null);
    const limit = 50;

    $effect(() => {
        if (runId) {
            loadAuditLog(0);
        }
    });

    async function loadAuditLog(newOffset: number) {
        loading = true;
        error = null;
        try {
            const params = new URLSearchParams({
                limit: String(limit),
                offset: String(newOffset),
            });
            const resp = await api.get<{ items: AuditEntry[]; total: number; offset: number }>(`/runs/${runId}/audit-log?${params}`);
            entries = (resp.items ?? []).filter((e) => {
                if (e.action !== 'UPDATE') return true;
                const keys = Object.keys(e.changes ?? {}).filter(
                    (k) => k !== 'execution_data' && k !== 'graph'
                );
                return keys.length > 0;
            });
            total = resp.total ?? 0;
            offset = resp.offset ?? newOffset;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load history';
        } finally {
            loading = false;
        }
    }

    function getActionLabel(entry: AuditEntry): string {
        const labels: Record<string, string> = {
            CREATE: 'created this run',
            UPDATE: 'updated this run',
            STEP_COMPLETE: 'completed a step',
            STEP_UNCOMPLETE: 'uncompleted a step',
            STEP_EDIT: 'edited a step',
            OVERRIDE_SET: 'set overrides at creation',
            OVERRIDE_EDIT: 'edited overrides while planned',
            NOTE_ADDED: 'added a note',
            ATTACHMENT_UPLOADED: 'uploaded a file',
            ATTACHMENT_DELETED: 'removed a file',
            ATTACHMENT_RESTORED: 'restored a file',
        };
        return labels[entry.action] ?? entry.action.toLowerCase();
    }

    function getDetails(entry: AuditEntry): DetailLine[] {
        const c = entry.changes ?? {};
        const lines: DetailLine[] = [];

        switch (entry.action) {
            case 'CREATE':
                if (c.name) lines.push({ label: 'Name', value: c.name });
                break;

            case 'UPDATE':
                if (c.status) lines.push({ label: 'Status', value: c.status });
                if (c.name) lines.push({ label: 'Name', value: c.name });
                break;

            case 'STEP_COMPLETE':
                if (c.step_name || c.step_id) lines.push({ label: 'Step', value: c.step_name ?? c.step_id });
                if (c.results && typeof c.results === 'object') {
                    for (const [key, val] of Object.entries(c.results)) {
                        lines.push({ label: key.replace(/_/g, ' '), value: String(val) });
                    }
                }
                break;

            case 'STEP_UNCOMPLETE':
                if (c.step_name || c.step_id) lines.push({ label: 'Step', value: c.step_name ?? c.step_id });
                break;

            case 'STEP_EDIT':
                if (c.step_name) lines.push({ label: 'Step', value: c.step_name });
                if (c.field_label || c.field) {
                    lines.push({
                        label: c.field_label ?? c.field,
                        value: String(c.new_value ?? ''),
                        oldValue: String(c.old_value ?? ''),
                    });
                }
                break;

            case 'OVERRIDE_SET':
            case 'OVERRIDE_EDIT':
                if (c.step_name) lines.push({ label: 'Step', value: c.step_name });
                if (c.field_label || c.field) {
                    lines.push({
                        label: c.field_label ?? c.field,
                        value: String(c.new_value ?? ''),
                        oldValue: String(c.old_value ?? ''),
                    });
                }
                break;

            case 'NOTE_ADDED':
                if (c.content) lines.push({ label: 'Content', value: c.content });
                if (c.flags?.length) lines.push({ label: 'Flags', value: c.flags.join(', ') });
                break;

            case 'ATTACHMENT_UPLOADED':
                if (c.filename) lines.push({ label: 'File', value: c.filename });
                if (c.content_type) lines.push({ label: 'Type', value: c.content_type });
                if (c.step_id) lines.push({ label: 'Step', value: c.step_id });
                else lines.push({ label: 'Scope', value: 'Run-level' });
                break;

            case 'ATTACHMENT_DELETED':
            case 'ATTACHMENT_RESTORED':
                if (c.filename) lines.push({ label: 'File', value: c.filename });
                break;
        }

        return lines;
    }
</script>

<div class="max-w-3xl mx-auto py-6">
    {#if loading}
        <div class="text-center py-12 text-muted-foreground">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-border mx-auto mb-3"></div>
            Loading history...
        </div>
    {:else if error}
        <div class="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
        </div>
    {:else}
        <AuditTimeline
            {entries}
            {total}
            {offset}
            {limit}
            {loading}
            {getActionLabel}
            {getDetails}
            onPageChange={(newOffset) => loadAuditLog(newOffset)}
        />
    {/if}
</div>
