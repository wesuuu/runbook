<script lang="ts">
    import LegalDocument from '$lib/components/legal/LegalDocument.svelte';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();
</script>

<svelte:head>
    <title>Terms of Service · Batchrite</title>
</svelte:head>

<main class="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
    <LegalDocument
        title="Terms of Service"
        markdown={data.doc.markdown}
        version={data.doc.version}
        effectiveDate={data.doc.effective_date}
    />
</main>
