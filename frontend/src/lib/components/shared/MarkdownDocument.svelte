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
    let container = $state<HTMLDivElement | null>(null);

    const displayMarkdown = $derived(
        toDisplayMarkdown(markdown, documentId, getToken()),
    );

    const html = $derived(
        DOMPurify.sanitize(
            marked.parse(displayMarkdown, { gfm: true, breaks: false }) as string,
        ),
    );

    /**
     * Belt-and-suspenders for the upstream filter in
     * ``ext/docling-extractor/`` — already-extracted documents may still
     * contain degenerate sub-32px "figure" PNGs that the browser
     * otherwise stretches into a column-width blurry artifact. We hide
     * them as they load.
     */
    const MIN_IMAGE_DIMENSION = 32;
    $effect(() => {
        // Re-run when html changes so we rebind to the new images.
        void html;
        if (!container) return;
        const onload = (event: Event) => {
            const img = event.currentTarget as HTMLImageElement;
            if (
                img.naturalWidth > 0 &&
                img.naturalWidth < MIN_IMAGE_DIMENSION &&
                img.naturalHeight < MIN_IMAGE_DIMENSION
            ) {
                img.style.display = 'none';
            }
        };
        const imgs = Array.from(container.querySelectorAll('img'));
        for (const img of imgs) {
            if (img.complete) {
                onload({ currentTarget: img } as unknown as Event);
            } else {
                img.addEventListener('load', onload, { once: true });
            }
        }
    });
</script>

<div bind:this={container} class="prose prose-sm max-w-none {className}">{@html html}</div>
