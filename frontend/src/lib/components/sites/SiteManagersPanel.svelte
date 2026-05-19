<!-- frontend/src/lib/components/sites/SiteManagersPanel.svelte
     ADMIN-only panel: list, grant, and revoke per-site SITE_MANAGER grants.
     The caller (site detail route) is responsible for gating render to ADMINs;
     this panel does NOT re-check permission. -->
<script lang="ts">
    import { api } from '$lib/api';
    import { getCurrentOrg } from '$lib/auth.svelte';
    import SiteManagerAddPicker from './SiteManagerAddPicker.svelte';

    interface Grant {
        id: string;
        user_id: string;
        site_id: string;
        granted_by_id: string | null;
        created_at: string;
        user?: {
            id?: string;
            name?: string | null;
            email?: string | null;
        } | null;
    }

    interface Props {
        siteId: string;
    }

    let { siteId }: Props = $props();

    let grants = $state<Grant[]>([]);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let pickerOpen = $state(false);
    let removingUserId = $state<string | null>(null);
    let removingBusy = $state(false);

    const org = $derived(getCurrentOrg());
    const grantedUserIds = $derived(grants.map((g) => g.user_id));

    async function load() {
        loading = true;
        error = null;
        try {
            const list = await api.get<Grant[]>(`/sites/${siteId}/managers`);
            grants = Array.isArray(list) ? list : [];
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load site managers.';
        } finally {
            loading = false;
        }
    }

    $effect(() => {
        // Re-load on siteId change
        if (siteId) {
            void load();
        }
    });

    function initials(name?: string | null, email?: string | null): string {
        if (name && name.trim().length > 0) {
            return name
                .trim()
                .split(/\s+/)
                .map((p) => p[0] ?? '')
                .slice(0, 2)
                .join('')
                .toUpperCase();
        }
        if (email && email.length > 0) {
            return email.slice(0, 2).toUpperCase();
        }
        return '??';
    }

    function formatDate(iso: string): string {
        try {
            return new Date(iso).toISOString().slice(0, 10);
        } catch {
            return iso;
        }
    }

    async function handlePickerConfirm(userIds: string[]) {
        await Promise.all(
            userIds.map((uid) =>
                api.post<Grant>(`/sites/${siteId}/managers`, { user_id: uid }),
            ),
        );
        pickerOpen = false;
        await load();
    }

    function askRemove(userId: string) {
        removingUserId = userId;
    }

    function cancelRemove() {
        removingUserId = null;
    }

    async function confirmRemove(userId: string) {
        removingBusy = true;
        try {
            await api.delete(`/sites/${siteId}/managers/${userId}`);
            removingUserId = null;
            await load();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to revoke grant.';
        } finally {
            removingBusy = false;
        }
    }
</script>

<section class="border border-border rounded-lg bg-white">
    <header class="flex items-center justify-between px-4 py-3 border-b border-border">
        <div>
            <div class="flex items-center gap-2">
                <span class="text-xs uppercase tracking-wide text-muted-foreground font-medium">Managers</span>
                <span class="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    {grants.length} granted
                </span>
            </div>
            <p class="text-xs text-muted-foreground mt-1">
                GLP-relevant edits route to these people.
            </p>
        </div>
        <button
            type="button"
            class="text-sm px-3 py-1.5 rounded-md border border-border bg-white hover:bg-muted cursor-pointer transition-all duration-150"
            onclick={() => (pickerOpen = true)}
        >
            + Add manager
        </button>
    </header>

    {#if error}
        <p class="px-4 py-2 text-xs text-destructive">{error}</p>
    {/if}

    {#if loading}
        <p class="px-4 py-6 text-xs text-muted-foreground">Loading…</p>
    {:else if grants.length === 0}
        <div class="px-4 py-8 text-center">
            <p class="text-sm font-medium text-foreground">No site managers.</p>
            <p class="text-xs text-muted-foreground mt-1 mb-3">
                Grant <span class="font-mono">SITE_MANAGER</span> to delegate calibration &amp; status edits for this site.
            </p>
            <button
                type="button"
                class="text-sm px-3 py-1.5 rounded-md border border-border bg-white hover:bg-muted cursor-pointer transition-all duration-150"
                onclick={() => (pickerOpen = true)}
            >
                + Add a manager
            </button>
        </div>
    {:else}
        <ul class="divide-y divide-border">
            {#each grants as g (g.id)}
                <li>
                    {#if removingUserId === g.user_id}
                        <div class="flex items-center gap-3 px-4 py-2.5 bg-destructive/5">
                            <span class="text-sm text-foreground flex-1">
                                Remove {g.user?.name ?? g.user?.email ?? 'this user'} as a site manager?
                            </span>
                            <button
                                type="button"
                                class="text-xs px-2 py-1 rounded-md text-muted-foreground hover:bg-muted cursor-pointer transition-all duration-150"
                                onclick={cancelRemove}
                                disabled={removingBusy}
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                class="text-xs px-2 py-1 rounded-md bg-destructive text-destructive-foreground hover:brightness-90 cursor-pointer transition-all duration-150"
                                onclick={() => confirmRemove(g.user_id)}
                                disabled={removingBusy}
                            >
                                {removingBusy ? 'Removing…' : 'Remove'}
                            </button>
                        </div>
                    {:else}
                        <div class="mgr-row flex items-center gap-3 px-4 py-2.5 hover:bg-muted/40 group">
                            <span class="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-semibold">
                                {initials(g.user?.name, g.user?.email)}
                            </span>
                            <div class="min-w-0 flex-1">
                                <div class="text-sm font-medium text-foreground truncate">
                                    {g.user?.name ?? '(unknown user)'}
                                </div>
                                <div class="text-xs text-muted-foreground font-mono truncate">
                                    {g.user?.email ?? ''}
                                </div>
                            </div>
                            <div class="text-right shrink-0 hidden sm:block">
                                <div class="text-xs text-muted-foreground font-mono">
                                    granted {formatDate(g.created_at)}
                                </div>
                            </div>
                            <button
                                type="button"
                                aria-label="Revoke grant"
                                title="Revoke grant"
                                class="opacity-0 group-hover:opacity-100 transition-opacity duration-150 cursor-pointer text-muted-foreground hover:text-destructive px-2"
                                onclick={() => askRemove(g.user_id)}
                            >
                                ✕
                            </button>
                        </div>
                    {/if}
                </li>
            {/each}
        </ul>
        <div class="px-4 py-2 text-xs text-muted-foreground border-t border-border bg-muted/30">
            Grants are per-site. ADMINs bypass entirely.
        </div>
    {/if}
</section>

{#if org}
    <SiteManagerAddPicker
        open={pickerOpen}
        orgId={org.id}
        alreadyGrantedUserIds={grantedUserIds}
        onClose={() => (pickerOpen = false)}
        onConfirm={handlePickerConfirm}
    />
{/if}
