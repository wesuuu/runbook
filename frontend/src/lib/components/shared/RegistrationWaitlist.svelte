<script lang="ts">
    import { ExternalLink } from 'lucide-svelte';
    import { Button } from '$lib/components/ui/button';
    import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '$lib/components/ui/card';

    interface Props {
        calendlyUrl: string;
    }

    let { calendlyUrl }: Props = $props();
</script>

<Card class="border-0 shadow-none bg-transparent">
    <CardHeader class="pb-4">
        <CardTitle class="text-lg">Join the first cohort</CardTitle>
        <CardDescription>Batchrite is currently invite-only.</CardDescription>
    </CardHeader>
    <CardContent class="space-y-4">
        <Button href={calendlyUrl} target="_blank" rel="noopener noreferrer" class="w-full">
            Request early access
            <ExternalLink class="ml-1.5 h-3.5 w-3.5 opacity-70" />
        </Button>
        <Button variant="outline" href="/login" class="w-full">
            Back to sign in
        </Button>
        <p class="text-xs text-muted-foreground text-center pt-2">
            By requesting access, you agree to our
            <a href="/legal/terms" class="underline hover:text-foreground transition-all duration-150 cursor-pointer">Terms of Service</a>
            and
            <a href="/legal/privacy" class="underline hover:text-foreground transition-all duration-150 cursor-pointer">Privacy Policy</a>.
        </p>
    </CardContent>
</Card>
