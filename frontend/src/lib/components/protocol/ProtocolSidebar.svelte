<script lang="ts">
    import { getCategoryColor, getCategoryIcon } from "$lib/categoryColors";
    import { api } from "$lib/api";
    import { getNextRoleColor } from "$lib/components/protocol/protocolNodes";

    interface Props {
        protocol: any;
        roles: any[];
        unitOps: any[];
        approvalRequired: boolean;
        protocolStatus: string;
        versionNumber: number;
        saving: boolean;
        previewingVersion: number | null;
        hasUnitOpNodes: boolean;
        onNameSaved: (name: string) => void;
        onDescriptionSaved: (description: string) => void;
        onRoleCreated: (role: any) => void;
        onRoleDeleted: (roleId: string) => void;
        onOpenCreateModal: (category: string) => void;
        onOpenPdfPreview: () => void;
        onSaveDraft: () => void;
        onSaveAndPublish: () => void;
        onDeleteOrArchive: () => void;
        onUnarchive: () => void;
    }

    let {
        protocol,
        roles,
        unitOps,
        approvalRequired,
        protocolStatus,
        versionNumber,
        saving,
        previewingVersion,
        hasUnitOpNodes,
        onNameSaved,
        onDescriptionSaved,
        onRoleCreated,
        onRoleDeleted,
        onOpenCreateModal,
        onOpenPdfPreview,
        onSaveDraft,
        onSaveAndPublish,
        onDeleteOrArchive,
        onUnarchive,
    }: Props = $props();

    // --- Internal state ---
    let editingName = $state(false);
    let nameInput = $state("");
    let editingDescription = $state(false);
    let descriptionInput = $state("");
    let searchQuery = $state("");
    let collapsedCategories = $state<Set<string>>(new Set());
    let showRoleInput = $state(false);
    let newRoleName = $state("");

    // --- Name editing ---
    function startEditingName() {
        nameInput = protocol?.name || "";
        editingName = true;
    }

    async function saveName() {
        if (!protocol || !nameInput.trim()) {
            editingName = false;
            return;
        }
        try {
            await api.put(`/science/protocols/${protocol.id}`, {
                name: nameInput.trim(),
            });
            onNameSaved(nameInput.trim());
        } catch {
            // silent
        }
        editingName = false;
    }

    function handleNameKeydown(e: KeyboardEvent) {
        if (e.key === "Enter") saveName();
        else if (e.key === "Escape") editingName = false;
    }

    // --- Description editing ---
    function startEditingDescription() {
        descriptionInput = protocol?.description || "";
        editingDescription = true;
    }

    async function saveDescription() {
        if (!protocol) {
            editingDescription = false;
            return;
        }
        try {
            await api.put(`/science/protocols/${protocol.id}`, {
                description: descriptionInput.trim(),
            });
            onDescriptionSaved(descriptionInput.trim());
        } catch {
            // silent
        }
        editingDescription = false;
    }

    function handleDescriptionKeydown(e: KeyboardEvent) {
        if (e.key === "Escape") editingDescription = false;
    }

    // --- Role management ---
    async function addRole() {
        if (!protocol || !newRoleName.trim()) return;
        try {
            const role = await api.post(
                `/science/protocols/${protocol.id}/roles`,
                {
                    name: newRoleName.trim(),
                    color: getNextRoleColor(roles.length),
                    sort_order: roles.length,
                },
            );
            newRoleName = "";
            showRoleInput = false;
            onRoleCreated(role);
        } catch (e: unknown) {
            console.error("Failed to add role:", e instanceof Error ? e.message : e);
        }
    }

    async function deleteRole(roleId: string) {
        if (!protocol) return;
        try {
            await api.delete(
                `/science/protocols/${protocol.id}/roles/${roleId}`,
            );
            onRoleDeleted(roleId);
        } catch (e: unknown) {
            console.error("Failed to delete role:", e instanceof Error ? e.message : e);
        }
    }

    // --- Category accordion ---
    function toggleCategory(cat: string) {
        const s = new Set(collapsedCategories);
        if (s.has(cat)) s.delete(cat);
        else s.add(cat);
        collapsedCategories = s;
    }

    // --- Drag start ---
    function onDragStart(event: DragEvent, op: any) {
        if (!event.dataTransfer) return;
        event.dataTransfer.setData(
            "application/svelteflow",
            JSON.stringify(op),
        );
        event.dataTransfer.effectAllowed = "move";
    }

    // --- Derived state ---
    const filteredOps = $derived(() => {
        if (!searchQuery.trim()) return unitOps;
        const q = searchQuery.toLowerCase();
        return unitOps.filter(
            (op: any) =>
                op.name.toLowerCase().includes(q) ||
                op.category.toLowerCase().includes(q),
        );
    });

    const categories = $derived(() => {
        const map = new Map<string, any[]>();
        for (const op of filteredOps()) {
            const cat = op.category || "Other";
            if (!map.has(cat)) map.set(cat, []);
            map.get(cat)!.push(op);
        }
        return map;
    });
