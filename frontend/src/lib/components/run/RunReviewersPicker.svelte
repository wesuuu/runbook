<script lang="ts">
    interface Member {
        id: string;
        full_name?: string | null;
        email?: string | null;
    }

    interface Props {
        studyDirectorId: string | null;
        qauReviewerId: string | null;
        members: Member[];
        disabled?: boolean;
        onChange: (reviewers: {
            studyDirectorId: string | null;
            qauReviewerId: string | null;
        }) => void;
    }

    let {
        studyDirectorId,
        qauReviewerId,
        members,
        disabled = false,
        onChange,
    }: Props = $props();

    function memberLabel(m: Member): string {
        return m.full_name || m.email || m.id;
    }

    function setSd(value: string) {
        onChange({ studyDirectorId: value || null, qauReviewerId });
    }

    function setQau(value: string) {
        onChange({ studyDirectorId, qauReviewerId: value || null });
    }
</script>

<div class="reviewers">
    <p class="group-label">GLP sign-off reviewers</p>

    <div class="reviewer-row">
        <label for="sd-picker">Study Director</label>
        <select
            id="sd-picker"
            class="input-field"
            {disabled}
            value={studyDirectorId ?? ''}
            onchange={(e) => setSd((e.currentTarget as HTMLSelectElement).value)}
        >
            <option value="">Unassigned</option>
            {#each members as m (m.id)}
                <option value={m.id}>{memberLabel(m)}</option>
            {/each}
        </select>
    </div>

    <div class="reviewer-row">
        <label for="qau-picker">QAU reviewer</label>
        <select
            id="qau-picker"
            class="input-field"
            {disabled}
            value={qauReviewerId ?? ''}
            onchange={(e) => setQau((e.currentTarget as HTMLSelectElement).value)}
        >
            <option value="">Unassigned</option>
            {#each members as m (m.id)}
                <option value={m.id}>{memberLabel(m)}</option>
            {/each}
        </select>
    </div>

    {#if !qauReviewerId}
        <p class="hint">Leave blank to open this review to the org QAU team.</p>
    {/if}
</div>

<style>
    .reviewers {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .group-label {
        font-size: 0.8125rem;
        font-weight: 600;
        color: var(--muted-fg, hsl(215 15% 42%));
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .reviewer-row {
        display: grid;
        grid-template-columns: 12rem 1fr;
        align-items: center;
        gap: 0.75rem;
    }
    .reviewer-row label {
        font-size: 0.875rem;
        color: var(--fg, hsl(215 40% 12%));
    }
    .input-field {
        width: 100%;
        padding: 0.5rem 0.75rem;
        border: 1px solid var(--border, hsl(205 22% 87%));
        border-radius: 0.375rem;
        background: var(--card, #fff);
        font-size: 0.875rem;
    }
    .input-field:focus {
        outline: none;
        border-color: rgb(20 184 166);
        box-shadow: 0 0 0 2px rgb(20 184 166 / 0.2);
    }
    .input-field:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
    .hint {
        font-size: 0.75rem;
        color: var(--muted-fg, hsl(215 15% 42%));
    }
</style>
