<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { getUser, isEmailVerified, refreshUser, resendVerification } from '$lib/auth.svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';
    import { toast } from 'svelte-sonner';

    let sending = $state(false);
    const userEmail = $derived(getUser()?.email ?? '');

    onMount(async () => {
        await refreshUser();
        if (isEmailVerified()) {
            goto('/');
        }
    });

    async function handleResend() {
        sending = true;
        try {
            await resendVerification();
            toast.success('Verification email sent!');
        } catch (err: unknown) {
            if (err instanceof Error && err.message.includes('Too many')) {
                toast.info(
                    'We\'ve already sent a few emails. Please check your inbox and spam folder, then try again in a few minutes.'
                );
            } else {
                toast.error(err instanceof Error ? err.message : 'Failed to resend email');
            }
        } finally {
            sending = false;
        }
    }

    function handleFocus() {
        refreshUser().then(() => {
            if (isEmailVerified()) {
                goto('/');
            }
        });
    }
</script>

<svelte:window onfocus={handleFocus} />

<div class="min-h-screen flex items-center justify-center bg-muted/40 px-4">
    <div class="w-full max-w-sm">
        <div class="flex flex-col items-center mb-8">
            <div
                class="w-12 h-12 bg-primary rounded-xl flex items-center justify-center text-primary-foreground font-bold text-xl shadow-sm mb-3"
            >
                R
            </div>
            <h1 class="text-2xl font-bold tracking-tight">Runbook</h1>
        </div>

        <Card>
            <CardHeader>
                <CardTitle>Check your email</CardTitle>
                <CardDescription>
                    We sent a verification link to <strong>{userEmail}</strong>. Click the link in the email to activate your account.
                </CardDescription>
            </CardHeader>
            <CardContent class="space-y-4">
                <p class="text-sm text-muted-foreground">
                    Didn't receive the email? Check your spam folder, or click below to resend.
                </p>

                <Button
                    variant="outline"
                    class="w-full"
                    disabled={sending}
                    onclick={handleResend}
                >
                    {sending ? 'Sending...' : 'Resend verification email'}
                </Button>

                <p class="text-sm text-center text-muted-foreground mt-4">
                    Wrong email?
                    <a href="/register" class="text-primary font-medium hover:underline">Start over</a>
                </p>
            </CardContent>
        </Card>
    </div>
</div>
