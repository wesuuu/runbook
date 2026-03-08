<script lang="ts">
    import { goto } from '$app/navigation';
    import { login } from '$lib/auth.svelte';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';

    let email = $state('');
    let password = $state('');
    let error = $state<string | null>(null);
    let loading = $state(false);

    async function handleSubmit(e: Event) {
        e.preventDefault();
        error = null;
        loading = true;

        try {
            await login(email, password);
            goto('/');
        } catch (err: unknown) {
            error = err instanceof Error ? err.message : 'Login failed';
        } finally {
            loading = false;
        }
    }
</script>

<div class="min-h-screen flex items-center justify-center bg-background dot-grid px-4 relative overflow-hidden">
    <!-- Decorative blobs -->
    <div class="absolute top-[-20%] right-[-10%] w-[600px] h-[600px] rounded-full bg-primary/[0.03] blur-3xl"></div>
    <div class="absolute bottom-[-20%] left-[-10%] w-[500px] h-[500px] rounded-full bg-accent/[0.04] blur-3xl"></div>

    <div class="w-full max-w-sm relative z-10">
        <div class="flex flex-col items-center mb-10">
            <div
                class="w-14 h-14 bg-primary rounded-2xl flex items-center justify-center shadow-lg shadow-primary/20 mb-4"
            >
                <span class="font-display text-2xl text-primary-foreground italic leading-none">R</span>
            </div>
            <h1 class="font-display text-3xl italic text-foreground tracking-tight">Runbook</h1>
            <p class="text-sm text-muted-foreground mt-2 tracking-wide">Digital Lab Notebook</p>
        </div>

        <div class="card-warm rounded-xl p-1">
            <Card class="border-0 shadow-none bg-transparent">
                <CardHeader class="pb-4">
                    <CardTitle class="text-lg">Sign In</CardTitle>
                    <CardDescription>Enter your credentials to continue.</CardDescription>
                </CardHeader>
                <CardContent>
                    <form onsubmit={handleSubmit} class="space-y-5">
                        {#if error}
                            <div class="bg-destructive/8 text-destructive text-sm p-3 rounded-lg border border-destructive/15">
                                {error}
                            </div>
                        {/if}

                        <div class="space-y-2">
                            <Label for="email" class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Email</Label>
                            <Input
                                id="email"
                                type="email"
                                bind:value={email}
                                placeholder="you@example.com"
                                required
                                class="h-11 bg-background/60 border-border/80 focus:border-primary"
                            />
                        </div>

                        <div class="space-y-2">
                            <Label for="password" class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Password</Label>
                            <Input
                                id="password"
                                type="password"
                                bind:value={password}
                                placeholder="Your password"
                                required
                                class="h-11 bg-background/60 border-border/80 focus:border-primary"
                            />
                        </div>

                        <Button type="submit" class="w-full h-11 font-semibold tracking-wide shadow-sm shadow-primary/20 hover:shadow-md hover:shadow-primary/30 transition-all" disabled={loading}>
                            {loading ? 'Signing in...' : 'Sign In'}
                        </Button>
                    </form>

                    <p class="text-sm text-center text-muted-foreground mt-6">
                        Don't have an account?
                        <a href="/register" class="text-primary font-semibold hover:underline">Register</a>
                    </p>
                </CardContent>
            </Card>
        </div>

        <p class="text-center text-xs text-muted-foreground/60 mt-8 tracking-wide">
            Trellis Bio &middot; Process Development Platform
        </p>
    </div>
</div>
