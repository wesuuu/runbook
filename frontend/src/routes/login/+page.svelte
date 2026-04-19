<script lang="ts">
    import { goto } from '$app/navigation';
    import { login, oauthLogin } from '$lib/auth.svelte';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';
    import ErrorAlert from '$lib/components/ui/error-alert.svelte';
    import { fade } from 'svelte/transition';
    import { blockDuration } from '$lib/transitions';
    import Logo from '$lib/components/Logo.svelte';

    let email = $state('');
    let password = $state('');
    let error = $state<string | null>(null);
    let loading = $state(false);
    let oauthLoading = $state(false);

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

    async function handleOAuthLogin(provider: 'google' | 'microsoft') {
        error = null;
        oauthLoading = true;

        try {
            await oauthLogin(provider);
        } catch (err: unknown) {
            error = err instanceof Error ? err.message : `${provider} login failed`;
            oauthLoading = false;
        }
    }
</script>

<div class="min-h-screen flex items-center justify-center bg-background dot-grid px-4 relative overflow-hidden">
    <!-- Decorative blobs -->
    <div class="absolute top-[-20%] right-[-10%] w-[600px] h-[600px] rounded-full bg-primary/[0.03] blur-3xl"></div>
    <div class="absolute bottom-[-20%] left-[-10%] w-[500px] h-[500px] rounded-full bg-accent/[0.04] blur-3xl"></div>

    <div class="w-full max-w-sm relative z-10">
        <div class="flex flex-col items-center mb-10">
            <div class="shadow-lg shadow-primary/20 mb-4 rounded-xl">
                <Logo size="lg" />
            </div>
            <h1 class="text-2xl font-bold text-foreground tracking-tight">Batchrite</h1>
            <p class="text-sm text-muted-foreground mt-1.5">Laboratory Execution System</p>
        </div>

        <div class="card-warm rounded-xl p-1">
            <Card class="border-0 shadow-none bg-transparent">
                <CardHeader class="pb-4">
                    <CardTitle class="text-lg">Sign In</CardTitle>
                    <CardDescription>Enter your credentials to continue.</CardDescription>
                </CardHeader>
                <CardContent>
                    {#if error}
                        <div in:fade={{ duration: blockDuration() }} class="mb-4">
                            <ErrorAlert message={error} />
                        </div>
                    {/if}

                    <div class="space-y-3 mb-6">
                        <Button
                            type="button"
                            variant="outline"
                            class="w-full h-11 font-semibold tracking-wide transition-all"
                            disabled={oauthLoading}
                            onclick={() => handleOAuthLogin('google')}
                            on:click={() => handleOAuthLogin('google')}
                        >
                            Sign In with Google
                        </Button>
                        <Button
                            type="button"
                            variant="outline"
                            class="w-full h-11 font-semibold tracking-wide transition-all"
                            disabled={oauthLoading}
                            onclick={() => handleOAuthLogin('microsoft')}
                            on:click={() => handleOAuthLogin('microsoft')}
                        >
                            Sign In with Microsoft
                        </Button>
                    </div>

                    <div class="relative mb-6">
                        <div class="absolute inset-0 flex items-center">
                            <div class="w-full border-t border-border/50"></div>
                        </div>
                        <div class="relative flex justify-center text-xs">
                            <span class="px-2 bg-background text-muted-foreground">or continue with email</span>
                        </div>
                    </div>

                    <form onsubmit={handleSubmit} class="space-y-5">
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
            Batchrite &middot; Laboratory Execution System
        </p>
    </div>
</div>
