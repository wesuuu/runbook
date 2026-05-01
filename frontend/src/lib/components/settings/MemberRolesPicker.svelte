<script lang="ts">
    import { Badge } from '$lib/components/ui/badge';
    import {
        Popover,
        PopoverTrigger,
        PopoverContent,
    } from '$lib/components/ui/popover';
    import { Button } from '$lib/components/ui/button';

    interface Props {
        roles: string[];
        disabled?: boolean;
        onChange: (newRoles: string[]) => void;
    }
    let { roles, disabled = false, onChange }: Props = $props();

    const ALL_ROLES = [
        { value: 'ADMIN', label: 'Admin' },
        { value: 'BILLING', label: 'Billing' },
        { value: 'PROTOCOL_APPROVER', label: 'Protocol approver' },
    ] as const;

    let open = $state(false);
    let draft = $state<string[]>([...roles]);

    $effect(() => {
        if (!open) draft = [...roles];
    });

    function toggle(role: string, checked: boolean) {
        if (checked) draft = [...new Set([...draft, role, 'MEMBER'])];
        else draft = draft.filter((r) => r !== role);
    }

    function commit() {
        const final = [...new Set([...draft, 'MEMBER'])];
        const same =
            final.length === roles.length &&
            final.every((r) => roles.includes(r));
        if (!same) onChange(final);
    }

    function handleOpenChange(next: boolean) {
        open = next;
        if (!next) commit();
    }

    function labelFor(role: string): string {
        return ALL_ROLES.find((r) => r.value === role)?.label ?? role;
    }
</script>

<div class="flex items-center gap-1.5 min-w-0">
    <div class="flex items-center gap-1.5 flex-wrap min-w-0">
        <Badge variant="secondary" class="opacity-70 cursor-default">Member</Badge>
        {#each roles.filter((r) => r !== 'MEMBER') as r (r)}
            <Badge variant="outline">{labelFor(r)}</Badge>
        {/each}
    </div>

    {#if !disabled}
        <Popover {open} onOpenChange={handleOpenChange}>
            <PopoverTrigger>
                <Button
                    variant="ghost"
                    size="sm"
                    aria-label="Edit roles"
                    class="h-6 px-2 text-xs"
                >
                    ▾
                </Button>
            </PopoverTrigger>
            <PopoverContent class="w-56 p-3 space-y-2">
                {#each ALL_ROLES as r (r.value)}
                    <label
                        class="flex items-center gap-2 text-sm cursor-pointer"
                    >
                        <input
                            type="checkbox"
                            checked={draft.includes(r.value)}
                            onchange={(e) =>
                                toggle(
                                    r.value,
                                    (e.target as HTMLInputElement).checked,
                                )}
                        />
                        <span>{r.label}</span>
                    </label>
                {/each}
                <hr class="my-2" />
                <div
                    class="flex items-center gap-2 text-xs text-muted-foreground"
                >
                    <input type="checkbox" checked disabled />
                    <span>Member <span class="opacity-60">(always)</span></span>
                </div>
            </PopoverContent>
        </Popover>
    {/if}
</div>
