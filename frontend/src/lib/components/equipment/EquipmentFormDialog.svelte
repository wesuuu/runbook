<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import SitePicker from '$lib/components/sites/SitePicker.svelte';
    import TagsInput from './TagsInput.svelte';
    import type { Site } from '$lib/schemas/sites';
    import type { Equipment, EquipmentCreate } from '$lib/schemas/science';

    interface Props {
        open: boolean;
        initial: Equipment | null;
        sites: Site[];
        tags: string[];
        canManage: boolean;
        onClose: () => void;
        onSubmit: (payload: Partial<EquipmentCreate>) => Promise<void>;
    }
    let { open, initial, sites, tags, canManage, onClose, onSubmit }: Props = $props();

    const labelClass = 'text-xs uppercase tracking-wide text-muted-foreground font-medium';
    const inputClass = 'w-full px-3 py-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white';
    const inputMonoClass = `${inputClass} font-mono`;

    let name = $state(initial?.name ?? '');
    let site_id = $state(initial?.site_id ?? sites[0]?.id ?? '');
    let equipment_type = $state(initial?.equipment_type ?? '');
    let room = $state(initial?.room ?? '');
    let location = $state(initial?.location ?? '');
    let description = $state(initial?.description ?? '');
    let tagsValue = $state<string[]>(initial?.tags ?? []);
    let manufacturer = $state(initial?.manufacturer ?? '');
    let model = $state(initial?.model ?? '');
    let serial_number = $state(initial?.serial_number ?? '');
    let status = $state<'ACTIVE' | 'MAINTENANCE' | 'RETIRED'>(initial?.status ?? 'ACTIVE');
    let install_date = $state(initial?.install_date ?? '');
    let last_calibration_date = $state(initial?.last_calibration_date ?? '');
    let next_calibration_date = $state(initial?.next_calibration_date ?? '');
    let saving = $state(false);

    async function submit() {
        saving = true;
        try {
            await onSubmit({
                name,
                site_id,
                equipment_type,
                room,
                location,
                description,
                tags: tagsValue,
                ...(canManage
                    ? {
                          manufacturer,
                          model,
                          serial_number,
                          status,
                          install_date: install_date || undefined,
                          last_calibration_date: last_calibration_date || undefined,
                          next_calibration_date: next_calibration_date || undefined,
                      }
                    : {}),
            });
            onClose();
        } finally {
            saving = false;
        }
    }
</script>

<Dialog.Root {open} onOpenChange={(v) => { if (!v) onClose(); }}>
    <Dialog.Content class="sm:max-w-xl">
        <Dialog.Header>
            <Dialog.Title>{initial ? 'Edit equipment' : 'New equipment'}</Dialog.Title>
        </Dialog.Header>

        <div class="space-y-3 py-2">
            <div>
                <label class={labelClass} for="eq-name">Name *</label>
                <Input id="eq-name" class="bg-white" bind:value={name} />
            </div>
            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class={labelClass}>Site *</label>
                    <SitePicker {sites} value={site_id} onChange={(v) => (site_id = v)} />
                </div>
                <div>
                    <label class={labelClass} for="eq-type">Type</label>
                    <Input id="eq-type" class="bg-white" bind:value={equipment_type} />
                </div>
            </div>
            <div class="grid grid-cols-2 gap-3">
                <div>
                    <label class={labelClass} for="eq-room">Room</label>
                    <Input id="eq-room" class="bg-white" bind:value={room} />
                </div>
                <div>
                    <label class={labelClass} for="eq-loc">Bench / Spot</label>
                    <Input id="eq-loc" class="bg-white" bind:value={location} />
                </div>
            </div>
            <div>
                <label class={labelClass} for="eq-desc">Description</label>
                <Input id="eq-desc" class="bg-white" bind:value={description} />
            </div>
            <div>
                <label class={labelClass}>Tags</label>
                <TagsInput value={tagsValue} suggestions={tags} onChange={(v) => (tagsValue = v)} />
            </div>

            <hr class="border-dashed" />

            <div class:opacity-60={!canManage}>
                <div class="flex items-center justify-between">
                    <span class={labelClass}>{canManage ? 'Regulated fields' : '🔒 Regulated fields'}</span>
                    {#if !canManage}
                        <span class="text-xs text-muted-foreground">SITE_MANAGER or ADMIN only</span>
                    {/if}
                </div>
                <div class="grid grid-cols-2 gap-3 mt-2">
                    <div>
                        <label class={labelClass} for="eq-mfr">Manufacturer</label>
                        <Input id="eq-mfr" class="bg-white" bind:value={manufacturer} disabled={!canManage} />
                    </div>
                    <div>
                        <label class={labelClass} for="eq-model">Model</label>
                        <Input id="eq-model" class="bg-white" bind:value={model} disabled={!canManage} />
                    </div>
                    <div>
                        <label class={labelClass} for="eq-serial">Serial</label>
                        <Input id="eq-serial" class="bg-white" bind:value={serial_number} disabled={!canManage} />
                    </div>
                    <div>
                        <label class={labelClass} for="eq-status">Status</label>
                        <select id="eq-status" class={inputClass} bind:value={status} disabled={!canManage}>
                            <option value="ACTIVE">Active</option>
                            <option value="MAINTENANCE">Maintenance</option>
                            <option value="RETIRED">Retired</option>
                        </select>
                    </div>
                    <div>
                        <label class={labelClass} for="eq-install">Install date</label>
                        <input
                            id="eq-install"
                            class={inputMonoClass}
                            type="date"
                            bind:value={install_date}
                            disabled={!canManage}
                        />
                    </div>
                    <div>
                        <label class={labelClass} for="eq-lastcal">Last calibration</label>
                        <input
                            id="eq-lastcal"
                            class={inputMonoClass}
                            type="date"
                            aria-label="Last calibration"
                            bind:value={last_calibration_date}
                            disabled={!canManage}
                        />
                    </div>
                    <div>
                        <label class={labelClass} for="eq-nextcal">Next calibration</label>
                        <input
                            id="eq-nextcal"
                            class={inputMonoClass}
                            type="date"
                            bind:value={next_calibration_date}
                            disabled={!canManage}
                        />
                    </div>
                </div>
            </div>
        </div>

        <Dialog.Footer>
            <Button variant="outline" onclick={onClose}>Cancel</Button>
            <Button onclick={submit} disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
