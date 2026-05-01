<script lang="ts">
    import RunCreatorUnitOpCard from './RunCreatorUnitOpCard.svelte';
    import EquipmentPickerModal from '$lib/components/modals/EquipmentPickerModal.svelte';
    import {
        computeEdits,
        groupUnitOpsByRole,
        groupEditsByRole,
        type Edit,
    } from '$lib/utils/runOverrides';
    import { detectEquipmentConflicts } from '$lib/components/protocol/protocolGraph';
    import type { ProtocolRole } from '$lib/schemas/protocols';
    import { fade, slide } from 'svelte/transition';
    import { flip } from 'svelte/animate';
    import { cubicOut } from 'svelte/easing';
    import { blockDuration, listDuration } from '$lib/transitions';

    interface OrgEquipment {
        id: string;
        name: string;
        description?: string;
        equipment_type?: string;
        location?: string;
        organization_id: string;
        created_at: string;
        updated_at: string;
    }

    type GraphNode = {
        id: string;
        type?: string;
        parentId?: string;
        data?: Record<string, unknown>;
        [k: string]: unknown;
    };

    type GraphEdge = { id?: string; source: string; target: string };

    type Graph = { nodes: GraphNode[]; edges: GraphEdge[] };

    interface Props {
        originalGraph: Graph;
        currentGraph: Graph;
        orgEquipment: OrgEquipment[];
        mediaPrepNodes: Array<{ id: string; label: string }>;
        roles: ProtocolRole[];
        activeRoleId: string | null;
        onChange: (nextGraph: Graph) => void;
        onRoleChange: (roleId: string) => void;
        onCreateEquipment?: (data: {
            name: string;
            description: string;
            equipment_type: string;
            location: string;
        }) => Promise<OrgEquipment>;
        readonly?: boolean;
    }

    let {
        originalGraph,
        currentGraph,
        orgEquipment,
        mediaPrepNodes,
        roles,
        activeRoleId,
        onChange,
        onRoleChange,
        onCreateEquipment,
    }: Props = $props();

    const isMultiRole = $derived(roles.length > 1);

    const allUnitOpNodes = $derived(
        (currentGraph?.nodes ?? []).filter((n) => n.type === 'unitOp'),
    );

    const visibleUnitOpNodes = $derived.by(() => {
        if (!isMultiRole || !activeRoleId) return allUnitOpNodes;
        const byRole = groupUnitOpsByRole(currentGraph);
        return byRole.get(activeRoleId) ?? [];
    });

    const edits = $derived(computeEdits(originalGraph, currentGraph));

    const editsByRole = $derived(
        isMultiRole ? groupEditsByRole(edits, currentGraph) : null,
    );

    const stats = $derived.by(() => {
        let value = 0;
        let swap = 0;
        let added = 0;
        let removed = 0;
        let instruction = 0;
        let schema = 0;
        for (const e of edits) {
            if (e.kind === 'VALUE') value++;
            else if (e.kind === 'SWAP') swap++;
            else if (e.kind === 'ADDED') added++;
            else if (e.kind === 'REMOVED') removed++;
            else if (e.kind === 'INSTRUCTION') instruction++;
            else if (e.kind === 'SCHEMA') schema++;
        }
        return { value, swap, added, removed, instruction, schema };
    });

    const conflicts = $derived(
        detectEquipmentConflicts(
            (currentGraph?.nodes ?? []) as Parameters<typeof detectEquipmentConflicts>[0],
            (currentGraph?.edges ?? []) as Parameters<typeof detectEquipmentConflicts>[1],
        ),
    );

    const activeRoleIndex = $derived(
        activeRoleId ? roles.findIndex((r) => r.id === activeRoleId) : -1,
    );
    const activeRole = $derived(
        activeRoleIndex >= 0 ? roles[activeRoleIndex] : null,
    );
    const activeRoleParamCount = $derived.by(() => {
        let n = 0;
        for (const node of visibleUnitOpNodes) {
            const params = (node.data as { params?: Record<string, unknown> } | undefined)?.params ?? {};
            n += Object.keys(params).length;
        }
        return n;
    });

    function gotoRole(delta: -1 | 1) {
        if (!isMultiRole || activeRoleIndex < 0) return;
        const next = (activeRoleIndex + delta + roles.length) % roles.length;
        onRoleChange(roles[next].id);
    }

    let swapNodeId = $state<string | null>(null);
    const swapNode = $derived(
        swapNodeId ? allUnitOpNodes.find((n) => n.id === swapNodeId) ?? null : null,
    );

    function patchNode(nextNode: GraphNode) {
        const nextNodes = currentGraph.nodes.map((n) =>
            n.id === nextNode.id ? nextNode : n,
        );
        onChange({ ...currentGraph, nodes: nextNodes });
    }

    function applyEquipment(next: Array<{ equipment_id: string; shareable: boolean }>) {
        if (!swapNode) return;
        patchNode({ ...swapNode, data: { ...swapNode.data, equipment: next } });
        swapNodeId = null;
    }

    function diffKey(e: Edit): string {
        return `${e.nodeId}|${e.kind}|${e.field ?? ''}`;
    }
