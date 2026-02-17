<script lang="ts">
    import { onMount } from 'svelte';
    import { api } from '$lib/api';
    import { getUser, getCurrentOrg, getOrgs } from '$lib/auth.svelte';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import {
        Card,
        CardContent,
        CardHeader,
        CardTitle,
        CardDescription,
    } from '$lib/components/ui/card';

    let activeTab = $state<'organization' | 'teams' | 'profile'>('organization');

    // Organization members
    let members = $state<any[]>([]);
    let membersLoading = $state(false);
    let inviteEmail = $state('');
    let inviteSearchResults = $state<any[]>([]);
    let inviteSearching = $state(false);
    let showInviteDialog = $state(false);

    // Teams
    let teams = $state<any[]>([]);
    let teamsLoading = $state(false);
    let newTeamName = $state('');
    let expandedTeamId = $state<string | null>(null);
    let teamMembers = $state<Map<string, any[]>>(new Map());

    // Helpers
    function getInitials(name: string | null, email: string): string {
        if (name) {
            return name.split(' ').map((w) => w[0]).join('').toUpperCase().slice(0, 2);
        }
        return email[0].toUpperCase();
    }

    // Load organization members
    async function loadMembers() {
        const org = getCurrentOrg();
        if (!org) return;
        membersLoading = true;
        try {
            members = await api.get(`/iam/organizations/${org.id}/members`);
        } catch {
            members = [];
        } finally {
            membersLoading = false;
        }
    }

    // Load teams
    async function loadTeams() {
        const org = getCurrentOrg();
        if (!org) return;
        teamsLoading = true;
        try {
            teams = await api.get(`/iam/organizations/${org.id}/teams`);
        } catch {
            teams = [];
        } finally {
            teamsLoading = false;
        }
    }

    // Load team members
    async function loadTeamMembers(teamId: string) {
        try {
            const result = await api.get<any[]>(`/iam/teams/${teamId}/members`);
            teamMembers = new Map(teamMembers);
            teamMembers.set(teamId, result);
        } catch {
            // ignore
        }
    }

    // Toggle team expansion
    async function toggleTeam(teamId: string) {
        if (expandedTeamId === teamId) {
            expandedTeamId = null;
        } else {
            expandedTeamId = teamId;
            if (!teamMembers.has(teamId)) {
                await loadTeamMembers(teamId);
            }
        }
    }

    // Search users for invite
    async function searchUsers() {
        if (!inviteEmail.trim() || inviteEmail.length < 3) {
            inviteSearchResults = [];
            return;
        }
        inviteSearching = true;
        try {
            inviteSearchResults = await api.get(`/iam/users?email=${encodeURIComponent(inviteEmail)}`);
        } catch {
            inviteSearchResults = [];
        } finally {
            inviteSearching = false;
        }
    }

    // Add member to org
    async function inviteMember(userId: string) {
        const org = getCurrentOrg();
        if (!org) return;
        try {
            await api.post(`/iam/organizations/${org.id}/members`, {
                user_id: userId,
                is_admin: false,
            });
            showInviteDialog = false;
            inviteEmail = '';
            inviteSearchResults = [];
            await loadMembers();
        } catch (e: any) {
            console.error('Failed to invite member:', e);
        }
    }

    // Remove member from org
    async function removeMember(userId: string) {
        const org = getCurrentOrg();
        if (!org) return;
        try {
            await api.delete(`/iam/organizations/${org.id}/members/${userId}`);
            await loadMembers();
        } catch (e: any) {
            console.error('Failed to remove member:', e);
        }
    }

    // Toggle admin status
    async function toggleAdmin(userId: string, currentIsAdmin: boolean) {
        const org = getCurrentOrg();
        if (!org) return;
        try {
            await api.put(`/iam/organizations/${org.id}/members/${userId}`, {
                is_admin: !currentIsAdmin,
            });
            await loadMembers();
        } catch (e: any) {
            console.error('Failed to toggle admin:', e);
        }
    }

    // Create team
    async function createTeam() {
        const org = getCurrentOrg();
        if (!org || !newTeamName.trim()) return;
        try {
            await api.post(`/iam/organizations/${org.id}/teams`, {
                name: newTeamName.trim(),
            });
            newTeamName = '';
            await loadTeams();
        } catch (e: any) {
            console.error('Failed to create team:', e);
        }
    }

    // Delete team
    async function deleteTeam(teamId: string) {
        const org = getCurrentOrg();
        if (!org) return;
        try {
            await api.delete(`/iam/organizations/${org.id}/teams/${teamId}`);
            await loadTeams();
        } catch (e: any) {
            console.error('Failed to delete team:', e);
        }
    }

    onMount(() => {
        loadMembers();
        loadTeams();
    });
