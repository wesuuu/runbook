<script lang="ts">
    import { goto } from '$app/navigation';
    import { getUser, getCurrentOrg, getOrgs, switchOrg, logout } from '$lib/auth.svelte';
    import { API_BASE } from '$lib/config';
    import * as DropdownMenu from '$lib/components/ui/dropdown-menu';

    function getInitials(): string {
        const user = getUser();
        if (!user) return '?';
        if (user.full_name) {
            return user.full_name
                .split(' ')
                .map((w) => w[0])
                .join('')
                .toUpperCase()
                .slice(0, 2);
        }
        return user.email[0].toUpperCase();
    }

    const avatarSrc = $derived(() => {
        const u = getUser();
        return u?.avatar_url ? `${API_BASE}${u.avatar_url}` : null;
    });

    function handleSignOut() {
        logout();
        goto('/login');
    }

    function handleSwitchOrg(org: { id: string; name: string; created_at: string; updated_at: string }) {
        switchOrg(org);
        // Reload current page to reflect new org context
        window.location.reload();
    }
</script>

<DropdownMenu.Root>
    <DropdownMenu.Trigger>
        {#if avatarSrc()}
            <img
                src={avatarSrc()}
                alt="Avatar"
                class="w-8 h-8 rounded-full object-cover hover:opacity-90 transition-opacity cursor-pointer"
            />
        {:else}
            <button
                class="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-xs font-semibold hover:opacity-90 transition-opacity"
            >
                {getInitials()}
            </button>
        {/if}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end" class="w-56" style="background-color: white; z-index: 100;">
        <div class="px-2 py-1.5">
            <p class="text-sm font-medium">{getUser()?.full_name || 'User'}</p>
            <p class="text-xs text-muted-foreground">{getUser()?.email}</p>
        </div>
        <DropdownMenu.Separator />

        {#if getOrgs().length > 0}
            <DropdownMenu.Label>Organization</DropdownMenu.Label>
            {#each getOrgs() as org}
                <DropdownMenu.Item onclick={() => handleSwitchOrg(org)}>
                    <span class="flex items-center gap-2 w-full">
                        {#if getCurrentOrg()?.id === org.id}
                            <span class="text-primary">&#10003;</span>
                        {:else}
                            <span class="w-4"></span>
                        {/if}
                        {org.name}
                    </span>
                </DropdownMenu.Item>
            {/each}
            <DropdownMenu.Separator />
        {/if}

        <DropdownMenu.Item onclick={() => goto('/settings')}>
            Settings
        </DropdownMenu.Item>
        <DropdownMenu.Separator />
        <DropdownMenu.Item onclick={handleSignOut} class="text-destructive">
            Sign Out
        </DropdownMenu.Item>
    </DropdownMenu.Content>
</DropdownMenu.Root>
