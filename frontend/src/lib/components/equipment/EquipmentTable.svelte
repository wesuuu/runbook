<script lang="ts">
    import type { Equipment } from '$lib/schemas/science';

    interface Props {
        rows: Equipment[];
        canManage: boolean;
        onEdit: (row: Equipment) => void;
        onArchive: (row: Equipment) => void;
    }
    let { rows, canManage, onEdit, onArchive }: Props = $props();

    function calPill(due: string | null | undefined): { cls: string; text: string } {
        if (!due) return { cls: 'cal-na', text: '—' };
        const days = Math.floor((new Date(due).getTime() - Date.now()) / 86_400_000);
        if (days < 0) return { cls: 'cal-expired', text: `⚠ Expired ${Math.abs(days)}d` };
        if (days < 30) return { cls: 'cal-warn', text: `⏰ ${days}d` };
        return { cls: 'cal-ok', text: `✓ ${due}` };
    }
</script>

<table class="equipment-table w-full">
    <thead>
        <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Room · Bench</th>
            <th>Status</th>
            <th>Calibration</th>
            <th>Tags</th>
            <th></th>
        </tr>
    </thead>
    <tbody>
        {#each rows as r (r.id)}
            {@const pill = calPill(r.next_calibration_date)}
            <tr
                class="cursor-pointer hover:bg-muted/50 transition-all duration-150"
                onclick={() => onEdit(r)}
            >
                <td>
                    <div class="font-medium">{r.name}</div>
                    {#if r.serial_number}
                        <div class="text-xs font-mono text-muted-foreground">
                            SN: {r.serial_number}
                        </div>
                    {/if}
                </td>
                <td>{r.equipment_type ?? '—'}</td>
                <td>
                    <div>{r.room ?? '—'}</div>
                    {#if r.location}
                        <div class="text-xs text-muted-foreground">{r.location}</div>
                    {/if}
                </td>
                <td>{r.status}</td>
                <td>
                    <span class="cal-pill {pill.cls}">{pill.text}</span>
                </td>
                <td>
                    {#each r.tags as t (t)}
                        <span class="tag-chip mr-1">{t}</span>
                    {/each}
                </td>
                <td>
                    {#if canManage}
                        <button
                            class="text-xs px-2 py-1 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-all duration-150"
                            onclick={(e) => {
                                e.stopPropagation();
                                onArchive(r);
                            }}
                        >
                            Archive
                        </button>
                    {/if}
                </td>
            </tr>
        {/each}
    </tbody>
</table>

<style>
    .equipment-table th,
    .equipment-table td {
        padding: 0.6rem 0.75rem;
        text-align: left;
        font-size: 0.875rem;
        border-bottom: 1px solid hsl(var(--border));
    }
    .equipment-table th {
        font-weight: 600;
        color: hsl(var(--muted-foreground));
        background: hsl(205 25% 98%);
    }
    .tag-chip {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        padding: 0.15rem 0.5rem;
        background: hsl(205 25% 95%);
        border: 1px solid hsl(var(--border));
        border-radius: 9999px;
        font-size: 0.75rem;
    }
    .cal-pill {
        display: inline-flex;
        padding: 0.15rem 0.5rem;
        border-radius: 9999px;
        font-size: 0.75rem;
    }
    .cal-ok {
        background: hsl(142 70% 95%);
        color: hsl(142 70% 30%);
    }
    .cal-warn {
        background: hsl(38 90% 95%);
        color: hsl(38 90% 30%);
    }
    .cal-expired {
        background: hsl(0 70% 95%);
        color: hsl(0 70% 40%);
    }
    .cal-na {
        color: hsl(var(--muted-foreground));
    }
</style>
