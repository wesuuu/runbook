<script lang="ts">
    import { marked } from 'marked';
    import DOMPurify from 'dompurify';
    import { getToken } from '$lib/auth.svelte';
    import { toDisplayMarkdown } from '$lib/utils/document-markdown';

    interface Props {
        /** Stored document markdown (relative image refs). */
        markdown: string;
        /** Owning document id — used to build absolute image URLs. */
        documentId: string;
        class?: string;
    }

    let { markdown, documentId, class: className = '' }: Props = $props();

    const displayMarkdown = $derived(
        toDisplayMarkdown(markdown, documentId, getToken()),
    );

    const html = $derived(
        DOMPurify.sanitize(
            marked.parse(displayMarkdown, { gfm: true, breaks: false }) as string,
        ),
    );
</script>

<div class="prose prose-sm max-w-none {className}">{@html html}</div>
