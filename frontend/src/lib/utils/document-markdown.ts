import { API_BASE } from '$lib/config';

/** Matches a markdown image whose target is a relative `images/{n}.png` asset. */
const RELATIVE_IMAGE_RE = /!\[([^\]]*)\]\(images\/(\d+)\.png\)/g;

/** Escapes a string for safe interpolation into a RegExp. */
function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Rewrites relative extracted-image refs (`images/3.png`) to absolute API URLs
 * with the auth token in the query string, so the live editor can render them.
 */
export function toDisplayMarkdown(
    markdown: string,
    documentId: string,
    token: string | null,
): string {
    const suffix = token ? `?token=${token}` : '';
    return markdown.replace(
        RELATIVE_IMAGE_RE,
        (_match, alt: string, n: string) =>
            `![${alt}](${API_BASE}/library/documents/${documentId}/images/${n}.png${suffix})`,
    );
}

/**
 * Inverse of {@link toDisplayMarkdown}: rewrites absolute extracted-image URLs
 * (with or without a `?token=` query) back to relative `images/{n}.png` refs
 * for storage. Only URLs under this document's image endpoint are touched.
 */
export function toStoredMarkdown(markdown: string, documentId: string): string {
    const prefix = escapeRegExp(
        `${API_BASE}/library/documents/${documentId}/images/`,
    );
    const absoluteImageRe = new RegExp(
        `!\\[([^\\]]*)\\]\\(${prefix}(\\d+)\\.png(?:\\?[^)]*)?\\)`,
        'g',
    );
    return markdown.replace(
        absoluteImageRe,
        (_match, alt: string, n: string) => `![${alt}](images/${n}.png)`,
    );
}
