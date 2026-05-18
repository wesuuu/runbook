<script lang="ts">
    import { Badge } from "$lib/components/ui/badge";
    import {
        Popover,
        PopoverTrigger,
        PopoverContent,
    } from "$lib/components/ui/popover";
    import { Button } from "$lib/components/ui/button";
    import { fade } from "svelte/transition";
    import { flip } from "svelte/animate";
    import MemberSitesInlinePicker from "./MemberSitesInlinePicker.svelte";
    import type { Site } from "$lib/schemas/sites";

    interface Props {
        roles: string[];
        disabled?: boolean;
        onChange: (newRoles: string[]) => void;
        // Optional site grant wiring (Task 31 / F-0088). When `allSites` is
        // provided and the row's roles include SITE_MANAGER, the popover
        // renders an inline site picker below the role checkboxes.
        allSites?: Site[];
        selectedSiteIds?: string[];
        onSitesChange?: (next: string[]) => void;
    }
    let {
        roles,
        disabled = false,
        onChange,
        allSites,
        selectedSiteIds,
        onSitesChange,
    }: Props = $props();

    const ALL_ROLES = [
        { value: "ADMIN", label: "Admin" },
        { value: "BILLING", label: "Billing" },
        { value: "PROTOCOL_APPROVER", label: "Protocol approver" },
        { value: "SITE_MANAGER", label: "Site manager" },
    ] as const;

    let open = $state(false);

    const siteGrantInvalid = $derived(
        roles.includes("SITE_MANAGER") && (selectedSiteIds?.length ?? 0) === 0,
    );

    function toggle(role: string, checked: boolean) {
        const next = checked
            ? [...new Set([...roles, role, "MEMBER"])]
            : [...new Set([...roles.filter((r) => r !== role), "MEMBER"])];
        const same =
            next.length === roles.length &&
            next.every((r) => roles.includes(r));
        if (same) return;
        // If SITE_MANAGER is being unticked and grants exist, clear them
        // first so the parent can issue bulk-DELETE before/after the role
        // patch. Parent decides whether to confirm.
        if (
            role === "SITE_MANAGER" &&
            !checked &&
            (selectedSiteIds?.length ?? 0) > 0 &&
            onSitesChange
        ) {
            onSitesChange([]);
        }
        onChange(next);
    }

    function labelFor(role: string): string {
        return ALL_ROLES.find((r) => r.value === role)?.label ?? role;
    }
</script>

<div class="flex items-start gap-1.5 w-[260px]">
    <div class="flex items-center gap-1.5 flex-wrap flex-1 min-w-0">
        <Badge variant="secondary" class="opacity-70 cursor-default">Member</Badge>
        {#each roles.filter((r) => r !== "MEMBER") as r (r)}
            <span
                animate:flip={{ duration: 150 }}
                in:fade={{ duration: 120 }}
                out:fade={{ duration: 120 }}
            >
                <Badge
                    variant="outline"
                    class={r === "SITE_MANAGER" && siteGrantInvalid
                        ? "border-destructive text-destructive"
                        : ""}
                >
                    {labelFor(r)}
                </Badge>
            </span>
        {/each}
    </div>

    {#if !disabled}
        <Popover bind:open>
            <PopoverTrigger>
                <Button
                    variant="ghost"
                    size="sm"
                    aria-label="Edit roles"
                    class="h-6 px-2 text-xs shrink-0"
                >
                    ▾
                </Button>
            </PopoverTrigger>
            <PopoverContent class="w-64 p-3 space-y-2">
                {#each ALL_ROLES as r (r.value)}
                    <label
                        class="flex items-center gap-2 text-sm cursor-pointer"
                    >
                        <input
                            type="checkbox"
                            checked={roles.includes(r.value)}
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
                <label
                    class="flex items-center gap-2 text-sm text-muted-foreground cursor-not-allowed"
                >
                    <input type="checkbox" checked disabled />
                    <span>Member <span class="opacity-60">(always)</span></span>
                </label>

                {#if roles.includes("SITE_MANAGER") && allSites && onSitesChange}
                    <div class="border-l-2 border-primary pl-3 ml-2 mt-2 space-y-2">
                        <p class="text-xs font-medium text-muted-foreground">
                            Managed sites
                        </p>
                        <MemberSitesInlinePicker
                            {allSites}
                            selectedSiteIds={selectedSiteIds ?? []}
                            onChange={onSitesChange}
                            hasSiteManagerRole={true}
                        />
                    </div>
                {/if}
            </PopoverContent>
        </Popover>
    {/if}
</div>
