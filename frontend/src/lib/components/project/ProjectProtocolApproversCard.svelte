<script lang="ts">
    import { onMount } from 'svelte';
    import { api } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import { Button } from '$lib/components/ui/button';
    import {
        Card,
        CardContent,
        CardDescription,
        CardHeader,
        CardTitle,
    } from '$lib/components/ui/card';

    interface Props {
        projectId: string;
        canManage: boolean;
    }

    interface ApproverEntry {
        id: string;
        principal_type: string;
        principal_id: string;
        name: string | null;
        email: string | null;
    }

    interface OrgMember {
        user_id: string;
        full_name: string | null;
        email: string | null;
    }

    let { projectId, canManage }: Props = $props();

    let approvers = $state<ApproverEntry[]>([]);
    let orgMembers = $state<OrgMember[]>([]);
    let newApproverUserId = $state('');
    let loading = $state(true);
    let errorMessage = $state<string | null>(null);

    async function load() {
        loading = true;
        errorMessage = null;
        try {
            approvers = await api.get<ApproverEntry[]>(
                `/projects/${projectId}/approvers`,
            );
            const org = getCurrentOrg();
            if (org && canManage) {
                const members = await api.get<any[]>(
                    `/iam/organizations/${org.id}/members`,
                );
                orgMembers = (members ?? []).map((m: any) => ({
                    user_id: m.user_id,
                    full_name: m.full_name ?? null,
                    email: m.email ?? null,
                }));
            }
        } catch (e: unknown) {
            errorMessage = e instanceof Error ? e.message : 'Failed to load.';
        } finally {
            loading = false;
        }
    }

    onMount(load);

    async function addApprover() {
        if (!newApproverUserId) return;
        errorMessage = null;
        try {
            const entry = await api.post<ApproverEntry>(
                `/projects/${projectId}/approvers`,
                {
                    principal_type: 'USER',
                    principal_id: newApproverUserId,
                },
            );
            approvers = [...approvers, entry];
            newApproverUserId = '';
        } catch (e: unknown) {
            errorMessage = e instanceof Error ? e.message : 'Failed to add.';
        }
    }

    async function removeApprover(permId: string) {
        errorMessage = null;
        try {
            await api.delete(`/projects/${projectId}/approvers/${permId}`);
            approvers = approvers.filter((a) => a.id !== permId);
        } catch (e: unknown) {
            errorMessage = e instanceof Error ? e.message : 'Failed to remove.';
        }
    }

    const availableMembers = $derived(
        orgMembers.filter(
            (m) => !approvers.some((a) => a.principal_id === m.user_id),
        ),
    );
</script>

<Card>
    <CardHeader>
        <CardTitle>Protocol Approvers</CardTitle>
        <CardDescription>
            Users with the APPROVE permission on this project. Org admins can
            always approve.
        </CardDescription>
    </CardHeader>
    <CardContent>
        {#if errorMessage}
            <p class="text-xs text-destructive mb-3">{errorMessage}</p>
        {/if}

        {#if loading}
            <p class="text-xs text-muted-foreground">Loading…</p>
        {:else if approvers.length === 0}
            <p class="text-xs text-muted-foreground mb-4">
                No approvers assigned yet.
            </p>
        {:else}
            <ul class="space-y-2 mb-4">
                {#each approvers as approver (approver.id)}
                    <li
                        class="flex items-center justify-between py-2 px-3 bg-muted/40 rounded-lg"
                        data-testid="approver-row"
                    >
                        <div class="flex items-center gap-2">
                            <div
                                class="w-7 h-7 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center text-xs font-bold"
                            >
                                {(approver.name ?? '?')[0].toUpperCase()}
                            </div>
                            <div>
                                <p class="text-sm font-medium">
                                    {approver.name ?? 'Unknown'}
                                </p>
                                {#if approver.email}
                                    <p class="text-xs text-muted-foreground">
                                        {approver.email}
                                    </p>
                                {/if}
                            </div>
                        </div>
                        {#if canManage}
                            <Button
                                variant="ghost"
                                size="sm"
                                class="text-xs text-muted-foreground hover:text-destructive"
                                onclick={() => removeApprover(approver.id)}
                            >
                                Remove
                            </Button>
                        {/if}
                    </li>
                {/each}
            </ul>
        {/if}

        {#if canManage}
            <div class="flex gap-2">
                <select
                    value={newApproverUserId}
                    onchange={(e) => (newApproverUserId = e.currentTarget.value)}
                    data-testid="approver-select"
                    class="flex-1 px-3 py-2 border border-border rounded-md text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                >
                    <option value="">Select a user…</option>
                    {#each availableMembers as member (member.user_id)}
                        <option value={member.user_id}>
                            {member.full_name ?? member.email}
                        </option>
                    {/each}
                </select>
                <Button onclick={addApprover} disabled={!newApproverUserId}>
                    Add
                </Button>
            </div>
        {/if}
    </CardContent>
</Card>
