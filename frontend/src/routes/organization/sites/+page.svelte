<script lang="ts">
    import { fade } from 'svelte/transition';
    import { api, ApiError } from '$lib/api';
    import { getToken, canManageSite, getCurrentOrgRoles } from '$lib/auth.svelte';
    import { API_BASE } from '$lib/config';
    import { toast } from '$lib/toast';
    import { Button } from '$lib/components/ui/button';
    import SiteList from '$lib/components/sites/SiteList.svelte';
    import SiteFormDialog from '$lib/components/sites/SiteFormDialog.svelte';
    import SiteArchiveWizardModal from '$lib/components/sites/SiteArchiveWizardModal.svelte';
    import SiteEmptyState from '$lib/components/sites/SiteEmptyState.svelte';
    import SiteManagersPanel from '$lib/components/sites/SiteManagersPanel.svelte';
    import EquipmentFilterBar from '$lib/components/equipment/EquipmentFilterBar.svelte';
    import EquipmentTable from '$lib/components/equipment/EquipmentTable.svelte';
    import EquipmentFormDialog from '$lib/components/equipment/EquipmentFormDialog.svelte';
    import EquipmentEmptyState from '$lib/components/equipment/EquipmentEmptyState.svelte';
    import {
        EquipmentListSchema,
        EquipmentSchema,
        type Equipment,
        type EquipmentCreate,
    } from '$lib/schemas/science';
    import {
        SiteListSchema,
        SiteSchema,
        type Site,
        type SiteCreate,
        type SiteArchiveRequest,
    } from '$lib/schemas/sites';

    interface FilterState {
        q: string;
        status: string | null;
        tag: string | null;
        includeArchived: boolean;
    }

    let { data } = $props<{ data: { sites: Site[]; equipment: Equipment[]; tags: string[] } }>();

    let sites = $state<Site[]>(data.sites);
    let equipment = $state<Equipment[]>(data.equipment);
    let tags = $state<string[]>(data.tags);
    let activeId = $state<string | null>(sites[0]?.id ?? null);

    let siteFormOpen = $state(false);
    let siteFormInitial = $state<Site | null>(null);
    let archiveOpen = $state(false);
    let equipmentFormOpen = $state(false);
    let equipmentFormInitial = $state<Equipment | null>(null);
    let filter = $state<FilterState>({
        q: '',
        status: null,
        tag: null,
        includeArchived: false,
    });

    const activeSite = $derived(sites.find((s) => s.id === activeId) ?? null);
    const adminFlag = $derived(getCurrentOrgRoles().includes('ADMIN'));
    const activeSiteManageable = $derived(activeSite ? canManageSite(activeSite.id) : false);
    const activeSiteIsDefault = $derived(Boolean(activeSite?.is_default));

    const visibleEquipment = $derived(
        equipment
            .filter((e) => (activeId ? e.site_id === activeId : true))
            .filter((e) => !filter.q || e.name.toLowerCase().includes(filter.q.toLowerCase()))
            .filter((e) => !filter.status || e.status === filter.status)
            .filter((e) => !filter.tag || (e.tags ?? []).includes(filter.tag))
            .filter((e) => filter.includeArchived || !e.archived_at),
    );

    const sitesWithCounts = $derived(
        sites.map((s) => ({
            ...s,
            equipment_count: equipment.filter(
                (e) => e.site_id === s.id && !e.archived_at,
            ).length,
        })),
    );

    async function reloadAll(): Promise<void> {
        const [nextSites, nextEquipment, nextTags] = await Promise.all([
            api.get<Site[]>('/sites', { schema: SiteListSchema }),
            api.get<Equipment[]>('/equipment', { schema: EquipmentListSchema }),
            api.get<string[]>('/equipment/tags'),
        ]);
        sites = nextSites;
        equipment = nextEquipment;
        tags = nextTags;
        if (activeId && !sites.some((s) => s.id === activeId)) {
            activeId = sites[0]?.id ?? null;
        }
    }

    async function saveSite(payload: SiteCreate): Promise<void> {
        try {
            if (siteFormInitial) {
                const updated = await api.patch<Site>(
                    `/sites/${siteFormInitial.id}`,
                    payload,
                    { schema: SiteSchema },
                );
                sites = sites.map((s) => (s.id === updated.id ? updated : s));
            } else {
                const created = await api.post<Site>('/sites', payload, {
                    schema: SiteSchema,
                });
                sites = [...sites, created];
                activeId = created.id;
            }
            siteFormOpen = false;
            siteFormInitial = null;
        } catch (err) {
            const msg = err instanceof Error ? err.message : 'Failed to save site';
            toast.error('Save failed', msg);
            throw err;
        }
    }

    async function submitArchive(payload: SiteArchiveRequest): Promise<void> {
        if (!activeSite) return;
        // The api client's `delete` helper does not send a body; the backend
        // archive endpoint (DELETE /sites/{id}) requires one, so we fetch
        // directly using the same auth header pattern as the api client.
        const token = getToken();
        const headers: HeadersInit = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const res = await fetch(`${API_BASE}/sites/${activeSite.id}`, {
            method: 'DELETE',
            headers,
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            let detail = 'Failed to archive site';
            try {
                const body = await res.json();
                detail = body.detail || body.message || detail;
            } catch {
                // body not JSON
            }
            toast.error('Archive failed', detail);
            throw new ApiError(res.status, detail);
        }
        archiveOpen = false;
        await reloadAll();
    }

    async function saveEquipment(payload: Partial<EquipmentCreate>): Promise<void> {
        try {
            if (equipmentFormInitial) {
                const updated = await api.patch<Equipment>(
                    `/equipment/${equipmentFormInitial.id}`,
                    payload,
                    { schema: EquipmentSchema },
                );
                equipment = equipment.map((e) => (e.id === updated.id ? updated : e));
            } else {
                const created = await api.post<Equipment>('/equipment', payload, {
                    schema: EquipmentSchema,
                });
                equipment = [...equipment, created];
            }
            equipmentFormOpen = false;
            equipmentFormInitial = null;
        } catch (err) {
            const msg = err instanceof Error ? err.message : 'Failed to save equipment';
            toast.error('Save failed', msg);
            throw err;
        }
    }

    async function archiveEquipment(row: Equipment): Promise<void> {
        try {
            await api.delete(`/equipment/${row.id}`);
            equipment = equipment.map((e) =>
                e.id === row.id
                    ? { ...e, archived_at: new Date().toISOString() }
                    : e,
            );
        } catch (err) {
            const msg = err instanceof Error ? err.message : 'Failed to archive equipment';
            toast.error('Archive failed', msg);
        }
    }
</script>

<div class="grid grid-cols-12 min-h-[80vh]" in:fade={{ duration: 120 }}>
    <SiteList
        sites={sitesWithCounts}
        {activeId}
        canEdit={adminFlag}
        onSelect={(id) => (activeId = id)}
        onAdd={() => {
            siteFormInitial = null;
            siteFormOpen = true;
        }}
    />

    <div class="col-span-9">
        {#if !activeSite}
            <SiteEmptyState
                canEdit={adminFlag}
                onAdd={() => {
                    siteFormInitial = null;
                    siteFormOpen = true;
                }}
            />
        {:else}
            <header class="px-6 py-4 flex items-center justify-between border-b border-border">
                <div>
                    <h3 class="text-base font-semibold">{activeSite.name}</h3>
                    <p class="text-xs text-muted-foreground">
                        {visibleEquipment.length} equipment
                    </p>
                </div>
                <div class="flex items-center gap-2">
                    {#if adminFlag}
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={activeSiteIsDefault}
                            title={activeSiteIsDefault
                                ? 'Default site cannot be archived'
                                : ''}
                            onclick={() => (archiveOpen = true)}
                        >
                            Archive
                        </Button>
                    {/if}
                    {#if activeSiteManageable}
                        <Button
                            variant="outline"
                            size="sm"
                            onclick={() => {
                                siteFormInitial = activeSite;
                                siteFormOpen = true;
                            }}
                        >
                            Rename
                        </Button>
                    {/if}
                    <Button
                        size="sm"
                        onclick={() => {
                            equipmentFormInitial = null;
                            equipmentFormOpen = true;
                        }}
                    >
                        + Add equipment
                    </Button>
                </div>
            </header>

            <div class="px-6 py-3 border-b border-border bg-muted/30">
                <EquipmentFilterBar
                    value={filter}
                    {tags}
                    onChange={(v) => (filter = v)}
                />
            </div>

            {#if visibleEquipment.length === 0}
                <EquipmentEmptyState
                    onAdd={() => {
                        equipmentFormInitial = null;
                        equipmentFormOpen = true;
                    }}
                />
            {:else}
                <EquipmentTable
                    rows={visibleEquipment}
                    canManage={activeSiteManageable}
                    onEdit={(r) => {
                        equipmentFormInitial = r;
                        equipmentFormOpen = true;
                    }}
                    onArchive={archiveEquipment}
                />
            {/if}

            {#if adminFlag}
                <div class="px-6 py-6 border-t border-border">
                    <SiteManagersPanel siteId={activeSite.id} />
                </div>
            {/if}
        {/if}
    </div>
</div>

{#if siteFormOpen}
    <SiteFormDialog
        open
        initial={siteFormInitial}
        onClose={() => (siteFormOpen = false)}
        onSubmit={saveSite}
    />
{/if}
{#if archiveOpen && activeSite}
    <SiteArchiveWizardModal
        open
        site={activeSite}
        otherSites={sites.filter((s) => s.id !== activeSite.id && !s.archived_at)}
        equipment={equipment.filter(
            (e) => e.site_id === activeSite.id && !e.archived_at,
        )}
        onClose={() => (archiveOpen = false)}
        onSubmit={submitArchive}
    />
{/if}
{#if equipmentFormOpen}
    <EquipmentFormDialog
        open
        initial={equipmentFormInitial}
        sites={sites.filter((s) => !s.archived_at)}
        {tags}
        canManage={activeSiteManageable}
        onClose={() => (equipmentFormOpen = false)}
        onSubmit={saveEquipment}
    />
{/if}
