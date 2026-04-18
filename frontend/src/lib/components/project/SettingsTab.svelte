<script lang="ts">
    import { onMount } from 'svelte';
    import { api } from "$lib/api";
    import { toast } from '$lib/toast';
    import { getCurrentOrg } from "$lib/auth.svelte";
    import { Button } from '$lib/components/ui/button';
    import { Badge } from '$lib/components/ui/badge';
    import { DocumentTemplateListSchema, type DocumentTemplate } from '$lib/schemas/templates';
    import TemplateConvertModal from '$lib/components/TemplateConvertModal.svelte';

    interface Props {
        projectId: string;
        project: any;
        onProjectUpdated: (project: any) => void;
    }

    let { projectId, project, onProjectUpdated }: Props = $props();

    let requireApproval = $state(false);
    let approvers = $state<any[]>([]);
    let orgMembers = $state<any[]>([]);
    let settingsLoaded = $state(false);
    let settingsSaving = $state(false);
    let settingsMessage = $state<string | null>(null);
    let newApproverUserId = $state<string>("");

    let permissionsEnabled = $state(false);
    let projectPermissions = $state<any[]>([]);
    let permissionsLoading = $state(false);
    let newGrantPrincipalType = $state<'USER' | 'TEAM'>('USER');
    let newGrantPrincipalId = $state('');
    let newGrantLevel = $state('EDIT');
    let teams = $state<any[]>([]);

    // Template state
    let allTemplates = $state<DocumentTemplate[]>([]);
    let templatesLoading = $state(true);
    let showConvert = $state(false);

    const projectTemplates = $derived(
        allTemplates.filter(t => t.project_id === projectId)
    );
    const orgTemplates = $derived(
        allTemplates.filter(t => !t.project_id)
    );

    async function loadProjectTemplates() {
        templatesLoading = true;
        try {
            // Load both org-level and project-level templates
            const [orgResult, projResult] = await Promise.all([
                api.get('/templates', { schema: DocumentTemplateListSchema }),
                api.get(`/templates?project_id=${projectId}`, {
                    schema: DocumentTemplateListSchema,
                }),
            ]);
            // Deduplicate (org list may include project templates)
            const seen = new Set<string>();
            const combined: DocumentTemplate[] = [];
            for (const t of [...projResult, ...orgResult]) {
                if (!seen.has(t.id)) {
                    seen.add(t.id);
                    combined.push(t);
                }
            }
            allTemplates = combined;
        } catch {
            allTemplates = [];
        } finally {
            templatesLoading = false;
        }
    }

    async function archiveTemplate(id: string) {
        try {
            await api.put(`/templates/${id}`, { status: 'ARCHIVED' });
            toast.success('Template archived');
            await loadProjectTemplates();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to archive');
        }
    }

    onMount(() => {
        loadProjectTemplates();
    });

    const PERMISSION_LEVELS = [
        { value: 'VIEWER', label: 'Viewer' },
        { value: 'EDIT', label: 'Editor' },
        { value: 'APPROVE', label: 'Approver' },
        { value: 'ADMIN', label: 'Admin' },
    ] as const;

    $effect(() => {
        loadSettings();
    });

    async function loadSettings() {
        if (settingsLoaded || !project) return;
        try {
            requireApproval = project.settings?.require_protocol_approval || false;
            permissionsEnabled = project.settings?.permissions_enabled || false;

            approvers = await api.get(`/projects/${projectId}/approvers`);

            const org = getCurrentOrg();
            if (org) {
                const memberList = await api.get<any[]>(`/iam/organizations/${org.id}/members`);
                orgMembers = memberList.map((m: any) => ({
                    id: m.user_id,
                    full_name: m.full_name,
                    email: m.email,
                }));
            }

            if (permissionsEnabled) {
                await loadProjectPermissions();
                await loadTeams();
            }

            settingsLoaded = true;
        } catch (e: unknown) {
            console.error("Failed to load settings:", e instanceof Error ? e.message : e);
        }
    }

    async function saveSettings() {
        if (!project) return;
        settingsSaving = true;
        settingsMessage = null;
        try {
            const updated: any = await api.put(`/projects/${projectId}`, {
                settings: {
                    ...project.settings,
                    require_protocol_approval: requireApproval,
                },
            });
            onProjectUpdated(updated);
            settingsMessage = "Settings saved";
            setTimeout(() => (settingsMessage = null), 2000);
        } catch (e: unknown) {
            settingsMessage = `Failed: ${e instanceof Error ? e.message : 'An error occurred'}`;
        } finally {
            settingsSaving = false;
        }
    }

    async function addApprover() {
        if (!newApproverUserId) return;
        try {
            const entry: any = await api.post(`/projects/${projectId}/approvers`, {
                principal_type: "USER",
                principal_id: newApproverUserId,
            });
            approvers = [...approvers, entry];
            newApproverUserId = "";
        } catch (e: unknown) {
            settingsMessage = `Failed: ${e instanceof Error ? e.message : 'An error occurred'}`;
            setTimeout(() => (settingsMessage = null), 3000);
        }
    }

    async function removeApprover(permId: string) {
        try {
            await api.delete(`/projects/${projectId}/approvers/${permId}`);
            approvers = approvers.filter((a: any) => a.id !== permId);
        } catch (e: unknown) {
            console.error("Failed to remove approver:", e instanceof Error ? e.message : e);
        }
    }

    async function loadProjectPermissions() {
        permissionsLoading = true;
        try {
            projectPermissions = await api.get(`/projects/${projectId}/permissions`);
        } catch {
            projectPermissions = [];
        } finally {
            permissionsLoading = false;
        }
    }

    async function loadTeams() {
        const org = getCurrentOrg();
        if (!org) return;
        try {
            teams = await api.get(`/iam/organizations/${org.id}/teams`);
        } catch {
            teams = [];
        }
    }

    async function togglePermissionsEnabled() {
        permissionsEnabled = !permissionsEnabled;
        settingsSaving = true;
        settingsMessage = null;
        try {
            const updated: any = await api.put(`/projects/${projectId}`, {
                settings: {
                    ...project.settings,
                    permissions_enabled: permissionsEnabled,
                },
            });
            onProjectUpdated(updated);
            settingsMessage = permissionsEnabled
                ? "Access control enabled"
                : "Access control disabled — all org members have Editor access";
            setTimeout(() => (settingsMessage = null), 3000);
            if (permissionsEnabled) {
                await loadProjectPermissions();
                await loadTeams();
            }
        } catch (e: unknown) {
            permissionsEnabled = !permissionsEnabled;
            settingsMessage = `Failed: ${e instanceof Error ? e.message : 'An error occurred'}`;
        } finally {
            settingsSaving = false;
        }
    }

    async function addPermissionGrant() {
        if (!newGrantPrincipalId) return;
        try {
            await api.post(`/iam/permissions`, {
                principal_type: newGrantPrincipalType,
                principal_id: newGrantPrincipalId,
                object_type: 'PROJECT',
                object_id: projectId,
                permission_level: newGrantLevel,
            });
            newGrantPrincipalId = '';
            newGrantLevel = 'EDIT';
            await loadProjectPermissions();
        } catch (e: unknown) {
            settingsMessage = `Failed: ${e instanceof Error ? e.message : 'An error occurred'}`;
            setTimeout(() => (settingsMessage = null), 3000);
        }
    }

    async function updatePermissionLevel(permissionId: string, level: string) {
        try {
            await api.put(`/projects/${projectId}/permissions/${permissionId}`, {
                permission_level: level,
            });
            await loadProjectPermissions();
        } catch (e: unknown) {
            settingsMessage = `Failed: ${e instanceof Error ? e.message : 'An error occurred'}`;
            setTimeout(() => (settingsMessage = null), 3000);
        }
    }

    async function removePermissionGrant(permissionId: string) {
        try {
            await api.delete(`/iam/permissions/${permissionId}`);
            await loadProjectPermissions();
        } catch (e: unknown) {
            console.error("Failed to remove permission:", e instanceof Error ? e.message : e);
        }
    }
