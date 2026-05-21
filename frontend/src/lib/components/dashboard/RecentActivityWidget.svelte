<script lang="ts">
    import { timeAgo } from '$lib/utils';
    import { EmptyState } from '$lib/components/ui/empty-state';

    interface ActivityItem {
        id: string;
        action: string;
        entity_type: string;
        entity_id: string;
        entity_name: string | null;
        actor_name: string | null;
        changes: Record<string, any>;
        created_at: string;
    }
    interface Props {
        activity: ActivityItem[];
        cap?: number;
    }
    let { activity, cap = 8 }: Props = $props();

    const shown = $derived(activity.slice(0, cap));

    function activityVerb(item: ActivityItem): string {
        const t = item.entity_type;
        const a = item.action;
        if (t === 'Run' && a === 'UPDATE') {
            const s = item.changes?.status;
            if (s === 'ACTIVE') return 'started run';
            if (s === 'COMPLETED') return 'completed run';
            if (s === 'EDITED') return 'edited run';
            return 'updated run';
        }
        if (t === 'Run' && a === 'CREATE') return 'created run';
        if (t === 'Protocol' && a === 'CREATE') return 'created protocol';
        if (t === 'Protocol' && a === 'UPDATE') return 'updated protocol';
        if (t === 'Project' && a === 'CREATE') return 'created project';
        if (t === 'Project' && a === 'UPDATE') return 'updated project';
        if (a === 'STEP_COMPLETE') return 'completed a step in';
        if (a === 'STEP_UNCOMPLETE') return 'uncompleted a step in';
        if (a === 'STEP_EDIT') return 'edited a step in';
        if (t === 'RunRoleAssignment' && a === 'CREATE') return 'assigned a role in';
        if (t === 'RunRoleAssignment' && a === 'DELETE') return 'removed a role in';
        return `${a.toLowerCase()} ${t.toLowerCase()}`;
    }

    function activityLink(item: ActivityItem): string {
        if (item.entity_type === 'Run' || item.entity_type === 'RunRoleAssignment') {
            return `/runs/${item.entity_id}`;
        }
        if (item.entity_type === 'Protocol') return `/protocols/${item.entity_id}`;
        if (item.entity_type === 'Project') return `/projects/${item.entity_id}`;
        return '#';
    }

    function actorInitials(name: string | null): string {
        if (!name) return '?';
        const parts = name.trim().split(/\s+/);
        if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
        return name[0].toUpperCase();
    }

    const actorColors = [
        'bg-primary/15 text-primary',
        'bg-accent/15 text-accent',
        'bg-emerald-100 text-emerald-700',
        'bg-violet-100 text-violet-700',
        'bg-rose-100 text-rose-700',
    ];
    function actorColor(name: string | null): string {
        if (!name) return actorColors[0];
        let hash = 0;
        for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
        return actorColors[Math.abs(hash) % actorColors.length];
    }
</script>

<div class="card-warm overflow-hidden rounded-xl">
    <h3 class="border-b border-border/50 px-4 py-3 text-xs font-bold uppercase tracking-widest text-muted-foreground">
        Recent Activity
    </h3>
    {#if shown.length === 0}
        <EmptyState title="No recent activity" />
    {:else}
        <div class="divide-y divide-border/50">
            {#each shown as item (item.id)}
                <a
                    href={activityLink(item)}
                    class="flex gap-3 p-3.5 transition-colors duration-150 hover:bg-muted/30"
                >
                    <div class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg {actorColor(item.actor_name)}">
                        <span class="text-[10px] font-bold">{actorInitials(item.actor_name)}</span>
                    </div>
                    <div class="min-w-0 flex-1">
                        <p class="text-xs leading-relaxed text-foreground/80">
                            <span class="font-semibold text-foreground">{item.actor_name || 'Someone'}</span>
                            {' '}{activityVerb(item)}{' '}
                            <span class="font-semibold text-foreground">{item.entity_name || ''}</span>
                        </p>
                        <p class="mt-0.5 text-[10px] tabular-nums text-muted-foreground">{timeAgo(item.created_at)}</p>
                    </div>
                </a>
            {/each}
        </div>
    {/if}
</div>
