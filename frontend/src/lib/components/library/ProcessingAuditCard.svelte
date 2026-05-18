<script lang="ts">
    import { onMount } from 'svelte';
    import { z } from 'zod';
    import { api } from '$lib/api';
    import {
        Card,
        CardContent,
        CardHeader,
        CardTitle,
        CardDescription,
    } from '$lib/components/ui/card';
    import { Badge } from '$lib/components/ui/badge';
    import { Button } from '$lib/components/ui/button';
    import { ChevronDown, ChevronRight, History } from 'lucide-svelte';

    interface Props {
        documentId: string;
        /**
         * Refresh trigger — bump from parent to refetch after a retry. The
         * card refetches whenever this value changes.
         */
        refreshKey?: number;
    }

    let { documentId, refreshKey = 0 }: Props = $props();

    const ProcessingJobAuditSchema = z
        .object({
            id: z.string(),
            job_type: z.string(),
            status: z.string(),
            started_at: z.string().nullable(),
            completed_at: z.string().nullable(),
            heartbeat_at: z.string().nullable(),
            attempts: z.number(),
            error_message: z.string().nullable(),
            stage: z.string().nullable(),
            stage_label: z.string().nullable(),
            current: z.number().nullable(),
            total: z.number().nullable(),
            percent: z.number().nullable(),
        })
        .passthrough();
    type ProcessingJobAudit = z.infer<typeof ProcessingJobAuditSchema>;

    const ProcessingAuditResponseSchema = z
        .object({
            document_id: z.string(),
            document_status: z.string(),
            chunk_count: z.number(),
            embedded_count: z.number(),
            jobs: z.array(ProcessingJobAuditSchema),
        })
        .passthrough();

    let jobs = $state<ProcessingJobAudit[]>([]);
    let chunkCount = $state(0);
    let embeddedCount = $state(0);
    let loading = $state(false);
    let error = $state<string | null>(null);
    let expanded = $state(false);

    async function load() {
        loading = true;
        error = null;
        try {
            const res = await api.get(
                `/library/documents/${documentId}/processing`,
                { schema: ProcessingAuditResponseSchema },
            );
            jobs = res.jobs;
            chunkCount = res.chunk_count;
            embeddedCount = res.embedded_count;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load audit';
        } finally {
            loading = false;
        }
    }

    onMount(load);
    // Refetch when parent bumps refreshKey
    $effect(() => {
        refreshKey;
        if (documentId) load();
    });

    function formatTimestamp(ts: string | null): string {
        if (!ts) return '—';
        return new Date(ts).toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function jobStatusBadge(status: string): {
        variant: 'default' | 'destructive' | 'secondary' | 'outline';
        cls: string;
    } {
        switch (status) {
            case 'COMPLETED':
                return {
                    variant: 'outline',
                    cls: 'border-accent/40 bg-accent/10 text-accent',
                };
            case 'RUNNING':
                return {
                    variant: 'outline',
                    cls: 'border-primary/40 bg-primary/5 text-primary',
                };
            case 'FAILED':
                return { variant: 'destructive', cls: '' };
            case 'PENDING':
                return { variant: 'outline', cls: 'text-muted-foreground' };
            default:
                return { variant: 'outline', cls: '' };
        }
    }

    function jobTypeLabel(t: string): string {
        switch (t) {
            case 'document_extract':
            case 'document_process':
                return 'Extract & chunk';
            case 'document_embed':
                return 'Embed chunks';
            case 'document_enrich':
                return 'Enrich (LLM)';
            default:
                return t.replace(/_/g, ' ');
        }
    }
</script>

<Card>
    <CardHeader class="cursor-pointer" onclick={() => (expanded = !expanded)}>
        <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
                {#if expanded}
                    <ChevronDown class="h-4 w-4 text-muted-foreground" />
                {:else}
                    <ChevronRight class="h-4 w-4 text-muted-foreground" />
                {/if}
                <History class="h-4 w-4 text-muted-foreground" />
                <CardTitle class="text-base">Processing history</CardTitle>
            </div>
            <div class="text-xs text-muted-foreground">
                {embeddedCount}/{chunkCount} embedded · {jobs.length} job{jobs.length === 1 ? '' : 's'}
            </div>
        </div>
        {#if !expanded}
            <CardDescription class="ml-6">
                Click to view the full background job log for this document.
            </CardDescription>
        {/if}
    </CardHeader>
    {#if expanded}
        <CardContent>
            {#if loading}
                <p class="text-sm text-muted-foreground">Loading...</p>
            {:else if error}
                <p class="text-sm text-destructive">Error: {error}</p>
            {:else if jobs.length === 0}
                <p class="text-sm text-muted-foreground">No background jobs recorded for this document.</p>
            {:else}
                <ul class="divide-y divide-border">
                    {#each jobs as job (job.id)}
                        {@const sb = jobStatusBadge(job.status)}
                        <li class="py-3 first:pt-0 last:pb-0 space-y-1">
                            <div class="flex items-center justify-between gap-3 flex-wrap">
                                <div class="flex items-center gap-2 min-w-0">
                                    <Badge variant={sb.variant} class={sb.cls}>{job.status}</Badge>
                                    <span class="font-medium text-sm truncate">{jobTypeLabel(job.job_type)}</span>
                                    {#if job.attempts > 1}
                                        <span class="text-xs text-muted-foreground">attempt {job.attempts}</span>
                                    {/if}
                                </div>
                                <div class="text-xs text-muted-foreground whitespace-nowrap">
                                    {formatTimestamp(job.started_at)}
                                    {#if job.completed_at}
                                        → {formatTimestamp(job.completed_at)}
                                    {/if}
                                </div>
                            </div>
                            {#if job.status === 'RUNNING' && job.stage_label}
                                <div class="ml-1 text-xs text-primary">
                                    {job.stage_label}
                                    {#if job.percent !== null}({job.percent}%){/if}
                                </div>
                            {/if}
                            {#if job.error_message}
                                <div class="ml-1 text-xs text-destructive break-words">
                                    {job.error_message}
                                </div>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {/if}
            <div class="mt-3 flex justify-end">
                <Button size="sm" variant="ghost" onclick={load} disabled={loading}>
                    Refresh
                </Button>
            </div>
        </CardContent>
    {/if}
</Card>
