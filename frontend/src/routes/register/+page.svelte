<script lang="ts">
    import { goto } from '$app/navigation';
    import { register } from '$lib/auth.svelte';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';

    let fullName = $state('');
    let email = $state('');
    let password = $state('');
    let confirmPassword = $state('');
    let error = $state<string | null>(null);
    let loading = $state(false);

    async function handleSubmit(e: Event) {
        e.preventDefault();
        error = null;

        if (password !== confirmPassword) {
            error = 'Passwords do not match';
            return;
        }

        if (password.length < 6) {
            error = 'Password must be at least 6 characters';
            return;
        }

        loading = true;
        try {
            await register(email, password, fullName);
            goto('/');
        } catch (err: unknown) {
            error = err instanceof Error ? err.message : 'Registration failed';
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
            <p class="text-sm text-muted-foreground mt-1">Create your account</p>
        </div>

        <Card>
            <CardHeader>
                <CardTitle>Create Account</CardTitle>
                <CardDescription>Fill in your details to get started.</CardDescription>
            </CardHeader>
            <CardContent>
                <form onsubmit={handleSubmit} class="space-y-4">
                    {#if error}
                        <div class="bg-destructive/10 text-destructive text-sm p-3 rounded-md">
                            {error}
                        </div>
                    {/if}

                    <div class="space-y-2">
                        <Label for="fullName">Full Name</Label>
                        <Input
                            id="fullName"
                            type="text"
                            bind:value={fullName}
                            placeholder="Jane Doe"
                        />
                    </div>

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
                            placeholder="At least 6 characters"
                            required
                        />
                    </div>

                    <div class="space-y-2">
                        <Label for="confirmPassword">Confirm Password</Label>
                        <Input
                            id="confirmPassword"
                            type="password"
                            bind:value={confirmPassword}
                            placeholder="Repeat your password"
                            required
                        />
                    </div>

                    <Button type="submit" class="w-full" disabled={loading}>
                        {loading ? 'Creating account...' : 'Create Account'}
                    </Button>
                </form>

                <p class="text-sm text-center text-muted-foreground mt-4">
                    Already have an account?
                    <a href="/login" class="text-primary font-medium hover:underline">Sign In</a>
                </p>
            </CardContent>
        </Card>
    </div>
</div>
