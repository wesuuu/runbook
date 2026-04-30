<script lang="ts">
    import VersionHistoryDrawer from '$lib/components/analytics/VersionHistoryDrawer.svelte';
    import type { Protocol, ProtocolVersion } from '$lib/schemas/protocols';

    interface Props {
        protocols: Protocol[];
        protocolId: string | null;
        protocolVersionNumber: number | null;
        versions: ProtocolVersion[];
        loadingVersions: boolean;
        onChange: (next: { protocolId: string | null; protocolVersionNumber: number | null }) => void;
        onValidate: (valid: boolean) => void;
        onLoadVersions: (protocolId: string) => void;
    }

    let {
        protocols,
        protocolId,
        protocolVersionNumber,
        versions,
        loadingVersions,
        onChange,
        onValidate,
        onLoadVersions,
    }: Props = $props();

    let drawerOpen = $state(false);

    const visibleProtocols = $derived(
        protocols.filter((p) => (p.status ?? '').toUpperCase() !== 'ARCHIVED'),
    );

    const selectedProtocol = $derived(protocols.find((p) => p.id === protocolId) ?? null);

    const effectiveVersionNumber = $derived(
        protocolVersionNumber ?? selectedProtocol?.version_number ?? null,
    );

    const selectedVersion = $derived(
        versions.find((v) => v.version_number === effectiveVersionNumber) ?? null,
    );

    const isLatest = $derived(
        protocolVersionNumber === null ||
        protocolVersionNumber === selectedProtocol?.version_number,
    );

    $effect(() => {
        onValidate(!!protocolId && !!effectiveVersionNumber);
    });

    function setProtocolId(v: string) {
        const next = v === '' ? null : v;
        onChange({ protocolId: next, protocolVersionNumber: null });
        if (next) onLoadVersions(next);
    }

    function setVersionNumber(v: string) {
        const num = v === '' ? null : parseInt(v, 10);
        onChange({ protocolId, protocolVersionNumber: num });
    }

    function pickFromDrawer(versionNumber: number) {
        onChange({ protocolId, protocolVersionNumber: versionNumber });
        drawerOpen = false;
    }

    function unitOpStats(v: ProtocolVersion | null): string {
        if (!v) return '';
        const graph = v.graph as { nodes?: Array<{ type?: string; data?: { paramSchema?: { properties?: Record<string, unknown> }; equipment?: unknown[] } }> } | undefined;
        const nodes = graph?.nodes ?? [];
        const unitOps = nodes.filter((n) => n.type === 'unitOp');
        let paramCount = 0;
        let eqCount = 0;
        for (const n of unitOps) {
            paramCount += Object.keys(n.data?.paramSchema?.properties ?? {}).length;
            eqCount += (n.data?.equipment ?? []).length;
        }
        return `${unitOps.length} unit ops · ${paramCount} params · ${eqCount} equipment slots`;
    }
</script>

