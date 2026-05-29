<script lang="ts">
    import { goto } from '$app/navigation';
    import { register } from '$lib/auth.svelte';
    import { REGISTRATION_ENABLED } from '$lib/feature-flags';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';
    import ErrorAlert from '$lib/components/ui/error-alert.svelte';
    import { fade } from 'svelte/transition';
    import { blockDuration } from '$lib/transitions';
    import Logo from '$lib/components/layout/Logo.svelte';
    import RegistrationWaitlist from '$lib/components/shared/RegistrationWaitlist.svelte';

    const CALENDLY_WAITLIST_URL = 'https://calendly.com/wes-batchrite/30min'; // F-0091

    const inviteToken =
        typeof window !== 'undefined'
            ? new URLSearchParams(window.location.search).get('invite')
            : null;
    const showForm = REGISTRATION_ENABLED || !!inviteToken;

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
            await register(email, password, fullName, inviteToken);
            goto('/check-email');
        } catch (err: unknown) {
            error = err instanceof Error ? err.message : 'Registration failed';
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
            <Logo size="lg" variant="full" animated orientation="stacked" />
            <p class="mt-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground/80">Laboratory Execution System</p>
        </div>

        {#if showForm}
            <div class="card-warm rounded-xl p-1">
                <Card class="border-0 shadow-none bg-transparent">
                    <CardHeader class="pb-4">
                        <CardTitle class="text-lg">Create Account</CardTitle>
                        <CardDescription>Fill in your details to get started.</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <form onsubmit={handleSubmit} class="space-y-4">
                            {#if error}
                                <div in:fade={{ duration: blockDuration() }} class="mb-4">
                                    <ErrorAlert message={error} />
                                </div>
                            {/if}

                            <div class="space-y-2">
                                <Label for="fullName" class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Full Name</Label>
                                <Input
                                    id="fullName"
                                    type="text"
                                    bind:value={fullName}
                                    placeholder="Jane Doe"
                                    class="h-11 bg-background/60 border-border/80 focus:border-primary"
                                />
                            </div>

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
                                    placeholder="At least 6 characters"
                                    required
                                    class="h-11 bg-background/60 border-border/80 focus:border-primary"
                                />
                            </div>

                            <div class="space-y-2">
                                <Label for="confirmPassword" class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Confirm Password</Label>
                                <Input
                                    id="confirmPassword"
                                    type="password"
                                    bind:value={confirmPassword}
                                    placeholder="Repeat your password"
                                    required
                                    class="h-11 bg-background/60 border-border/80 focus:border-primary"
                                />
                            </div>

                            <Button type="submit" class="w-full h-11 font-semibold tracking-wide shadow-sm shadow-primary/20 hover:shadow-md hover:shadow-primary/30 transition-all" disabled={loading}>
                                {loading ? 'Creating account...' : 'Create Account'}
                            </Button>
                        </form>

                        <p class="text-sm text-center text-muted-foreground mt-6">
                            Already have an account?
                            <a href="/login" class="text-primary font-semibold hover:underline">Sign In</a>
                        </p>

                        <p class="text-xs text-muted-foreground text-center mt-4">
                            By continuing, you agree to our
                            <a href="/legal/terms" class="underline hover:text-foreground transition-all duration-150">Terms of Service</a>
                            and
                            <a href="/legal/privacy" class="underline hover:text-foreground transition-all duration-150">Privacy Policy</a>.
                        </p>
                    </CardContent>
                </Card>
            </div>
        {:else}
            <div in:fade={{ duration: blockDuration() }}>
                <RegistrationWaitlist calendlyUrl={CALENDLY_WAITLIST_URL} />
            </div>
        {/if}

        <p class="text-center text-xs text-muted-foreground/60 mt-8 tracking-wide">
            Batchrite &middot; Laboratory Execution System
        </p>
    </div>
</div>
