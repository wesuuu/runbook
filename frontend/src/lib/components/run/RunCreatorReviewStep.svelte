<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import type { Edit } from '$lib/utils/runOverrides';

    interface Props {
        runName: string;
        experimentName: string | null;
        protocolName: string;
        versionNumber: number;
        isLatestVersion: boolean;
        edits: Edit[];
        assignees: Array<{ role: string; name: string }>;
        creating: boolean;
        error: string | null;
        onCreate: () => void;
    }

    let {
        runName, experimentName, protocolName, versionNumber, isLatestVersion,
        edits, assignees, creating, error, onCreate,
    }: Props = $props();
</script>

<section class="step-body">
    <header class="step-header">
        <h2>Step 5 · Review &amp; create</h2>
        <p class="step-help">Looks good? Create the run and start working.</p>
    </header>

    <dl class="summary">
        <div class="summary-row">
            <dt>Name</dt>
            <dd>{runName}</dd>
        </div>
        {#if experimentName}
            <div class="summary-row">
                <dt>Experiment</dt>
                <dd>{experimentName}</dd>
            </div>
        {/if}
        <div class="summary-row">
            <dt>Protocol</dt>
            <dd>
                {protocolName}
                <span class="version-pill">v{versionNumber}</span>
                {#if isLatestVersion}<span class="latest-pill">LATEST</span>{/if}
            </dd>
        </div>
        <div class="summary-row">
            <dt>{assignees.length > 1 ? 'Assignees' : 'Assignee'}</dt>
            <dd>
                {#if assignees.length === 0}
                    <span class="muted">Not assigned — assign later from the run page</span>
                {:else}
                    {#each assignees as a (a.role + a.name)}
                        <span class="assignee-pill">{a.role}: {a.name}</span>
                    {/each}
                {/if}
            </dd>
        </div>
    </dl>

    <section class="edits-summary">
        <h3 class="edits-title">Overrides ({edits.length})</h3>
        {#if edits.length === 0}
            <p class="muted">This run uses protocol defaults — no overrides.</p>
        {:else}
            <ul class="edits-list">
                {#each edits as e (e.nodeId + e.kind + (e.field ?? ''))}
                    <li class="edit-row">
                        <span class="edit-tag tag-{e.kind.toLowerCase()}">{e.kind}</span>
                        <span class="edit-step">{e.stepName}</span>
                        <span class="edit-field">{e.fieldLabel ?? ''}</span>
                        {#if e.oldValue !== undefined && e.newValue !== undefined && e.kind !== 'INSTRUCTION'}
                            <span class="edit-diff">{String(e.oldValue)} → {String(e.newValue)}</span>
                        {/if}
                    </li>
                {/each}
            </ul>
        {/if}
    </section>

    {#if error}
        <p class="error">{error}</p>
    {/if}

    <div class="actions">
        <Button onclick={onCreate} disabled={creating}>
            {creating ? 'Creating…' : 'Create run'}
        </Button>
    </div>
</section>

<style>
    .step-body {
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
        max-width: 42rem;
    }
    .step-header h2 {
        font-size: 1.25rem;
        font-weight: 600;
        color: rgb(15 23 42);
    }
    .step-help {
        font-size: 0.875rem;
        color: rgb(71 85 105);
        margin-top: 0.25rem;
    }
    .summary {
        border-radius: 0.5rem;
        border: 1px solid rgb(226 232 240);
        background-color: rgb(248 250 252 / 0.5);
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .summary-row {
        display: grid;
        grid-template-columns: 120px 1fr;
        gap: 0.5rem;
        align-items: center;
        font-size: 0.875rem;
    }
    .summary-row dt {
        color: rgb(100 116 139);
        font-weight: 500;
        text-transform: uppercase;
        font-size: 0.75rem;
    }
    .summary-row dd {
        color: rgb(15 23 42);
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .version-pill {
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.5rem;
        border-radius: 0.375rem;
        background-color: rgb(204 251 241);
        color: rgb(17 94 89);
        font-size: 0.75rem;
        font-weight: 600;
    }
    .latest-pill {
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.375rem;
        border-radius: 0.25rem;
        background-color: rgb(209 250 229);
        color: rgb(6 95 70);
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
    }
    .assignee-pill {
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.5rem;
        border-radius: 0.375rem;
        background-color: rgb(241 245 249);
        color: rgb(30 41 59);
        font-size: 0.75rem;
        font-weight: 500;
    }
    .edits-summary {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .edits-title {
        font-size: 0.875rem;
        font-weight: 600;
        color: rgb(15 23 42);
    }
    .muted {
        font-size: 0.875rem;
        color: rgb(100 116 139);
        font-style: italic;
    }
    .edits-list {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        list-style: none;
        padding: 0;
        margin: 0;
    }
    .edit-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.875rem;
        flex-wrap: wrap;
    }
    .edit-tag {
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.375rem;
        border-radius: 0.25rem;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
    }
    .tag-value, .tag-swap {
        background-color: rgb(209 250 229);
        color: rgb(6 95 70);
    }
    .tag-added, .tag-schema {
        background-color: rgb(254 243 199);
        color: rgb(146 64 14);
    }
    .tag-removed {
        background-color: rgb(254 226 226);
        color: rgb(153 27 27);
    }
    .tag-instruction {
        background-color: rgb(219 234 254);
        color: rgb(30 64 175);
    }
    .edit-step {
        font-weight: 500;
        color: rgb(30 41 59);
    }
    .edit-field {
        color: rgb(71 85 105);
    }
    .edit-diff {
        color: rgb(100 116 139);
        font-size: 0.75rem;
    }
    .error {
        font-size: 0.875rem;
        color: rgb(220 38 38);
    }
    .actions {
        display: flex;
        justify-content: flex-end;
    }
</style>
