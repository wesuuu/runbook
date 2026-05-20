<script lang="ts">
    import { getCategoryColor, getCategoryIcon } from "$lib/categoryColors";
    import { api } from "$lib/api";
    import { getNextRoleColor } from "$lib/components/protocol/protocolNodes";
    import { Button } from "$lib/components/ui/button";
    import ApprovalHistory from "$lib/components/protocol/ApprovalHistory.svelte";
    import ApprovalSignatureDialog from "$lib/components/protocol/ApprovalSignatureDialog.svelte";
    import SignoffBlock from "$lib/components/shared/SignoffBlock.svelte";
    import type { GlpRole, GlpSignoffResponse } from "$lib/schemas/glpSignoff";
    import { slide } from "svelte/transition";
    import { cubicOut } from "svelte/easing";

    interface Props {
        protocol: any;
        roles: any[];
        unitOps: any[];
        approvalRequired: boolean;
        protocolStatus: string;
        versionNumber: number;
        saving: boolean;
        previewingVersion: number | null;
        isHistoricalPreview: boolean;
        hasUnitOpNodes: boolean;
        canApprove?: boolean;
        currentUserId?: string;
        signoffs?: GlpSignoffResponse[];
        signoffRequiredRoles?: GlpRole[];
        signerMap?: Record<string, { id: string; full_name: string; email: string }>;
        signoffAttestationDefaults?: Partial<Record<GlpRole, string>>;
        onSignoffClick?: (role: GlpRole, defaultAttestation: string) => void;
        submitDisabledReason?: string | null;
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
        onOpClick: (op: any) => void;
        onApprovalChange?: () => void;
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
        isHistoricalPreview,
        hasUnitOpNodes,
        canApprove = false,
        currentUserId = '',
        signoffs = [],
        signoffRequiredRoles = [],
        signerMap = {},
        signoffAttestationDefaults = {},
        onSignoffClick,
        submitDisabledReason = null,
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
        onOpClick,
        onApprovalChange,
    }: Props = $props();

    let signatureDialogOpen = $state(false);
    let signatureMode = $state<'approve' | 'reject'>('approve');

    // The Approval section was removed in F-0087: approval is now driven
    // entirely by the GLP Settings inspector. We still need a compact
    // workflow strip so approvers can act on PENDING_APPROVAL protocols
    // and anyone can see the approval history.
    const showWorkflowSection = $derived(
        !!protocol &&
            (approvalRequired ||
                protocolStatus === 'PENDING_APPROVAL' ||
                protocolStatus === 'APPROVED'),
    );

    function openApproveDialog() {
        signatureMode = 'approve';
        signatureDialogOpen = true;
    }

    function openRejectDialog() {
        signatureMode = 'reject';
        signatureDialogOpen = true;
    }

    function handleSignatureSuccess() {
        onApprovalChange?.();
    }
    // Suppress unused variable warning
    void currentUserId;

    // --- Internal state ---
    let editingName = $state(false);
    let nameInput = $state("");
    let editingDescription = $state(false);
    let descriptionInput = $state("");
    let searchQuery = $state("");
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
            await api.put(`/protocols/${protocol.id}`, {
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
            await api.put(`/protocols/${protocol.id}`, {
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
                `/protocols/${protocol.id}/roles`,
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
                `/protocols/${protocol.id}/roles/${roleId}`,
            );
            onRoleDeleted(roleId);
        } catch (e: unknown) {
            console.error("Failed to delete role:", e instanceof Error ? e.message : e);
        }
    }

    // --- Library/category accordion ---
    type LibraryGroup = {
        key: string;            // "lib:core" or "_custom"
        displayName: string;
        categories: Map<string, any[]>;
    };

    const LIBRARY_DISPLAY_NAMES: Record<string, string> = {
        core: "Core",
    };

    function libraryDisplayName(slug: string): string {
        return LIBRARY_DISPLAY_NAMES[slug] ??
            slug.split("_")
                .map(s => s.charAt(0).toUpperCase() + s.slice(1))
                .join(" ");
    }

    let manualCollapse = $state<Set<string>>(new Set());

    function toggleGroup(key: string) {
        const s = new Set(manualCollapse);
        if (s.has(key)) s.delete(key);
        else s.add(key);
        manualCollapse = s;
    }

    const effectiveCollapse = $derived(
        searchQuery.trim() ? new Set<string>() : manualCollapse
    );

    const groups = $derived.by((): LibraryGroup[] => {
        const ops = filteredOps();
        const byLib: Map<string, Map<string, any[]>> = new Map();

        for (const op of ops) {
            const libKey = op.library_slug ? `lib:${op.library_slug}` : "_custom";
            if (!byLib.has(libKey)) byLib.set(libKey, new Map());
            const cats = byLib.get(libKey)!;
            const cat = op.category || "Other";
            if (!cats.has(cat)) cats.set(cat, []);
            cats.get(cat)!.push(op);
        }

        const out: LibraryGroup[] = [];
        for (const [libKey, cats] of byLib) {
            if (cats.size === 0) continue;
            const display = libKey === "_custom"
                ? "Custom (My Org)"
                : libraryDisplayName(libKey.slice(4));
            out.push({ key: libKey, displayName: display, categories: cats });
        }
        // Custom always last; libraries alphabetical otherwise
        out.sort((a, b) => {
            if (a.key === "_custom") return 1;
            if (b.key === "_custom") return -1;
            return a.displayName.localeCompare(b.displayName);
        });
        return out;
    });

    // --- Drag start ---
    function onDragStart(event: DragEvent, op: any) {
        if (!event.dataTransfer) return;
        event.dataTransfer.setData(
            "application/svelteflow",
            JSON.stringify(op),
        );
        event.dataTransfer.effectAllowed = "move";
    }

    // --- Search helpers ---
    function escapeHtml(s: string): string {
        return s.replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        } as Record<string, string>)[c]);
    }

    function highlightMatch(text: string, query: string): string {
        if (!query.trim()) return escapeHtml(text);
        const q = query.toLowerCase();
        const lower = text.toLowerCase();
        const idx = lower.indexOf(q);
        if (idx < 0) return escapeHtml(text);
        return `${escapeHtml(text.slice(0, idx))}<mark>${escapeHtml(text.slice(idx, idx + q.length))}</mark>${escapeHtml(text.slice(idx + q.length))}`;
    }

    // --- Derived state ---
    const filteredOps = $derived(() => {
        if (!searchQuery.trim()) return unitOps;
        const q = searchQuery.toLowerCase();
        return unitOps.filter(
            (op: any) =>
                op.name.toLowerCase().includes(q) ||
                op.category.toLowerCase().includes(q) ||
                (op.library_slug ?? "").toLowerCase().includes(q) ||
                libraryDisplayName(op.library_slug ?? "").toLowerCase().includes(q)
        );
    });

