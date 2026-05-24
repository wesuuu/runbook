<script lang="ts">
import { Button } from '$lib/components/ui/button';
import { toast } from 'svelte-sonner';
import { api } from '$lib/api';

interface Props {
    experimentId: string;
    slug: string;
}
let { experimentId, slug }: Props = $props();

let busy = $state(false);

async function download() {
    busy = true;
    try {
        await api.downloadBlob(
            `/experiments/${experimentId}/export.pdf`,
            `experiment-${slug}.pdf`,
        );
    } catch (err) {
        const msg = err instanceof Error ? err.message : 'PDF export failed';
        toast.error(msg);
    } finally {
        busy = false;
    }
}
</script>

<Button variant="outline" disabled={busy} onclick={download}>
    {busy ? 'Generating…' : 'Export summary'}
</Button>
