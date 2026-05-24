<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import {
		suggestNextLocalId,
		findLocalIdConflicts
	} from '$lib/protocol/equipmentIds';
	import type { Node } from '@xyflow/svelte';
	import type { Site } from '$lib/schemas/sites';
	import SitePicker from '$lib/components/sites/SitePicker.svelte';
	import { Search, Plus, Check, X, LayoutGrid } from 'lucide-svelte';

	interface Equipment {
		id: string;
		name: string;
		description?: string;
		equipment_type?: string;
		location?: string;
		organization_id: string;
		created_at: string;
		updated_at: string;
	}

	interface SelectedEquipment {
		equipment_id: string;
		local_id?: string;
		shareable: boolean;
	}

	interface Props {
		open: boolean;
		sites?: Site[];
		mode?: 'pick' | 'create';
		nodeId?: string;
		currentEquipment?: SelectedEquipment[];
		orgEquipment?: Equipment[];
		allNodes?: Node[];
		conflictingIds?: Set<string>;
		onClose?: () => void;
		onApply?: (equipment: SelectedEquipment[]) => void;
		onCreateEquipment: (data: {
			name: string;
			description: string;
			equipment_type: string;
			location: string;
			room?: string;
			site_id?: string;
			serial_number?: string;
			last_calibration_date?: string | null;
			next_calibration_date?: string | null;
			calibration_certificate_path?: string;
		}) => Promise<Equipment>;
	}

	let {
		open = false,
		sites = [],
		mode = 'pick',
		nodeId = '',
		currentEquipment = [],
		orgEquipment = [],
		allNodes = [],
		conflictingIds = new Set(),
		onClose = () => {},
		onApply = () => {},
		onCreateEquipment
	}: Props = $props();

	const STORAGE_KEY = 'f0088:lastSiteId';

	function resolveInitialSiteId(): string {
		const cached =
			typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
		if (cached) {
			const match = sites.find((s) => s.id === cached && !s.archived_at);
			if (match) return match.id;
		}
		const orgDefault = sites.find((s) => s.is_default && !s.archived_at);
		return orgDefault?.id ?? sites[0]?.id ?? '';
	}

	type Tab = 'browse' | 'new';

	let searchQuery = $state('');
	// Start on `new` for `mode='create'` because the form is the whole
	// modal; otherwise start on `browse`. Re-derived on each open via the
	// wasOpen effect below, so changing mode mid-session is supported.
	let activeTab = $state<Tab>('browse');
	let selectedItems = $state<Map<string, { local_id: string; shareable: boolean }>>(new Map());
	let isCreating = $state(false);

	// Form state for creating equipment
	let newEquipmentName = $state('');
	let newEquipmentDescription = $state('');
	let newEquipmentType = $state('');
	let newEquipmentRoom = $state('');
	let newEquipmentLocation = $state('');
	let newSiteId = $state<string>(resolveInitialSiteId());
	let newEquipmentSerial = $state('');
	let newEquipmentLastCal = $state('');
	let newEquipmentNextCal = $state('');
	let newEquipmentCertPath = $state('');
	let createError = $state('');

	$effect(() => {
		if (newSiteId && typeof localStorage !== 'undefined') {
			localStorage.setItem(STORAGE_KEY, newSiteId);
		}
	});

	function resetCreateFormFields() {
		newEquipmentName = '';
		newEquipmentDescription = '';
		newEquipmentType = '';
		newEquipmentRoom = '';
		newEquipmentLocation = '';
		newEquipmentSerial = '';
		newEquipmentLastCal = '';
		newEquipmentNextCal = '';
		newEquipmentCertPath = '';
		createError = '';
		// newSiteId intentionally stays — sticky preference (see resolveInitialSiteId).
	}

	function discardCreateForm() {
		resetCreateFormFields();
		if (mode !== 'create') activeTab = 'browse';
	}

	function handleCertificateFile(event: Event) {
		const target = event.target as HTMLInputElement;
		const file = target.files?.[0];
		if (file) {
			newEquipmentCertPath = file.name;
		}
	}

	// Initialize selected items and (in pick mode) reset the create form on
	// each false→true open transition only. Tracking just `open` ensures a
	// parent re-render that swaps `currentEquipment` or `mode` while the
	// modal is already open won't clobber a half-typed form. In `create`
	// mode the form is the whole modal — leave it untouched.
	// Contract: parents must toggle `open` (close → reopen) to refresh
	// `currentEquipment` / `mode` mid-session. Current call sites
	// (Inspector, RunOverridesEditor) honour this.
	let wasOpen = false;
	$effect(() => {
		if (open && !wasOpen) {
			selectedItems = new Map(
				currentEquipment.map((e) => [
					e.equipment_id,
					{ local_id: e.local_id ?? '', shareable: e.shareable }
				])
			);
			activeTab = mode === 'create' ? 'new' : 'browse';
			if (mode !== 'create') resetCreateFormFields();
		}
		wasOpen = open;
	});

	const filteredEquipment = $derived.by(() => {
		const query = searchQuery.toLowerCase();
		return orgEquipment.filter(
			(e) =>
				e.name.toLowerCase().includes(query) ||
				(e.description?.toLowerCase().includes(query) ?? false) ||
				(e.equipment_type?.toLowerCase().includes(query) ?? false) ||
				(e.location?.toLowerCase().includes(query) ?? false)
		);
	});

	function buildVirtualNodes(): Node[] {
		const virtualSelf = {
			id: nodeId,
			type: 'unitOp',
			position: { x: 0, y: 0 },
			data: {
				equipment: Array.from(selectedItems.entries()).map(([eqId, st]) => ({
					equipment_id: eqId,
					local_id: st.local_id,
					shareable: st.shareable
				}))
			}
		} as unknown as Node;
		const otherNodes = allNodes.filter((n) => n.id !== nodeId);
		return [...otherNodes, virtualSelf];
	}

	const conflictsHere = $derived.by(() => {
		return findLocalIdConflicts(buildVirtualNodes());
	});

	const hasConflicts = $derived.by(() => {
		for (const st of selectedItems.values()) {
			if (st.local_id && conflictsHere.has(st.local_id)) return true;
		}
		return false;
	});

	const selectedCount = $derived(selectedItems.size);

	const selectedList = $derived.by(() =>
		Array.from(selectedItems.entries()).map(([equipmentId, st], index) => ({
			equipmentId,
			index,
			local_id: st.local_id,
			shareable: st.shareable,
			equipment: orgEquipment.find((e) => e.id === equipmentId),
			isDup: !!st.local_id && conflictsHere.has(st.local_id)
		}))
	);

	function nextLocalIdInContext(): string {
		return suggestNextLocalId(buildVirtualNodes());
	}

	function toggleEquipment(equipmentId: string) {
		const next = new Map(selectedItems);
		if (next.has(equipmentId)) {
			next.delete(equipmentId);
		} else {
			next.set(equipmentId, {
				local_id: nextLocalIdInContext(),
				shareable: true
			});
		}
		selectedItems = next;
	}

	function removeSelected(equipmentId: string) {
		if (!selectedItems.has(equipmentId)) return;
		const next = new Map(selectedItems);
		next.delete(equipmentId);
		selectedItems = next;
	}

	function updateLocalId(equipmentId: string, value: string) {
		const current = selectedItems.get(equipmentId);
		if (!current) return;
		const next = new Map(selectedItems);
		next.set(equipmentId, { ...current, local_id: value });
		selectedItems = next;
	}

	async function handleCreate() {
		if (!newEquipmentName.trim()) {
			createError = 'Equipment name is required';
			return;
		}
		if (!newSiteId) {
			createError = 'Site is required';
			return;
		}

		isCreating = true;
		createError = '';

		try {
			const newEq = await onCreateEquipment({
				name: newEquipmentName,
				description: newEquipmentDescription,
				equipment_type: newEquipmentType,
				location: newEquipmentLocation,
				room: newEquipmentRoom,
				site_id: newSiteId,
				serial_number: newEquipmentSerial,
				last_calibration_date: newEquipmentLastCal || null,
				next_calibration_date: newEquipmentNextCal || null,
				calibration_certificate_path: newEquipmentCertPath
			});

			// Add to selected items only in pick mode, then return to browse.
			if (mode !== 'create') {
				const next = new Map(selectedItems);
				next.set(newEq.id, {
					local_id: nextLocalIdInContext(),
					shareable: true
				});
				selectedItems = next;
			}

			resetCreateFormFields();

			if (mode === 'create') {
				onClose?.();
			} else {
				activeTab = 'browse';
			}
		} catch (e) {
			createError = `Failed to create equipment: ${e instanceof Error ? e.message : 'Unknown error'}`;
		} finally {
			isCreating = false;
		}
	}

	function handleApply() {
		const equipment: SelectedEquipment[] = Array.from(selectedItems.entries()).map(
			([equipmentId, st]) => ({
				equipment_id: equipmentId,
				local_id: st.local_id || undefined,
				shareable: st.shareable
			})
		);
		onApply(equipment);
		onClose();
	}

	function handleOpenChange(value: boolean) {
		if (!value) onClose();
	}
