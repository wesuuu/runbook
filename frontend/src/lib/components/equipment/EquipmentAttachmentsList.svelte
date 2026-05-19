<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import type { EquipmentAttachment } from '$lib/schemas/science';

    interface Props {
        attachments: EquipmentAttachment[];
        canManage: boolean;
        onUpload: (file: File) => Promise<void>;
        onDelete: (id: string) => Promise<void>;
    }
    let { attachments, canManage, onUpload, onDelete }: Props = $props();
    let fileInput: HTMLInputElement | null = $state(null);
    let uploading = $state(false);

    async function pick(e: Event) {
        const f = (e.currentTarget as HTMLInputElement).files?.[0];
        if (!f) return;
        uploading = true;
        try { await onUpload(f); } finally { uploading = false; if (fileInput) fileInput.value = ''; }
    }
</script>

<div class="space-y-2">
    <ul class="space-y-1">
        {#each attachments as a (a.id)}
            <li class="flex items-center justify-between text-sm">
                <span>{a.original_filename} <span class="text-xs text-muted-foreground font-mono">({Math.round(a.size_bytes / 1024)} KB)</span></span>
                {#if canManage}
                    <button class="text-xs px-2 py-1 rounded-md text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer transition-all duration-150" onclick={() => onDelete(a.id)}>Delete</button>
                {/if}
            </li>
        {/each}
    </ul>
    {#if canManage}
        <input bind:this={fileInput} type="file" class="hidden" onchange={pick}
               accept=".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx,.xls,.xlsx" />
        <Button onclick={() => fileInput?.click()} disabled={uploading}>
            {uploading ? 'Uploading…' : '+ Upload (PDF, Office, image — 25 MB)'}
        </Button>
    {/if}
</div>
