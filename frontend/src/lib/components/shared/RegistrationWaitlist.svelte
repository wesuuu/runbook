<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';

    interface Props {
        calendlyUrl: string;
    }

    let { calendlyUrl }: Props = $props();
</script>

<Card>
    <CardHeader>
        <CardTitle>Join the first cohort</CardTitle>
        <CardDescription>
            Batchrite is currently in early access. Request an invite to be among the
            first Process Development teams on the platform.
        </CardDescription>
    </CardHeader>
    <CardContent class="space-y-4">
        <Button href={calendlyUrl} target="_blank" rel="noopener noreferrer" class="w-full">
            Request early access
        </Button>
        <Button variant="outline" href="/login" class="w-full">
            Back to sign in
        </Button>
        <p class="text-xs text-muted-foreground text-center pt-2">
            By requesting access, you agree to our
            <a href="/legal/terms" class="underline hover:text-foreground transition-all duration-150">Terms of Service</a>
            and
            <a href="/legal/privacy" class="underline hover:text-foreground transition-all duration-150">Privacy Policy</a>.
        </p>
    </CardContent>
</Card>
