<script lang="ts">
    import { designateProtocolApproval } from '$lib/api';

    interface Props {
        protocolId: string;
        requiresApproval: boolean;
        status: string;
        canManage: boolean;
        projectSettingEnabled: boolean;
        onChanged: (next: boolean) => void;
    }

    let {
        protocolId,
        requiresApproval,
        status,
        canManage,
        projectSettingEnabled,
        onChanged,
    }: Props = $props();

    let pending = $state(false);
    let errorMessage = $state<string | null>(null);

    const disabledReason = $derived(
        !canManage
            ? 'Only the protocol creator or a project admin can change this.'
            : !projectSettingEnabled
              ? 'Enable Project Settings → "Require protocol approval" first.'
              : status !== 'DRAFT'
                ? 'Can only change while status is DRAFT.'
                : null,
    );

    const isDisabled = $derived(!!disabledReason || pending);

    async function toggle() {
        if (isDisabled) return;
        pending = true;
        errorMessage = null;
        try {
            const next = !requiresApproval;
            await designateProtocolApproval(protocolId, next);
            onChanged(next);
        } catch (e: unknown) {
            errorMessage = e instanceof Error ? e.message : 'Failed to update.';
        } finally {
            pending = false;
        }
    }
</script>

<div class="flex flex-col gap-1">
    <div class="flex items-center gap-3">
        <button
            type="button"
            role="switch"
            aria-checked={requiresApproval}
            aria-label="Requires approval"
            disabled={isDisabled}
            onclick={toggle}
            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors disabled:cursor-not-allowed disabled:opacity-60 {requiresApproval
                ? 'bg-teal-600'
                : 'bg-slate-300'}"
        >
            <span
                class="pointer-events-none block h-4 w-4 rounded-full bg-white shadow-sm transition-transform {requiresApproval
                    ? 'translate-x-4'
                    : 'translate-x-0'}"
            ></span>
        </button>
        <span class="text-sm font-medium text-foreground">Requires approval</span>
        {#if disabledReason}
            <span
                class="text-xs text-muted-foreground"
                title={disabledReason}
                aria-label={disabledReason}
            >
                ⓘ
            </span>
        {/if}
    </div>
    {#if disabledReason}
        <p class="text-xs text-muted-foreground pl-12">{disabledReason}</p>
    {/if}
    {#if errorMessage}
        <p class="text-xs text-destructive pl-12">{errorMessage}</p>
    {/if}
</div>