</script>

<div class="max-w-4xl mx-auto space-y-6">
    <div>
        <h1 class="text-3xl font-bold tracking-tight">Settings</h1>
        <p class="text-muted-foreground">Manage your organization, teams, and profile.</p>
    </div>

    <!-- Tabs -->
    <div class="flex border-b border-border">
        <button
            class="px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors {activeTab === 'organization' ? 'border-foreground text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'}"
            onclick={() => (activeTab = 'organization')}
        >
            Organization
        </button>
        <button
            class="px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors {activeTab === 'teams' ? 'border-foreground text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'}"
            onclick={() => (activeTab = 'teams')}
        >
            Teams
        </button>
        <button
            class="px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors {activeTab === 'profile' ? 'border-foreground text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'}"
            onclick={() => (activeTab = 'profile')}
        >
            Profile
        </button>
    </div>

    <!-- Organization Tab -->
    {#if activeTab === 'organization'}
        <Card>
            <CardHeader>
                <div class="flex items-center justify-between">
                    <div>
                        <CardTitle>{getCurrentOrg()?.name || 'No Organization'}</CardTitle>
                        <CardDescription>Members of your organization.</CardDescription>
                    </div>
                    <Button size="sm" onclick={() => (showInviteDialog = true)}>
                        Invite Member
                    </Button>
                </div>
            </CardHeader>
            <CardContent>
                {#if membersLoading}
                    <p class="text-sm text-muted-foreground py-4 text-center">Loading members...</p>
                {:else if members.length === 0}
                    <p class="text-sm text-muted-foreground py-4 text-center">No members found.</p>
                {:else}
                    <div class="divide-y divide-border">
                        {#each members as member}
                            <div class="flex items-center justify-between py-3">
                                <div class="flex items-center gap-3">
                                    <div class="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-semibold">
                                        {getInitials(member.full_name, member.email)}
                                    </div>
                                    <div>
                                        <p class="text-sm font-medium">{member.full_name || member.email}</p>
                                        <p class="text-xs text-muted-foreground">{member.email}</p>
                                    </div>
                                </div>
                                <div class="flex items-center gap-2">
                                    {#if member.is_admin}
                                        <span class="text-xs font-semibold px-2 py-0.5 rounded-full bg-primary/10 text-primary">Admin</span>
                                    {/if}
                                    <Button variant="ghost" size="sm" onclick={() => toggleAdmin(member.user_id, member.is_admin)}>
                                        {member.is_admin ? 'Remove Admin' : 'Make Admin'}
                                    </Button>
                                    <Button variant="ghost" size="sm" class="text-destructive" onclick={() => removeMember(member.user_id)}>
                                        Remove
                                    </Button>
                                </div>
                            </div>
                        {/each}
                    </div>
                {/if}
            </CardContent>
        </Card>

        <!-- Invite Dialog -->
        {#if showInviteDialog}
            <Card>
                <CardHeader>
                    <CardTitle>Invite Member</CardTitle>
                    <CardDescription>Search by email to add a member to your organization.</CardDescription>
                </CardHeader>
                <CardContent class="space-y-4">
                    <div class="flex gap-2">
                        <Input
                            bind:value={inviteEmail}
                            placeholder="Search by email..."
                            oninput={searchUsers}
                        />
                        <Button variant="outline" onclick={() => { showInviteDialog = false; inviteEmail = ''; inviteSearchResults = []; }}>
                            Cancel
                        </Button>
                    </div>
                    {#if inviteSearching}
                        <p class="text-sm text-muted-foreground">Searching...</p>
                    {:else if inviteSearchResults.length > 0}
                        <div class="divide-y divide-border rounded-md border">
                            {#each inviteSearchResults as user}
                                <div class="flex items-center justify-between px-3 py-2">
                                    <div>
                                        <p class="text-sm font-medium">{user.full_name || user.email}</p>
                                        <p class="text-xs text-muted-foreground">{user.email}</p>
                                    </div>
                                    <Button size="sm" onclick={() => inviteMember(user.id)}>Add</Button>
                                </div>
                            {/each}
                        </div>
                    {:else if inviteEmail.length >= 3}
                        <p class="text-sm text-muted-foreground">No users found.</p>
                    {/if}
                </CardContent>
            </Card>
        {/if}

    <!-- Teams Tab -->
    {:else if activeTab === 'teams'}
        <Card>
            <CardHeader>
                <div class="flex items-center justify-between">
                    <div>
                        <CardTitle>Teams</CardTitle>
                        <CardDescription>Manage teams within your organization.</CardDescription>
                    </div>
                </div>
            </CardHeader>
            <CardContent class="space-y-4">
                <!-- Create team -->
                <div class="flex gap-2">
                    <Input
                        bind:value={newTeamName}
                        placeholder="New team name..."
                        onkeydown={(e) => { if (e.key === 'Enter') createTeam(); }}
                    />
                    <Button onclick={createTeam} disabled={!newTeamName.trim()}>Create</Button>
                </div>

                {#if teamsLoading}
                    <p class="text-sm text-muted-foreground py-4 text-center">Loading teams...</p>
                {:else if teams.length === 0}
                    <p class="text-sm text-muted-foreground py-4 text-center">No teams yet. Create one above.</p>
                {:else}
                    <div class="divide-y divide-border rounded-md border">
                        {#each teams as team}
                            <div>
                                <div class="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-muted/50" onclick={() => toggleTeam(team.id)}>
                                    <div class="flex items-center gap-2">
                                        <span class="text-xs text-muted-foreground">{expandedTeamId === team.id ? '&#9660;' : '&#9654;'}</span>
                                        <span class="text-sm font-medium">{team.name}</span>
                                    </div>
                                    <Button variant="ghost" size="sm" class="text-destructive" onclick={(e) => { e.stopPropagation(); deleteTeam(team.id); }}>
                                        Delete
                                    </Button>
                                </div>
                                {#if expandedTeamId === team.id}
                                    <div class="px-4 pb-3 pl-10">
                                        {#if teamMembers.has(team.id)}
                                            {#each teamMembers.get(team.id) || [] as tm}
                                                <div class="flex items-center justify-between py-1.5">
                                                    <span class="text-sm">{tm.full_name || tm.email || tm.user_id}</span>
                                                    <span class="text-xs text-muted-foreground">{tm.role}</span>
                                                </div>
                                            {/each}
                                            {#if (teamMembers.get(team.id) || []).length === 0}
                                                <p class="text-xs text-muted-foreground">No members in this team.</p>
                                            {/if}
                                        {:else}
                                            <p class="text-xs text-muted-foreground">Loading...</p>
                                        {/if}
                                    </div>
                                {/if}
                            </div>
                        {/each}
                    </div>
                {/if}
            </CardContent>
        </Card>

    <!-- Profile Tab -->
    {:else if activeTab === 'profile'}
        <Card>
            <CardHeader>
                <CardTitle>Profile</CardTitle>
                <CardDescription>Your account information.</CardDescription>
            </CardHeader>
            <CardContent class="space-y-4">
                <div class="space-y-2">
                    <Label>Name</Label>
                    <Input value={getUser()?.full_name || ''} disabled />
                </div>
                <div class="space-y-2">
                    <Label>Email</Label>
                    <Input value={getUser()?.email || ''} disabled />
                </div>
                <div class="pt-4 border-t border-border">
                    <p class="text-sm text-muted-foreground">Password change coming soon.</p>
                </div>
            </CardContent>
        </Card>
    {/if}
</div>
