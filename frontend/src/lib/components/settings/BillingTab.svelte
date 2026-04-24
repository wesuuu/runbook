<script lang="ts">
    import { onMount } from 'svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';
    import { subscription, loadSubscription, openPortal } from '$lib/stores/subscription.svelte';

    onMount(loadSubscription);

    function planLabel(tier: string | undefined): string {
        if (tier === 'essentials') return 'Essentials';
        if (tier === 'pro') return 'Pro';
        if (tier === 'enterprise') return 'Enterprise';
        return '—';
    }

    function statusLabel(status: string | null): string {
        if (!status) return 'No subscription';
        const map: Record<string, string> = {
            trialing: 'Trialing',
            active: 'Active',
            past_due: 'Past due',
            canceled: 'Canceled',
            unpaid: 'Unpaid',
            incomplete: 'Incomplete',
        };
        return map[status] ?? status;
    }

    function statusClasses(status: string | null): string {
        if (!status) return 'bg-muted text-muted-foreground';
        const map: Record<string, string> = {
            trialing: 'bg-blue-100 text-blue-800',
            active: 'bg-green-100 text-green-800',
            past_due: 'bg-amber-100 text-amber-800',
            canceled: 'bg-red-100 text-red-800',
            unpaid: 'bg-red-100 text-red-800',
            incomplete: 'bg-amber-100 text-amber-800',
        };
        return map[status] ?? 'bg-muted text-muted-foreground';
    }

    function formatDate(iso: string | null): string {
        if (!iso) return '';
        return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
    }
</script>

{#if subscription.loading}
    <p class="text-sm text-muted-foreground py-8 text-center">Loading billing…</p>
{:else if subscription.unconfigured}
    <Card>
        <CardHeader>
            <CardTitle>Billing unavailable</CardTitle>
            <CardDescription>Billing is not configured for this environment. Contact an administrator.</CardDescription>
        </CardHeader>
    </Card>
{:else if subscription.error}
    <Card>
        <CardHeader>
            <CardTitle>Unable to load billing</CardTitle>
            <CardDescription>{subscription.error}</CardDescription>
        </CardHeader>
        <CardContent>
            <Button onclick={loadSubscription}>Try again</Button>
        </CardContent>
    </Card>
{:else if subscription.state}
    {@const s = subscription.state}
    <div class="space-y-6">
        <!-- Header card: current plan + status -->
        <Card>
            <CardHeader>
                <div class="flex items-start justify-between gap-4">
                    <div>
                        <CardTitle>{planLabel(s.tier)}</CardTitle>
                        <CardDescription class="mt-1">
                            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium {statusClasses(s.status)}">
                                {statusLabel(s.status)}
                            </span>
                        </CardDescription>
                    </div>
                </div>
            </CardHeader>
            <CardContent class="space-y-3 text-sm">
                {#if s.status === 'trialing' && s.days_remaining_in_trial != null}
                    <p>
                        {s.days_remaining_in_trial} day{s.days_remaining_in_trial === 1 ? '' : 's'} left in your trial.
                        Add a payment method to keep your subscription active.
                    </p>
                    <Button onclick={() => openPortal()}>Add payment method</Button>
                {:else if s.cancel_at_period_end && s.current_period_end}
                    <p>
                        Your subscription will end on {formatDate(s.current_period_end)}. You can reactivate from the billing portal.
                    </p>
                    <Button variant="outline" onclick={() => openPortal()}>Manage billing</Button>
                {:else if s.is_locked_out}
                    <p class="text-destructive">
                        Your subscription is not active. Reads and exports remain available, but new changes are blocked.
                    </p>
                    <Button onclick={() => openPortal()}>Re-subscribe</Button>
                {:else if s.status === 'active' && s.current_period_end}
                    <p>Next billing date: {formatDate(s.current_period_end)}.</p>
                {/if}

                <!-- Seat usage -->
                <p class="text-muted-foreground">
                    {#if s.seat_limit == null}
                        {s.seat_count} {s.seat_count === 1 ? 'member' : 'members'}
                    {:else}
                        {s.seat_count} of {s.seat_limit} {s.seat_limit === 1 ? 'seat' : 'seats'} used
                    {/if}
                </p>

                {#if s.seat_limit_exceeded && s.seat_limit != null}
                    <div class="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-900 text-sm">
                        Your organization has {s.seat_count} members but the {planLabel(s.tier)} plan allows {s.seat_limit}.
                        Remove {s.seat_count - s.seat_limit} {s.seat_count - s.seat_limit === 1 ? 'member' : 'members'}
                        or upgrade to clear this warning.
                        <div class="mt-2 flex gap-2">
                            <Button size="sm" onclick={() => openPortal()}>Upgrade</Button>
                            <a href="/settings?tab=members" class="text-sm underline underline-offset-4 self-center">Manage members</a>
                        </div>
                    </div>
                {/if}
            </CardContent>
        </Card>

        <!-- Plan rows -->
        <Card>
            <CardHeader>
                <CardTitle>Plans</CardTitle>
            </CardHeader>
            <CardContent class="divide-y divide-border">
                <div class="py-4 flex items-center justify-between">
                    <div>
                        <p class="font-medium">Essentials</p>
                        <p class="text-xs text-muted-foreground">Included tier for new orgs.</p>
                    </div>
                    {#if s.tier === 'essentials'}
                        <span class="text-xs text-muted-foreground">Your plan</span>
                    {:else}
                        <Button variant="outline" size="sm" onclick={() => openPortal()}>Downgrade</Button>
                    {/if}
                </div>
                <div class="py-4 flex items-center justify-between">
                    <div>
                        <p class="font-medium">Pro</p>
                        <p class="text-xs text-muted-foreground">Advanced features for teams.</p>
                    </div>
                    {#if s.tier === 'pro'}
                        <span class="text-xs text-muted-foreground">Your plan</span>
                    {:else}
                        <Button size="sm" onclick={() => openPortal()}>Upgrade</Button>
                    {/if}
                </div>
                <div class="py-4 flex items-center justify-between">
                    <div>
                        <p class="font-medium">Enterprise</p>
                        <p class="text-xs text-muted-foreground">Custom deployment, SLA, dedicated support.</p>
                    </div>
                    <a href="mailto:sales@batchrite.com" class="text-sm underline underline-offset-4">Contact sales</a>
                </div>
            </CardContent>
        </Card>

        <!-- Manage billing -->
        <Card>
            <CardContent class="flex items-center justify-between pt-6">
                <div>
                    <p class="font-medium">Manage billing</p>
                    <p class="text-sm text-muted-foreground">Update payment method, view invoice history, or cancel.</p>
                </div>
                <Button variant="outline" onclick={() => openPortal()}>Open billing portal</Button>
            </CardContent>
        </Card>
    </div>
{:else}
    <Card>
        <CardHeader>
            <CardTitle>Billing</CardTitle>
            <CardDescription>You don't have billing access for this organization.</CardDescription>
        </CardHeader>
    </Card>
{/if}
