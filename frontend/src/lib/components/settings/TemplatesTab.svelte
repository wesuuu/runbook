<script lang="ts">
    import { onMount } from 'svelte';
    import { api } from '$lib/api';
    import { toast } from '$lib/toast';
    import {
        DocumentTemplateListSchema,
        TemplateVariablesSchema,
        type DocumentTemplate,
        type TemplateVariables,
        type TemplateVariableEntry,
    } from '$lib/schemas/templates';
    import { Button } from '$lib/components/ui/button';
    import TemplateUploadModal from './TemplateUploadModal.svelte';
    import TemplateConvertModal from '$lib/components/TemplateConvertModal.svelte';

    let { isAdmin = false }: { isAdmin: boolean } = $props();

    let templates = $state<DocumentTemplate[]>([]);
    let variables = $state<TemplateVariables | null>(null);
    let loading = $state(true);
    let showUpload = $state(false);
    let showConvert = $state(false);
    let showVariables = $state(false);
    let typeFilter = $state<string>('');

    const variableEntries = $derived(
        variables
            ? (Object.entries(variables) as [string, TemplateVariableEntry[]][])
            : [],
    );

    const filtered = $derived(
        typeFilter ? templates.filter((t) => t.template_type === typeFilter) : templates,
    );

    onMount(() => {
        loadTemplates();
        loadVariables();
    });

    async function loadTemplates() {
        loading = true;
        try {
            templates = await api.get('/templates', {
                schema: DocumentTemplateListSchema,
            });
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to load templates');
        } finally {
            loading = false;
        }
    }

    async function loadVariables() {
        try {
            variables = await api.get('/templates/variables', {
                schema: TemplateVariablesSchema,
            });
        } catch {
            /* non-critical */
        }
    }

    async function archiveTemplate(id: string) {
        try {
            await api.put(`/templates/${id}`, { status: 'ARCHIVED' });
            toast.success('Template archived');
            await loadTemplates();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to archive');
        }
    }

    async function unarchiveTemplate(id: string) {
        try {
            await api.put(`/templates/${id}`, { status: 'ACTIVE' });
            toast.success('Template restored');
            await loadTemplates();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to restore');
        }
    }

    async function setAsDefault(id: string) {
        try {
            await api.put(`/templates/${id}`, { set_as_default: true });
            toast.success('Default template updated');
            await loadTemplates();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to set default');
        }
    }
</script>