</script>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
	<Dialog.Content class="sm:max-w-lg max-h-[85vh] flex flex-col p-0 gap-0 overflow-hidden">
		<Dialog.Header class="px-6 pt-6 pb-3 space-y-2">
			<Dialog.Title>{mode === 'create' ? 'Create Equipment' : 'Select Equipment'}</Dialog.Title>
			{#if mode !== 'create'}
				<p class="text-xs text-muted-foreground">
					Pick equipment for this step, then assign protocol-local IDs in the
					selection panel below.
				</p>
				<!-- segmented tabs -->
				<div class="tabs" role="tablist" aria-label="Equipment picker view">
					<button
						type="button"
						role="tab"
						aria-selected={activeTab === 'browse'}
						class="tab"
						class:active={activeTab === 'browse'}
						onclick={() => (activeTab = 'browse')}
					>
						<LayoutGrid class="size-3.5" aria-hidden="true" />
						Browse
						<span class="count">{orgEquipment.length}</span>
					</button>
					<button
						type="button"
						role="tab"
						aria-selected={activeTab === 'new'}
						class="tab"
						class:active={activeTab === 'new'}
						onclick={() => (activeTab = 'new')}
					>
						<Plus class="size-3.5" aria-hidden="true" />
						New equipment
					</button>
				</div>
			{/if}
		</Dialog.Header>

		<!-- single scroll region -->
		<div class="equipment-modal">
			{#if mode !== 'create' && activeTab === 'browse'}
				<!-- search (sticky) -->
				<div class="search-bar">
					<div class="search-input-wrap">
						<Search class="search-icon size-4" aria-hidden="true" />
						<Input
							type="text"
							placeholder="Search {orgEquipment.length} items by name, type, or location…"
							bind:value={searchQuery}
							class="pl-9"
						/>
					</div>
				</div>

				<!-- equipment card grid -->
				{#if filteredEquipment.length > 0}
					<div class="equipment-list">
						{#each filteredEquipment as equipment (equipment.id)}
							{@const isSelected = selectedItems.has(equipment.id)}
							<button
								type="button"
								class="equipment-item"
								class:is-selected={isSelected}
								onclick={() => toggleEquipment(equipment.id)}
								aria-pressed={isSelected}
								title={equipment.name}
							>
								{#if isSelected}
									<span class="check-icon" aria-hidden="true">
										<Check class="size-3" stroke-width="3" />
									</span>
								{/if}
								<div class="equipment-name">{equipment.name}</div>
								<div class="equipment-meta">
									{#if equipment.equipment_type}
										<span class="type-badge">{equipment.equipment_type}</span>
									{/if}
									{#if equipment.location}
										<span class="equipment-location">📍 {equipment.location}</span>
									{/if}
								</div>
							</button>
						{/each}
					</div>
				{:else}
					<div class="empty-state">
						{#if orgEquipment.length === 0}
							<p>No equipment in this organization yet.</p>
							<Button
								variant="link"
								size="sm"
								class="h-auto p-0"
								onclick={() => (activeTab = 'new')}
							>
								Create the first one →
							</Button>
						{:else}
							<p>No equipment matches "<strong>{searchQuery}</strong>".</p>
						{/if}
					</div>
				{/if}

				<!-- inline path to the New equipment tab -->
				<Button
					variant="outline"
					size="sm"
					class="self-start"
					onclick={() => (activeTab = 'new')}
				>
					<Plus class="size-3.5" />
					Add equipment not in this list
				</Button>
			{:else}
				<!-- create form (covers full body, both 'new' tab and create-only mode) -->
				<div class="create-form">
					{#if mode === 'create'}
						<p class="text-xs text-muted-foreground">
							Add a new piece of equipment to your organization's catalog.
						</p>
					{/if}

					<div class="form-grid">
						<div class="form-group form-group-full">
							<Label for="eq-name">Equipment name *</Label>
							<Input
								id="eq-name"
								type="text"
								placeholder="e.g., Avanti J-26 XPI"
								bind:value={newEquipmentName}
							/>
						</div>

						<div class="form-group form-group-full">
							<Label for="eq-desc">Description</Label>
							<Input
								id="eq-desc"
								type="text"
								placeholder="e.g., High-speed floor centrifuge"
								bind:value={newEquipmentDescription}
							/>
						</div>

						<div class="form-group">
							<Label for="eq-type">Type</Label>
							<Input
								id="eq-type"
								type="text"
								placeholder="Centrifuge"
								bind:value={newEquipmentType}
							/>
						</div>
						<div class="form-group">
							<Label for="eq-site">Site *</Label>
							<SitePicker {sites} value={newSiteId} onChange={(v) => (newSiteId = v)} />
						</div>

						<div class="form-group">
							<Label for="eq-room">Room</Label>
							<Input id="eq-room" type="text" placeholder="Rm 204" bind:value={newEquipmentRoom} />
						</div>
						<div class="form-group">
							<Label for="eq-loc">Bench / spot</Label>
							<Input
								id="eq-loc"
								type="text"
								placeholder="Bench A2"
								bind:value={newEquipmentLocation}
							/>
						</div>

						<div class="form-group form-group-full">
							<Label for="eq-serial">Serial number</Label>
							<Input
								id="eq-serial"
								type="text"
								placeholder="SN-12345"
								bind:value={newEquipmentSerial}
							/>
						</div>

						<div class="form-group">
							<Label for="eq-last-cal">Last calibrated</Label>
							<Input id="eq-last-cal" type="date" bind:value={newEquipmentLastCal} />
						</div>
						<div class="form-group">
							<Label for="eq-next-cal">Calibration due</Label>
							<Input id="eq-next-cal" type="date" bind:value={newEquipmentNextCal} />
						</div>

						<div class="form-group form-group-full">
							<Label for="eq-cert">Calibration certificate</Label>
							<Input
								id="eq-cert"
								type="file"
								accept="application/pdf,image/*"
								onchange={handleCertificateFile}
							/>
							{#if newEquipmentCertPath}
								<span class="text-xs text-muted-foreground">
									Selected: {newEquipmentCertPath}
								</span>
							{/if}
						</div>
					</div>

					{#if createError}
						<div class="error-message">{createError}</div>
					{/if}

					<div class="create-form-footer">
						{#if mode !== 'create'}
							<Button
								variant="secondary"
								onclick={discardCreateForm}
								disabled={isCreating}
							>
								Discard
							</Button>
						{/if}
						<Button onclick={handleCreate} disabled={isCreating}>
							{isCreating ? 'Creating…' : 'Create equipment'}
						</Button>
					</div>
				</div>
			{/if}
		</div>

		{#if mode !== 'create'}
			<!-- selection dock (sticky above footer when ≥1 selected) -->
			{#if selectedCount > 0}
				<div class="dock">
					<div class="dock-title">
						<span>Selected for this step</span>
						<span class="dock-pill">{selectedCount}</span>
					</div>
					<div class="dock-list">
						{#each selectedList as item (item.equipmentId)}
							<div class="dock-row">
								<span class="dock-num">{item.index + 1}</span>
								<span
									class="dock-name"
									title={item.equipment?.name ?? item.equipmentId}
								>
									{item.equipment?.name ?? '(deleted equipment)'}
								</span>
								<label class="dock-id">
									<span class="dock-id-label">ID</span>
									<input
										type="text"
										class="dock-id-input"
										class:dock-id-error={item.isDup}
										value={item.local_id}
										oninput={(e) =>
											updateLocalId(
												item.equipmentId,
												(e.currentTarget as HTMLInputElement).value
											)}
										placeholder="E-001"
									/>
								</label>
								<button
									type="button"
									class="dock-remove"
									aria-label="Remove {item.equipment?.name ?? 'equipment'}"
									onclick={() => removeSelected(item.equipmentId)}
								>
									<X class="size-3" stroke-width="2.4" />
								</button>
							</div>
						{/each}
					</div>
					{#if hasConflicts}
						<p class="dock-error">Resolve duplicate IDs before applying.</p>
					{/if}
				</div>
			{/if}

			<Dialog.Footer class="px-6 py-3 border-t border-border mt-0">
				<Button variant="secondary" onclick={onClose}>Cancel</Button>
				<Button onclick={handleApply} disabled={hasConflicts}>Apply</Button>
			</Dialog.Footer>
		{/if}
	</Dialog.Content>
</Dialog.Root>

<style>
	/* Theme tokens (--card, --border, --primary, …) already include hsl(),
	   so use var(--token) directly. For opacity use color-mix(). */

	/* ---------- tabs ---------- */
	.tabs {
		display: inline-flex;
		background: var(--muted);
		border-radius: var(--radius-md);
		padding: 0.1875rem;
		gap: 0.125rem;
	}
	.tab {
		appearance: none;
		border: none;
		background: transparent;
		font: inherit;
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--muted-fg);
		padding: 0.3125rem 0.625rem;
		border-radius: calc(var(--radius-md) - 0.125rem);
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		gap: 0.375rem;
		transition: background-color 120ms ease, color 120ms ease;
	}
	.tab:hover { color: var(--fg); }
	.tab.active {
		background: var(--card);
		color: var(--fg);
		box-shadow: 0 1px 2px rgb(0 0 0 / 0.06);
	}
	.tab .count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 1.125rem;
		padding: 0 0.3125rem;
		height: 1.0625rem;
		border-radius: 999px;
		background: var(--primary);
		color: var(--primary-fg);
		font-size: 0.6875rem;
		font-weight: 600;
		line-height: 1;
	}
	.tab:not(.active) .count {
		background: var(--border);
		color: var(--fg);
	}

	/* ---------- single scroll region ---------- */
	.equipment-modal {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 0.5rem 1.5rem 1rem;
		overflow-y: auto;
		min-height: 0;
		flex: 1;
	}

	/* ---------- search ---------- */
	.search-bar {
		position: sticky;
		top: 0;
		z-index: 1;
		background: linear-gradient(180deg, var(--bg) 86%, transparent);
		padding: 0.5rem 0 0.25rem;
		flex-shrink: 0;
	}
	.search-input-wrap {
		position: relative;
	}
	.search-input-wrap :global(.search-icon) {
		position: absolute;
		left: 0.75rem;
		top: 50%;
		translate: 0 -50%;
		color: var(--muted-fg);
		pointer-events: none;
	}

	/* ---------- card grid ---------- */
	.equipment-list {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.5rem;
	}
	.equipment-item {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 0.25rem;
		padding: 0.625rem 0.75rem;
		border: 1px solid var(--border);
		border-radius: var(--radius-md);
		background: var(--card);
		text-align: left;
		font: inherit;
		color: inherit;
		cursor: pointer;
		min-width: 0;
		transition: border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease;
	}
	.equipment-item:hover {
		border-color: color-mix(in oklch, var(--ring) 60%, transparent);
		box-shadow: 0 2px 8px rgb(0 0 0 / 0.05);
	}
	.equipment-item.is-selected {
		border-color: var(--primary);
		box-shadow:
			0 0 0 1px var(--primary),
			0 2px 10px color-mix(in oklch, var(--primary) 12%, transparent);
	}
	.check-icon {
		position: absolute;
		top: 0.5rem;
		right: 0.5rem;
		width: 1.0625rem;
		height: 1.0625rem;
		border-radius: 999px;
		background: var(--primary);
		color: var(--primary-fg);
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}
	.equipment-name {
		font-weight: 500;
		font-size: 0.875rem;
		color: var(--fg);
		line-height: 1.3;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		padding-right: 1.5rem; /* clear the check icon */
		min-width: 0;
	}
	.equipment-meta {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		font-size: 0.6875rem;
		color: var(--muted-fg);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}
	.type-badge {
		display: inline-flex;
		align-items: center;
		height: 1.125rem;
		padding: 0 0.4375rem;
		border-radius: 999px;
		background: var(--muted);
		color: var(--muted-fg);
		font-size: 0.625rem;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		flex-shrink: 0;
	}
	.equipment-location {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* ---------- empty state ---------- */
	.empty-state {
		padding: 2.5rem 1rem;
		text-align: center;
		color: var(--muted-fg);
		font-size: 0.875rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
		border: 1px dashed var(--border);
		border-radius: var(--radius-md);
	}
	.empty-state p { margin: 0; }

	/* ---------- create form ---------- */
	.create-form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.form-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.625rem 0.75rem;
	}
	.form-group {
		display: flex;
		flex-direction: column;
		gap: 0.3125rem;
		min-width: 0;
	}
	.form-group-full { grid-column: span 2; }

	.error-message {
		padding: 0.5rem 0.625rem;
		background-color: color-mix(in oklch, var(--destructive) 10%, transparent);
		color: var(--destructive);
		border-radius: var(--radius-sm);
		font-size: 0.8125rem;
	}

	.create-form-footer {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		padding-top: 0.75rem;
		border-top: 1px solid var(--border);
	}

	/* ---------- selection dock ---------- */
	.dock {
		flex-shrink: 0;
		border-top: 1px solid var(--border);
		background: color-mix(in oklch, var(--primary) 6%, transparent);
		padding: 0.625rem 1.5rem 0.625rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		max-height: 14rem;
	}
	.dock-title {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.6875rem;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--primary);
	}
	.dock-pill {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 1.25rem;
		padding: 0.0625rem 0.4375rem;
		height: 1.125rem;
		border-radius: 999px;
		background: var(--primary);
		color: var(--primary-fg);
		font-size: 0.6875rem;
		font-weight: 700;
		letter-spacing: 0;
	}
	.dock-list {
		display: flex;
		flex-direction: column;
		gap: 0.3125rem;
		overflow-y: auto;
		min-height: 0;
	}
	.dock-row {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto auto;
		align-items: center;
		gap: 0.5rem;
		background: var(--card);
		border: 1px solid color-mix(in oklch, var(--primary) 25%, transparent);
		border-radius: var(--radius-sm);
		padding: 0.3125rem 0.5rem 0.3125rem 0.625rem;
	}
	.dock-num {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.25rem;
		height: 1.25rem;
		border-radius: 999px;
		background: var(--primary);
		color: var(--primary-fg);
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.625rem;
		font-weight: 700;
		line-height: 1;
		flex-shrink: 0;
	}
	.dock-name {
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--fg);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}
	.dock-id {
		display: inline-flex;
		align-items: center;
		gap: 0.3125rem;
	}
	.dock-id-label {
		font-size: 0.625rem;
		font-weight: 700;
		color: var(--muted-fg);
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}
	.dock-id-input {
		height: 1.625rem;
		width: 4.25rem;
		padding: 0 0.4375rem;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border);
		background: var(--card);
		font-family: var(--font-mono, ui-monospace, monospace);
		font-size: 0.75rem;
		text-align: center;
		color: var(--fg);
		transition: border-color 120ms ease, box-shadow 120ms ease;
	}
	.dock-id-input:focus-visible {
		outline: none;
		border-color: var(--ring);
		box-shadow: 0 0 0 2px color-mix(in oklch, var(--ring) 20%, transparent);
	}
	.dock-id-error {
		border-color: var(--destructive);
		background: color-mix(in oklch, var(--destructive) 6%, transparent);
	}
	.dock-remove {
		appearance: none;
		background: transparent;
		border: none;
		width: 1.5rem;
		height: 1.5rem;
		border-radius: 999px;
		color: var(--muted-fg);
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		transition: background-color 120ms ease, color 120ms ease;
	}
	.dock-remove:hover {
		background: color-mix(in oklch, var(--destructive) 12%, transparent);
		color: var(--destructive);
	}
	.dock-error {
		margin: 0;
		font-size: 0.75rem;
		color: var(--destructive);
		font-weight: 500;
	}
</style>