<section class="step-body">
    <header class="step-header">
        <h2>Step 2 · Pick a protocol & version</h2>
        <p class="step-help">Latest version is selected by default — change if you need to reproduce an older run.</p>
    </header>

    <div class="grid-row">
        <div class="field">
            <label for="proto-pick" class="field-label">Protocol</label>
            <select
                id="proto-pick"
                value={protocolId ?? ''}
                onchange={(e) => setProtocolId((e.target as HTMLSelectElement).value)}
                class="input-field"
            >
                <option value="">Select a protocol</option>
                {#each visibleProtocols as p (p.id)}
                    <option value={p.id}>{p.name}</option>
                {/each}
            </select>
        </div>

        <div class="field">
            <label for="ver-pick" class="field-label">Version</label>
            <select
                id="ver-pick"
                value={protocolVersionNumber ?? ''}
                onchange={(e) => setVersionNumber((e.target as HTMLSelectElement).value)}
                disabled={!protocolId || loadingVersions}
                class="input-field"
            >
                <option value="">Latest</option>
                {#each versions as v (v.version_number)}
                    <option value={v.version_number}>
                        v{v.version_number} — {new Date(v.created_at).toLocaleDateString()}
                        {#if v.created_by_name}· {v.created_by_name}{/if}
                    </option>
                {/each}
            </select>
        </div>
    </div>

    {#if selectedVersion}
        <div class="version-card">
            <div class="version-card-head">
                <span class="version-pill">v{selectedVersion.version_number}</span>
                <span class="version-name">{selectedVersion.name}</span>
                {#if isLatest}
                    <span class="latest-pill">LATEST</span>
                {/if}
            </div>
            <p class="version-stats">{unitOpStats(selectedVersion)}</p>
            <p class="version-desc">
                {selectedVersion.description || 'No description for this version.'}
            </p>
            <button type="button" class="compare-link" onclick={() => (drawerOpen = true)}>
                ↳ Compare versions
            </button>
        </div>
    {/if}
</section>

{#if drawerOpen && protocolId}
    <VersionHistoryDrawer
        versions={versions.map((v) => ({
            id: v.id,
            version_number: v.version_number,
            name: v.name,
            description: v.description ?? null,
            change_summary: v.change_summary ?? null,
            created_by_name: v.created_by_name ?? null,
            created_at: v.created_at,
        }))}
        currentVersion={effectiveVersionNumber ?? 0}
        loading={loadingVersions}
        onRevert={pickFromDrawer}
        onClose={() => (drawerOpen = false)}
    />
{/if}

<style>
    .step-body {
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
    }
    .step-header h2 {
        font-size: 1.25rem;
        font-weight: 600;
        color: rgb(15 23 42);
    }
    .step-help {
        font-size: 0.875rem;
        color: rgb(71 85 105);
        margin-top: 0.25rem;
    }
    .grid-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1rem;
    }
    .field {
        display: flex;
        flex-direction: column;
        gap: 0.375rem;
    }
    .field-label {
        font-size: 0.875rem;
        font-weight: 500;
        color: rgb(51 65 85);
    }
    .input-field {
        width: 100%;
        padding: 0.5rem 0.75rem;
        border: 1px solid rgb(209 213 219);
        border-radius: 0.5rem;
        font-size: 0.875rem;
        background-color: white;
    }
    .input-field:focus {
        outline: none;
        border-color: transparent;
        box-shadow: 0 0 0 2px rgb(20 184 166);
    }
    .input-field:disabled {
        background-color: rgb(249 250 251);
        color: rgb(100 116 139);
        cursor: not-allowed;
    }
    .version-card {
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid rgb(226 232 240);
        background-color: rgb(248 250 252 / 0.5);
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    .version-card-head {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .version-pill {
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.5rem;
        border-radius: 0.375rem;
        background-color: rgb(204 251 241);
        color: rgb(17 94 89);
        font-size: 0.75rem;
        font-weight: 600;
    }
    .version-name {
        font-size: 0.875rem;
        font-weight: 500;
        color: rgb(15 23 42);
    }
    .latest-pill {
        display: inline-flex;
        align-items: center;
        padding: 0.125rem 0.375rem;
        border-radius: 0.25rem;
        background-color: rgb(209 250 229);
        color: rgb(6 95 70);
        font-size: 0.625rem;
        font-weight: 700;
        text-transform: uppercase;
    }
    .version-stats {
        font-size: 0.75rem;
        color: rgb(100 116 139);
    }
    .version-desc {
        font-size: 0.875rem;
        color: rgb(51 65 85);
    }
    .compare-link {
        font-size: 0.75rem;
        color: rgb(15 118 110);
        align-self: flex-start;
        cursor: pointer;
        background: none;
        border: none;
        padding: 0;
        transition: all 150ms;
    }
    .compare-link:hover {
        text-decoration: underline;
    }
</style>
