<script lang="ts">
    import { onMount } from 'svelte';
    import { api } from '$lib/api';
    import { z } from 'zod';
    import { toast } from '$lib/toast';
    import { getUser, getCurrentOrg, getOrgs, refreshUser, getUserPreferences, getToken } from '$lib/auth.svelte';
    import { API_BASE } from '$lib/config';
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
    import ProjectDataTable from '$lib/components/project/ProjectDataTable.svelte';
    import { formatDate } from '$lib/components/project/projectUtils';
    import AiSettingsTab from '$lib/components/settings/AiSettingsTab.svelte';
    import TemplatesTab from '$lib/components/settings/TemplatesTab.svelte';
    import BillingTab from '$lib/components/settings/BillingTab.svelte';
    import AppearanceTab from '$lib/components/settings/AppearanceTab.svelte';
    import SignatureCard from '$lib/components/settings/SignatureCard.svelte';
    import MemberRolesPicker from '$lib/components/settings/MemberRolesPicker.svelte';
    import SitesEquipmentTab from '$lib/components/sites/SitesEquipmentTab.svelte';
    import OrgProtocolApproversCard from '$lib/components/settings/OrgProtocolApproversCard.svelte';
    import ConfirmDialog from '$lib/components/ui/confirm-dialog.svelte';
    import { SiteListSchema, type Site } from '$lib/schemas/sites';
    import { fade } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { blockDuration, listDuration } from '$lib/transitions';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';

    type TabName = 'organization' | 'teams' | 'sites' | 'profile' | 'appearance' | 'notifications' | 'ai' | 'templates' | 'billing' | 'legal';
    const VALID_TABS: TabName[] = ['organization', 'teams', 'sites', 'profile', 'appearance', 'notifications', 'ai', 'templates', 'billing', 'legal'];

    const activeTab = $derived.by<TabName>(() => {
        const t = $page.url.searchParams.get('tab');
        return VALID_TABS.includes(t as TabName) ? (t as TabName) : 'organization';
    });

    function setTab(tab: TabName) {
        goto(`?tab=${tab}`, { replaceState: false, keepFocus: true, noScroll: true });
    }

    const currentUser = $derived(getUser());

    function formatLegalDate(iso: string | null): string {
        if (!iso) return '—';
        return new Date(iso).toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        });
    }

    // Notifications
    let channels = $state<any[]>([]);
    let channelsLoading = $state(false);
    let channelsLoaded = $state(false);
    let showAddChannel = $state(false);
    let newChannelType = $state('SLACK');
    let newChannelName = $state('');
    let newChannelConfig = $state<Record<string, string>>({});
    let channelSaving = $state(false);
    let channelTestResults = $state<Map<string, { status: string; detail: string }>>(new Map());
    let expandedChannelId = $state<string | null>(null);
    let channelSubscriptions = $state<Map<string, any[]>>(new Map());

    const CHANNEL_TYPES = [
        { value: 'SLACK', label: 'Slack' },
        { value: 'EMAIL', label: 'Email' },
        { value: 'TEAMS', label: 'Microsoft Teams' },
        { value: 'DISCORD', label: 'Discord' },
        { value: 'WEBHOOK', label: 'Webhook' },
    ] as const;

    const EVENT_TYPES = [
        { value: 'RUN_STARTED', label: 'Run Started' },
        { value: 'RUN_COMPLETED', label: 'Run Completed' },
        { value: 'ROLE_ASSIGNED', label: 'Role Assigned' },
        { value: 'ROLE_UNASSIGNED', label: 'Role Unassigned' },
        { value: 'ROLE_REASSIGNED', label: 'Role Reassigned' },
        { value: 'INVITE_SENT', label: 'Invite Sent' },
        { value: 'INVITE_ACCEPTED', label: 'Invite Accepted' },
        { value: 'PROTOCOL_APPROVED', label: 'Protocol Approved' },
        { value: 'PROTOCOL_REVERTED', label: 'Protocol Reverted' },
        { value: 'PROTOCOL_APPROVAL_REQUESTED', label: 'Protocol Approval Requested' },
        { value: 'STEP_DEVIATION', label: 'Step Deviation' },
    ] as const;

    const CONFIG_FIELDS: Record<string, { key: string; label: string; placeholder: string; type?: string }[]> = {
        SLACK: [
            { key: 'webhook_url', label: 'Webhook URL', placeholder: 'https://hooks.slack.com/services/...' },
        ],
        EMAIL: [
            { key: 'to_address', label: 'Email Address', placeholder: 'you@example.com', type: 'email' },
        ],
        TEAMS: [
            { key: 'webhook_url', label: 'Webhook URL', placeholder: 'https://outlook.office.com/webhook/...' },
        ],
        DISCORD: [
            { key: 'webhook_url', label: 'Webhook URL', placeholder: 'https://discord.com/api/webhooks/...' },
        ],
        WEBHOOK: [
            { key: 'url', label: 'URL', placeholder: 'https://example.com/webhook' },
            { key: 'secret', label: 'Secret (optional)', placeholder: 'HMAC signing secret' },
        ],
    };

    async function loadChannels() {
        channelsLoading = true;
        try {
            channels = await api.get('/notifications/channels/me');
        } catch {
            channels = [];
        } finally {
            channelsLoading = false;
            channelsLoaded = true;
        }
    }

    async function addChannel() {
        if (!newChannelName.trim()) return;
        channelSaving = true;
        try {
            await api.post('/notifications/channels/me', {
                name: newChannelName.trim(),
                channel_type: newChannelType,
                config: { ...newChannelConfig },
                enabled: true,
            });
            showAddChannel = false;
            newChannelName = '';
            newChannelConfig = {};
            await loadChannels();
        } catch (e: unknown) {
            console.error('Failed to add channel:', e instanceof Error ? e.message : e);
        } finally {
            channelSaving = false;
        }
    }

    async function toggleChannelEnabled(channelId: string, enabled: boolean) {
        try {
            await api.put(`/notifications/channels/me/${channelId}`, { enabled: !enabled });
            await loadChannels();
        } catch (e: unknown) {
            console.error('Failed to toggle channel:', e instanceof Error ? e.message : e);
        }
    }

    async function deleteChannel(channelId: string) {
        try {
            await api.delete(`/notifications/channels/me/${channelId}`);
            await loadChannels();
        } catch (e: unknown) {
            console.error('Failed to delete channel:', e instanceof Error ? e.message : e);
        }
    }

    async function testChannel(channelId: string) {
        channelTestResults = new Map(channelTestResults);
        channelTestResults.set(channelId, { status: 'TESTING', detail: 'Sending...' });
        try {
            const result = await api.post(`/notifications/channels/${channelId}/test`, undefined, {
                schema: z.object({ status: z.string(), detail: z.string() }).passthrough(),
            });
            channelTestResults = new Map(channelTestResults);
            channelTestResults.set(channelId, result);
            setTimeout(() => {
                channelTestResults = new Map(channelTestResults);
                channelTestResults.delete(channelId);
            }, 5000);
        } catch (e: unknown) {
            channelTestResults = new Map(channelTestResults);
            channelTestResults.set(channelId, { status: 'FAILED', detail: e instanceof Error ? e.message : 'Test failed' });
        }
    }

    async function loadSubscriptions(channelId: string) {
        try {
            const subs = await api.get(`/notifications/channels/${channelId}/subscriptions`, {
                schema: z.array(z.record(z.string(), z.unknown())),
            });
            channelSubscriptions = new Map(channelSubscriptions);
            channelSubscriptions.set(channelId, subs);
        } catch {
            channelSubscriptions = new Map(channelSubscriptions);
            channelSubscriptions.set(channelId, []);
        }
    }

    async function toggleExpandChannel(channelId: string) {
        if (expandedChannelId === channelId) {
            expandedChannelId = null;
        } else {
            expandedChannelId = channelId;
            if (!channelSubscriptions.has(channelId)) {
                await loadSubscriptions(channelId);
            }
        }
    }

    function isEventSubscribed(channelId: string, eventType: string): boolean {
        const subs = channelSubscriptions.get(channelId) || [];
        return subs.some((s: any) => s.event_type === eventType && s.enabled);
    }

    async function toggleSubscription(channelId: string, eventType: string) {
        const subs = channelSubscriptions.get(channelId) || [];
        const existing = subs.find((s: any) => s.event_type === eventType);
        try {
            if (existing && existing.enabled) {
                await api.delete(`/notifications/channels/${channelId}/subscriptions/${existing.id}`);
            } else {
                await api.post(`/notifications/channels/${channelId}/subscriptions`, {
                    event_type: eventType,
                    enabled: true,
                });
            }
            await loadSubscriptions(channelId);
        } catch (e: unknown) {
            console.error('Failed to toggle subscription:', e instanceof Error ? e.message : e);
        }
    }

    function getChannelTypeLabel(type: string): string {
        return CHANNEL_TYPES.find((t) => t.value === type)?.label || type;
    }

    // Organization members
    let members = $state<any[]>([]);
    let membersLoading = $state(false);
    let membersError = $state('');
    const isOrgAdmin = $derived(
        members.some(
            (m: any) =>
                m.user_id === getUser()?.id && (m.roles ?? []).includes('ADMIN'),
        )
    );
    let inviteEmail = $state('');
    let showInviteDialog = $state(false);
    let memberStatusFilter = $state<'all' | 'active' | 'pending'>('all');

    // Sites (for SITE_MANAGER grant picker; F-0088 Task 31).
    let allSites = $state<Site[]>([]);
    // Per-member managed site ids, keyed by user_id.
    let managedSiteIdsByUser = $state<Record<string, string[]>>({});

    // Confirm-on-untick state when SITE_MANAGER is being removed while
    // grants still exist. We stash the intended next-roles list and apply
    // it only after the admin confirms the bulk revoke.
    let confirmRevokeOpen = $state(false);
    let pendingRevoke = $state<{
        userId: string;
        userLabel: string;
        nextRoles: string[];
        siteCount: number;
    } | null>(null);

    // Library reload
    let reloading = $state(false);
    let lastReloadedAt = $state<Date | null>(null);

    async function reloadLibraries() {
        reloading = true;
        try {
            const res: any = await api.post('/admin/libraries/reload');
            const libs = res?.libraries ?? [];
            const opCount = libs.reduce((acc: number, l: any) => acc + (l.op_count ?? 0), 0);
            toast.success('Libraries reloaded', `${libs.length} libraries, ${opCount} ops`);
            lastReloadedAt = new Date();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Reload failed');
        } finally {
            reloading = false;
        }
    }

    function formatRelative(d: Date): string {
        const seconds = Math.round((Date.now() - d.getTime()) / 1000);
        if (seconds < 60) return `${seconds}s ago`;
        const minutes = Math.round(seconds / 60);
        if (minutes < 60) return `${minutes}m ago`;
        return `${Math.round(minutes / 60)}h ago`;
    }

    type MemberRow = {
        type: 'member' | 'invitation';
        id: string;
        email: string;
        name: string | null;
        roles: string[];
        role: string;
        status: string;
        date: string;
        raw: any;
    };

    function invitationStatus(inv: any): string {
        return new Date(inv.expires_at) < new Date() ? 'Expired' : 'Pending';
    }

    const allRows = $derived.by(() => {
        const rows: MemberRow[] = [];
        for (const m of members) {
            rows.push({
                type: 'member',
                id: m.user_id,
                email: m.email || '',
                name: m.full_name || null,
                roles: m.roles ?? [],
                role: '',
                status: 'Active',
                date: m.created_at || '',
                raw: m,
            });
        }
        for (const inv of pendingInvitations) {
            rows.push({
                type: 'invitation',
                id: inv.id,
                email: inv.invited_email,
                name: null,
                roles: [],
                role: inv.role,
                status: invitationStatus(inv),
                date: inv.created_at || '',
                raw: inv,
            });
        }
        if (memberStatusFilter === 'active') return rows.filter((r) => r.status === 'Active');
        if (memberStatusFilter === 'pending') return rows.filter((r) => r.status === 'Pending' || r.status === 'Expired');
        return rows;
    });

    const memberColumns = [
        { key: 'name', label: 'User', sortable: true },
        { key: 'role', label: 'Role', sortable: true, align: 'center' as const },
        { key: 'status', label: 'Status', sortable: true, align: 'center' as const },
        { key: 'date', label: 'Joined / Sent', sortable: true, align: 'center' as const },
    ];

    // Admin gets an actions column
    const memberColumnsAdmin = $derived(
        isOrgAdmin
            ? [...memberColumns, { key: '_actions', label: 'Actions', align: 'right' as const }]
            : memberColumns
    );

    function memberFilterFn(item: MemberRow, query: string): boolean {
        if (!query) return true;
        const roleHay = (item.role || (item.roles ?? []).join(' ')).toLowerCase();
        return (
            (item.name?.toLowerCase().includes(query) ?? false) ||
            item.email.toLowerCase().includes(query) ||
            roleHay.includes(query) ||
            item.status.toLowerCase().includes(query)
        );
    }

    // Teams
    let teams = $state<any[]>([]);
    let teamsLoading = $state(false);
    let newTeamName = $state('');
    let expandedTeamId = $state<string | null>(null);
    let teamMembers = $state<Map<string, any[]>>(new Map());

    // Profile
    let profileName = $state(getUser()?.full_name || '');
    let profileJobTitle = $state(getUser()?.job_title || '');
    let profileSaving = $state(false);
    let profileMessage = $state('');

    // Avatar
    let avatarUploading = $state(false);
    let avatarFileInput: HTMLInputElement;

    // Password
    let currentPassword = $state('');
    let newPassword = $state('');
    let confirmPassword = $state('');
    let passwordSaving = $state(false);
    let passwordMessage = $state('');
    let passwordError = $state('');

    // Preferences
    let fontSize = $state(getUserPreferences().font_size || 'medium');
    let density = $state(getUserPreferences().density || 'comfortable');
    let prefsSaving = $state(false);

    const avatarUrl = $derived(() => {
        const u = getUser();
        return u?.avatar_url ? `${API_BASE}${u.avatar_url}?token=${getToken()}` : null;
    });

    async function saveProfile() {
        profileSaving = true;
        profileMessage = '';
        try {
            await api.put('/auth/me', {
                full_name: profileName || null,
                job_title: profileJobTitle || null,
            });
            await refreshUser();
            profileMessage = 'Profile saved.';
            setTimeout(() => (profileMessage = ''), 3000);
        } catch (e: unknown) {
            profileMessage = e instanceof Error ? e.message : 'Failed to save.';
        } finally {
            profileSaving = false;
        }
    }

    async function uploadAvatar(e: Event) {
        const input = e.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;
        avatarUploading = true;
        try {
            await api.uploadFile('/auth/me/avatar', file);
            await refreshUser();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to upload avatar.');
        } finally {
            avatarUploading = false;
            input.value = '';
        }
    }

    async function removeAvatar() {
        avatarUploading = true;
        try {
            await api.delete('/auth/me/avatar');
            await refreshUser();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to remove avatar.');
        } finally {
            avatarUploading = false;
        }
    }

    async function changePassword() {
        passwordError = '';
        passwordMessage = '';
        if (newPassword.length < 8) {
            passwordError = 'New password must be at least 8 characters.';
            return;
        }
        if (newPassword !== confirmPassword) {
            passwordError = 'Passwords do not match.';
            return;
        }
        passwordSaving = true;
        try {
            await api.put('/auth/me/password', {
                current_password: currentPassword,
                new_password: newPassword,
            });
            currentPassword = '';
            newPassword = '';
            confirmPassword = '';
            passwordMessage = 'Password changed.';
            setTimeout(() => (passwordMessage = ''), 3000);
        } catch (e: unknown) {
            passwordError = e instanceof Error ? e.message : 'Failed to change password.';
        } finally {
            passwordSaving = false;
        }
    }

    async function savePreferences() {
        prefsSaving = true;
        try {
            await api.put('/auth/me/preferences', {
                font_size: fontSize,
                density,
            });
            await refreshUser();
        } catch {
            // ignore
        } finally {
            prefsSaving = false;
        }
    }

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
        membersError = '';
        try {
            const [memberList, siteList] = await Promise.all([
                api.get(`/iam/organizations/${org.id}/members`),
                api
                    .get('/sites', { schema: SiteListSchema })
                    .catch(() => [] as Site[]),
            ]);
            members = memberList as any[];
            allSites = siteList as Site[];
            await loadManagedSitesForMembers();
        } catch (e: unknown) {
            members = [];
            membersError = e instanceof Error ? e.message : 'Failed to load members.';
        } finally {
            membersLoading = false;
        }
    }

    // For each member who currently holds SITE_MANAGER, fetch the list of
    // sites they manage. Cheap when few members have the role.
    async function loadManagedSitesForMembers() {
        const siteManagerMembers = members.filter((m: any) =>
            (m.roles ?? []).includes('SITE_MANAGER'),
        );
        if (siteManagerMembers.length === 0) {
            managedSiteIdsByUser = {};
            return;
        }
        const entries = await Promise.all(
            siteManagerMembers.map(async (m: any) => {
                try {
                    const rows = await api.get<Array<{ grant_id: string; site: { id: string } }>>(
                        `/users/${m.user_id}/managed-sites`,
                    );
                    return [m.user_id, rows.map((r) => r.site.id)] as const;
                } catch {
                    return [m.user_id, [] as string[]] as const;
                }
            }),
        );
        const next: Record<string, string[]> = {};
        for (const [uid, ids] of entries) {
            next[uid] = ids;
        }
        managedSiteIdsByUser = next;
    }

    // Diff-and-apply site grants for a member. POST for added, DELETE for
    // removed, in parallel. On failure roll back optimistic state.
    async function updateMemberSites(userId: string, nextSiteIds: string[]) {
        const previous = managedSiteIdsByUser[userId] ?? [];
        const added = nextSiteIds.filter((id) => !previous.includes(id));
        const removed = previous.filter((id) => !nextSiteIds.includes(id));
        if (added.length === 0 && removed.length === 0) return;
        // Optimistic update
        managedSiteIdsByUser = { ...managedSiteIdsByUser, [userId]: nextSiteIds };
        try {
            await Promise.all([
                ...added.map((siteId) =>
                    api.post(`/sites/${siteId}/managers`, { user_id: userId }),
                ),
                ...removed.map((siteId) =>
                    api.delete(`/sites/${siteId}/managers/${userId}`),
                ),
            ]);
        } catch (e: unknown) {
            // Rollback
            managedSiteIdsByUser = {
                ...managedSiteIdsByUser,
                [userId]: previous,
            };
            toast.error(
                'Failed to update site grants',
                e instanceof Error ? e.message : '',
            );
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
            const result = await api.get(`/iam/teams/${teamId}/members`, {
                schema: z.array(z.record(z.string(), z.unknown())),
            });
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

    let inviteSending = $state(false);
    let pendingInvitations = $state<any[]>([]);

    // Load pending invitations for this org
    async function loadInvitations() {
        const org = getCurrentOrg();
        if (!org) return;
        try {
            pendingInvitations = await api.get(`/iam/organizations/${org.id}/invitations`);
        } catch {
            pendingInvitations = [];
        }
    }

    // Send invitation by email
    async function sendInvitation() {
        const org = getCurrentOrg();
        if (!org || !inviteEmail.trim()) return;
        inviteSending = true;
        try {
            await api.post(`/iam/organizations/${org.id}/invitations`, {
                email: inviteEmail.trim(),
                role: 'MEMBER',
            });
            toast.success('Invitation sent', `Sent to ${inviteEmail.trim()}`);
            inviteEmail = '';
            showInviteDialog = false;
            await loadInvitations();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to send invitation');
        } finally {
            inviteSending = false;
        }
    }

    // Resend invitation (new token + reset expiry + resend email)
    async function resendInvitation(invitation: any) {
        try {
            await api.post(`/iam/invitations/${invitation.id}/resend`);
            toast.success('Invitation resent', `Sent to ${invitation.invited_email}`);
            await loadInvitations();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to resend invitation');
        }
    }

    // Revoke invitation
    async function revokeInvitation(invitationId: string) {
        try {
            await api.delete(`/iam/invitations/${invitationId}`);
            toast.success('Invitation revoked');
            await loadInvitations();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to revoke invitation');
        }
    }

    // Remove member from org
    async function removeMember(userId: string) {
        const org = getCurrentOrg();
        if (!org) return;
        try {
            await api.delete(`/iam/organizations/${org.id}/members/${userId}`);
            await loadMembers();
        } catch (e: unknown) {
            console.error('Failed to remove member:', e instanceof Error ? e.message : e);
        }
    }

    // Update member roles (multi-role) with optimistic update.
    // If SITE_MANAGER is being removed while the member still holds grants,
    // bounce through a confirm dialog before issuing the bulk DELETE +
    // role patch.
    async function updateMemberRoles(userId: string, roles: string[]) {
        const org = getCurrentOrg();
        if (!org) return;
        const member = members.find((m) => m.user_id === userId);
        if (!member) return;
        const wasSiteManager = (member.roles ?? []).includes('SITE_MANAGER');
        const willBeSiteManager = roles.includes('SITE_MANAGER');
        const grantCount = (managedSiteIdsByUser[userId] ?? []).length;
        if (wasSiteManager && !willBeSiteManager && grantCount > 0) {
            pendingRevoke = {
                userId,
                userLabel: member.full_name || member.email || 'this member',
                nextRoles: roles,
                siteCount: grantCount,
            };
            confirmRevokeOpen = true;
            return;
        }
        await applyMemberRolesUpdate(userId, roles);
    }

    async function applyMemberRolesUpdate(userId: string, roles: string[]) {
        const org = getCurrentOrg();
        if (!org) return;
        const member = members.find((m) => m.user_id === userId);
        if (!member) return;
        const previousRoles = member.roles;
        member.roles = roles;
        try {
            const updated = await api.patch(
                `/iam/organizations/${org.id}/members/${userId}`,
                { roles },
            );
            if (updated && Array.isArray(updated.roles)) {
                member.roles = updated.roles;
            }
        } catch (e: unknown) {
            member.roles = previousRoles;
            toast.error(
                'Failed to update roles',
                e instanceof Error ? e.message : '',
            );
        }
    }

    async function confirmRevokeSiteManager() {
        if (!pendingRevoke) return;
        const { userId, nextRoles } = pendingRevoke;
        // Clear grants first so backend state is consistent before the
        // role bit drops.
        await updateMemberSites(userId, []);
        await applyMemberRolesUpdate(userId, nextRoles);
        confirmRevokeOpen = false;
        pendingRevoke = null;
    }

    function cancelRevokeSiteManager() {
        confirmRevokeOpen = false;
        pendingRevoke = null;
        // No state to roll back; the picker's local checkbox is driven by
        // the row.roles prop, so re-rendering with unchanged roles
        // restores its visual state.
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
        } catch (e: unknown) {
            console.error('Failed to create team:', e instanceof Error ? e.message : e);
        }
    }

    // Delete team
    async function deleteTeam(teamId: string) {
        const org = getCurrentOrg();
        if (!org) return;
        try {
            await api.delete(`/iam/organizations/${org.id}/teams/${teamId}`);
            await loadTeams();
        } catch (e: unknown) {
            console.error('Failed to delete team:', e instanceof Error ? e.message : e);
        }
    }

    onMount(() => {
        loadMembers();
        loadInvitations();
        loadTeams();
    });

    // Auto-load notifications channel list once when the notifications tab
    // is active. Guarded by a one-shot `channelsLoaded` latch — the effect
    // must never read `channels`, or reassigning it to [] re-triggers the load.
    $effect(() => {
        if (activeTab === 'notifications' && !channelsLoaded && !channelsLoading) {
            loadChannels();
        }
    });
</script>

<div class="max-w-6xl mx-auto space-y-8">
    <div>
        <h1 class="text-3xl font-bold tracking-tight">Settings</h1>
        <p class="text-muted-foreground">Manage your organization, teams, and profile.</p>
    </div>

    <!-- Tabs -->
    <div class="flex border-b border-border overflow-x-auto">
        <Button
            variant="tab"
            data-active={activeTab === 'organization'}
            onclick={() => setTab('organization')}
            class="py-2.5 min-h-11"
        >
            Organization
        </Button>
        <Button
            variant="tab"
            data-active={activeTab === 'teams'}
            onclick={() => setTab('teams')}
            class="py-2.5 min-h-11"
        >
            Teams
        </Button>
        <Button
            variant="tab"
            data-active={activeTab === 'sites'}
            onclick={() => setTab('sites')}
            class="py-2.5 min-h-11"
        >
            Sites &amp; Equipment
        </Button>
        <Button
            variant="tab"
            data-active={activeTab === 'profile'}
            onclick={() => setTab('profile')}
            class="py-2.5 min-h-11"
        >
            Profile
        </Button>
        <Button
            variant="tab"
            data-active={activeTab === 'appearance'}
            onclick={() => setTab('appearance')}
            class="py-2.5 min-h-11"
        >
            Appearance
        </Button>
        <Button
            variant="tab"
            data-active={activeTab === 'notifications'}
            onclick={() => setTab('notifications')}
            class="py-2.5 min-h-11"
        >
            Notifications
        </Button>
        <Button
            variant="tab"
            data-active={activeTab === 'ai'}
            onclick={() => setTab('ai')}
            class="py-2.5 min-h-11"
        >
            AI Models
        </Button>
        <Button
            variant="tab"
            data-active={activeTab === 'templates'}
            onclick={() => setTab('templates')}
            class="py-2.5 min-h-11"
        >
            Templates
        </Button>
        <Button
            variant="tab"
            data-active={activeTab === 'billing'}
            onclick={() => setTab('billing')}
            class="py-2.5 min-h-11"
        >
            Billing
        </Button>
        <Button
            variant="tab"
            data-active={activeTab === 'legal'}
            onclick={() => setTab('legal')}
            class="py-2.5 min-h-11"
        >
            Legal
        </Button>
    </div>

    <!-- Organization Tab -->
    {#if activeTab === 'organization'}
        <Card>
            <CardHeader>
                <div class="flex items-center justify-between">
                    <div>
                        <CardTitle>{getCurrentOrg()?.name || 'No Organization'}</CardTitle>
                        <CardDescription>Members and invitations for your organization.</CardDescription>
                    </div>
                    <div class="flex items-center gap-2">
                        {#if isOrgAdmin && pendingInvitations.length > 0}
                            <div class="flex gap-1">
                                {#each [{ value: 'all', label: 'All' }, { value: 'active', label: 'Active' }, { value: 'pending', label: 'Pending' }] as filter}
                                    <Button
                                        size="sm"
                                        rounded="full"
                                        class="h-auto px-3 py-1 text-xs font-medium shadow-none {memberStatusFilter === filter.value ? 'bg-foreground text-background hover:bg-foreground/90' : 'bg-muted text-muted-foreground hover:text-foreground hover:bg-muted/80'}"
                                        onclick={() => { memberStatusFilter = filter.value as any; }}
                                    >
                                        {filter.label}
                                    </Button>
                                {/each}
                            </div>
                        {/if}
                        {#if isOrgAdmin}
                            <Button size="sm" onclick={() => (showInviteDialog = true)}>
                                Invite Member
                            </Button>
                        {/if}
                    </div>
                </div>
            </CardHeader>
            <CardContent class="space-y-4">
                <!-- Invite form (inline, collapsible) -->
                {#if isOrgAdmin && showInviteDialog}
                    <div class="flex gap-2 p-3 rounded-md border border-dashed">
                        <Input
                            bind:value={inviteEmail}
                            placeholder="colleague@company.com"
                            type="email"
                        />
                        <Button onclick={sendInvitation} disabled={inviteSending || !inviteEmail.trim()}>
                            {inviteSending ? 'Sending...' : 'Send Invite'}
                        </Button>
                        <Button variant="outline" onclick={() => { showInviteDialog = false; inviteEmail = ''; }}>
                            Cancel
                        </Button>
                    </div>
                {/if}
            </CardContent>

            {#if membersLoading}
                <div in:fade={{ duration: blockDuration() }} class="px-8 py-8 text-center">
                    <p class="text-sm text-muted-foreground">Loading members...</p>
                </div>
            {:else if membersError}
                <div in:fade={{ duration: blockDuration() }} class="px-8 py-8 text-center">
                    <p class="text-sm text-destructive">{membersError}</p>
                </div>
            {:else}
                <ProjectDataTable
                    items={allRows}
                    columns={memberColumnsAdmin}
                    filterPlaceholder="Filter members..."
                    defaultSortKey="name"
                    defaultSortDir="asc"
                    filterFn={memberFilterFn}
                >
                    {#snippet mobileCard(row)}
                        <div class="py-3">
                            <div class="flex items-center justify-between mb-1">
                                <div class="flex items-center gap-2">
                                    <div class="w-7 h-7 rounded-full {row.type === 'member' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'} flex items-center justify-center text-xs font-semibold">
                                        {#if row.type === 'member'}
                                            {getInitials(row.name, row.email)}
                                        {:else}
                                            <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4 20-7z"/></svg>
                                        {/if}
                                    </div>
                                    <span class="text-sm font-medium">{row.name || row.email}</span>
                                </div>
                                {#if row.status === 'Active'}
                                    <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">Active</span>
                                {:else if row.status === 'Expired'}
                                    <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">Expired</span>
                                {:else}
                                    <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">Pending</span>
                                {/if}
                            </div>
                            <div class="flex items-center gap-2 text-xs text-muted-foreground ml-9">
                                {#if row.type === 'member'}
                                    <div onclick={(e) => e.stopPropagation()} role="presentation">
                                        <MemberRolesPicker
                                            roles={row.roles}
                                            disabled={!isOrgAdmin}
                                            allSites={allSites.filter((s) => !s.archived_at)}
                                            selectedSiteIds={managedSiteIdsByUser[row.id] ?? []}
                                            onChange={(roles) => updateMemberRoles(row.id, roles)}
                                            onSitesChange={(siteIds) => updateMemberSites(row.id, siteIds)}
                                        />
                                    </div>
                                {:else}
                                    <span>{row.role || 'Member'}</span>
                                {/if}
                                <span>&middot;</span>
                                <span>{row.date ? formatDate(row.date) : '—'}</span>
                            </div>
                        </div>
                    {/snippet}

                    {#snippet cells(row)}
                        <td class="py-3 px-4 pl-6 sm:pl-10">
                            <div class="flex items-center gap-3">
                                <div class="w-8 h-8 rounded-full {row.type === 'member' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'} flex items-center justify-center text-xs font-semibold">
                                    {#if row.type === 'member'}
                                        {getInitials(row.name, row.email)}
                                    {:else}
                                        <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4 20-7z"/></svg>
                                    {/if}
                                </div>
                                <div>
                                    <p class="text-sm font-medium text-slate-800">{row.name || row.email}</p>
                                    {#if row.name}
                                        <p class="text-xs text-muted-foreground">{row.email}</p>
                                    {/if}
                                </div>
                            </div>
                        </td>
                        <td class="py-3 px-4 text-center">
                            {#if row.type === 'member'}
                                <div
                                    class="flex justify-center"
                                    onclick={(e) => e.stopPropagation()}
                                    role="presentation"
                                >
                                    <MemberRolesPicker
                                        roles={row.roles}
                                        disabled={!isOrgAdmin}
                                        allSites={allSites.filter((s) => !s.archived_at)}
                                        selectedSiteIds={managedSiteIdsByUser[row.id] ?? []}
                                        onChange={(roles) => updateMemberRoles(row.id, roles)}
                                        onSitesChange={(siteIds) => updateMemberSites(row.id, siteIds)}
                                    />
                                </div>
                            {:else}
                                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700">
                                    {row.role || 'Member'}
                                </span>
                            {/if}
                        </td>
                        <td class="py-3 px-4 text-center">
                            {#if row.status === 'Active'}
                                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">Active</span>
                            {:else if row.status === 'Expired'}
                                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">Expired</span>
                            {:else}
                                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">Pending</span>
                            {/if}
                        </td>
                        <td class="py-3 px-4 text-center text-xs text-muted-foreground whitespace-nowrap">
                            {row.date ? formatDate(row.date) : '—'}
                        </td>
                        {#if isOrgAdmin}
                            <td class="py-3 px-4 pr-6 sm:pr-10 text-right whitespace-nowrap">
                                {#if row.type === 'member'}
                                    <Button variant="ghost" size="sm" class="text-destructive" onclick={(e) => { e.stopPropagation(); removeMember(row.id); }}>
                                        Remove
                                    </Button>
                                {:else}
                                    <div class="flex gap-1 justify-end">
                                        <Button size="sm" variant="outline" onclick={(e) => { e.stopPropagation(); resendInvitation(row.raw); }}>
                                            Resend
                                        </Button>
                                        <Button size="sm" variant="ghost" class="text-destructive" onclick={(e) => { e.stopPropagation(); revokeInvitation(row.id); }}>
                                            Revoke
                                        </Button>
                                    </div>
                                {/if}
                            </td>
                        {/if}
                    {/snippet}

                    {#snippet empty()}
                        <p class="text-[15px] font-semibold text-slate-600">No members yet</p>
                        <p class="text-[13px] text-slate-400">Invite someone to get started.</p>
                    {/snippet}
                </ProjectDataTable>
            {/if}

            {#if isOrgAdmin}
                <CardContent class="border-t pt-6">
                    <h3 class="text-sm font-semibold mb-1">Unit Operation Libraries</h3>
                    <p class="text-sm text-muted-foreground mb-3">
                        Refresh the catalog of system unit operations after a deployment
                        or library file update.
                    </p>
                    <div class="flex items-center gap-3">
                        <Button onclick={reloadLibraries} disabled={reloading}>
                            {reloading ? 'Reloading...' : 'Reload Libraries'}
                        </Button>
                        {#if lastReloadedAt}
                            <span class="text-xs text-muted-foreground">Last reloaded: {formatRelative(lastReloadedAt)}</span>
                        {/if}
                    </div>
                </CardContent>
            {/if}
        </Card>

        <div class="mt-6">
            <OrgProtocolApproversCard canManage={isOrgAdmin} />
        </div>

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
                {#if isOrgAdmin}
                    <!-- Create team -->
                    <div class="flex gap-2">
                        <Input
                            bind:value={newTeamName}
                            placeholder="New team name..."
                            onkeydown={(e) => { if (e.key === 'Enter') createTeam(); }}
                        />
                        <Button onclick={createTeam} disabled={!newTeamName.trim()}>Create</Button>
                    </div>
                {/if}

                {#if teamsLoading}
                    <p in:fade={{ duration: blockDuration() }} class="text-sm text-muted-foreground py-4 text-center">Loading teams...</p>
                {:else if teams.length === 0}
                    <p in:fade={{ duration: blockDuration() }} class="text-sm text-muted-foreground py-4 text-center">No teams yet. Create one above.</p>
                {:else}
                    <div class="divide-y divide-border rounded-md border">
                        {#each teams as team (team.id)}
                            <div animate:flip={{ duration: listDuration() }} in:fade={{ duration: listDuration() }}>
                                <div class="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-muted/50 transition-colors duration-150" onclick={() => toggleTeam(team.id)}>
                                    <div class="flex items-center gap-2">
                                        <span class="text-xs text-muted-foreground">{expandedTeamId === team.id ? '▼' : '▶'}</span>
                                        <span class="text-sm font-medium">{team.name}</span>
                                    </div>
                                    {#if isOrgAdmin}
                                        <Button variant="ghost" size="sm" class="text-destructive" onclick={(e) => { e.stopPropagation(); deleteTeam(team.id); }}>
                                            Delete
                                        </Button>
                                    {/if}
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

    <!-- Sites & Equipment Tab -->
    {:else if activeTab === 'sites'}
        <SitesEquipmentTab />

    <!-- Profile Tab -->
    {:else if activeTab === 'profile'}
        <!-- Avatar & Profile Info -->
        <Card>
            <CardHeader>
                <CardTitle>Profile</CardTitle>
                <CardDescription>Your account information and avatar.</CardDescription>
            </CardHeader>
            <CardContent class="space-y-6">
                <!-- Avatar -->
                <div class="flex items-center gap-6">
                    <div class="relative">
                        {#if avatarUrl()}
                            <img
                                src={avatarUrl()}
                                alt="Avatar"
                                class="w-20 h-20 rounded-full object-cover border-2 border-border"
                            />
                        {:else}
                            <div class="w-20 h-20 rounded-full bg-primary/10 text-primary flex items-center justify-center text-2xl font-semibold border-2 border-border">
                                {getInitials(getUser()?.full_name || null, getUser()?.email || '')}
                            </div>
                        {/if}
                        {#if avatarUploading}
                            <div in:fade={{ duration: blockDuration() }} class="absolute inset-0 rounded-full bg-background/70 flex items-center justify-center">
                                <div class="w-5 h-5 border-2 border-muted-foreground/30 border-t-primary rounded-full animate-spin"></div>
                            </div>
                        {/if}
                    </div>
                    <div class="flex flex-col gap-2">
                        <input
                            type="file"
                            accept="image/jpeg,image/png,image/webp"
                            class="hidden"
                            bind:this={avatarFileInput}
                            onchange={uploadAvatar}
                        />
                        <Button size="sm" variant="outline" onclick={() => avatarFileInput.click()} disabled={avatarUploading}>
                            Upload Photo
                        </Button>
                        {#if avatarUrl()}
                            <Button size="sm" variant="ghost" class="text-destructive" onclick={removeAvatar} disabled={avatarUploading}>
                                Remove
                            </Button>
                        {/if}
                        <p class="text-xs text-muted-foreground">JPEG, PNG, or WebP. Max 5 MB.</p>
                    </div>
                </div>

                <!-- Profile Fields -->
                <div class="grid gap-4 sm:grid-cols-2">
                    <div class="space-y-2">
                        <Label>Full Name</Label>
                        <Input bind:value={profileName} placeholder="Your name" />
                    </div>
                    <div class="space-y-2">
                        <Label>Job Title</Label>
                        <Input bind:value={profileJobTitle} placeholder="e.g. Process Development Scientist" />
                    </div>
                </div>
                <div class="space-y-2">
                    <Label>Email</Label>
                    <Input value={getUser()?.email || ''} disabled />
                    <p class="text-xs text-muted-foreground">Email cannot be changed.</p>
                </div>

                <div class="flex items-center gap-3">
                    <Button onclick={saveProfile} disabled={profileSaving}>
                        {profileSaving ? 'Saving...' : 'Save Profile'}
                    </Button>
                    {#if profileMessage}
                        <span class="text-sm text-muted-foreground">{profileMessage}</span>
                    {/if}
                </div>
            </CardContent>
        </Card>

        <SignatureCard />

        <!-- Password -->
        <Card>
            <CardHeader>
                <CardTitle>Change Password</CardTitle>
            </CardHeader>
            <CardContent class="space-y-4">
                <div class="space-y-2">
                    <Label>Current Password</Label>
                    <Input type="password" bind:value={currentPassword} />
                </div>
                <div class="grid gap-4 sm:grid-cols-2">
                    <div class="space-y-2">
                        <Label>New Password</Label>
                        <Input type="password" bind:value={newPassword} />
                    </div>
                    <div class="space-y-2">
                        <Label>Confirm New Password</Label>
                        <Input type="password" bind:value={confirmPassword} />
                    </div>
                </div>
                {#if passwordError}
                    <p in:fade={{ duration: blockDuration() }} class="text-sm text-destructive">{passwordError}</p>
                {/if}
                <div class="flex items-center gap-3">
                    <Button onclick={changePassword} disabled={passwordSaving || !currentPassword || !newPassword}>
                        {passwordSaving ? 'Changing...' : 'Change Password'}
                    </Button>
                    {#if passwordMessage}
                        <span class="text-sm text-muted-foreground">{passwordMessage}</span>
                    {/if}
                </div>
            </CardContent>
        </Card>

        <!-- App Preferences -->
        <Card>
            <CardHeader>
                <CardTitle>Preferences</CardTitle>
                <CardDescription>Customize the app appearance.</CardDescription>
            </CardHeader>
            <CardContent class="space-y-6">
                <!-- Font Size -->
                <div class="space-y-2">
                    <Label>Font Size</Label>
                    <div class="flex gap-2">
                        {#each [['small', 'Small'], ['medium', 'Medium'], ['large', 'Large']] as [value, label]}
                            <Button
                                variant={fontSize === value ? 'default' : 'outline'}
                                onclick={() => { fontSize = value; savePreferences(); }}
                            >
                                {label}
                            </Button>
                        {/each}
                    </div>
                </div>

                <!-- Density -->
                <div class="space-y-2">
                    <Label>Density</Label>
                    <div class="flex gap-2">
                        {#each [['comfortable', 'Comfortable'], ['compact', 'Compact']] as [value, label]}
                            <Button
                                variant={density === value ? 'default' : 'outline'}
                                onclick={() => { density = value; savePreferences(); }}
                            >
                                {label}
                            </Button>
                        {/each}
                    </div>
                </div>

                {#if prefsSaving}
                    <p class="text-sm text-muted-foreground">Saving...</p>
                {/if}
            </CardContent>
        </Card>

    <!-- Appearance Tab -->
    {:else if activeTab === 'appearance'}
        <AppearanceTab />

    <!-- Notifications Tab -->
    {:else if activeTab === 'notifications'}
        <Card>
            <CardHeader>
                <div class="flex items-center justify-between">
                    <div>
                        <CardTitle>Notification Channels</CardTitle>
                        <CardDescription>Configure where you receive notifications — Slack, email, webhooks, and more.</CardDescription>
                    </div>
                    <Button size="sm" onclick={() => { showAddChannel = true; newChannelType = 'SLACK'; newChannelName = ''; newChannelConfig = {}; }}>
                        Add Channel
                    </Button>
                </div>
            </CardHeader>
            <CardContent>
                {#if channelsLoading || !channelsLoaded}
                    <p in:fade={{ duration: blockDuration() }} class="text-sm text-muted-foreground py-4 text-center">Loading channels...</p>
                {:else if channels.length === 0 && !showAddChannel}
                    <div in:fade={{ duration: blockDuration() }} class="text-center py-8">
                        <p class="text-sm text-muted-foreground mb-3">No notification channels configured yet.</p>
                        <Button size="sm" variant="outline" onclick={() => { showAddChannel = true; newChannelType = 'SLACK'; newChannelName = ''; newChannelConfig = {}; }}>
                            Add your first channel
                        </Button>
                    </div>
                {:else}
                    <div class="divide-y divide-border">
                        {#each channels as channel (channel.id)}
                            <div class="py-3" animate:flip={{ duration: listDuration() }} in:fade={{ duration: listDuration() }}>
                                <div class="flex items-center justify-between">
                                    <Button variant="ghost" class="flex items-center gap-3 text-left flex-1 min-w-0 h-auto py-0 px-0 justify-start" onclick={() => toggleExpandChannel(channel.id)}>
                                        <span class="text-xs text-muted-foreground">{expandedChannelId === channel.id ? '▼' : '▶'}</span>
                                        <div class="min-w-0">
                                            <p class="text-sm font-medium truncate">{channel.name}</p>
                                            <p class="text-xs text-muted-foreground">{getChannelTypeLabel(channel.channel_type)}</p>
                                        </div>
                                    </Button>
                                    <div class="flex items-center gap-2 shrink-0">
                                        {#if channelTestResults.has(channel.id)}
                                            {@const result = channelTestResults.get(channel.id)}
                                            <span class="text-xs {result?.status === 'SENT' ? 'text-green-600' : result?.status === 'TESTING' ? 'text-muted-foreground' : 'text-destructive'}">
                                                {result?.status === 'TESTING' ? 'Sending...' : result?.status === 'SENT' ? 'Sent!' : 'Failed'}
                                            </span>
                                        {/if}
                                        <Button variant="ghost" size="sm" onclick={() => testChannel(channel.id)}>
                                            Test
                                        </Button>
                                        <button
                                            type="button"
                                            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors {channel.enabled ? 'bg-primary' : 'bg-muted'}"
                                            role="switch"
                                            aria-checked={channel.enabled}
                                            onclick={() => toggleChannelEnabled(channel.id, channel.enabled)}
                                        >
                                            <span class="pointer-events-none block h-4 w-4 rounded-full bg-background shadow-sm transition-transform {channel.enabled ? 'translate-x-4' : 'translate-x-0'}"></span>
                                        </button>
                                        <Button variant="ghost" size="sm" class="text-destructive" onclick={() => deleteChannel(channel.id)}>
                                            Remove
                                        </Button>
                                    </div>
                                </div>

                                {#if expandedChannelId === channel.id}
                                    <div class="mt-3 ml-7 space-y-3">
                                        <div>
                                            <p class="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Subscribed Events</p>
                                            <div class="grid grid-cols-2 gap-1.5">
                                                {#each EVENT_TYPES as evt}
                                                    {@const subscribed = isEventSubscribed(channel.id, evt.value)}
                                                    <label class="flex items-center gap-2 text-sm cursor-pointer py-1 px-2 rounded hover:bg-muted/50">
                                                        <input
                                                            type="checkbox"
                                                            checked={subscribed}
                                                            onchange={() => toggleSubscription(channel.id, evt.value)}
                                                            class="rounded border-border"
                                                        />
                                                        {evt.label}
                                                    </label>
                                                {/each}
                                            </div>
                                        </div>
                                    </div>
                                {/if}
                            </div>
                        {/each}
                    </div>
                {/if}
            </CardContent>
        </Card>

        <!-- Add Channel Form -->
        {#if showAddChannel}
            <Card>
                <CardHeader>
                    <CardTitle>Add Notification Channel</CardTitle>
                    <CardDescription>Choose a channel type and configure its settings.</CardDescription>
                </CardHeader>
                <CardContent class="space-y-4">
                    <div class="space-y-2">
                        <Label>Channel Type</Label>
                        <div class="flex flex-wrap gap-2">
                            {#each CHANNEL_TYPES as ct}
                                <Button
                                    variant={newChannelType === ct.value ? 'default' : 'outline'}
                                    size="sm"
                                    onclick={() => { newChannelType = ct.value; newChannelConfig = {}; }}
                                >
                                    {ct.label}
                                </Button>
                            {/each}
                        </div>
                    </div>

                    <div class="space-y-2">
                        <Label>Channel Name</Label>
                        <Input bind:value={newChannelName} placeholder="e.g. My Slack DMs" />
                    </div>

                    {#each CONFIG_FIELDS[newChannelType] || [] as field}
                        <div class="space-y-2">
                            <Label>{field.label}</Label>
                            <Input
                                type={field.type || 'text'}
                                value={newChannelConfig[field.key] || ''}
                                oninput={(e) => { newChannelConfig = { ...newChannelConfig, [field.key]: e.currentTarget.value }; }}
                                placeholder={field.placeholder}
                            />
                        </div>
                    {/each}

                    <div class="flex items-center gap-2 pt-2">
                        <Button onclick={addChannel} disabled={channelSaving || !newChannelName.trim()}>
                            {channelSaving ? 'Saving...' : 'Add Channel'}
                        </Button>
                        <Button variant="outline" onclick={() => { showAddChannel = false; }}>
                            Cancel
                        </Button>
                    </div>
                </CardContent>
            </Card>
        {/if}

    {:else if activeTab === 'ai'}
        <Card>
            <CardHeader>
                <CardTitle>AI Models</CardTitle>
                <CardDescription>Configure AI providers for each capability</CardDescription>
            </CardHeader>
            <CardContent>
                <AiSettingsTab isAdmin={isOrgAdmin} />
            </CardContent>
        </Card>

    {:else if activeTab === 'templates'}
        <TemplatesTab isAdmin={isOrgAdmin} />
    {:else if activeTab === 'billing'}
        <BillingTab />

    <!-- Legal Tab -->
    {:else if activeTab === 'legal'}
        <Card>
            <CardHeader>
                <CardTitle>Legal</CardTitle>
                <CardDescription>
                    Terms of Service and Privacy Policy you have accepted.
                </CardDescription>
            </CardHeader>
            <CardContent>
                {#if currentUser?.tos_accepted_at && currentUser?.tos_version}
                    <p class="text-sm text-muted-foreground mb-6">
                        You accepted our Terms of Service version
                        <strong class="text-foreground">{currentUser.tos_version}</strong>
                        on
                        <strong class="text-foreground">{formatLegalDate(currentUser.tos_accepted_at)}</strong>.
                    </p>
                {:else}
                    <p class="text-sm text-muted-foreground mb-6">
                        You have not yet accepted our Terms of Service.
                    </p>
                {/if}
                <div class="flex flex-wrap gap-4 text-sm">
                    <a
                        href="/legal/terms"
                        class="underline text-foreground hover:text-primary transition-all duration-150 cursor-pointer"
                    >View Terms of Service</a>
                    <a
                        href="/legal/privacy"
                        class="underline text-foreground hover:text-primary transition-all duration-150 cursor-pointer"
                    >View Privacy Policy</a>
                </div>
            </CardContent>
        </Card>
    {/if}
</div>

<ConfirmDialog
    bind:open={confirmRevokeOpen}
    title="Remove site manager role?"
    message={pendingRevoke
        ? `Revoke ${pendingRevoke.siteCount} site grant(s) for ${pendingRevoke.userLabel}?`
        : ''}
    confirmLabel="Revoke"
    confirmVariant="danger"
    onConfirm={confirmRevokeSiteManager}
    onCancel={cancelRevokeSiteManager}
/>
