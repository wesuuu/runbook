<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { api, submitProtocolForApproval } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import type { Protocol } from '$lib/schemas/protocols';

    interface Props {
        open: boolean;
        protocolId: string;
        projectId: string;
        onSuccess?: (protocol: Protocol) => void;
        onCancel?: () => void;
    }

    interface ApproverOption {
        userId: string;
        name: string;
        email: string;
        sources: ('project' | 'org')[];
    }

    let {
        open = $bindable(false),
        protocolId,
        projectId,
        onSuccess,
        onCancel,
    }: Props = $props();

    let loading = $state(false);
    let loaded = $state(false);
    let submitting = $state(false);
    let errorMessage = $state<string | null>(null);
    let projectApprovers = $state<ApproverOption[]>([]);
    let orgApprovers = $state<ApproverOption[]>([]);
    let selected = $state<Set<string>>(new Set());

    const submitDisabled = $derived(submitting || selected.size === 0);

    function reset() {
        projectApprovers = [];
        orgApprovers = [];
        selected = new Set();
        errorMessage = null;
        submitting = false;
        loaded = false;
    }

    async function loadEligible() {
        loading = true;
        errorMessage = null;
        try {
            const projectMap = new Map<string, ApproverOption>();
            const orgMap = new Map<string, ApproverOption>();

            // Project approvers (USER principals only — teams not supported by submit endpoint)
            const projApprovers = await api.get<any[]>(
                `/projects/${projectId}/approvers`,
            );
            for (const a of projApprovers ?? []) {
                if (a.principal_type !== 'USER' || !a.principal_id) continue;
                projectMap.set(a.principal_id, {
                    userId: a.principal_id,
                    name: a.name ?? 'Unknown',
                    email: a.email ?? '',
                    sources: ['project'],
                });
            }

            // Org members with PROTOCOL_APPROVER role
            const org = getCurrentOrg();
            if (org) {
                const members = await api.get<any[]>(
                    `/iam/organizations/${org.id}/members`,
                );
                for (const m of members ?? []) {
                    const roles: string[] = Array.isArray(m.roles) ? m.roles : [];
                    if (!roles.includes('PROTOCOL_APPROVER')) continue;
                    orgMap.set(m.user_id, {
                        userId: m.user_id,
                        name: m.full_name ?? m.email ?? 'Unknown',
                        email: m.email ?? '',
                        sources: ['org'],
                    });
                }
            }

            // Hybrid users (in both): keep them in projectMap with merged sources, drop from orgMap
            for (const [userId, opt] of orgMap) {
                if (projectMap.has(userId)) {
                    const existing = projectMap.get(userId)!;
                    projectMap.set(userId, {
                        ...existing,
                        sources: ['project', 'org'],
                    });
                    orgMap.delete(userId);
                }
            }

            projectApprovers = Array.from(projectMap.values());
            orgApprovers = Array.from(orgMap.values());
            loaded = true;
        } catch (e: unknown) {
            errorMessage =
                e instanceof Error ? e.message : 'Failed to load approvers.';
        } finally {
            loading = false;
        }
    }

    $effect(() => {
        if (open && !loaded && !loading) {
            loadEligible();
        }
    });

    function toggle(userId: string) {
        const next = new Set(selected);
        if (next.has(userId)) next.delete(userId);
        else next.add(userId);
        selected = next;
    }

    function handleCancel() {
        reset();
        open = false;
        onCancel?.();
    }

    async function handleSubmit() {
        if (submitDisabled) return;
        submitting = true;
        errorMessage = null;
        try {
            const result = await submitProtocolForApproval(
                protocolId,
                Array.from(selected),
            );
            reset();
            open = false;
            onSuccess?.(result);
        } catch (e: unknown) {
            errorMessage = e instanceof Error ? e.message : 'Failed to submit.';
            submitting = false;
        }
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-lg">
        <Dialog.Header>
            <Dialog.Title>Submit for Approval</Dialog.Title>
            <Dialog.Description>
                Pick at least one eligible approver. They will be notified.
            </Dialog.Description>
        </Dialog.Header>

        <div class="space-y-4 max-h-[60vh] overflow-y-auto">
            {#if loading}
                <p class="text-sm text-muted-foreground">Loading approvers…</p>
            {:else if errorMessage}
                <p class="text-sm text-destructive">{errorMessage}</p>
            {:else}
                <section>
                    <h4 class="text-xs font-bold uppercase tracking-wide text-muted-foreground mb-2">
                        Project approvers
                    </h4>
                    {#if projectApprovers.length === 0}
                        <p class="text-xs text-muted-foreground">
                            No project approvers configured.
                        </p>
                    {:else}
                        <ul class="space-y-1">
                            {#each projectApprovers as opt (opt.userId)}
                                <li>
                                    <label class="flex items-center gap-2 py-1 cursor-pointer hover:bg-muted rounded px-2">
                                        <input
                                            type="checkbox"
                                            checked={selected.has(opt.userId)}
                                            onchange={() => toggle(opt.userId)}
                                            class="w-4 h-4"
                                            data-testid={`approver-${opt.userId}`}
                                        />
                                        <span class="text-sm font-medium">{opt.name}</span>
                                        {#if opt.email}
                                            <span class="text-xs text-muted-foreground">
                                                {opt.email}
                                            </span>
                                        {/if}
                                        {#if opt.sources.includes('org')}
                                            <span class="text-[10px] uppercase font-semibold text-blue-600 ml-auto">
                                                also org
                                            </span>
                                        {/if}
                                    </label>
                                </li>
                            {/each}
                        </ul>
                    {/if}
                </section>

                <section>
                    <h4 class="text-xs font-bold uppercase tracking-wide text-muted-foreground mb-2">
                        Org approvers
                    </h4>
                    {#if orgApprovers.length === 0}
                        <p class="text-xs text-muted-foreground">
                            No additional org-wide approvers.
                        </p>
                    {:else}
                        <ul class="space-y-1">
                            {#each orgApprovers as opt (opt.userId)}
                                <li>
                                    <label class="flex items-center gap-2 py-1 cursor-pointer hover:bg-muted rounded px-2">
                                        <input
                                            type="checkbox"
                                            checked={selected.has(opt.userId)}
                                            onchange={() => toggle(opt.userId)}
                                            class="w-4 h-4"
                                            data-testid={`approver-${opt.userId}`}
                                        />
                                        <span class="text-sm font-medium">{opt.name}</span>
                                        {#if opt.email}
                                            <span class="text-xs text-muted-foreground">
                                                {opt.email}
                                            </span>
                                        {/if}
                                    </label>
                                </li>
                            {/each}
                        </ul>
                    {/if}
                </section>
            {/if}
        </div>

        <Dialog.Footer>
            <Button variant="secondary" onclick={handleCancel} disabled={submitting}>
                Cancel
            </Button>
            <Button onclick={handleSubmit} disabled={submitDisabled}>
                {submitting ? '…' : `Submit (${selected.size})`}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
