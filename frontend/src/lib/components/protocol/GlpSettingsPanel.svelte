<script lang="ts">
    import { X } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Textarea } from '$lib/components/ui/textarea';
    import { api } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import type { GlpSettings, QauMode } from '$lib/schemas/glpSignoff';

    interface Props {
        open: boolean;
        glpSettings: GlpSettings;
        onApply: (next: GlpSettings) => void;
        onClose: () => void;
    }

    let { open, glpSettings, onApply, onClose }: Props = $props();

    interface MemberOption {
        userId: string;
        name: string;
        email: string;
        roles: string[];
    }

    // Local working copy — edits are not propagated until Apply.
    let requireStudyDirector = $state(false);
    let requireQau = $state(false);
    let studyDirectorUserId = $state<string | null>(null);
    let qauMode = $state<QauMode>('ANY_ORG_QAU');
    let qauUserId = $state<string | null>(null);
    let operatorText = $state('');
    let studyDirectorText = $state('');
    let qauText = $state('');
    let stepText = $state('');

    let members = $state<MemberOption[]>([]);
    let membersLoading = $state(false);
    let membersError = $state<string | null>(null);

    // Re-sync local state whenever the panel opens or the upstream
    // settings change (e.g., after a save round-trip). Reading the prop
    // inside the effect (not at the top level) keeps the dependency live.
    let lastSyncedKey = $state('');
    $effect(() => {
        if (!open) return;
        const key = JSON.stringify(glpSettings);
        if (key === lastSyncedKey) return;
        lastSyncedKey = key;
        requireStudyDirector = glpSettings.require_study_director;
        requireQau = glpSettings.require_qau;
        studyDirectorUserId = glpSettings.study_director_user_id;
        qauMode = glpSettings.qau_mode;
        qauUserId = glpSettings.qau_user_id;
        operatorText = glpSettings.operator_attestation_text;
        studyDirectorText = glpSettings.study_director_attestation_text;
        qauText = glpSettings.qau_attestation_text;
        stepText = glpSettings.step_attestation_text;
    });

    // Load org members on first open so the SD/QAU pickers can render.
    $effect(() => {
        if (!open) return;
        if (members.length > 0 || membersLoading) return;
        loadMembers();
    });

    async function loadMembers(): Promise<void> {
        const org = getCurrentOrg();
        if (!org) return;
        membersLoading = true;
        membersError = null;
        try {
            const raw = await api.get<any[]>(
                `/iam/organizations/${org.id}/members`,
            );
            members = (raw ?? []).map((m) => ({
                userId: m.user_id,
                name: m.full_name ?? m.email ?? 'Unknown',
                email: m.email ?? '',
                roles: Array.isArray(m.roles) ? m.roles : [],
            }));
        } catch (e: unknown) {
            membersError =
                e instanceof Error ? e.message : 'Failed to load members.';
        } finally {
            membersLoading = false;
        }
    }

    const qauMembers = $derived(
        members.filter((m) => m.roles.includes('QAU')),
    );

    function handleApply(): void {
        onApply({
            require_study_director: requireStudyDirector,
            require_qau: requireQau,
            // Only persist designated IDs when the matching toggle is on;
            // clearing the toggle nulls out the assignment so a future
            // re-enable doesn't silently inherit a stale designation.
            study_director_user_id: requireStudyDirector
                ? studyDirectorUserId
                : null,
            qau_mode: qauMode,
            qau_user_id:
                requireQau && qauMode === 'SPECIFIC_USER' ? qauUserId : null,
            operator_attestation_text: operatorText,
            study_director_attestation_text: studyDirectorText,
            qau_attestation_text: qauText,
            step_attestation_text: stepText,
        });
        onClose();
    }

    function handleCancel(): void {
        // Re-sync from props on next open; just close.
        lastSyncedKey = '';
        onClose();
    }
</script>

