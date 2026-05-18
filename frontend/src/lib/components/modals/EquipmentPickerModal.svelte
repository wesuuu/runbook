<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import {
		suggestNextLocalId,
		findLocalIdConflicts
	} from '$lib/protocol/equipmentIds';
	import type { Node } from '@xyflow/svelte';

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
		nodeId: string;
		currentEquipment: SelectedEquipment[];
		orgEquipment: Equipment[];
		allNodes: Node[];
		conflictingIds: Set<string>;
		onClose: () => void;
		onApply: (equipment: SelectedEquipment[]) => void;
		onCreateEquipment: (data: {
			name: string;
			description: string;
			equipment_type: string;
			location: string;
			serial_number: string;
			last_calibration_date: string | null;
			next_calibration_date: string | null;
			calibration_certificate_path: string;
		}) => Promise<Equipment>;
	}

	let {
		open = false,
		nodeId,
		currentEquipment = [],
		orgEquipment = [],
		allNodes = [],
		conflictingIds = new Set(),
		onClose,
		onApply,
		onCreateEquipment
	}: Props = $props();

	let searchQuery = $state('');
	let showCreateForm = $state(false);
	let createSectionEl = $state<HTMLDivElement | null>(null);
	let selectedItems = $state<Map<string, { local_id: string; shareable: boolean }>>(new Map());
	let isCreating = $state(false);

	// Form state for creating equipment
	let newEquipmentName = $state('');
	let newEquipmentDescription = $state('');
	let newEquipmentType = $state('');
	let newEquipmentLocation = $state('');
	let newEquipmentSerial = $state('');
	let newEquipmentLastCal = $state('');
	let newEquipmentNextCal = $state('');
	let newEquipmentCertPath = $state('');
	let createError = $state('');

	function handleCertificateFile(event: Event) {
		const target = event.target as HTMLInputElement;
		const file = target.files?.[0];
		if (file) {
			// Until a dedicated calibration-certificate upload endpoint exists
			// (backend Task 21 stores a path string), fall back to recording
			// the file name. Operators can later replace this with a real path
			// once the upload route ships.
			newEquipmentCertPath = file.name;
		}
	}

	// Initialize selected items when modal opens
	$effect(() => {
		if (open) {
			selectedItems = new Map(
				currentEquipment.map((e) => [
					e.equipment_id,
					{ local_id: e.local_id ?? '', shareable: e.shareable }
				])
			);
		}
	});

	// Scroll the create form into view when it opens so the submit button is visible
	$effect(() => {
		if (showCreateForm && createSectionEl) {
			// Defer to allow DOM to render the form before scrolling
			setTimeout(() => createSectionEl?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 50);
		}
	});

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

		isCreating = true;
		createError = '';

		try {
			const newEq = await onCreateEquipment({
				name: newEquipmentName,
				description: newEquipmentDescription,
				equipment_type: newEquipmentType,
				location: newEquipmentLocation,
				serial_number: newEquipmentSerial,
				last_calibration_date: newEquipmentLastCal || null,
				next_calibration_date: newEquipmentNextCal || null,
				calibration_certificate_path: newEquipmentCertPath
			});

			// Add to selected items
			selectedItems.set(newEq.id, {
				local_id: nextLocalIdInContext(),
				shareable: false
			});
			selectedItems = selectedItems;

			// Reset form
			newEquipmentName = '';
			newEquipmentDescription = '';
			newEquipmentType = '';
			newEquipmentLocation = '';
			newEquipmentSerial = '';
			newEquipmentLastCal = '';
			newEquipmentNextCal = '';
			newEquipmentCertPath = '';
			showCreateForm = false;
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
			<Dialog.Title>Select Equipment</Dialog.Title>
		</Dialog.Header>

		<div class="equipment-modal">
			<!-- Search bar -->
			<div class="search-bar">
				<input
					type="text"
					placeholder="Search equipment by name or description..."
					bind:value={searchQuery}
					class="search-input"
				/>
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

			<!-- Create new equipment section -->
			<div class="create-section" bind:this={createSectionEl}>
				<Button
					variant="link"
					size="sm"
					class="h-auto p-0 justify-start font-medium"
					onclick={() => (showCreateForm = !showCreateForm)}
				>
					{showCreateForm ? '✕ Cancel' : '+ Add New Equipment'}
				</Button>

				{#if showCreateForm}
					<div class="create-form">
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
							<label for="eq-loc">Location</label>
							<input
								id="eq-loc"
								type="text"
								placeholder="e.g., Lab 1"
								bind:value={newEquipmentLocation}
								class="form-input"
							/>
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

						<Button
							class="w-full"
							onclick={handleCreate}
							disabled={isCreating}
						>
							{isCreating ? 'Creating...' : 'Create Equipment'}
						</Button>
					</div>
				{/if}
			</div>
		</div>

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
	</Dialog.Content>
</Dialog.Root>

<style>
	.equipment-modal {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1rem 1.5rem;
		max-height: 500px;
		overflow-y: auto;
	}

	.search-bar {
		flex-shrink: 0;
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
		flex: 1;
		overflow-y: auto;
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
		background-color: #e0f2fe;
		color: #0369a1;
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
		background-color: hsl(var(--muted));
		border-radius: 0.375rem;
		border: 1px solid hsl(var(--border));
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
		background: hsl(var(--background));
		color: hsl(var(--foreground));
	}

	.form-input:focus {
		outline: none;
		border-color: hsl(var(--primary));
		box-shadow: 0 0 0 2px hsl(var(--primary) / 0.1);
	}

	.error-message {
		padding: 0.5rem;
		background-color: #fee2e2;
		color: #991b1b;
		border-radius: 0.25rem;
		font-size: 0.875rem;
		margin-bottom: 0.75rem;
	}

</style>
