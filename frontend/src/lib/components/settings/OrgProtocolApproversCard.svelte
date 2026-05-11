<script lang="ts">
    import { onMount } from 'svelte';
    import { api } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import { Badge } from '$lib/components/ui/badge';
    import { Button } from '$lib/components/ui/button';
    import {
        Card,
        CardContent,
        CardDescription,
        CardHeader,
        CardTitle,
    } from '$lib/components/ui/card';

    interface Props {
        canManage: boolean;
    }

    interface OrgMember {
        user_id: string;
        full_name: string | null;
        email: string | null;
        roles: string[];
    }

    let { canManage }: Props = $props();

    let members = $state<OrgMember[]>([]);
    let loading = $state(true);
    let errorMessage = $state<string | null>(null);
    let newMemberId = $state('');

    const PROTOCOL_APPROVER = 'PROTOCOL_APPROVER';

    const approvers = $derived(
        members.filter((m) => m.roles.includes(PROTOCOL_APPROVER)),
    );
    const candidates = $derived(
        members.filter((m) => !m.roles.includes(PROTOCOL_APPROVER)),
    );

    async function load() {
        loading = true;
        errorMessage = null;
        const org = getCurrentOrg();
        if (!org) {
            loading = false;
            return;
        }
        try {
            const list = await api.get<any[]>(
                `/iam/organizations/${org.id}/members`,
            );
            members = (list ?? []).map((m: any) => ({
                user_id: m.user_id,
                full_name: m.full_name ?? null,
                email: m.email ?? null,
                roles: Array.isArray(m.roles) ? m.roles : [],
            }));
        } catch (e: unknown) {
            errorMessage = e instanceof Error ? e.message : 'Failed to load.';
        } finally {
            loading = false;
        }
    }

    onMount(load);

    async function setRoles(userId: string, nextRoles: string[]) {
        const org = getCurrentOrg();
        if (!org) return;
        errorMessage = null;
        const idx = members.findIndex((m) => m.user_id === userId);
        if (idx < 0) return;
        const previous = members[idx].roles;
        members[idx] = { ...members[idx], roles: nextRoles };
        try {
            const updated: any = await api.patch(
                `/iam/organizations/${org.id}/members/${userId}`,
                { roles: nextRoles },
            );
            if (updated && Array.isArray(updated.roles)) {
                members[idx] = { ...members[idx], roles: updated.roles };
            }
        } catch (e: unknown) {
            members[idx] = { ...members[idx], roles: previous };
            errorMessage =
                e instanceof Error ? e.message : 'Failed to update roles.';
        }
    }

    async function addApprover() {
        if (!newMemberId) return;
        const member = members.find((m) => m.user_id === newMemberId);
        if (!member) return;
        const next = [...new Set([...member.roles, PROTOCOL_APPROVER, 'MEMBER'])];
        await setRoles(newMemberId, next);
        newMemberId = '';
    }

    async function removeApprover(userId: string) {
        const member = members.find((m) => m.user_id === userId);
        if (!member) return;
        const next = [
            ...new Set(member.roles.filter((r) => r !== PROTOCOL_APPROVER)),
        ];
        if (!next.includes('MEMBER')) next.push('MEMBER');
        await setRoles(userId, next);
    }
</script>

<Card>
    <CardHeader>
        <CardTitle>Protocol Approvers (Org)</CardTitle>
        <CardDescription>
            Org members granted the PROTOCOL_APPROVER role can approve protocols
            in any project.
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
                No org-wide approvers yet.
            </p>
        {:else}
            <ul class="space-y-2 mb-4">
                {#each approvers as a (a.user_id)}
                    <li
                        data-testid="approver-row"
                        class="flex items-center justify-between py-2 px-3 bg-muted/40 rounded-lg"
                    >
                        <div class="flex items-center gap-2">
                            <div
                                class="w-7 h-7 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold"
                            >
                                {(a.full_name ?? a.email ?? '?')[0]?.toUpperCase()}
                            </div>
                            <div>
                                <p class="text-sm font-medium">
                                    {a.full_name ?? a.email ?? 'Unknown'}
                                </p>
                                {#if a.email}
                                    <p class="text-xs text-muted-foreground">
                                        {a.email}
                                    </p>
                                {/if}
                            </div>
                            <Badge variant="outline" data-testid="approver-badge">
                                Protocol approver
                            </Badge>
                        </div>
                        {#if canManage}
                            <Button
                                variant="ghost"
                                size="sm"
                                class="text-xs text-muted-foreground hover:text-destructive"
                                onclick={() => removeApprover(a.user_id)}
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
                    value={newMemberId}
                    onchange={(e) => (newMemberId = e.currentTarget.value)}
                    data-testid="approver-select"
                    class="flex-1 px-3 py-2 border border-border rounded-md text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                >
                    <option value="">Select a member…</option>
                    {#each candidates as c (c.user_id)}
                        <option value={c.user_id}>
                            {c.full_name ?? c.email}
                        </option>
                    {/each}
                </select>
                <Button onclick={addApprover} disabled={!newMemberId}>Add</Button>
            </div>
        {/if}
    </CardContent>
</Card>
