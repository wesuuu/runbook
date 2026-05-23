<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import {
		suggestNextLocalId,
		findLocalIdConflicts
	} from '$lib/protocol/equipmentIds';
	import type { Node } from '@xyflow/svelte';
	import type { Site } from '$lib/schemas/sites';
	import SitePicker from '$lib/components/sites/SitePicker.svelte';

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

	let searchQuery = $state('');
	let showCreateForm = $state(mode === 'create');
	let createSectionEl = $state<HTMLDivElement | null>(null);
	let createFormEl = $state<HTMLDivElement | null>(null);
	let isCreateFormInView = $state(true);
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
		showCreateForm = false;
		resetCreateFormFields();
	}

	function closeCreateForm() {
		// Surfaced via the sticky search row; same behavior as Discard.
		discardCreateForm();
	}

	function handleCertificateFile(event: Event) {
		const target = event.target as HTMLInputElement;
		const file = target.files?.[0];
		if (file) {
			newEquipmentCertPath = file.name;
		}
	}

	// Initialize selected items and (in pick mode) reset the create form on
	// every open so a half-typed form doesn't leak across opens. In `create`
	// mode the form is the whole modal — leave it untouched.
	$effect(() => {
		if (open) {
			selectedItems = new Map(
				currentEquipment.map((e) => [
					e.equipment_id,
					{ local_id: e.local_id ?? '', shareable: e.shareable }
				])
			);
			if (mode !== 'create') {
				showCreateForm = false;
				resetCreateFormFields();
			}
		}
	});

	// Scroll the create form into view when it opens so the user sees the
	// fields, not the empty footer. `block: 'nearest'` avoids overshooting.
	$effect(() => {
		if (showCreateForm && createSectionEl) {
			setTimeout(
				() => createSectionEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }),
				50,
			);
		}
	});

	$effect(() => {
		if (!showCreateForm || !createFormEl) {
			isCreateFormInView = true;
			return;
		}
		const target = createFormEl;
		const obs = new IntersectionObserver(
			(entries) => {
				const entry = entries[0];
				if (entry) isCreateFormInView = entry.isIntersecting;
			},
			{ threshold: 0.1 },
		);
		obs.observe(target);
		return () => obs.disconnect();
	});

	function scrollCreateFormIntoView() {
		createFormEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
	}

	const filteredEquipment = $derived(() => {
		const query = searchQuery.toLowerCase();
		return orgEquipment.filter(
			e => e.name.toLowerCase().includes(query) ||
			    (e.description?.toLowerCase().includes(query))
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

	function nextLocalIdInContext(): string {
		return suggestNextLocalId(buildVirtualNodes());
	}

	function toggleEquipment(equipmentId: string) {
		if (selectedItems.has(equipmentId)) {
			selectedItems.delete(equipmentId);
		} else {
			selectedItems.set(equipmentId, {
				local_id: nextLocalIdInContext(),
				shareable: false
			});
		}
		selectedItems = selectedItems; // Trigger reactivity
	}

	function updateLocalId(equipmentId: string, value: string) {
		const current = selectedItems.get(equipmentId);
		if (!current) return;
		selectedItems.set(equipmentId, { ...current, local_id: value });
		selectedItems = selectedItems;
	}

	function toggleShareable(equipmentId: string) {
		const current = selectedItems.get(equipmentId);
		if (!current) return;
		selectedItems.set(equipmentId, { ...current, shareable: !current.shareable });
		selectedItems = selectedItems; // Trigger reactivity
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

			// Add to selected items only in pick mode
			if (mode !== 'create') {
				selectedItems.set(newEq.id, {
					local_id: nextLocalIdInContext(),
					shareable: false
				});
				selectedItems = selectedItems;
			}

			// Reset form
			newEquipmentName = '';
			newEquipmentDescription = '';
			newEquipmentType = '';
			newEquipmentRoom = '';
			newEquipmentLocation = '';
			newEquipmentSerial = '';
			newEquipmentLastCal = '';
			newEquipmentNextCal = '';
			newEquipmentCertPath = '';
			showCreateForm = mode === 'create';

			// In create-only mode, close the modal after create
			if (mode === 'create') onClose?.();
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

	function getEquipmentName(equipmentId: string): string {
		return orgEquipment.find(e => e.id === equipmentId)?.name || equipmentId;
	}

	function hasConflict(equipmentId: string): boolean {
		const st = selectedItems.get(equipmentId);
		return conflictingIds.has(equipmentId) && !(st?.shareable ?? false);
	}

	function handleOpenChange(value: boolean) {
		if (!value) onClose();
	}
</script>

<Dialog.Root {open} onOpenChange={handleOpenChange}>
	<Dialog.Content class="sm:max-w-lg max-h-[85vh] flex flex-col p-0 gap-0">
		<Dialog.Header class="px-6 pt-6 pb-0">
			<Dialog.Title>{mode === 'create' ? 'Create Equipment' : 'Select Equipment'}</Dialog.Title>
		</Dialog.Header>

		<div class="equipment-modal">
			{#if mode !== 'create'}
			<!-- Search bar (sticky inside the single scroller) -->
			<div class="search-bar">
				<input
					type="text"
					placeholder="Search equipment by name or description..."
					bind:value={searchQuery}
					class="search-input"
				/>
				{#if showCreateForm && !isCreateFormInView}
					<Button
						variant="link"
						size="sm"
						class="sticky-link h-auto p-0"
						onclick={scrollCreateFormIntoView}
					>
						Go to form ↓
					</Button>
					<Button
						variant="link"
						size="sm"
						class="sticky-link h-auto p-0"
						onclick={closeCreateForm}
					>
						✕ Close form
					</Button>
				{/if}
			</div>

			<!-- Equipment list -->
			<div class="equipment-list">
				{#if filteredEquipment().length > 0}
					{#each filteredEquipment() as equipment (equipment.id)}
						<div class="equipment-item">
							<div class="item-header">
								<input
									type="checkbox"
									id="eq-{equipment.id}"
									checked={selectedItems.has(equipment.id)}
									onchange={() => toggleEquipment(equipment.id)}
									class="checkbox"
								/>
								<label for="eq-{equipment.id}" class="equipment-label">
									<div class="equipment-name">
										{equipment.name}
										{#if equipment.equipment_type}
											<span class="type-badge">{equipment.equipment_type}</span>
										{/if}
									</div>
									{#if equipment.description}
										<div class="equipment-description">{equipment.description}</div>
									{/if}
									{#if equipment.location}
										<div class="equipment-location">📍 {equipment.location}</div>
									{/if}
								</label>
							</div>

							<!-- Local ID, shareable toggle, conflict badge -->
							{#if selectedItems.has(equipment.id)}
								{@const sel = selectedItems.get(equipment.id)!}
								{@const localIdDup =
									!!sel.local_id && conflictsHere.has(sel.local_id)}
								<div class="item-controls">
									<label class="localid-label">
										ID
										<input
											type="text"
											value={sel.local_id}
											oninput={(e) =>
												updateLocalId(
													equipment.id,
													(e.currentTarget as HTMLInputElement).value
												)}
											class="localid-input"
											class:localid-error={localIdDup}
											placeholder="E-001"
										/>
									</label>
									{#if localIdDup}
										<span class="conflict-badge">⚠ Duplicate ID</span>
									{/if}
									{#if hasConflict(equipment.id)}
										<span class="conflict-badge">⚠ Conflict</span>
									{/if}
									<label class="shareable-label">
										<input
											type="checkbox"
											checked={sel.shareable}
											onchange={() => toggleShareable(equipment.id)}
											class="shareable-checkbox"
										/>
										Shareable
									</label>
								</div>
							{/if}
						</div>
					{/each}
				{:else}
					<div class="empty-state">
						{#if orgEquipment.length === 0}
							<p>No equipment in organization yet. Create one below.</p>
						{:else}
							<p>No equipment matches your search.</p>
						{/if}
					</div>
				{/if}
			</div>
			{/if}

			<!-- Create new equipment section -->
			<div class="create-section" bind:this={createSectionEl}>
				{#if mode !== 'create' && !showCreateForm}
				<Button
					variant="link"
					size="sm"
					class="h-auto p-0 justify-start font-medium"
					onclick={() => (showCreateForm = true)}
				>
					+ Add New Equipment
				</Button>
				{/if}

				{#if showCreateForm}
					<div class="create-form" bind:this={createFormEl}>
						<h4>Create Equipment</h4>
						<div class="form-group">
							<label for="eq-name">Equipment Name *</label>
							<input
								id="eq-name"
								type="text"
								placeholder="e.g., Centrifuge A"
								bind:value={newEquipmentName}
								class="form-input"
							/>
						</div>

						<div class="form-group">
							<label for="eq-desc">Description</label>
							<input
								id="eq-desc"
								type="text"
								placeholder="e.g., High-speed centrifuge"
								bind:value={newEquipmentDescription}
								class="form-input"
							/>
						</div>

						<div class="form-group">
							<label for="eq-type">Equipment Type</label>
							<input
								id="eq-type"
								type="text"
								placeholder="e.g., Centrifuge"
								bind:value={newEquipmentType}
								class="form-input"
							/>
						</div>

						<div class="form-group">
							<label for="eq-room">Room</label>
							<input
								id="eq-room"
								type="text"
								placeholder="e.g., Room 204"
								bind:value={newEquipmentRoom}
								class="form-input"
							/>
						</div>

						<div class="form-group">
							<label for="eq-loc">Bench / Spot</label>
							<input
								id="eq-loc"
								type="text"
								placeholder="e.g., Bench A2"
								bind:value={newEquipmentLocation}
								class="form-input"
							/>
						</div>

						<div class="form-group">
							<label for="eq-site">Site *</label>
							<SitePicker {sites} value={newSiteId} onChange={(v) => (newSiteId = v)} />
						</div>

						<div class="form-group">
							<label for="eq-serial">Serial Number</label>
							<input
								id="eq-serial"
								type="text"
								placeholder="e.g., SN-12345"
								bind:value={newEquipmentSerial}
								class="form-input"
							/>
						</div>

						<div class="form-group">
							<label for="eq-last-cal">Last Calibrated</label>
							<input
								id="eq-last-cal"
								type="date"
								bind:value={newEquipmentLastCal}
								class="form-input"
							/>
						</div>

						<div class="form-group">
							<label for="eq-next-cal">Calibration Due</label>
							<input
								id="eq-next-cal"
								type="date"
								bind:value={newEquipmentNextCal}
								class="form-input"
							/>
						</div>

						<div class="form-group">
							<label for="eq-cert">Calibration Certificate</label>
							<input
								id="eq-cert"
								type="file"
								accept="application/pdf,image/*"
								onchange={handleCertificateFile}
								class="form-input"
							/>
							{#if newEquipmentCertPath}
								<span class="text-xs text-muted-foreground">
									Selected: {newEquipmentCertPath}
								</span>
							{/if}
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
							<Button
								onclick={handleCreate}
								disabled={isCreating}
							>
								{isCreating ? 'Creating...' : 'Create Equipment'}
							</Button>
						</div>
					</div>
				{/if}
			</div>
		</div>

		{#if mode !== 'create'}
		<Dialog.Footer class="px-6 pb-6 pt-0 border-t border-border mt-0">
			{#if hasConflicts}
				<span class="footer-error">Resolve duplicate IDs before applying</span>
			{/if}
			<Button variant="secondary" onclick={onClose}>
				Cancel
			</Button>
			<Button onclick={handleApply} disabled={hasConflicts}>
				Apply
			</Button>
		</Dialog.Footer>
		{/if}
	</Dialog.Content>
</Dialog.Root>

<style>
	.equipment-modal {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1rem 1.5rem;
		overflow-y: auto;
		min-height: 0;
		flex: 1;
	}

	.search-bar {
		flex-shrink: 0;
		position: sticky;
		top: 0;
		z-index: 1;
		background: hsl(var(--background));
		padding: 0.25rem 0;
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.search-bar .search-input {
		flex: 1;
	}

	:global(.sticky-link) {
		flex-shrink: 0;
		white-space: nowrap;
	}

	.search-input {
		width: 100%;
		padding: 0.75rem;
		border: 1px solid hsl(var(--border));
		border-radius: 0.375rem;
		font-size: 0.875rem;
		font-family: inherit;
		background: hsl(var(--background));
		color: hsl(var(--foreground));
	}

	.search-input:focus {
		outline: none;
		border-color: hsl(var(--primary));
		box-shadow: 0 0 0 3px hsl(var(--primary) / 0.1);
	}

	.equipment-list {
		border: 1px solid hsl(var(--border));
		border-radius: 0.375rem;
		padding: 0.5rem 0;
	}

	.equipment-item {
		padding: 0.75rem 0.75rem;
		border-bottom: 1px solid hsl(var(--border) / 0.5);
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.equipment-item:last-child {
		border-bottom: none;
	}

	.item-header {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		flex: 1;
	}

	.checkbox {
		margin-top: 0.25rem;
		cursor: pointer;
	}

	.equipment-label {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		cursor: pointer;
		flex: 1;
	}

	.equipment-name {
		font-weight: 500;
		color: hsl(var(--foreground));
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.type-badge {
		display: inline-block;
		padding: 0.25rem 0.5rem;
		background-color: hsl(var(--muted));
		color: hsl(var(--muted-foreground));
		border-radius: 0.25rem;
		font-size: 0.75rem;
		font-weight: 500;
	}

	.equipment-description {
		font-size: 0.875rem;
		color: hsl(var(--muted-foreground));
	}

	.equipment-location {
		font-size: 0.75rem;
		color: hsl(var(--muted-foreground));
	}

	.item-controls {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.conflict-badge {
		display: inline-block;
		padding: 0.25rem 0.5rem;
		background-color: #fef08a;
		color: #92400e;
		border-radius: 0.25rem;
		font-size: 0.75rem;
		font-weight: 500;
		white-space: nowrap;
	}

	.localid-label {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		font-size: 0.75rem;
		color: hsl(var(--muted-foreground));
		font-weight: 500;
	}

	.localid-input {
		width: 5rem;
		padding: 0.25rem 0.375rem;
		border: 1px solid hsl(var(--border));
		border-radius: 0.25rem;
		font-size: 0.75rem;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		background: hsl(var(--background));
		color: hsl(var(--foreground));
	}

	.localid-input:focus {
		outline: none;
		border-color: hsl(var(--primary));
		box-shadow: 0 0 0 2px hsl(var(--primary) / 0.1);
	}

	.localid-error {
		border-color: #dc2626;
	}

	.footer-error {
		flex: 1;
		font-size: 0.75rem;
		color: #b91c1c;
		font-weight: 500;
	}

	.shareable-label {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		font-size: 0.875rem;
		cursor: pointer;
		white-space: nowrap;
	}

	.shareable-checkbox {
		width: 1rem;
		height: 1rem;
		cursor: pointer;
	}

	.empty-state {
		padding: 2rem 1rem;
		text-align: center;
		color: hsl(var(--muted-foreground));
		font-size: 0.875rem;
	}

	.create-section {
		flex-shrink: 0;
		border-top: 1px solid hsl(var(--border));
		padding-top: 0.75rem;
	}

	.create-form {
		margin-top: 0.75rem;
		padding: 0.75rem;
		background-color: hsl(var(--muted) / 0.4);
		border-radius: 0.375rem;
		border: 1px solid hsl(var(--border));
		border-left: 4px solid hsl(var(--primary));
	}

	.create-form h4 {
		margin: 0 0 0.75rem 0;
		font-size: 0.875rem;
		font-weight: 600;
		color: hsl(var(--foreground));
	}

	.form-group {
		margin-bottom: 0.75rem;
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.form-group label {
		font-size: 0.75rem;
		font-weight: 500;
		color: hsl(var(--muted-foreground));
	}

	.form-input {
		padding: 0.5rem;
		border: 1px solid hsl(var(--border));
		border-radius: 0.25rem;
		font-size: 0.875rem;
		font-family: inherit;
		background: hsl(var(--card));
		color: hsl(var(--foreground));
	}

	.form-input:focus {
		outline: none;
		border-color: hsl(var(--primary));
		box-shadow: 0 0 0 2px hsl(var(--primary) / 0.1);
	}

	.error-message {
		padding: 0.5rem;
		background-color: hsl(var(--destructive) / 0.1);
		color: hsl(var(--destructive));
		border-radius: 0.25rem;
		font-size: 0.875rem;
		margin-bottom: 0.75rem;
	}

	.create-form-footer {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		margin-top: 0.5rem;
		padding-top: 0.75rem;
		border-top: 1px solid hsl(var(--border));
	}
</style>
