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

<div class="min-h-screen flex items-center justify-center bg-muted/40 px-4">
    <div class="w-full max-w-sm">
        <div class="flex flex-col items-center mb-8">
            <div
                class="w-12 h-12 bg-primary rounded-xl flex items-center justify-center text-primary-foreground font-bold text-xl shadow-sm mb-3"
            >
                R
            </div>
            <h1 class="text-2xl font-bold tracking-tight">Runbook</h1>
            <p class="text-sm text-muted-foreground mt-1">Sign in to your account</p>
        </div>

        <Card>
            <CardHeader>
                <CardTitle>Sign In</CardTitle>
                <CardDescription>Enter your credentials to continue.</CardDescription>
            </CardHeader>
            <CardContent>
                <form onsubmit={handleSubmit} class="space-y-4">
                    {#if error}
                        <div class="bg-destructive/10 text-destructive text-sm p-3 rounded-md">
                            {error}
                        </div>
                    {/if}

                    <div class="space-y-2">
                        <Label for="email">Email</Label>
                        <Input
                            id="email"
                            type="email"
                            bind:value={email}
                            placeholder="you@example.com"
                            required
                        />
                    </div>

                    <div class="space-y-2">
                        <Label for="password">Password</Label>
                        <Input
                            id="password"
                            type="password"
                            bind:value={password}
                            placeholder="Your password"
                            required
                        />
                    </div>

                    <Button type="submit" class="w-full" disabled={loading}>
                        {loading ? 'Signing in...' : 'Sign In'}
                    </Button>
                </form>

                <p class="text-sm text-center text-muted-foreground mt-4">
                    Don't have an account?
                    <a href="/register" class="text-primary font-medium hover:underline">Register</a>
                </p>
            </CardContent>
        </Card>
    </div>
</div>
