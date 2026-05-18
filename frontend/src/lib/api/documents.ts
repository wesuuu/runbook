import { api } from '$lib/api';
import { getToken } from '$lib/auth.svelte';
import { API_BASE } from '$lib/config';
import {
    DocumentResponseSchema,
    MarkdownResponseSchema,
    type DocumentResponse,
    type MarkdownResponse,
} from '$lib/schemas/documents';

/** GET the raw stored markdown. 404s until extraction has completed. */
export function getDocumentMarkdown(documentId: string): Promise<MarkdownResponse> {
    return api.get(`/library/documents/${documentId}/markdown`, {
        schema: MarkdownResponseSchema,
    });
}

/** PUT refined markdown. Backend flips refinement_status to IN_PROGRESS on first edit. */
export function updateDocumentMarkdown(
    documentId: string,
    markdown: string,
): Promise<DocumentResponse> {
    return api.put(
        `/library/documents/${documentId}/markdown`,
        { markdown },
        { schema: DocumentResponseSchema },
    );
}

/** POST refine/complete — transitions the document to INDEXING. */
export function completeDocumentRefinement(
    documentId: string,
): Promise<DocumentResponse> {
    return api.post(
        `/library/documents/${documentId}/refine/complete`,
        { reopen: false },
        { schema: DocumentResponseSchema },
    );
}

/** POST refine/complete with reopen:true — re-opens a completed document. */
export function reopenDocumentRefinement(
    documentId: string,
): Promise<DocumentResponse> {
    return api.post(
        `/library/documents/${documentId}/refine/complete`,
        { reopen: true },
        { schema: DocumentResponseSchema },
    );
}

/** Absolute, token-bearing URL for an extracted figure — safe for <img src>. */
export function documentImageUrl(documentId: string, n: number): string {
    const token = getToken();
    const suffix = token ? `?token=${token}` : '';
    return `${API_BASE}/library/documents/${documentId}/images/${n}.png${suffix}`;
}

/** Absolute, token-bearing URL for a pymupdf source-page render (PDF only). */
export function documentSourcePageUrl(documentId: string, page: number): string {
    const token = getToken();
    const suffix = token ? `?token=${token}` : '';
    return `${API_BASE}/library/documents/${documentId}/source-page/${page}.png${suffix}`;
}
