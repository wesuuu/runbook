<script lang="ts">
    import { api } from '$lib/api';
    import { PROVIDERS, CAPABILITIES, getProviderDef, type ProviderDef } from '$lib/ai-providers';
    import { AiSettingsListSchema, AiTestConnectionSchema, type AiProviderConfig } from '$lib/schemas/ai';

    let { isAdmin = false }: { isAdmin: boolean } = $props();

    let configs = $state<AiProviderConfig[]>([]);
    let subscriptionTier = $state('essentials');
    let expandedCapability = $state<string | null>(null);
    let loading = $state(true);
    let saving = $state(false);
    let testResults = $state<Record<string, { success: boolean; message: string }>>({});
    let testing = $state<Record<string, boolean>>({});
    let error = $state<string | null>(null);

    // Edit form state
    let editProvider = $state('ollama');
    let editModelName = $state('');
    let editCredentials = $state<Record<string, string>>({});
    let editEnabled = $state(true);

    const configMap = $derived(
        Object.fromEntries(configs.map((c) => [c.capability, c]))
    );

    const isPro = $derived(
        subscriptionTier === 'pro' || subscriptionTier === 'enterprise'
    );

    type CardState = 'app-default' | 'custom' | 'not-configured';

    function getCardState(capId: string): CardState {
        if (configMap[capId]) return 'custom';
        if (isPro) return 'app-default';
        return 'not-configured';
    }

    function stateBadge(state: CardState): { label: string; classes: string } {
        switch (state) {
            case 'app-default':
                return { label: 'App Default', classes: 'bg-green-100 text-green-800' };
            case 'custom':
                return { label: 'Custom', classes: 'bg-blue-100 text-blue-800' };
            case 'not-configured':
                return { label: 'Not Configured', classes: 'bg-amber-100 text-amber-800' };
        }
    }

    async function loadSettings() {
        loading = true;
        error = null;
        try {
            const data = await api.get('/ai/settings', { schema: AiSettingsListSchema });
            configs = data.items;
            subscriptionTier = data.subscription_tier;
        } catch (e) {
            error = 'Failed to load AI settings';
        } finally {
            loading = false;
        }
    }

    function startEdit(capId: string) {
        const existing = configMap[capId];
        if (existing) {
            editProvider = existing.provider;
            editModelName = existing.model_name;
            editCredentials = {};
            editEnabled = existing.is_enabled;
        } else {
            editProvider = PROVIDERS[0].id;
            editModelName = '';
            editCredentials = {};
            editEnabled = true;
        }
        testResults = { ...testResults, [capId]: undefined as any };
        expandedCapability = capId;
    }

    function cancelEdit() {
        expandedCapability = null;
    }

    async function saveConfig(capId: string) {
        saving = true;
        error = null;
        try {
            const body: Record<string, unknown> = {
                provider: editProvider,
                model_name: editModelName,
                is_enabled: editEnabled,
            };
            const hasCredentials = Object.values(editCredentials).some((v) => v);
            if (hasCredentials) {
                body.credentials = editCredentials;
            }
            await api.put(`/ai/settings/${capId}`, body);
            expandedCapability = null;
            await loadSettings();
        } catch (e: any) {
            error = e?.data?.detail || e?.message || 'Failed to save configuration';
        } finally {
            saving = false;
        }
    }

    async function deleteConfig(capId: string) {
        try {
            await api.delete(`/ai/settings/${capId}`);
            expandedCapability = null;
            await loadSettings();
        } catch (e) {
            error = 'Failed to remove configuration';
        }
    }

    async function testConnection(capId: string) {
        testing = { ...testing, [capId]: true };
        testResults = { ...testResults, [capId]: undefined as any };
        try {
            const result = await api.post(`/ai/settings/${capId}/test`, {}, { schema: AiTestConnectionSchema });
            testResults = { ...testResults, [capId]: result };
        } catch (e) {
            testResults = { ...testResults, [capId]: { success: false, message: 'Test request failed' } };
        } finally {
            testing = { ...testing, [capId]: false };
        }
    }

    $effect(() => {
        loadSettings();
    });
</script>