{#if open}
    <aside
        class="glp-panel"
        aria-label="GLP Settings"
    >
        <div class="glp-header">
            <div>
                <div class="glp-eyebrow">INSPECTOR</div>
                <h2 class="glp-title">GLP Settings</h2>
            </div>
            <div class="glp-header-actions">
                <span class="glp-scope-badge">Protocol-level</span>
                <Button
                    variant="ghost"
                    size="icon-sm"
                    onclick={handleCancel}
                    aria-label="Close GLP settings panel"
                >
                    <X class="size-4" />
                </Button>
            </div>
        </div>

        <div class="glp-body">
            <section class="glp-section">
                <div class="glp-toggle-row">
                    <div class="glp-toggle-copy">
                        <div class="glp-toggle-title">Require Study Director sign-off</div>
                        <div class="glp-toggle-help">§58.33 — overall conduct of the study</div>
                    </div>
                    <Button
                        type="button"
                        variant={requireStudyDirector ? 'default' : 'outline'}
                        size="sm"
                        onclick={() => (requireStudyDirector = !requireStudyDirector)}
                        aria-pressed={requireStudyDirector}
                    >
                        {requireStudyDirector ? 'On' : 'Off'}
                    </Button>
                </div>

                {#if requireStudyDirector}
                    <div class="glp-field glp-field-indent">
                        <label class="glp-field-label" for="glp-sd-picker">Designated Study Director</label>
                        {#if membersLoading}
                            <div class="glp-picker-help">Loading members…</div>
                        {:else if membersError}
                            <div class="glp-picker-error">{membersError}</div>
                        {:else}
                            <select
                                id="glp-sd-picker"
                                class="glp-select"
                                bind:value={studyDirectorUserId}
                                data-testid="glp-sd-picker"
                            >
                                <option value={null}>— Select a Study Director —</option>
                                {#each members as m (m.userId)}
                                    <option value={m.userId}>{m.name} ({m.email})</option>
                                {/each}
                            </select>
                            <div class="glp-picker-help">
                                Single named individual responsible for the
                                study's overall conduct.
                            </div>
                        {/if}
                    </div>
                {/if}

                <div class="glp-toggle-row">
                    <div class="glp-toggle-copy">
                        <div class="glp-toggle-title">Require QAU sign-off</div>
                        <div class="glp-toggle-help">§58.35 — independent quality review</div>
                    </div>
                    <Button
                        type="button"
                        variant={requireQau ? 'default' : 'outline'}
                        size="sm"
                        onclick={() => (requireQau = !requireQau)}
                        aria-pressed={requireQau}
                    >
                        {requireQau ? 'On' : 'Off'}
                    </Button>
                </div>

                {#if requireQau}
                    <div class="glp-field glp-field-indent">
                        <div class="glp-field-label">QAU assignment</div>
                        <div class="glp-radio-group" role="radiogroup">
                            <label class="glp-radio-row">
                                <input
                                    type="radio"
                                    name="qau-mode"
                                    value="ANY_ORG_QAU"
                                    checked={qauMode === 'ANY_ORG_QAU'}
                                    onchange={() => (qauMode = 'ANY_ORG_QAU')}
                                    data-testid="glp-qau-mode-any"
                                />
                                <span class="glp-radio-copy">
                                    <span class="glp-radio-title">Any org-level QAU</span>
                                    <span class="glp-radio-help">
                                        Any organization member with the QAU
                                        role can sign off.
                                        {#if qauMembers.length > 0}
                                            ({qauMembers.length} eligible)
                                        {:else}
                                            (No QAU-role members yet — assign
                                            in Org Settings.)
                                        {/if}
                                    </span>
                                </span>
                            </label>
                            <label class="glp-radio-row">
                                <input
                                    type="radio"
                                    name="qau-mode"
                                    value="SPECIFIC_USER"
                                    checked={qauMode === 'SPECIFIC_USER'}
                                    onchange={() => (qauMode = 'SPECIFIC_USER')}
                                    data-testid="glp-qau-mode-specific"
                                />
                                <span class="glp-radio-copy">
                                    <span class="glp-radio-title">Designate a person</span>
                                    <span class="glp-radio-help">
                                        Pin QAU sign-off to one named
                                        individual for this protocol.
                                    </span>
                                </span>
                            </label>
                        </div>

                        {#if qauMode === 'SPECIFIC_USER'}
                            <select
                                class="glp-select glp-select-nested"
                                bind:value={qauUserId}
                                data-testid="glp-qau-picker"
                            >
                                <option value={null}>— Select QAU reviewer —</option>
                                {#each members as m (m.userId)}
                                    <option value={m.userId}>{m.name} ({m.email})</option>
                                {/each}
                            </select>
                        {/if}
                    </div>
                {/if}
            </section>

            <section class="glp-section glp-section-divider">
                <div class="glp-section-head">
                    <span class="glp-section-label">Attestation defaults</span>
                </div>

                <div class="glp-field">
                    <label class="glp-field-label" for="glp-operator-text">Operator</label>
                    <Textarea
                        id="glp-operator-text"
                        rows={2}
                        bind:value={operatorText}
                    />
                </div>

                <div class="glp-field">
                    <label class="glp-field-label" for="glp-study-director-text">Study Director</label>
                    <Textarea
                        id="glp-study-director-text"
                        rows={2}
                        bind:value={studyDirectorText}
                    />
                </div>

                <div class="glp-field">
                    <label class="glp-field-label" for="glp-qau-text">QAU</label>
                    <Textarea
                        id="glp-qau-text"
                        rows={2}
                        bind:value={qauText}
                    />
                </div>

                <div class="glp-field">
                    <label class="glp-field-label" for="glp-step-text">Per-step attestation</label>
                    <Textarea
                        id="glp-step-text"
                        rows={2}
                        bind:value={stepText}
                    />
                </div>
            </section>

            <p class="glp-footnote">
                These settings are snapshotted into every ProtocolVersion at
                publish time and into each Run at start. Changing them
                mid-run has no effect on in-flight records.
            </p>
        </div>

        <div class="glp-footer">
            <Button variant="ghost" size="sm" onclick={handleCancel}>Cancel</Button>
            <Button variant="default" size="sm" onclick={handleApply}>Apply</Button>
        </div>
    </aside>
{/if}

<style>
    .glp-panel {
        width: 360px;
        flex-shrink: 0;
        border-left: 1px solid hsl(240, 5.9%, 90%);
        background: white;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }

    .glp-header {
        padding: 12px 16px;
        border-bottom: 1px solid hsl(240, 5.9%, 90%);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
    }

    .glp-eyebrow {
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 10px;
        color: hsl(240, 3.8%, 46.1%);
        letter-spacing: 0.04em;
    }

    .glp-title {
        font-size: 14px;
        font-weight: 600;
        letter-spacing: -0.01em;
        margin: 0;
    }

    .glp-header-actions {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .glp-scope-badge {
        font-size: 10px;
        font-weight: 500;
        padding: 2px 8px;
        border-radius: 999px;
        background: hsl(240, 4.8%, 95.9%);
        color: hsl(240, 3.8%, 46.1%);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .glp-body {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 20px;
    }

    .glp-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .glp-section-divider {
        border-top: 1px solid hsl(240, 5.9%, 90%);
        padding-top: 16px;
    }

    .glp-section-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }

    .glp-section-label {
        font-size: 12px;
        font-weight: 600;
        color: hsl(240, 5.9%, 10%);
    }

    .glp-toggle-row {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
    }

    .glp-toggle-copy {
        flex: 1;
        min-width: 0;
    }

    .glp-toggle-title {
        font-size: 13px;
        font-weight: 500;
        color: hsl(240, 5.9%, 10%);
    }

    .glp-toggle-help {
        font-size: 11px;
        color: hsl(240, 3.8%, 46.1%);
        margin-top: 2px;
    }

    .glp-field {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .glp-field-indent {
        margin-left: 12px;
        padding-left: 12px;
        border-left: 2px solid hsl(173, 80%, 40%);
    }

    .glp-field-label {
        font-size: 11px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: hsl(240, 3.8%, 46.1%);
    }

    .glp-select {
        height: 32px;
        padding: 0 8px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        font-size: 13px;
        background: white;
        color: hsl(240, 5.9%, 10%);
    }

    .glp-select-nested {
        margin-top: 6px;
    }

    .glp-picker-help {
        font-size: 11px;
        color: hsl(240, 3.8%, 46.1%);
        font-style: italic;
    }

    .glp-picker-error {
        font-size: 12px;
        color: hsl(0, 72%, 51%);
    }

    .glp-radio-group {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .glp-radio-row {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        cursor: pointer;
    }

    .glp-radio-row input[type='radio'] {
        margin-top: 3px;
        cursor: pointer;
    }

    .glp-radio-copy {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .glp-radio-title {
        font-size: 13px;
        font-weight: 500;
        color: hsl(240, 5.9%, 10%);
    }

    .glp-radio-help {
        font-size: 11px;
        color: hsl(240, 3.8%, 46.1%);
    }

    .glp-footnote {
        font-size: 11px;
        font-style: italic;
        color: hsl(240, 3.8%, 46.1%);
        border-top: 1px solid hsl(240, 5.9%, 90%);
        padding-top: 12px;
        margin: 0;
    }

    .glp-footer {
        padding: 12px 16px;
        border-top: 1px solid hsl(240, 5.9%, 90%);
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 8px;
        background: hsl(240, 4.8%, 98%);
    }
</style>
