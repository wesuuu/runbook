import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({
    getToken: () => 'tok123',
    logout: () => {},
}));

import {
    completeDocumentRefinement,
    documentImageUrl,
    documentSourcePageUrl,
    getDocumentMarkdown,
    updateDocumentMarkdown,
} from './documents';

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

const DOC = {
    id: 'doc-1',
    org_id: 'org-1',
    uploaded_by_id: 'user-1',
    title: 'SOP',
    original_filename: 'sop.pdf',
    mime_type: 'application/pdf',
    file_size_bytes: 10,
    file_path: 'p',
    status: 'AWAITING_REFINEMENT',
    created_at: '2026-05-14T00:00:00Z',
    updated_at: '2026-05-14T00:00:00Z',
};

describe('documents API client', () => {
    beforeEach(() => {
        localStorage.setItem('auth_token', 'tok123');
    });
    afterEach(() => {
        vi.restoreAllMocks();
        localStorage.clear();
    });

    it('GETs stored markdown', async () => {
        const fetchMock = vi
            .spyOn(globalThis, 'fetch')
            .mockResolvedValue(jsonResponse({ markdown: '# Hi' }));
        const res = await getDocumentMarkdown('doc-1');
        expect(res.markdown).toBe('# Hi');
        expect(fetchMock.mock.calls[0][0]).toContain('/library/documents/doc-1/markdown');
        expect(fetchMock.mock.calls[0][1]?.method).toBe('GET');
    });

    it('PUTs refined markdown with the wrapped body', async () => {
        const fetchMock = vi
            .spyOn(globalThis, 'fetch')
            .mockResolvedValue(jsonResponse(DOC));
        const res = await updateDocumentMarkdown('doc-1', '# Edited');
        expect(res.id).toBe('doc-1');
        const init = fetchMock.mock.calls[0][1];
        expect(init?.method).toBe('PUT');
        expect(JSON.parse(init?.body as string)).toEqual({ markdown: '# Edited' });
    });

    it('POSTs refine/complete with reopen:false', async () => {
        const fetchMock = vi
            .spyOn(globalThis, 'fetch')
            .mockResolvedValue(jsonResponse({ ...DOC, status: 'INDEXING' }));
        const res = await completeDocumentRefinement('doc-1');
        expect(res.status).toBe('INDEXING');
        expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({
            reopen: false,
        });
    });

    it('builds token-bearing image and source-page URLs', () => {
        expect(documentImageUrl('doc-1', 3)).toBe(
            'http://localhost:8000/library/documents/doc-1/images/3.png?token=tok123',
        );
        expect(documentSourcePageUrl('doc-1', 2)).toBe(
            'http://localhost:8000/library/documents/doc-1/source-page/2.png?token=tok123',
        );
    });
});
