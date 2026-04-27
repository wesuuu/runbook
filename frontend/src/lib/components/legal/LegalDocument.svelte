<script lang="ts">
    import MarkdownRenderer from '$lib/components/shared/MarkdownRenderer.svelte';

    interface Props {
        title: string;
        markdown: string;
        version: string;
        effectiveDate: string;
    }

    let { title, markdown, version, effectiveDate }: Props = $props();
</script>

<article class="legal-document">
    <header class="mb-6">
        <h1 class="text-2xl font-semibold text-foreground tracking-tight">{title}</h1>
        <p class="text-sm text-muted-foreground mt-1">
            Version {version} · Effective {effectiveDate}
        </p>
    </header>
    <div class="prose prose-sm max-w-none dark:prose-invert">
        <MarkdownRenderer content={markdown} format="markdown" />
    </div>
</article>

<style>
    .legal-document :global(h1) {
        font-size: 1.25rem;
        line-height: 1.75rem;
        font-weight: 600;
        margin-top: 1.5rem;
        margin-bottom: 0.75rem;
    }
    .legal-document :global(h2) {
        font-size: 1.125rem;
        line-height: 1.75rem;
        font-weight: 600;
        margin-top: 1.25rem;
        margin-bottom: 0.5rem;
    }
    .legal-document :global(p) {
        margin-bottom: 0.75rem;
        line-height: 1.625;
    }
    .legal-document :global(ul),
    .legal-document :global(ol) {
        margin-bottom: 0.75rem;
        padding-left: 1.5rem;
        list-style-type: disc;
    }
</style>