</script>

<div class="overrides-editor">
    <div class="cards-column">
        {#if isMultiRole && activeRole}
            <div class="role-context" transition:slide={{ duration: 200, easing: cubicOut }}>
                <div class="rc-left">
                    <div class="role-bar" style:background={activeRole.color}></div>
                    <div>
                        <div class="rc-name">{activeRole.name}</div>
                        <div class="rc-meta">
                            Role {activeRoleIndex + 1} of {roles.length} ·
                            {visibleUnitOpNodes.length} UO ·
                            {activeRoleParamCount} params
                        </div>
                    </div>
                </div>
                <div class="role-nav">
                    <button
                        type="button"
                        aria-label="Previous role"
                        onclick={() => gotoRole(-1)}
                    >‹</button>
                    <span class="pos">{activeRoleIndex + 1} / {roles.length}</span>
                    <button
                        type="button"
                        aria-label="Next role"
                        onclick={() => gotoRole(1)}
                    >›</button>
                </div>
            </div>
        {/if}

        {#if visibleUnitOpNodes.length === 0}
            <div class="empty" in:fade={{ duration: blockDuration() }}>
                {#if isMultiRole}No unit ops for this role.{:else}No unit ops in this protocol.{/if}
            </div>
        {:else}
            {#each visibleUnitOpNodes as node (node.id)}
                <div
                    in:fade={{ duration: listDuration() }}
                    animate:flip={{ duration: listDuration() }}
                >
                    <RunCreatorUnitOpCard
                        node={node as Parameters<typeof RunCreatorUnitOpCard>[0]['node']}
                        {mediaPrepNodes}
                        {orgEquipment}
                        conflictingIds={new Set(conflicts.get(node.id) ?? [])}
                        onChange={patchNode}
                        onSwapEquipment={(id) => { swapNodeId = id; }}
                    />
                </div>
            {/each}
        {/if}
    </div>

    <aside class="diff-aside">
        <div class="aside-head">
            <h3 class="aside-title">Override summary</h3>
            <span class="aside-scope">all roles</span>
        </div>

        <div class="stats">
            <div class="stat-cell"><div class="stat-num" class:zero={stats.value === 0}>{stats.value}</div><div class="stat-lbl">Value</div></div>
            <div class="stat-cell"><div class="stat-num" class:zero={stats.swap === 0}>{stats.swap}</div><div class="stat-lbl">Equipment</div></div>
            <div class="stat-cell"><div class="stat-num" class:zero={stats.added === 0}>{stats.added}</div><div class="stat-lbl">Added</div></div>
            <div class="stat-cell"><div class="stat-num" class:zero={stats.removed === 0}>{stats.removed}</div><div class="stat-lbl">Removed</div></div>
        </div>

        {#if isMultiRole && editsByRole}
            {#each roles as role (role.id)}
                {@const groupEdits = editsByRole.get(role.id) ?? []}
                <div class="role-group">
                    <button
                        type="button"
                        class="role-group-head"
                        class:active={role.id === activeRoleId}
                        onclick={() => onRoleChange(role.id)}
                    >
                        <span class="rg-mark" style:background={role.color}></span>
                        <span class="rg-name">{role.name}</span>
                        <span class="rg-count">{groupEdits.length} edit{groupEdits.length === 1 ? '' : 's'}</span>
                    </button>
                    {#if groupEdits.length === 0}
                        <div class="rg-empty">— inheriting all defaults —</div>
                    {:else}
                        <ul class="diff-list">
                            {#each groupEdits as e (diffKey(e))}
                                <li class="diff-item">
                                    <span class="diff-tag tag-{e.kind.toLowerCase()}">{e.kind}</span>
                                    <span class="diff-step">{e.stepName}</span>
                                    {#if e.fieldLabel}<span class="diff-field">{e.fieldLabel}</span>{/if}
                                </li>
                            {/each}
                        </ul>
                    {/if}
                </div>
            {/each}
            {#if edits.length === 0}
                <p class="aside-empty">No edits — run will use protocol defaults.</p>
            {/if}
        {:else if edits.length > 0}
            <h4 class="aside-subtitle">Edits</h4>
            <ul class="diff-list">
                {#each edits as e (diffKey(e))}
                    <li class="diff-item">
                        <span class="diff-tag tag-{e.kind.toLowerCase()}">{e.kind}</span>
                        <span class="diff-step">{e.stepName}</span>
                        {#if e.fieldLabel}<span class="diff-field">{e.fieldLabel}</span>{/if}
                    </li>
                {/each}
            </ul>
        {:else}
            <p class="aside-empty">No edits — run will use protocol defaults.</p>
        {/if}
    </aside>
</div>

{#if swapNode}
    <EquipmentPickerModal
        open={true}
        nodeId={swapNode.id}
        currentEquipment={(swapNode.data as { equipment?: Array<{ equipment_id: string; shareable: boolean }> })?.equipment ?? []}
        orgEquipment={orgEquipment as Parameters<typeof EquipmentPickerModal>[0]['orgEquipment']}
        conflictingIds={new Set(conflicts.get(swapNode.id) ?? [])}
        onClose={() => (swapNodeId = null)}
        onApply={applyEquipment}
        onCreateEquipment={onCreateEquipment as Parameters<typeof EquipmentPickerModal>[0]['onCreateEquipment']}
    />
{/if}

<style>
    .overrides-editor {
        display: grid;
        gap: 1.5rem;
        grid-template-columns: 1fr 320px;
    }
    @media (max-width: 1100px) {
        .overrides-editor {
            grid-template-columns: 1fr;
        }
    }
    .cards-column {
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    .empty {
        padding: 1.5rem;
        font-size: 0.875rem;
        color: rgb(100 116 139);
        font-style: italic;
        border: 1px dashed rgb(226 232 240);
        border-radius: 0.5rem;
        text-align: center;
    }

    .role-context {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        padding: 0.75rem 1rem;
        background-color: white;
        border: 1px solid rgb(226 232 240);
        border-radius: 0.5rem;
    }
    .rc-left {
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }
    .role-bar {
        width: 0.25rem;
        height: 2rem;
        border-radius: 0.125rem;
        flex-shrink: 0;
    }
    .rc-name {
        font-size: 1rem;
        font-weight: 600;
        letter-spacing: -0.01em;
    }
    .rc-meta {
        margin-top: 0.125rem;
        font-size: 11px;
        color: rgb(100 116 139);
        font-family: ui-monospace, SFMono-Regular, monospace;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .role-nav {
        display: inline-flex;
        border: 1px solid rgb(226 232 240);
        border-radius: 0.375rem;
        overflow: hidden;
        background-color: white;
    }
    .role-nav button {
        width: 2rem;
        height: 2rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background-color: white;
        color: rgb(15 23 42);
        font-size: 0.875rem;
        cursor: pointer;
        border: none;
        transition: background-color 150ms;
    }
    .role-nav button:hover {
        background-color: rgb(241 245 249);
    }
    .role-nav .pos {
        padding: 0 0.75rem;
        display: inline-flex;
        align-items: center;
        font-family: ui-monospace, SFMono-Regular, monospace;
        font-size: 11px;
        color: rgb(100 116 139);
        background-color: rgb(248 250 252);
        border-left: 1px solid rgb(226 232 240);
        border-right: 1px solid rgb(226 232 240);
        letter-spacing: 0.05em;
    }

    .diff-aside {
        align-self: flex-start;
        position: sticky;
        top: 1rem;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid rgb(226 232 240);
        background-color: white;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }
    .aside-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .aside-title {
        font-size: 0.875rem;
        font-weight: 600;
        color: rgb(15 23 42);
    }
    .aside-scope {
        font-size: 11px;
        font-family: ui-monospace, SFMono-Regular, monospace;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: rgb(100 116 139);
    }
    .aside-subtitle {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: rgb(100 116 139);
        font-weight: 500;
        margin-top: 0.5rem;
    }
    .aside-empty {
        font-size: 0.75rem;
        color: rgb(100 116 139);
        font-style: italic;
    }

    .stats {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.5rem;
    }
    .stat-cell {
        padding: 0.625rem 0.75rem;
        border-radius: 0.375rem;
        border: 1px solid rgb(226 232 240);
        background-color: rgb(248 250 252 / 0.6);
    }
    .stat-num {
        font-family: ui-monospace, SFMono-Regular, monospace;
        font-size: 22px;
        font-weight: 500;
        line-height: 1;
        color: rgb(15 23 42);
    }
    .stat-num.zero {
        color: rgb(148 163 184);
    }
    .stat-lbl {
        margin-top: 0.25rem;
        font-size: 11px;
        font-family: ui-monospace, SFMono-Regular, monospace;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: rgb(100 116 139);
    }

    .role-group {
        margin-top: 0.5rem;
    }
    .role-group-head {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        width: 100%;
        text-align: left;
        padding: 0.5rem 0.625rem;
        margin: 0 -0.625rem 0.25rem;
        font-size: 0.75rem;
        color: rgb(100 116 139);
        background: transparent;
        border: 0;
        border-radius: 0.375rem;
        cursor: pointer;
        transition: background-color 150ms;
    }
    .role-group-head:hover {
        background-color: rgb(248 250 252);
    }
    .role-group-head.active {
        background: hsl(195 60% 96%);
    }
    .role-group-head.active .rg-name {
        color: rgb(20 184 166);
    }
    .rg-mark {
        width: 0.5rem;
        height: 0.5rem;
        border-radius: 9999px;
        flex-shrink: 0;
    }
    .rg-name {
        font-weight: 600;
        font-size: 13px;
        color: rgb(15 23 42);
    }
    .rg-count {
        margin-left: auto;
        font-family: ui-monospace, SFMono-Regular, monospace;
        font-size: 11px;
        letter-spacing: 0.05em;
        color: rgb(100 116 139);
    }
    .rg-empty {
        padding: 0.5rem 0 0.25rem;
        font-size: 0.75rem;
        color: rgb(100 116 139);
        font-style: italic;
    }

    .diff-list {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        font-size: 0.75rem;
    }
    .diff-item {
        display: flex;
        align-items: center;
        gap: 0.375rem;
    }
    .diff-tag {
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.375rem;
        border-radius: 0.25rem;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
    }
    .tag-value, .tag-swap {
        background-color: rgb(209 250 229);
        color: rgb(6 95 70);
    }
    .tag-added, .tag-schema {
        background-color: rgb(254 243 199);
        color: rgb(146 64 14);
    }
    .tag-removed {
        background-color: rgb(254 226 226);
        color: rgb(153 27 27);
    }
    .tag-instruction {
        background-color: rgb(219 234 254);
        color: rgb(30 64 175);
    }
    .diff-step {
        font-weight: 500;
        color: rgb(51 65 85);
    }
    .diff-field {
        color: rgb(100 116 139);
    }
</style>
