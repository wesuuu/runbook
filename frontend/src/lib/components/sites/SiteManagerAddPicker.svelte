<!-- frontend/src/lib/components/sites/SiteManagerAddPicker.svelte
     Modal picker that lists org members and grants SITE_MANAGER to the selected ones. -->
<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { api } from '$lib/api';

    interface Props {
        open: boolean;
        orgId: string;
        alreadyGrantedUserIds: string[];
        onClose: () => void;
        onConfirm: (userIds: string[]) => Promise<void>;
    }

    let { open, orgId, alreadyGrantedUserIds, onClose, onConfirm }: Props = $props();

    interface NormalizedMember {
        userId: string;
        name: string;
        email: string;
    }

    let members = $state<NormalizedMember[]>([]);
    let loading = $state(false);
    let loadedFor = $state<string | null>(null);
    let error = $state<string | null>(null);
    let search = $state('');
    let selected = $state<Set<string>>(new Set());
    let submitting = $state(false);

    function normalize(raw: any): NormalizedMember | null {
        const userId =
            raw?.user?.id ?? raw?.user_id ?? raw?.id ?? null;
        if (!userId) return null;
        const name =
            raw?.user?.name ?? raw?.full_name ?? raw?.name ?? '(unknown)';
        const email =
            raw?.user?.email ?? raw?.email ?? '';
        return { userId, name, email };
    }

    async function loadMembers() {
        loading = true;
        error = null;
        try {
            const raw = await api.get<any[]>(`/iam/organizations/${orgId}/members`);
            const list = Array.isArray(raw) ? raw : [];
            members = list
                .map(normalize)
                .filter((m): m is NormalizedMember => m !== null);
            loadedFor = orgId;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load members.';
        } finally {
            loading = false;
        }
    }

    $effect(() => {
        if (open && loadedFor !== orgId && !loading) {
            void loadMembers();
        }
        if (!open) {
            // Reset transient state when the modal closes
            search = '';
            selected = new Set();
            submitting = false;
        }
    });

    const filtered = $derived.by(() => {
        const q = search.trim().toLowerCase();
        if (!q) return members;
        return members.filter(
            (m) =>
                m.name.toLowerCase().includes(q) ||
                m.email.toLowerCase().includes(q),
        );
    });

    function toggle(userId: string) {
        const next = new Set(selected);
        if (next.has(userId)) {
            next.delete(userId);
        } else {
            next.add(userId);
        }
        selected = next;
    }

    async function submit() {
        if (selected.size === 0 || submitting) return;
        submitting = true;
        try {
            await onConfirm(Array.from(selected));
            selected = new Set();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to add managers.';
        } finally {
            submitting = false;
        }
    }
</script>

<Dialog.Root {open} onOpenChange={(v) => { if (!v) onClose(); }}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>Add site managers</Dialog.Title>
            <Dialog.Description>
                Select members to grant SITE_MANAGER for this site.
            </Dialog.Description>
        </Dialog.Header>

        <div class="space-y-3 py-1">
            <Input
                placeholder="Search members…"
                bind:value={search}
                disabled={loading}
            />

            {#if error}
                <p class="text-xs text-destructive">{error}</p>
            {/if}

            <div class="max-h-72 overflow-y-auto border border-border rounded-lg">
                {#if loading}
                    <p class="text-xs text-muted-foreground p-4">Loading members…</p>
                {:else if filtered.length === 0}
                    <p class="text-xs text-muted-foreground p-4">No members match.</p>
                {:else}
                    <ul class="divide-y divide-border">
                        {#each filtered as m (m.userId)}
                            {@const granted = alreadyGrantedUserIds.includes(m.userId)}
                            {@const isSelected = selected.has(m.userId)}
                            <li>
                                <label
                                    class="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-muted/40 transition-colors duration-150"
                                    class:opacity-50={granted}
                                    class:cursor-not-allowed={granted}
                                >
                                    <input
                                        type="checkbox"
                                        class="h-4 w-4 rounded border-border cursor-pointer"
                                        checked={isSelected}
                                        disabled={granted}
                                        onchange={() => toggle(m.userId)}
                                    />
                                    <div class="min-w-0 flex-1">
                                        <div class="text-sm font-medium truncate">{m.name}</div>
                                        <div class="text-xs text-muted-foreground font-mono truncate">{m.email}</div>
                                    </div>
                                    {#if granted}
                                        <span class="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground shrink-0">
                                            Already granted
                                        </span>
                                    {/if}
                                </label>
                            </li>
                        {/each}
                    </ul>
                {/if}
            </div>
        </div>

        <Dialog.Footer>
            <span class="text-xs text-muted-foreground mr-auto self-center">
                {selected.size} selected
            </span>
            <Button variant="outline" onclick={onClose} disabled={submitting}>Cancel</Button>
            <Button onclick={submit} disabled={selected.size === 0 || submitting}>
                {submitting ? 'Adding…' : 'Add'}
            </Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