</script>

<aside class="sidebar">
    <!-- Header -->
    <div class="sidebar-header">
        {#if editingName}
            <input
                type="text"
                bind:value={nameInput}
                onblur={saveName}
                onkeydown={handleNameKeydown}
                class="name-input"
                autofocus
            />
        {:else if protocol}
            <button class="name-display" onclick={startEditingName}>
                {protocol.name}
                <span class="edit-hint">&#9998;</span>
            </button>
        {:else}
            <span class="name-placeholder">Loading...</span>
        {/if}

        {#if protocol}
            <!-- Status badge -->
            {#if approvalRequired || protocolStatus !== "DRAFT"}
                <div class="status-row">
                    <span
                        class="status-badge"
                        class:draft={protocolStatus === "DRAFT"}
                        class:pending={protocolStatus === "PENDING_APPROVAL"}
                        class:approved={protocolStatus === "APPROVED"}
                    >
                        {protocolStatus === "PENDING_APPROVAL" ? "Pending Approval" : protocolStatus === "APPROVED" ? "Approved" : "Draft"}
                    </span>
                    {#if versionNumber > 0}
                        <span class="version-tag">v{versionNumber}</span>
                    {/if}
                </div>
            {/if}

            {#if editingDescription}
                <textarea
                    bind:value={descriptionInput}
                    onblur={saveDescription}
                    onkeydown={handleDescriptionKeydown}
                    class="description-input"
                    rows="2"
                    placeholder="Add a description..."
                    autofocus
                ></textarea>
            {:else}
                <button class="description-display" onclick={startEditingDescription}>
                    {protocol.description || "Add description..."}
                </button>
            {/if}

            <a href="/projects/{protocol.project_id}?tab=protocols" class="back-link">
                &#8592; Back to Project
            </a>
        {/if}
    </div>

    <!-- Roles Section -->
    <div class="sidebar-section">
        <div class="section-header-row">
            <span class="section-title">ROLES</span>
            <button
                class="icon-btn"
                onclick={() => (showRoleInput = !showRoleInput)}>+</button
            >
        </div>

        {#if showRoleInput}
            <div class="role-input-row">
                <input
                    type="text"
                    bind:value={newRoleName}
                    placeholder="Role name..."
                    class="role-input"
                    onkeydown={(e) => {
                        if (e.key === "Enter") addRole();
                    }}
                />
                <button class="role-add-btn" onclick={addRole}>Add</button>
            </div>
        {/if}

        <div class="roles-list">
            {#each roles as role}
                <div class="role-item">
                    <div
                        class="role-dot"
                        style:background={role.color}
                    ></div>
                    <span class="role-name">{role.name}</span>
                    <button
                        class="role-delete-btn"
                        onclick={() => deleteRole(role.id)}>&#10005;</button
                    >
                </div>
            {/each}
        </div>
    </div>

    <!-- Search -->
    <div class="sidebar-section search-section">
        <input
            type="text"
            bind:value={searchQuery}
            placeholder="Search ops..."
            class="search-input"
        />
    </div>

    <!-- Process Start -->
    <div class="sidebar-section">
        <div class="section-header-row">
            <span class="section-title">PROCESS</span>
        </div>
        <div class="cat-ops">
            <div
                role="button"
                tabindex="0"
                class="op-item"
                draggable="true"
                ondragstart={(e) => {
                    if (!e.dataTransfer) return;
                    e.dataTransfer.setData(
                        "application/svelteflow",
                        JSON.stringify({ _nodeType: "processStart" }),
                    );
                    e.dataTransfer.effectAllowed = "move";
                }}
            >
                <span class="op-icon" style="color: #6366f1;">&#x25B6;</span>
                <div class="op-info">
                    <span class="op-name">Process Start</span>
                    <span class="op-desc">Beginning of a process chain</span>
                </div>
            </div>
        </div>
    </div>

    <!-- Unit Operations -->
    <div class="ops-list">
        <div class="section-header-row">
            <span class="section-title">UNIT OPERATIONS</span>
        </div>

        {#if unitOps.length === 0}
            <p class="loading-text">Loading...</p>
        {:else}
            {#each [...categories().entries()] as [category, ops]}
                <div class="category-group">
                    <button
                        class="category-header"
                        onclick={() => toggleCategory(category)}
                    >
                        <span
                            class="cat-dot"
                            style:background={getCategoryColor(category)}
                        ></span>
                        <span class="cat-name">{category}</span>
                        <span
                            class="cat-chevron"
                            class:collapsed={collapsedCategories.has(
                                category,
                            )}>&#9662;</span
                        >
                        <span
                            class="cat-add-btn"
                            role="button"
                            tabindex="0"
                            onclick={(e) => {
                                e.stopPropagation();
                                onOpenCreateModal(category);
                            }}
                            onkeydown={(e) => {
                                if (e.key === "Enter") {
                                    e.stopPropagation();
                                    onOpenCreateModal(category);
                                }
                            }}
                            title="Add unit op to {category}">+</span
                        >
                    </button>

                    {#if !collapsedCategories.has(category)}
                        <div class="cat-ops">
                            {#each ops as op}
                                <div
                                    role="button"
                                    tabindex="0"
                                    class="op-item"
                                    draggable="true"
                                    ondragstart={(e) => onDragStart(e, op)}
                                >
                                    <span class="op-icon"
                                        >{getCategoryIcon(
                                            op.category,
                                        )}</span
                                    >
                                    <div class="op-info">
                                        <span class="op-name">
                                            {op.name}
                                            {#if op.scope && op.scope !== 'global'}
                                                <span
                                                    class="scope-dot {op.scope === 'organization' ? 'scope-org' : 'scope-project'}"
                                                    title="{op.scope === 'organization' ? 'Organization' : 'Project'}"
                                                ></span>
                                            {:else if op.scope === 'global'}
                                                <span class="scope-dot scope-global" title="Global"></span>
                                            {/if}
                                        </span>
                                        {#if op.description}
                                            <span class="op-desc"
                                                >{op.description}</span
                                            >
                                        {/if}
                                    </div>
                                </div>
                            {/each}
                        </div>
                    {/if}
                </div>
            {/each}
        {/if}
    </div>

    <!-- Drag hint -->
    <div class="drag-hint">
        <span>Drag nodes to canvas to add</span>
    </div>

    <!-- Save Button -->
    <div class="sidebar-footer">
        {#if hasUnitOpNodes}
            <button
                class="preview-sop-btn"
                onclick={onOpenPdfPreview}
                disabled={!protocol}
            >
                Preview Documents
            </button>
        {/if}
        <div class="button-group">
            <button
                class="save-btn"
                onclick={onSaveDraft}
                disabled={saving || !protocol || protocolStatus === "PENDING_APPROVAL" || protocolStatus === "ARCHIVED" || previewingVersion !== null}
                title="Save changes as a draft (no publish)"
            >
                {saving ? "Saving..." : previewingVersion !== null ? "Previewing..." : protocolStatus === "PENDING_APPROVAL" ? "Locked" : protocolStatus === "ARCHIVED" ? "Archived" : "Save Draft"}
            </button>
            <button
                class="publish-btn"
                onclick={onSaveAndPublish}
                disabled={saving || !protocol || protocolStatus === "PENDING_APPROVAL" || protocolStatus === "APPROVED" || protocolStatus === "ARCHIVED" || previewingVersion !== null}
                title={approvalRequired ? "Submit protocol for approval" : "Publish protocol"}
            >
                {saving ? "Saving..." : previewingVersion !== null ? "Previewing..." : approvalRequired ? "Submit for Approval" : "Publish"}
            </button>
        </div>
        {#if protocol && protocolStatus !== "PENDING_APPROVAL"}
            <button
                class="delete-archive-btn"
                onclick={protocolStatus === "ARCHIVED" ? onUnarchive : onDeleteOrArchive}
            >
                {protocolStatus === "ARCHIVED" ? "Unarchive" : protocolStatus === "APPROVED" ? "Archive" : "Delete"}
            </button>
        {/if}
    </div>
</aside>

<style>
    .sidebar {
        width: 280px;
        background: white;
        border-right: 1px solid hsl(240, 5.9%, 90%);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        flex-shrink: 0;
    }

    .sidebar-header {
        padding: 16px;
        border-bottom: 1px solid hsl(240, 5.9%, 90%);
    }

    .name-input {
        width: 100%;
        font-size: 16px;
        font-weight: 700;
        padding: 6px 8px;
        border: 1.5px solid hsl(173, 58%, 39%);
        border-radius: 6px;
        outline: none;
        color: #0f172a;
        box-sizing: border-box;
    }

    .name-display {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 16px;
        font-weight: 700;
        color: #0f172a;
        background: transparent;
        border: none;
        cursor: pointer;
        padding: 0;
        text-align: left;
        width: 100%;
    }

    .name-display:hover {
        color: hsl(173, 58%, 39%);
    }

    .edit-hint {
        font-size: 12px;
        opacity: 0;
        transition: opacity 0.15s;
    }

    .name-display:hover .edit-hint {
        opacity: 1;
    }

    .name-placeholder {
        font-size: 16px;
        font-weight: 700;
        color: #94a3b8;
    }

    .description-input {
        width: 100%;
        font-size: 12px;
        padding: 6px 8px;
        border: 1.5px solid hsl(173, 58%, 39%);
        border-radius: 6px;
        outline: none;
        color: #334155;
        box-sizing: border-box;
        font-family: inherit;
        resize: vertical;
        margin-top: 6px;
    }

    .description-display {
        display: block;
        font-size: 12px;
        color: #94a3b8;
        background: transparent;
        border: none;
        cursor: pointer;
        padding: 0;
        text-align: left;
        width: 100%;
        margin-top: 6px;
        line-height: 1.4;
        word-break: break-word;
    }

    .description-display:hover {
        color: hsl(173, 58%, 39%);
    }

    .back-link {
        display: block;
        font-size: 12px;
        color: #94a3b8;
        margin-top: 6px;
        text-decoration: none;
    }

    .back-link:hover {
        color: hsl(173, 58%, 39%);
    }

    .sidebar-section {
        padding: 12px 16px;
        border-bottom: 1px solid #f1f5f9;
    }

    .section-header-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
    }

    .section-title {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: #94a3b8;
        text-transform: uppercase;
    }

    .icon-btn {
        width: 22px;
        height: 22px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 4px;
        background: white;
        color: hsl(173, 58%, 39%);
        cursor: pointer;
        font-size: 14px;
        font-weight: 700;
        display: flex;
        align-items: center;
        justify-content: center;
        line-height: 1;
    }

    .icon-btn:hover {
        background: #f8fafc;
    }

    .role-input-row {
        display: flex;
        gap: 6px;
        margin-bottom: 8px;
    }

    .role-input {
        flex: 1;
        padding: 5px 8px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 4px;
        font-size: 12px;
        font-family: inherit;
    }

    .role-input:focus {
        outline: none;
        border-color: hsl(173, 58%, 39%);
    }

    .role-add-btn {
        padding: 5px 10px;
        background: hsl(173, 58%, 39%);
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        cursor: pointer;
    }

    .roles-list {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .role-item {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 6px;
        border-radius: 4px;
    }

    .role-item:hover {
        background: #f8fafc;
    }

    .role-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .role-name {
        flex: 1;
        font-size: 12px;
        color: #334155;
        font-weight: 500;
    }

    .role-delete-btn {
        width: 18px;
        height: 18px;
        border: none;
        background: transparent;
        color: transparent;
        cursor: pointer;
        border-radius: 4px;
        font-size: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .role-item:hover .role-delete-btn {
        color: #94a3b8;
    }

    .role-delete-btn:hover {
        background: #fee2e2;
        color: #ef4444 !important;
    }

    .search-section {
        padding: 8px 16px;
    }

    .search-input {
        width: 100%;
        padding: 7px 10px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 6px;
        font-size: 12px;
        font-family: inherit;
        color: #334155;
        box-sizing: border-box;
    }

    .search-input::placeholder {
        color: #94a3b8;
    }

    .search-input:focus {
        outline: none;
        border-color: hsl(173, 58%, 39%);
        box-shadow: 0 0 0 2px hsla(173, 58%, 39%, 0.1);
    }

    .ops-list {
        flex: 1;
        overflow-y: auto;
        padding: 12px 16px;
    }

    .loading-text {
        font-size: 12px;
        color: #94a3b8;
        font-style: italic;
    }

    .category-group {
        margin-bottom: 8px;
    }

    .category-header {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        padding: 6px 4px;
        background: transparent;
        border: none;
        cursor: pointer;
        font-family: inherit;
        border-radius: 4px;
    }

    .category-header:hover {
        background: #f8fafc;
    }

    .cat-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .cat-name {
        flex: 1;
        font-size: 12px;
        font-weight: 600;
        color: #334155;
        text-align: left;
    }

    .cat-chevron {
        font-size: 10px;
        color: #94a3b8;
        transition: transform 0.15s;
    }

    .cat-chevron.collapsed {
        transform: rotate(-90deg);
    }

    .cat-add-btn {
        width: 18px;
        height: 18px;
        border: none;
        background: transparent;
        color: #94a3b8;
        cursor: pointer;
        font-size: 14px;
        font-weight: 700;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        transition: opacity 0.15s;
    }

    .category-header:hover .cat-add-btn {
        opacity: 1;
    }

    .cat-add-btn:hover {
        color: hsl(173, 58%, 39%);
        background: #f1f5f9;
    }

    .cat-ops {
        padding-left: 20px;
        margin-top: 2px;
    }

    .op-item {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        padding: 6px 8px;
        border-radius: 6px;
        cursor: grab;
        transition: background 0.15s;
        margin-bottom: 2px;
    }

    .op-item:hover {
        background: #f8fafc;
    }

    .op-item:active {
        cursor: grabbing;
        background: #f1f5f9;
    }

    .op-icon {
        font-size: 14px;
        line-height: 1.3;
        flex-shrink: 0;
    }

    .op-info {
        display: flex;
        flex-direction: column;
        min-width: 0;
    }

    .op-name {
        font-size: 12px;
        font-weight: 600;
        color: #1e293b;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .scope-dot {
        display: inline-block;
        width: 6px;
        height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .scope-global {
        background-color: #94a3b8;
    }

    .scope-org {
        background-color: #3b82f6;
    }

    .scope-project {
        background-color: #22c55e;
    }

    .op-desc {
        font-size: 10px;
        color: #94a3b8;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 180px;
    }

    .drag-hint {
        padding: 8px 16px;
        text-align: center;
    }

    .drag-hint span {
        font-size: 10px;
        color: #cbd5e1;
        font-weight: 500;
    }

    .sidebar-footer {
        padding: 12px 16px;
        border-top: 1px solid hsl(240, 5.9%, 90%);
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .button-group {
        display: flex;
        gap: 8px;
    }

    .preview-sop-btn {
        width: 100%;
        padding: 9px 16px;
        background: white;
        color: hsl(173, 58%, 39%);
        border: 1px solid hsl(173, 58%, 39%);
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s;
        margin-bottom: 8px;
    }

    .preview-sop-btn:hover:not(:disabled) {
        background: hsl(173, 58%, 96%);
    }

    .preview-sop-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .save-btn {
        flex: 1;
        padding: 10px 16px;
        background: hsl(173, 58%, 39%);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s;
    }

    .save-btn:hover:not(:disabled) {
        background: hsl(173, 58%, 34%);
    }

    .save-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .publish-btn {
        flex: 1;
        padding: 10px 16px;
        background: hsl(34, 97%, 49%);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s;
    }

    .publish-btn:hover:not(:disabled) {
        background: hsl(34, 97%, 44%);
    }

    .publish-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .delete-archive-btn {
        width: 100%;
        padding: 8px 16px;
        background: white;
        color: #dc2626;
        border: 1px solid #fecaca;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        font-family: inherit;
        transition: all 0.15s;
        margin-top: 4px;
    }

    .delete-archive-btn:hover {
        background: #fef2f2;
        border-color: #f87171;
    }

    /* Status badge */
    .status-row {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-top: 6px;
    }

    .status-badge {
        font-size: 10px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 10px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }

    .status-badge.draft {
        background: #f1f5f9;
        color: #64748b;
    }

    .status-badge.pending {
        background: #fef3c7;
        color: #92400e;
    }

    .status-badge.approved {
        background: #d1fae5;
        color: #065f46;
    }

    .version-tag {
        font-size: 10px;
        font-weight: 600;
        color: #94a3b8;
        font-family: monospace;
    }
</style>