{#if loading}
    <div class="flex items-center justify-center py-12">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-foreground"></div>
    </div>
{:else}
    {#if error}
        <div class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
            {error}
        </div>
    {/if}

    {#if !isPro}
        <div class="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
            Your organization is on the <strong>{subscriptionTier}</strong> tier.
            Configure your own AI providers below, or upgrade to Pro for platform-managed AI.
        </div>
    {/if}

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        {#each CAPABILITIES as cap}
            {@const state = getCardState(cap.id)}
            {@const config = configMap[cap.id]}
            {@const badge = stateBadge(state)}
            {@const isExpanded = expandedCapability === cap.id}

            <div class="border rounded-lg p-4 {isExpanded ? 'ring-2 ring-primary' : ''}">
                <!-- Header -->
                <div class="flex items-center justify-between">
                    <div>
                        <h3 class="font-medium text-sm">{cap.label}</h3>
                        <p class="text-xs text-muted-foreground">{cap.description}</p>
                    </div>
                    <span class="text-xs px-2 py-0.5 rounded-full {badge.classes}">{badge.label}</span>
                </div>

                <!-- Summary line -->
                {#if config}
                    <p class="text-xs text-muted-foreground mt-2">
                        {config.provider} / {config.model_name}
                        {#if !config.credentials_set}
                            <span class="text-amber-600"> — no credentials</span>
                        {/if}
                    </p>
                {:else if state === 'app-default'}
                    <p class="text-xs text-muted-foreground mt-2">Using platform model</p>
                {/if}

                <!-- Admin actions (collapsed) -->
                {#if !isExpanded}
                    <div class="flex items-center gap-3 mt-3">
                        {#if isAdmin}
                            <button
                                class="text-xs text-primary hover:underline"
                                onclick={() => startEdit(cap.id)}
                            >
                                {state === 'not-configured' ? 'Configure' : 'Edit'}
                            </button>
                        {/if}
                        {#if state === 'app-default' || state === 'custom'}
                            <button
                                class="text-xs px-3 py-1 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
                                onclick={() => testConnection(cap.id)}
                                disabled={testing[cap.id]}
                            >
                                {#if testing[cap.id]}
                                    <span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
                                    Testing...
                                {:else}
                                    Test Connection
                                {/if}
                            </button>
                        {/if}
                    </div>
                    {#if testResults[cap.id]}
                        <div class="text-xs mt-2 p-2 rounded {testResults[cap.id].success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}">
                            {testResults[cap.id].message}
                        </div>
                    {/if}
                {/if}

                <!-- Expanded edit form -->
                {#if isAdmin && isExpanded}
                    <div class="mt-4 space-y-3 border-t pt-3">
                        <!-- Provider select -->
                        <div>
                            <label class="text-xs font-medium block mb-1">Provider</label>
                            <select
                                class="w-full text-sm border rounded px-2 py-1.5 bg-background"
                                bind:value={editProvider}
                                onchange={() => { editCredentials = {}; }}
                            >
                                {#each PROVIDERS as p}
                                    <option value={p.id}>{p.label}</option>
                                {/each}
                            </select>
                        </div>

                        <!-- Model name -->
                        <div>
                            <label class="text-xs font-medium block mb-1">Model Name</label>
                            <input
                                type="text"
                                class="w-full text-sm border rounded px-2 py-1.5"
                                bind:value={editModelName}
                                placeholder="e.g. claude-sonnet-4-20250514"
                            />
                        </div>

                        <!-- Dynamic credential fields -->
                        {#each getProviderDef(editProvider)?.fields ?? [] as field}
                            <div>
                                <label class="text-xs font-medium block mb-1">
                                    {field.label}
                                    {#if field.required}<span class="text-red-500">*</span>{/if}
                                </label>
                                <input
                                    type={field.type === 'secret' ? 'password' : 'text'}
                                    class="w-full text-sm border rounded px-2 py-1.5"
                                    placeholder={field.placeholder ?? ''}
                                    value={editCredentials[field.name] ?? ''}
                                    oninput={(e) => {
                                        editCredentials = { ...editCredentials, [field.name]: e.currentTarget.value };
                                    }}
                                />
                                {#if config?.credentials_set && field.type === 'secret'}
                                    <p class="text-xs text-muted-foreground mt-0.5">Leave blank to keep existing</p>
                                {/if}
                            </div>
                        {/each}

                        <!-- Enabled toggle -->
                        <label class="flex items-center gap-2 text-xs">
                            <input type="checkbox" bind:checked={editEnabled} />
                            Enabled
                        </label>

                        <!-- Action buttons -->
                        <div class="flex items-center gap-2 pt-2 flex-wrap">
                            <button
                                class="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded hover:opacity-90"
                                onclick={() => saveConfig(cap.id)}
                                disabled={saving || !editModelName}
                            >
                                {saving ? 'Saving...' : 'Save'}
                            </button>
                            <button
                                class="px-3 py-1.5 text-xs border rounded-md hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
                                onclick={() => testConnection(cap.id)}
                                disabled={testing[cap.id]}
                            >
                                {#if testing[cap.id]}
                                    <span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
                                    Testing...
                                {:else}
                                    Test Connection
                                {/if}
                            </button>
                            <button
                                class="px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
                                onclick={cancelEdit}
                            >
                                Cancel
                            </button>
                            {#if state === 'custom' && isPro}
                                <button
                                    class="ml-auto px-3 py-1.5 text-xs text-amber-700 hover:underline"
                                    onclick={() => deleteConfig(cap.id)}
                                >
                                    Use App Default
                                </button>
                            {/if}
                        </div>

                        <!-- Test result -->
                        {#if testResults[cap.id]}
                            <div class="text-xs mt-2 p-2 rounded {testResults[cap.id].success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}">
                                {testResults[cap.id].message}
                            </div>
                        {/if}
                    </div>
                {/if}
            </div>
        {/each}
    </div>
{/if}