<div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
        <div>
            <h3 class="text-lg font-semibold">Document Templates</h3>
            <p class="text-sm text-muted-foreground">
                Manage .docx templates for SOP and Batch Record exports.
            </p>
        </div>
        {#if isAdmin}
            <div class="flex gap-2">
                <Button variant="outline" onclick={() => (showConvert = true)}>Convert Document</Button>
                <Button onclick={() => (showUpload = true)}>Upload Template</Button>
            </div>
        {/if}
    </div>

    <!-- Type filter -->
    <div class="flex gap-2">
        <button
            class="px-3 py-1 text-sm rounded-md transition-colors {typeFilter === ''
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted hover:bg-muted/80'}"
            onclick={() => (typeFilter = '')}
        >
            All
        </button>
        <button
            class="px-3 py-1 text-sm rounded-md transition-colors {typeFilter === 'SOP'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted hover:bg-muted/80'}"
            onclick={() => (typeFilter = 'SOP')}
        >
            SOP
        </button>
        <button
            class="px-3 py-1 text-sm rounded-md transition-colors {typeFilter === 'BATCH_RECORD'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted hover:bg-muted/80'}"
            onclick={() => (typeFilter = 'BATCH_RECORD')}
        >
            Batch Record
        </button>
    </div>

    <!-- Table -->
    {#if loading}
        <div class="flex items-center justify-center py-12 text-muted-foreground">
            Loading templates...
        </div>
    {:else if filtered.length === 0}
        <div class="flex items-center justify-center py-12 text-muted-foreground">
            No templates found.
        </div>
    {:else}
        <div class="border rounded-lg overflow-hidden">
            <table class="w-full text-sm">
                <thead class="bg-muted/50">
                    <tr>
                        <th class="text-left px-4 py-2 font-medium">Name</th>
                        <th class="text-left px-4 py-2 font-medium">Type</th>
                        <th class="text-left px-4 py-2 font-medium">Filename</th>
                        <th class="text-left px-4 py-2 font-medium">Status</th>
                        <th class="text-right px-4 py-2 font-medium">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {#each filtered as template}
                        <tr class="border-t hover:bg-muted/30">
                            <td class="px-4 py-3">
                                <span class="font-medium">{template.name}</span>
                                {#if template.is_current_default}
                                    <span
                                        class="ml-2 px-1.5 py-0.5 text-xs bg-primary/10 text-primary rounded"
                                    >
                                        Default
                                    </span>
                                {/if}
                                {#if template.is_system}
                                    <span
                                        class="ml-1 px-1.5 py-0.5 text-xs bg-muted text-muted-foreground rounded"
                                    >
                                        System
                                    </span>
                                {/if}
                                {#if template.description}
                                    <p class="text-xs text-muted-foreground mt-0.5">
                                        {template.description}
                                    </p>
                                {/if}
                            </td>
                            <td class="px-4 py-3 text-muted-foreground">
                                {template.template_type === 'BATCH_RECORD' ? 'Batch Record' : 'SOP'}
                            </td>
                            <td class="px-4 py-3 text-muted-foreground text-xs font-mono">
                                {template.original_filename}
                            </td>
                            <td class="px-4 py-3">
                                <span
                                    class="px-1.5 py-0.5 text-xs rounded {template.status === 'ACTIVE'
                                        ? 'bg-green-100 text-green-700'
                                        : 'bg-gray-100 text-gray-500'}"
                                >
                                    {template.status}
                                </span>
                            </td>
                            <td class="px-4 py-3 text-right">
                                {#if isAdmin && !template.is_system}
                                    {#if !template.is_current_default && template.status === 'ACTIVE'}
                                        <button
                                            class="text-xs text-primary hover:underline mr-3"
                                            onclick={() => setAsDefault(template.id)}
                                        >
                                            Set Default
                                        </button>
                                    {/if}
                                    {#if template.status === 'ACTIVE'}
                                        <button
                                            class="text-xs text-destructive hover:underline"
                                            onclick={() => archiveTemplate(template.id)}
                                        >
                                            Archive
                                        </button>
                                    {:else}
                                        <button
                                            class="text-xs text-primary hover:underline"
                                            onclick={() => unarchiveTemplate(template.id)}
                                        >
                                            Restore
                                        </button>
                                    {/if}
                                {/if}
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}

    <!-- Variable Reference (collapsible) -->
    <div class="mt-8">
        <button
            class="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            onclick={() => (showVariables = !showVariables)}
        >
            <span class="text-xs">{showVariables ? '\u25BC' : '\u25B6'}</span>
            Template Variable Reference
        </button>
        {#if showVariables && variableEntries.length}
            <div class="mt-3 border rounded-lg p-4 bg-muted/30 space-y-4">
                {#each variableEntries as [section, vars]}
                    <div>
                        <h4 class="text-sm font-semibold capitalize mb-2">
                            {section.replace(/_/g, ' ')}
                        </h4>
                        <div class="space-y-1">
                            {#each vars as v}
                                <div class="flex items-start gap-3 text-xs">
                                    <code
                                        class="px-1.5 py-0.5 bg-background rounded font-mono min-w-[200px] shrink-0"
                                    >
                                        {v.syntax || `{{ ${v.name} }}`}
                                    </code>
                                    <span class="text-muted-foreground">{v.description}</span>
                                    {#if v.example !== undefined}
                                        <span class="text-muted-foreground/60 ml-auto shrink-0">
                                            e.g. {v.example}
                                        </span>
                                    {/if}
                                </div>
                            {/each}
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>
</div>

<!-- Upload Modal -->
{#if showUpload}
    <TemplateUploadModal
        onClose={() => (showUpload = false)}
        onSuccess={() => {
            showUpload = false;
            loadTemplates();
        }}
    />
{/if}

<!-- Convert Modal -->
<TemplateConvertModal
    bind:open={showConvert}
    onSuccess={() => loadTemplates()}
/>