</script>

<aside class="sidebar" data-tour="protocol-sidebar">
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
            <Button variant="ghost" class="name-display" onclick={startEditingName}>
                {protocol.name}
                <span class="edit-hint">&#9998;</span>
            </Button>
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
                <Button variant="ghost" class="description-display" onclick={startEditingDescription}>
                    {protocol.description || "Add description..."}
                </Button>
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
            <Button
                variant="outline"
                size="icon-sm"
                class="icon-btn"
                onclick={() => (showRoleInput = !showRoleInput)}
            >
                +
            </Button>
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
                <Button size="sm" onclick={addRole}>Add</Button>
            </div>
        {/if}

        <div class="roles-list">
            {#each roles as role}
                <div
                    class="role-item"
                    draggable="true"
                    title="Drag onto canvas to add lane"
                    ondragstart={(e) => {
                        if (!e.dataTransfer) return;
                        e.dataTransfer.setData(
                            "application/svelteflow",
                            JSON.stringify({
                                _nodeType: "swimLane",
                                role: { id: role.id, name: role.name, color: role.color },
                            }),
                        );
                        e.dataTransfer.effectAllowed = "move";
                    }}
                >
                    <div
                        class="role-dot"
                        style:background={role.color}
                    ></div>
                    <span class="role-name">{role.name}</span>
                    <Button
                        variant="ghost"
                        size="icon-sm"
                        class="role-delete-btn"
                        onclick={() => deleteRole(role.id)}
                    >
                        &#10005;
                    </Button>
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
            {#each groups as group (group.key)}
                <div class="library-group">
                    <Button
                        variant="ghost"
                        class="library-header"
                        onclick={() => toggleGroup(group.key)}
                    >
                        <span class="lib-name">{@html highlightMatch(group.displayName, searchQuery)}</span>
                        <span
                            class="cat-chevron"
                            class:collapsed={effectiveCollapse.has(group.key)}
                        >&#9662;</span>
                    </Button>

                    {#if !effectiveCollapse.has(group.key)}
                        <div class="lib-content" transition:slide={{ duration: 180, easing: cubicOut }}>
                        {#each [...group.categories.entries()] as [category, ops]}
                            <div class="category-group">
                                <Button
                                    variant="ghost"
                                    class="category-header"
                                    onclick={() => toggleGroup(`${group.key}:${category}`)}
                                >
                                    <span class="cat-dot" style:background={getCategoryColor(category)}></span>
                                    <span class="cat-name">{@html highlightMatch(category, searchQuery)}</span>
                                    <span
                                        class="cat-chevron"
                                        class:collapsed={effectiveCollapse.has(`${group.key}:${category}`)}
                                    >&#9662;</span>
                                    <span
                                        class="cat-add-btn"
                                        role="button"
                                        tabindex="0"
                                        onclick={(e) => { e.stopPropagation(); onOpenCreateModal(category); }}
                                        onkeydown={(e) => { if (e.key === "Enter") { e.stopPropagation(); onOpenCreateModal(category); } }}
                                        title="Add unit op to {category}"
                                    >+</span>
                                </Button>

                                {#if !effectiveCollapse.has(`${group.key}:${category}`)}
                                    <div class="cat-ops" transition:slide={{ duration: 180, easing: cubicOut }}>
                                        {#each ops as op}
                                            <div
                                                role="button"
                                                tabindex="0"
                                                class="op-item"
                                                draggable="true"
                                                ondragstart={(e) => onDragStart(e, op)}
                                                onclick={() => onOpClick(op)}
                                                onkeydown={(e) => { if (e.key === "Enter") onOpClick(op); }}
                                            >
                                                <span class="op-icon">{getCategoryIcon(op.category)}</span>
                                                <div class="op-info">
                                                    <span class="op-name">
                                                        {@html highlightMatch(op.name, searchQuery)}
                                                        {#if op.scope === 'organization'}
                                                            <span class="scope-dot scope-org" title="Organization"></span>
                                                        {:else if op.scope === 'project'}
                                                            <span class="scope-dot scope-project" title="Project"></span>
                                                        {/if}
                                                    </span>
                                                    {#if op.description}
                                                        <span class="op-desc">{op.description}</span>
                                                    {/if}
                                                </div>
                                            </div>
                                        {/each}
                                    </div>
                                {/if}
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

    <!-- Workflow strip — appears when GLP approval is in play. The
         designation that used to live here moved into GLP Settings. -->
    {#if showWorkflowSection && protocol}
        <div class="sidebar-section approval-section" data-testid="workflow-section">
            <div class="section-header-row">
                <span class="section-title">WORKFLOW</span>
            </div>

            {#if canApprove && protocolStatus === 'PENDING_APPROVAL'}
                <div class="approval-actions">
                    <Button
                        variant="default"
                        class="approve-btn"
                        onclick={openApproveDialog}
                        data-testid="approval-approve-btn"
                    >
                        Approve
                    </Button>
                    <Button
                        variant="outline"
                        class="reject-btn"
                        onclick={openRejectDialog}
                        data-testid="approval-reject-btn"
                    >
                        Reject
                    </Button>
                </div>
            {/if}

            {#if protocol && signoffRequiredRoles.length > 0 && (protocolStatus === 'PENDING_APPROVAL' || protocolStatus === 'APPROVED') && onSignoffClick}
                <div class="mt-3" data-testid="protocol-glp-signoffs">
                    <div class="flex items-baseline justify-between mb-2">
                        <h3 class="text-sm font-semibold">GLP Sign-offs</h3>
                        <span class="text-[10px] font-mono text-muted-foreground">21 CFR Part 58</span>
                    </div>
                    <SignoffBlock
                        entityType="protocol"
                        entityId={protocol.id}
                        requiredRoles={signoffRequiredRoles}
                        {signoffs}
                        signers={signerMap}
                        {currentUserId}
                        attestationDefaults={signoffAttestationDefaults}
                        onSignClick={onSignoffClick}
                        compact
                    />
                </div>
            {/if}

            {#if approvalRequired}
                <ApprovalHistory protocolId={protocol.id} />
            {/if}
        </div>
    {/if}

    <!-- Save Button -->
    <div class="sidebar-footer">
        <Button
            variant="outline"
            class="preview-sop-btn"
            onclick={onOpenPdfPreview}
            disabled={!protocol || !hasUnitOpNodes}
            title={hasUnitOpNodes
                ? 'Preview the generated SOP and Batch Record'
                : 'Add at least one unit operation to preview the SOP and Batch Record'}
        >
            Preview Documents
        </Button>
        <div class="button-group">
            <Button
                variant="default"
                class="save-btn"
                onclick={onSaveDraft}
                disabled={saving || !protocol || protocolStatus === "PENDING_APPROVAL" || protocolStatus === "ARCHIVED" || isHistoricalPreview}
                title="Save changes as a draft (no publish)"
                data-tour="protocol-save"
            >
                {saving ? "Saving..." : isHistoricalPreview ? "Previewing..." : protocolStatus === "PENDING_APPROVAL" ? "Locked" : protocolStatus === "ARCHIVED" ? "Archived" : "Save Draft"}
            </Button>
            <Button
                variant="default"
                class="publish-btn"
                onclick={onSaveAndPublish}
                disabled={saving || !protocol || protocolStatus === "PENDING_APPROVAL" || protocolStatus === "APPROVED" || protocolStatus === "ARCHIVED" || isHistoricalPreview || !!submitDisabledReason}
                title={submitDisabledReason ?? (approvalRequired ? "Submit protocol for approval" : "Publish protocol")}
            >
                {saving ? "Saving..." : isHistoricalPreview ? "Previewing..." : approvalRequired ? "Submit for Approval" : "Publish"}
            </Button>
        </div>
        {#if protocol && protocolStatus !== "PENDING_APPROVAL"}
            <Button
                variant="outline"
                class="delete-archive-btn"
                onclick={protocolStatus === "ARCHIVED" ? onUnarchive : onDeleteOrArchive}
            >
                {protocolStatus === "ARCHIVED" ? "Unarchive" : protocolStatus === "APPROVED" ? "Archive" : "Delete"}
            </Button>
        {/if}
    </div>
</aside>

{#if protocol}
    <ApprovalSignatureDialog
        bind:open={signatureDialogOpen}
        mode={signatureMode}
        protocolId={protocol.id}
        onSuccess={handleSignatureSuccess}
    />
{/if}

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

    :global(.name-display) {
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
        height: auto;
        white-space: normal;
        overflow: visible;
    }

    :global(.name-display:hover) {
        color: hsl(173, 58%, 39%);
        background: transparent;
    }

    .edit-hint {
        font-size: 12px;
        opacity: 0;
        transition: opacity 0.15s;
    }

    :global(.name-display:hover) .edit-hint {
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

    :global(.description-display) {
        display: block;
        font-size: 12px;
        color: #94a3b8;
        background: transparent;
        border: none;
        cursor: pointer;
        padding: 0;
        text-align: left;
        width: 100%;
        height: auto;
        margin-top: 6px;
        line-height: 1.4;
        word-break: break-word;
        justify-content: flex-start;
        font-weight: normal;
        white-space: normal;
        overflow: visible;
    }

    :global(.description-display:hover) {
        color: hsl(173, 58%, 39%);
        background: transparent;
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

    :global(.icon-btn) {
        width: 22px;
        height: 22px;
        min-width: 22px;
        border: 1px solid hsl(240, 5.9%, 90%);
        border-radius: 4px;
        background: white;
        color: hsl(173, 58%, 39%);
        font-size: 14px;
        font-weight: 700;
        line-height: 1;
        padding: 0;
    }

    :global(.icon-btn:hover) {
        background: #f8fafc;
        color: hsl(173, 58%, 39%);
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

    :global(.role-delete-btn) {
        width: 18px;
        height: 18px;
        min-width: 18px;
        border: none;
        background: transparent;
        color: transparent;
        border-radius: 4px;
        font-size: 10px;
        padding: 0;
    }

    .role-item:hover :global(.role-delete-btn) {
        color: #94a3b8;
    }

    :global(.role-delete-btn:hover) {
        background: #fee2e2 !important;
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

    .library-group {
        margin-bottom: 12px;
    }

    :global(.library-header) {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        height: auto;
        padding: 6px 4px;
        background: transparent;
        border: none;
        font-family: inherit;
        border-radius: 4px;
        justify-content: flex-start;
        font-weight: 600;
    }

    :global(.library-header:hover) {
        background: #f8fafc;
    }

    .lib-name {
        flex: 1;
        font-size: 13px;
        font-weight: 700;
        color: #0f172a;
        text-align: left;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .category-group {
        margin-bottom: 8px;
    }

    :global(.category-header) {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        height: auto;
        padding: 6px 4px;
        background: transparent;
        border: none;
        font-family: inherit;
        border-radius: 4px;
        justify-content: flex-start;
        font-weight: 400;
    }

    :global(.category-header:hover) {
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

    :global(.category-header:hover) .cat-add-btn {
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

    :global(.ops-list mark) {
        background: hsla(40, 95%, 60%, 0.4);
        color: inherit;
        padding: 0 1px;
        border-radius: 2px;
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

    :global(.preview-sop-btn) {
        width: 100%;
        height: auto;
        padding: 9px 16px;
        background: white;
        color: hsl(173, 58%, 39%);
        border: 1px solid hsl(173, 58%, 39%);
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 8px;
    }

    :global(.preview-sop-btn:hover:not(:disabled)) {
        background: hsl(173, 58%, 96%);
        color: hsl(173, 58%, 39%);
    }

    :global(.save-btn) {
        flex: 1;
        height: auto;
        padding: 10px 16px;
        background: hsl(173, 58%, 39%);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
    }

    :global(.save-btn:hover:not(:disabled)) {
        background: hsl(173, 58%, 34%);
        color: white;
    }

    :global(.publish-btn) {
        flex: 1;
        height: auto;
        padding: 10px 16px;
        background: hsl(34, 97%, 49%);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
    }

    :global(.publish-btn:hover:not(:disabled)) {
        background: hsl(34, 97%, 44%);
        color: white;
    }

    :global(.delete-archive-btn) {
        width: 100%;
        height: auto;
        padding: 8px 16px;
        background: white;
        color: #dc2626;
        border: 1px solid #fecaca;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        font-family: inherit;
        margin-top: 4px;
    }

    :global(.delete-archive-btn:hover) {
        background: #fef2f2;
        border-color: #f87171;
        color: #dc2626;
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

    .approval-section {
        background: #fafafa;
    }

    .approval-actions {
        display: flex;
        gap: 6px;
        margin-top: 6px;
    }

    :global(.approval-action-btn) {
        width: 100%;
        margin-top: 6px;
    }

    :global(.approve-btn) {
        flex: 1;
        background: hsl(160, 60%, 40%);
        color: white;
    }

    :global(.approve-btn:hover) {
        background: hsl(160, 60%, 35%);
        color: white;
    }

    :global(.reject-btn) {
        flex: 1;
        color: hsl(0, 70%, 45%);
        border-color: hsl(0, 70%, 80%);
    }
</style>