</script>

<div class="p-8 max-w-2xl">
    <h3 class="text-lg font-bold text-slate-900 mb-1.5">Project Settings</h3>
    <p class="text-sm text-slate-500 mb-6">Manage project configuration.</p>

    {#if settingsMessage}
        <div class="mb-4 text-sm font-medium {settingsMessage.startsWith('Failed') ? 'text-red-600' : 'text-emerald-600'}">
            {settingsMessage}
        </div>
    {/if}

    <!-- Protocol Approval Section -->
    <div class="bg-white border border-slate-200 rounded-lg p-6 mb-6">
        <h4 class="text-sm font-bold text-slate-800 mb-1">Protocol Approval</h4>
        <p class="text-xs text-slate-500 mb-4">Require protocols to be approved before they can be used in runs.</p>

        <label class="flex items-center gap-3 cursor-pointer">
            <input
                type="checkbox"
                bind:checked={requireApproval}
                class="w-4 h-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
            />
            <span class="text-sm text-slate-700 font-medium">Require protocol approval before use</span>
        </label>
    </div>

    <!-- Approvers Section -->
    {#if requireApproval}
        <div class="bg-white border border-slate-200 rounded-lg p-6 mb-6">
            <h4 class="text-sm font-bold text-slate-800 mb-1">Approvers</h4>
            <p class="text-xs text-slate-500 mb-4">Users who can approve or reject protocols in this project.</p>

            {#if approvers.length === 0}
                <p class="text-xs text-slate-400 mb-4">No approvers assigned yet. Org admins can always approve.</p>
            {:else}
                <div class="space-y-2 mb-4">
                    {#each approvers as approver}
                        <div class="flex items-center justify-between py-2 px-3 bg-slate-50 rounded-lg">
                            <div class="flex items-center gap-2">
                                <div class="w-7 h-7 rounded-full bg-teal-100 text-teal-700 flex items-center justify-center text-xs font-bold">
                                    {(approver.name || "?")[0].toUpperCase()}
                                </div>
                                <div>
                                    <p class="text-sm font-medium text-slate-700">{approver.name || "Unknown"}</p>
                                    {#if approver.email}
                                        <p class="text-xs text-slate-400">{approver.email}</p>
                                    {/if}
                                </div>
                            </div>
                            <Button
                                variant="ghost"
                                size="sm"
                                class="h-auto p-0 text-xs text-slate-400 hover:text-red-500 hover:bg-transparent"
                                onclick={() => removeApprover(approver.id)}
                            >
                                Remove
                            </Button>
                        </div>
                    {/each}
                </div>
            {/if}

            <div class="flex gap-2">
                <select
                    bind:value={newApproverUserId}
                    class="flex-1 px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
                >
                    <option value="">Select a user...</option>
                    {#each orgMembers.filter((m) => !approvers.some((a) => a.principal_id === m.id)) as member}
                        <option value={member.id}>{member.full_name || member.email}</option>
                    {/each}
                </select>
                <Button
                    onclick={addApprover}
                    disabled={!newApproverUserId}
                >
                    Add
                </Button>
            </div>
        </div>
    {/if}

    <!-- Access Control Section -->
    <div class="bg-white border border-slate-200 rounded-lg p-6 mb-6">
        <h4 class="text-sm font-bold text-slate-800 mb-1">Access Control</h4>
        <p class="text-xs text-slate-500 mb-4">Restrict who can access this project. When off, all organization members have Editor access.</p>

        <label class="flex items-center gap-3 cursor-pointer">
            <button
                type="button"
                class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors {permissionsEnabled ? 'bg-teal-600' : 'bg-slate-300'}"
                role="switch"
                aria-checked={permissionsEnabled}
                aria-label="Restrict access to granted users and teams"
                onclick={togglePermissionsEnabled}
            >
                <span class="pointer-events-none block h-4 w-4 rounded-full bg-white shadow-sm transition-transform {permissionsEnabled ? 'translate-x-4' : 'translate-x-0'}"></span>
            </button>
            <span class="text-sm text-slate-700 font-medium">Restrict access to granted users and teams</span>
        </label>
    </div>

    <!-- Permission Grants -->
    {#if permissionsEnabled}
        <div class="bg-white border border-slate-200 rounded-lg p-6 mb-6">
            <h4 class="text-sm font-bold text-slate-800 mb-1">Permission Grants</h4>
            <p class="text-xs text-slate-500 mb-4">Manage who has access to this project and at what level. Org admins always have full access.</p>

            {#if permissionsLoading}
                <p class="text-xs text-slate-400 py-3 text-center">Loading permissions...</p>
            {:else if projectPermissions.length === 0}
                <p class="text-xs text-slate-400 mb-4">No grants yet. Only org admins can access this project.</p>
            {:else}
                <div class="space-y-2 mb-4">
                    {#each projectPermissions as perm}
                        <div class="flex items-center justify-between py-2 px-3 bg-slate-50 rounded-lg">
                            <div class="flex items-center gap-2">
                                <div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold {perm.principal_type === 'TEAM' ? 'bg-indigo-100 text-indigo-700' : 'bg-teal-100 text-teal-700'}">
                                    {perm.principal_type === 'TEAM' ? 'T' : (perm.name || '?')[0].toUpperCase()}
                                </div>
                                <div>
                                    <p class="text-sm font-medium text-slate-700">{perm.name || 'Unknown'}</p>
                                    {#if perm.email}
                                        <p class="text-xs text-slate-400">{perm.email}</p>
                                    {:else if perm.principal_type === 'TEAM'}
                                        <p class="text-xs text-slate-400">Team</p>
                                    {/if}
                                </div>
                            </div>
                            <div class="flex items-center gap-2">
                                <select
                                    class="px-2 py-1 border border-slate-200 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-teal-500"
                                    value={perm.permission_level}
                                    onchange={(e) => updatePermissionLevel(perm.id, e.currentTarget.value)}
                                >
                                    {#each PERMISSION_LEVELS as level}
                                        <option value={level.value}>{level.label}</option>
                                    {/each}
                                </select>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    class="h-auto p-0 text-xs text-slate-400 hover:text-red-500 hover:bg-transparent"
                                    onclick={() => removePermissionGrant(perm.id)}
                                >
                                    Remove
                                </Button>
                            </div>
                        </div>
                    {/each}
                </div>
            {/if}

            <!-- Add Grant -->
            <div class="flex gap-2 items-end">
                <div class="flex gap-1">
                    <Button
                        variant={newGrantPrincipalType === 'USER' ? 'default' : 'outline'}
                        size="sm"
                        class="h-auto px-2 py-1.5 text-xs font-medium rounded-r-none"
                        onclick={() => { newGrantPrincipalType = 'USER'; newGrantPrincipalId = ''; }}
                    >
                        User
                    </Button>
                    <Button
                        variant={newGrantPrincipalType === 'TEAM' ? 'default' : 'outline'}
                        size="sm"
                        class="h-auto px-2 py-1.5 text-xs font-medium rounded-l-none"
                        onclick={() => { newGrantPrincipalType = 'TEAM'; newGrantPrincipalId = ''; }}
                    >
                        Team
                    </Button>
                </div>
                <select
                    bind:value={newGrantPrincipalId}
                    class="flex-1 px-3 py-1.5 border border-slate-200 rounded text-sm bg-white focus:outline-none focus:ring-1 focus:ring-teal-500"
                >
                    <option value="">
                        {newGrantPrincipalType === 'USER' ? 'Select a user...' : 'Select a team...'}
                    </option>
                    {#if newGrantPrincipalType === 'USER'}
                        {#each orgMembers.filter((m) => !projectPermissions.some((p) => p.principal_id === m.id && p.principal_type === 'USER')) as member}
                            <option value={member.id}>{member.full_name || member.email}</option>
                        {/each}
                    {:else}
                        {#each teams.filter((t) => !projectPermissions.some((p) => p.principal_id === t.id && p.principal_type === 'TEAM')) as team}
                            <option value={team.id}>{team.name}</option>
                        {/each}
                    {/if}
                </select>
                <select
                    bind:value={newGrantLevel}
                    class="px-2 py-1.5 border border-slate-200 rounded text-sm bg-white focus:outline-none focus:ring-1 focus:ring-teal-500"
                >
                    {#each PERMISSION_LEVELS as level}
                        <option value={level.value}>{level.label}</option>
                    {/each}
                </select>
                <Button
                    size="sm"
                    onclick={addPermissionGrant}
                    disabled={!newGrantPrincipalId}
                >
                    Add
                </Button>
            </div>
        </div>
    {/if}

    <!-- Document Templates Section -->
    <div class="bg-white border border-slate-200 rounded-lg p-6 mb-6">
        <div class="flex items-center justify-between mb-4">
            <div>
                <h4 class="text-sm font-bold text-slate-800 mb-1">Document Templates</h4>
                <p class="text-xs text-slate-500">Templates scoped to this project for SOP and Batch Record exports.</p>
            </div>
            <Button variant="outline" size="sm" onclick={() => (showConvert = true)}>
                Convert Document
            </Button>
        </div>

        {#if templatesLoading}
            <p class="text-xs text-slate-400">Loading templates...</p>
        {:else if allTemplates.length === 0}
            <p class="text-xs text-slate-400">No templates yet. Convert a filled document to create one.</p>
        {:else}
            <div class="space-y-2">
                {#each allTemplates as template}
                    <div class="flex items-center justify-between p-3 border border-slate-100 rounded-lg">
                        <div>
                            <div class="flex items-center gap-2">
                                <p class="text-sm font-medium text-slate-800">{template.name}</p>
                                <div class="flex items-center gap-1">
                                    <Badge variant="outline">
                                        {template.template_type === 'SOP' ? 'Protocol' : 'Batch Record'}
                                    </Badge>
                                    <Badge variant={template.project_id === projectId ? 'default' : 'secondary'}>
                                        {template.project_id === projectId ? 'Project' : 'Organization'}
                                    </Badge>
                                    {#if template.is_default || template.is_current_default}
                                        <Badge variant="outline" class="border-emerald-300 text-emerald-700">Default</Badge>
                                    {/if}
                                </div>
                            </div>
                        </div>
                        {#if template.project_id === projectId}
                            <Button
                                variant="ghost"
                                size="sm"
                                class="h-auto p-0 text-xs text-slate-400 hover:text-red-500 hover:bg-transparent"
                                onclick={() => archiveTemplate(template.id)}
                            >
                                Archive
                            </Button>
                        {/if}
                    </div>
                {/each}
            </div>
        {/if}
    </div>

    <!-- Save Settings -->
    <Button onclick={saveSettings} disabled={settingsSaving}>
        {settingsSaving ? "Saving..." : "Save Settings"}
    </Button>
</div>

<!-- Convert Modal (project-scoped) -->
<TemplateConvertModal
    bind:open={showConvert}
    {projectId}
    onSuccess={() => loadProjectTemplates()}
/>
