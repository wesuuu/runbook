# TD-0085 Phase 2 — Refinement Editor Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the document refinement editor frontend — a `/library/documents/[id]/refine` route where a PD scientist reviews docling-extracted markdown in a WYSIWYG editor, fixes OCR/layout artifacts (with optional AI assist), and marks refinement complete to trigger indexing.

**Architecture:** A SvelteKit route hosts a three-column workspace. The center is a thin wrapper around the existing `edra` Tiptap setup that round-trips markdown. The left rail shows the source-page render + extraction status pipeline; the right rail stacks a low-confidence flag queue and a selection-scoped AI-fix panel. All four refinement components live in a new `lib/components/document-refinement/` domain bucket. A shared `MarkdownDocument.svelte` renders stored markdown read-only. Everything hits the Phase 1 backend API, which is already implemented and smoke-verified.

**Tech Stack:** Svelte 5 (runes), SvelteKit file-based routing, `edra`/Tiptap with `tiptap-markdown`, shadcn-svelte primitives, Zod, `marked` + `dompurify`, Vitest + `@testing-library/svelte`, Playwright.

---

## Context for the implementer

**You are working in a git worktree:** `/home/wesuuu/Code/trellisbio/.claude/worktrees/td-0085-docling-extraction`. Run all commands from `frontend/` unless told otherwise. Frontend deps are already installed (`node_modules/` exists).

**The Phase 1 backend is done.** These endpoints exist and are verified working. Note the real prefix is `/library` (the router is mounted at `/library` in `backend/app/main.py:398`), so every path below is `/library/documents/...`:

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/library/documents/{id}` | `DocumentResponse` (or `DocumentDetailResponse` — superset) |
| `GET` | `/library/documents/{id}/markdown` | `{ "markdown": "..." }` — 404 until extraction done |
| `PUT` | `/library/documents/{id}/markdown` | `DocumentResponse` — body `{ "markdown": "..." }` |
| `POST` | `/library/documents/{id}/refine/ai` | `{ "suggested_markdown": "...", "model_used": "..." }` |
| `POST` | `/library/documents/{id}/refine/complete` | `DocumentResponse` — body `{ "reopen": false }` |
| `GET` | `/library/documents/{id}/images/{n}.png` | PNG bytes (extracted figure) |
| `GET` | `/library/documents/{id}/source-page/{n}.png` | PNG bytes (pymupdf page render, PDF only) |

The `refine/ai` request body shape (from `backend/app/schemas/library.py`):
```
{ scope: "selection"|"block"|"document", selection_markdown: str, instruction: str,
  surrounding_context_markdown: str|null, page: int|null, bbox: [float,float,float,float]|null }
```

**Document status flow (new pipeline):** `UPLOADED → QUEUED → EXTRACTING → AWAITING_REFINEMENT → INDEXING → READY`. The refinement editor is meaningful only at `AWAITING_REFINEMENT`. Legacy documents use `PROCESSING/INDEXED/ENRICHED` and never enter this editor.

**Phase 1 caveat — flags are always empty.** The backend's `_collect_flags` is a Phase 1 stub returning `[]`, so `refinement_flags` is `[]` and `refinement_status` is `NOT_REQUIRED` in practice today. `RefinementQueue` must render a clean empty state, and the flag-click → scroll/AI wiring is built for forward-compatibility — it is exercised by unit tests with synthetic flags, not by live data yet.

**Image refs in stored markdown are relative** — `![caption](images/3.png)`. The editor must rewrite these to absolute, token-bearing API URLs for display, and rewrite them back to relative on save. That round-trip is a pure util (Task 2), tested in isolation.

**Key existing files you will read or reuse:**
- `frontend/src/lib/api.ts` — the `api` object (`api.get/post/put`, optional `{ schema }` validation). `_authHeaders()` injects the Bearer token automatically.
- `frontend/src/lib/auth.svelte.ts` — `getToken()` returns the JWT string (needed for `<img src>` `?token=` URLs).
- `frontend/src/lib/config.ts` — exports `API_BASE`.
- `frontend/src/lib/schemas/index.ts` — barrel that re-exports every domain schema file.
- `frontend/src/lib/components/edra/shadcn/index.ts` — exports `EdraEditor`, `EdraToolBar`, `EdraBubbleMenu`, `EdraDragHandleExtended`.
- `frontend/src/lib/components/edra/types.ts` — `EdraEditorProps` (`content`, `editable`, `editor` bindable, `onUpdate`, `autofocus`, `class`).
- `frontend/src/routes/experiments/[id]/+page.svelte` — the one existing `EdraEditor` usage; copy its dynamic-import pattern.
- `frontend/src/routes/protocols/[id]/+page.svelte` — the autosave / `hasUnsavedChanges` / `beforeunload` pattern to mirror.
- `frontend/src/lib/components/shared/MarkdownRenderer.svelte` — existing chunk renderer (do **not** modify; `MarkdownDocument.svelte` is its sibling, purpose-built for whole-document stored markdown).
- `scripts/mocks/editor-mockups.html` — "Concept II" is the chosen design. Three columns, themed `lab-glass`; reference its class names (`.workspace`, `.card-warm`, `.rail-card`, `.flag-item`, `.ai-panel`) for layout intent, but implement with Tailwind utilities matching house style.

**House conventions you must follow** (`.claude/rules/conventions.md`, `.claude/rules/frontend-components.md`):
- Components: `interface Props` + `$props()` destructuring; callbacks prefixed `on` (`onAccept`, `onCancel`).
- New components go in a domain subdirectory — this plan creates `lib/components/document-refinement/`.
- Reuse `lib/components/ui/` primitives (`Button`, `Badge`, `Dialog`, `Card`); never hand-roll a button or dialog.
- All clickable elements use `cursor-pointer` + a hover state + `transition-*`.
- Page-level content gets a `fade` transition on its top wrapper.
- TypeScript: `const`/`let` only, named exports, single quotes, semicolons, triple-equals, no `any`.

**Test commands** (from `frontend/`):
- `npm run test -- <path>` — Vitest single-run for one file.
- `npm run check` — `svelte-check` + `tsc`.
- `npm run test:e2e -- <path>` — Playwright (needs dev servers running).

**Commit format:** `<type>(<scope>): <description>` — use `feat(library)` for new code, `test(library)` for test-only, `docs` for the rules update. Commit after every green task.

---

## File Structure

**Created:**
- `frontend/src/lib/schemas/documents.ts` — Zod schemas for document + refinement payloads.
- `frontend/src/lib/schemas/documents.test.ts` — schema parse tests.
- `frontend/src/lib/utils/document-markdown.ts` — pure image-src rewrite util (relative ⇄ absolute).
- `frontend/src/lib/utils/document-markdown.test.ts` — util tests.
- `frontend/src/lib/api/documents.ts` — typed API client methods + image URL builders.
- `frontend/src/lib/api/documents.test.ts` — API client tests (mocked `fetch`).
- `frontend/src/lib/components/shared/MarkdownDocument.svelte` — read-only whole-document markdown renderer.
- `frontend/src/lib/components/shared/MarkdownDocument.test.ts` — render test.
- `frontend/src/lib/components/document-refinement/RefinementSidebar.svelte` — left rail.
- `frontend/src/lib/components/document-refinement/RefinementSidebar.test.ts`
- `frontend/src/lib/components/document-refinement/RefinementQueue.svelte` — right rail flag queue.
- `frontend/src/lib/components/document-refinement/RefinementQueue.test.ts`
- `frontend/src/lib/components/document-refinement/RefinementAiPanel.svelte` — right rail AI-fix panel.
- `frontend/src/lib/components/document-refinement/RefinementAiPanel.test.ts`
- `frontend/src/lib/components/document-refinement/RefinementEditor.svelte` — center Tiptap wrapper.
- `frontend/src/lib/components/document-refinement/RefinementEditor.test.ts`
- `frontend/src/routes/library/documents/[id]/refine/+page.svelte` — the refinement route.
- `frontend/e2e/document-refinement.spec.ts` — Playwright smoke.

**Modified:**
- `frontend/src/lib/schemas/index.ts` — add `export * from './documents';`.
- `frontend/src/lib/utils/document-utils.ts` — add new statuses to `STATUS_COLORS` / `getStatusLabel`.
- `frontend/src/routes/library/+page.svelte` — "Needs refinement" badge + Refine link in the list.
- `frontend/src/routes/library/[id]/+page.svelte` — "Refine document" button when `AWAITING_REFINEMENT`.
- `.claude/rules/conventions.md` — add `document-refinement/` to the component-placement bucket list.

---

## Task 1: Zod schemas for documents

**Files:**
- Create: `frontend/src/lib/schemas/documents.ts`
- Create: `frontend/src/lib/schemas/documents.test.ts`
- Modify: `frontend/src/lib/schemas/index.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/schemas/documents.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';

import {
    DocumentResponseSchema,
    MarkdownResponseSchema,
    RefineAiResponseSchema,
    RefinementFlagSchema,
} from './documents';

describe('documents schemas', () => {
    it('parses a minimal DocumentResponse with null docling fields', () => {
        const raw = {
            id: 'doc-1',
            org_id: 'org-1',
            uploaded_by_id: 'user-1',
            title: 'SOP 12',
            original_filename: 'sop12.pdf',
            mime_type: 'application/pdf',
            file_size_bytes: 1024,
            file_path: 'org-1/documents/doc-1.pdf',
            status: 'AWAITING_REFINEMENT',
            created_at: '2026-05-14T00:00:00Z',
            updated_at: '2026-05-14T00:00:00Z',
        };
        const parsed = DocumentResponseSchema.parse(raw);
        expect(parsed.status).toBe('AWAITING_REFINEMENT');
        expect(parsed.tags).toEqual([]);
        expect(parsed.refinement_flags).toBeUndefined();
        expect(parsed.can_delete).toBe(false);
    });

    it('parses a DocumentResponse carrying refinement flags', () => {
        const raw = {
            id: 'doc-2',
            org_id: 'org-1',
            uploaded_by_id: 'user-1',
            title: 'SOP 13',
            original_filename: 'sop13.pdf',
            mime_type: 'application/pdf',
            file_size_bytes: 2048,
            file_path: 'org-1/documents/doc-2.pdf',
            status: 'AWAITING_REFINEMENT',
            created_at: '2026-05-14T00:00:00Z',
            updated_at: '2026-05-14T00:00:00Z',
            source_format: 'PDF',
            refinement_status: 'PENDING',
            refinement_flags: [
                {
                    id: 'flag-001',
                    kind: 'low_confidence_ocr',
                    confidence: 0.31,
                    block_anchor: 'table-1.row-1.col-2',
                    source_text: 'NaHzPO4119.98',
                    page: 1,
                    bbox: [0.42, 0.31, 0.58, 0.34],
                },
            ],
        };
        const parsed = DocumentResponseSchema.parse(raw);
        expect(parsed.refinement_flags).toHaveLength(1);
        expect(parsed.refinement_flags?.[0].source_text).toBe('NaHzPO4119.98');
    });

    it('parses the markdown and AI response shapes', () => {
        expect(MarkdownResponseSchema.parse({ markdown: '# Title' }).markdown).toBe('# Title');
        const ai = RefineAiResponseSchema.parse({
            suggested_markdown: 'NaH2PO4 119.98',
            model_used: 'claude-sonnet-4-6',
        });
        expect(ai.model_used).toBe('claude-sonnet-4-6');
    });

    it('rejects a flag missing its id', () => {
        expect(() => RefinementFlagSchema.parse({ kind: 'low_confidence_ocr' })).toThrow();
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/lib/schemas/documents.test.ts`
Expected: FAIL — `Failed to resolve import "./documents"`.

- [ ] **Step 3: Create the schema file**

Create `frontend/src/lib/schemas/documents.ts`:

```typescript
import { z } from 'zod';

/** A single docling-emitted low-confidence region. Phase 1 always emits []. */
export const RefinementFlagSchema = z
    .object({
        id: z.string(),
        kind: z.string(),
        confidence: z.number().nullable().optional(),
        block_anchor: z.string().nullable().optional(),
        source_text: z.string().nullable().optional(),
        page: z.number().nullable().optional(),
        bbox: z.array(z.number()).nullable().optional(),
    })
    .passthrough();
export type RefinementFlag = z.infer<typeof RefinementFlagSchema>;

/** Mirrors backend DocumentResponse (schemas/library.py). */
export const DocumentResponseSchema = z
    .object({
        id: z.string(),
        org_id: z.string(),
        project_id: z.string().nullable().optional(),
        uploaded_by_id: z.string(),
        title: z.string(),
        original_filename: z.string(),
        mime_type: z.string(),
        file_size_bytes: z.number(),
        file_path: z.string(),
        status: z.string(),
        page_count: z.number().nullable().optional(),
        tags: z.array(z.unknown()).default([]),
        doc_metadata: z.record(z.string(), z.unknown()).default({}),
        error_message: z.string().nullable().optional(),
        source_url: z.string().nullable().optional(),
        processing_started_at: z.string().nullable().optional(),
        structure_metadata: z.record(z.string(), z.unknown()).nullable().optional(),
        created_at: z.string(),
        updated_at: z.string(),
        can_delete: z.boolean().default(false),
        source_format: z.string().nullable().optional(),
        refinement_status: z.string().nullable().optional(),
        refinement_flags: z.array(RefinementFlagSchema).nullable().optional(),
        refined_by_id: z.string().nullable().optional(),
        refined_at: z.string().nullable().optional(),
    })
    .passthrough();
export type DocumentResponse = z.infer<typeof DocumentResponseSchema>;

/** GET /library/documents/{id}/markdown */
export const MarkdownResponseSchema = z
    .object({
        markdown: z.string(),
    })
    .passthrough();
export type MarkdownResponse = z.infer<typeof MarkdownResponseSchema>;

/** POST /library/documents/{id}/refine/ai */
export const RefineAiResponseSchema = z
    .object({
        suggested_markdown: z.string(),
        model_used: z.string(),
    })
    .passthrough();
export type RefineAiResponse = z.infer<typeof RefineAiResponseSchema>;
```

- [ ] **Step 4: Add the barrel export**

In `frontend/src/lib/schemas/index.ts`, add this line alphabetically near the other `export *` lines (after `export * from './chat';`):

```typescript
export * from './documents';
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm run test -- src/lib/schemas/documents.test.ts`
Expected: PASS — 4 tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/schemas/documents.ts frontend/src/lib/schemas/documents.test.ts frontend/src/lib/schemas/index.ts
git commit -m "feat(library): add Zod schemas for document refinement payloads"
```

---

## Task 2: Markdown image-src rewrite util

The stored markdown holds relative image refs (`images/3.png`). The editor renders absolute, token-bearing URLs. This pure util converts both directions.

**Files:**
- Create: `frontend/src/lib/utils/document-markdown.ts`
- Create: `frontend/src/lib/utils/document-markdown.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/utils/document-markdown.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';

import { toDisplayMarkdown, toStoredMarkdown } from './document-markdown';

const DOC_ID = 'doc-abc';
const BASE = 'http://localhost:8000';

describe('document-markdown rewrite util', () => {
    it('rewrites relative image refs to absolute token-bearing URLs', () => {
        const stored = 'Intro\n\n![Figure 1](images/3.png)\n\nMore text.';
        const display = toDisplayMarkdown(stored, DOC_ID, 'tok123');
        expect(display).toContain(
            `![Figure 1](${BASE}/library/documents/${DOC_ID}/images/3.png?token=tok123)`,
        );
    });

    it('omits the token query when no token is given', () => {
        const display = toDisplayMarkdown('![x](images/1.png)', DOC_ID, null);
        expect(display).toBe(`![x](${BASE}/library/documents/${DOC_ID}/images/1.png)`);
    });

    it('rewrites absolute image URLs back to relative on save', () => {
        const display = `![Figure 1](${BASE}/library/documents/${DOC_ID}/images/3.png?token=tok123)`;
        expect(toStoredMarkdown(display, DOC_ID)).toBe('![Figure 1](images/3.png)');
    });

    it('round-trips losslessly', () => {
        const stored = '# Doc\n\n![a](images/0.png)\n\ntext\n\n![b](images/12.png)\n';
        const back = toStoredMarkdown(toDisplayMarkdown(stored, DOC_ID, 'tok'), DOC_ID);
        expect(back).toBe(stored);
    });

    it('leaves non-image-asset URLs untouched', () => {
        const md = '![ext](https://example.com/pic.png)\n\n[link](images/3.png)';
        expect(toDisplayMarkdown(md, DOC_ID, 'tok')).toBe(md);
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/lib/utils/document-markdown.test.ts`
Expected: FAIL — `Failed to resolve import "./document-markdown"`.

- [ ] **Step 3: Create the util**

Create `frontend/src/lib/utils/document-markdown.ts`:

```typescript
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- src/lib/utils/document-markdown.test.ts`
Expected: PASS — 5 tests. (`API_BASE` resolves to `http://localhost:8000` in the test env since `VITE_API_PORT` is unset.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/utils/document-markdown.ts frontend/src/lib/utils/document-markdown.test.ts
git commit -m "feat(library): add markdown image-src rewrite util for refinement editor"
```

---

## Task 3: API client methods for refinement

**Files:**
- Create: `frontend/src/lib/api/documents.ts`
- Create: `frontend/src/lib/api/documents.test.ts`

Note: `$lib/api` resolves to `api.ts`; `$lib/api/documents` resolves to this new file. They coexist without conflict.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/api/documents.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    completeDocumentRefinement,
    documentImageUrl,
    documentSourcePageUrl,
    getDocumentMarkdown,
    refineDocumentWithAi,
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

    it('POSTs an AI refine request mapping camelCase to snake_case', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ suggested_markdown: 'fixed', model_used: 'claude-sonnet-4-6' }),
        );
        const res = await refineDocumentWithAi('doc-1', {
            scope: 'selection',
            selectionMarkdown: 'NaHzPO4',
            instruction: 'fix the formula',
            surroundingContextMarkdown: 'before NaHzPO4 after',
        });
        expect(res.suggested_markdown).toBe('fixed');
        const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
        expect(body).toEqual({
            scope: 'selection',
            selection_markdown: 'NaHzPO4',
            instruction: 'fix the formula',
            surrounding_context_markdown: 'before NaHzPO4 after',
            page: null,
            bbox: null,
        });
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/lib/api/documents.test.ts`
Expected: FAIL — `Failed to resolve import "./documents"`.

- [ ] **Step 3: Create the API client**

Create `frontend/src/lib/api/documents.ts`:

```typescript
import { api } from '$lib/api';
import { getToken } from '$lib/auth.svelte';
import { API_BASE } from '$lib/config';
import {
    DocumentResponseSchema,
    MarkdownResponseSchema,
    RefineAiResponseSchema,
    type DocumentResponse,
    type MarkdownResponse,
    type RefineAiResponse,
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

export interface RefineAiParams {
    scope: 'selection' | 'block' | 'document';
    selectionMarkdown: string;
    instruction: string;
    surroundingContextMarkdown?: string;
    page?: number;
    bbox?: [number, number, number, number];
}

/** POST a selection-scoped AI fix request; returns the suggested replacement. */
export function refineDocumentWithAi(
    documentId: string,
    params: RefineAiParams,
): Promise<RefineAiResponse> {
    return api.post(
        `/library/documents/${documentId}/refine/ai`,
        {
            scope: params.scope,
            selection_markdown: params.selectionMarkdown,
            instruction: params.instruction,
            surrounding_context_markdown: params.surroundingContextMarkdown ?? null,
            page: params.page ?? null,
            bbox: params.bbox ?? null,
        },
        { schema: RefineAiResponseSchema },
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- src/lib/api/documents.test.ts`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api/documents.ts frontend/src/lib/api/documents.test.ts
git commit -m "feat(library): add document refinement API client methods"
```

---

## Task 4: Status helpers for the new pipeline statuses

`document-utils.ts` does not know `EXTRACTING`, `AWAITING_REFINEMENT`, or `INDEXING`. Without this, the library list/detail pages render the raw enum string and a wrong badge color.

**Files:**
- Modify: `frontend/src/lib/utils/document-utils.ts`
- Create: `frontend/src/lib/utils/document-utils.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/utils/document-utils.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';

import { getStatusColor, getStatusLabel } from './document-utils';

describe('document-utils new-pipeline statuses', () => {
    it('labels the docling pipeline statuses', () => {
        expect(getStatusLabel('EXTRACTING')).toBe('Extracting');
        expect(getStatusLabel('AWAITING_REFINEMENT')).toBe('Needs refinement');
        expect(getStatusLabel('INDEXING')).toBe('Indexing');
    });

    it('colors AWAITING_REFINEMENT as a warning, others as secondary/default', () => {
        expect(getStatusColor('AWAITING_REFINEMENT')).toBe('warning');
        expect(getStatusColor('EXTRACTING')).toBe('secondary');
        expect(getStatusColor('INDEXING')).toBe('secondary');
    });

    it('still handles legacy statuses', () => {
        expect(getStatusLabel('ENRICHED')).toBe('Ready');
        expect(getStatusColor('FAILED')).toBe('destructive');
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/lib/utils/document-utils.test.ts`
Expected: FAIL — `getStatusLabel('EXTRACTING')` returns `'EXTRACTING'`, not `'Extracting'`.

- [ ] **Step 3: Extend the status maps**

In `frontend/src/lib/utils/document-utils.ts`, replace the `STATUS_COLORS` constant:

```typescript
const STATUS_COLORS: Record<string, string> = {
    UPLOADED: 'secondary',
    QUEUED: 'secondary',
    PROCESSING: 'secondary',
    EXTRACTING: 'secondary',
    AWAITING_REFINEMENT: 'warning',
    INDEXING: 'secondary',
    INDEXED: 'default',
    ENRICHED: 'default',
    READY: 'default',
    FAILED: 'destructive',
};
```

In the same file, replace the `getStatusLabel` function:

```typescript
export function getStatusLabel(status: string): string {
    switch (status) {
        case 'UPLOADED':
            return 'Uploaded';
        case 'QUEUED':
            return 'Queued';
        case 'PROCESSING':
            return 'Processing';
        case 'EXTRACTING':
            return 'Extracting';
        case 'AWAITING_REFINEMENT':
            return 'Needs refinement';
        case 'INDEXING':
            return 'Indexing';
        case 'INDEXED':
        case 'ENRICHED':
        case 'READY':
            return 'Ready';
        case 'FAILED':
            return 'Failed';
        default:
            return status;
    }
}
```

Note: `getStatusColor` returns `'warning'` for `AWAITING_REFINEMENT`. The `Badge` component variant prop is typed loosely (`as any` is already used at the call sites), and a `warning` variant exists in `lib/components/ui/badge`. If `npm run check` later flags `warning` as an invalid `Badge` variant, fall back to `'secondary'` in `STATUS_COLORS` — do not invent a new badge variant.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- src/lib/utils/document-utils.test.ts`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/utils/document-utils.ts frontend/src/lib/utils/document-utils.test.ts
git commit -m "feat(library): teach document-utils the docling pipeline statuses"
```

---

## Task 5: Shared MarkdownDocument renderer

A read-only whole-document markdown → HTML renderer that rewrites relative image refs to absolute URLs. Distinct from the existing `MarkdownRenderer.svelte` (which is chunk-oriented and does plaintext heuristics) — this one renders trusted docling markdown for a single document.

**Files:**
- Create: `frontend/src/lib/components/shared/MarkdownDocument.svelte`
- Create: `frontend/src/lib/components/shared/MarkdownDocument.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/components/shared/MarkdownDocument.test.ts`:

```typescript
import { render } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import MarkdownDocument from './MarkdownDocument.svelte';

describe('MarkdownDocument', () => {
    it('renders markdown headings and paragraphs as HTML', () => {
        const { container } = render(MarkdownDocument, {
            props: { markdown: '# Batch Record\n\nProduct: mAb-X', documentId: 'doc-1' },
        });
        expect(container.querySelector('h1')?.textContent).toBe('Batch Record');
        expect(container.querySelector('p')?.textContent).toContain('mAb-X');
    });

    it('rewrites relative image refs to absolute API URLs', () => {
        const { container } = render(MarkdownDocument, {
            props: { markdown: '![Fig 1](images/2.png)', documentId: 'doc-1' },
        });
        const img = container.querySelector('img');
        expect(img?.getAttribute('src')).toContain(
            '/library/documents/doc-1/images/2.png',
        );
    });

    it('renders a table from GFM markdown', () => {
        const md = '| A | B |\n| --- | --- |\n| 1 | 2 |';
        const { container } = render(MarkdownDocument, {
            props: { markdown: md, documentId: 'doc-1' },
        });
        expect(container.querySelector('table')).not.toBeNull();
        expect(container.querySelectorAll('td')).toHaveLength(2);
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/lib/components/shared/MarkdownDocument.test.ts`
Expected: FAIL — cannot resolve `./MarkdownDocument.svelte`.

- [ ] **Step 3: Create the component**

Create `frontend/src/lib/components/shared/MarkdownDocument.svelte`:

```svelte
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- src/lib/components/shared/MarkdownDocument.test.ts`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/shared/MarkdownDocument.svelte frontend/src/lib/components/shared/MarkdownDocument.test.ts
git commit -m "feat(library): add shared MarkdownDocument read-only renderer"
```

---

## Task 6: RefinementSidebar — left rail

Source-page thumbnail (PDF only, via pymupdf endpoint) + a vertical extraction-status pipeline.

**Files:**
- Create: `frontend/src/lib/components/document-refinement/RefinementSidebar.svelte`
- Create: `frontend/src/lib/components/document-refinement/RefinementSidebar.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/components/document-refinement/RefinementSidebar.test.ts`:

```typescript
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import RefinementSidebar from './RefinementSidebar.svelte';

const BASE_PROPS = {
    documentId: 'doc-1',
    mimeType: 'application/pdf',
    pageCount: 3,
    status: 'AWAITING_REFINEMENT',
    sourceFormat: 'PDF',
    ocrEngine: 'easyocr',
};

describe('RefinementSidebar', () => {
    it('renders the source-page thumbnail for a PDF', () => {
        const { container } = render(RefinementSidebar, { props: BASE_PROPS });
        const img = container.querySelector('img');
        expect(img?.getAttribute('src')).toContain(
            '/library/documents/doc-1/source-page/1.png',
        );
    });

    it('advances the page when Next is clicked', async () => {
        const { container } = render(RefinementSidebar, { props: BASE_PROPS });
        await fireEvent.click(screen.getByRole('button', { name: /next page/i }));
        expect(container.querySelector('img')?.getAttribute('src')).toContain(
            '/source-page/2.png',
        );
    });

    it('does not render a thumbnail for a non-PDF source', () => {
        const { container } = render(RefinementSidebar, {
            props: { ...BASE_PROPS, mimeType: 'image/png', sourceFormat: 'IMAGE' },
        });
        expect(container.querySelector('img')).toBeNull();
    });

    it('marks the current pipeline step active from the status', () => {
        render(RefinementSidebar, { props: BASE_PROPS });
        const active = screen.getByText('Awaiting refinement').closest('li');
        expect(active?.getAttribute('data-active')).toBe('true');
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/lib/components/document-refinement/RefinementSidebar.test.ts`
Expected: FAIL — cannot resolve `./RefinementSidebar.svelte`.

- [ ] **Step 3: Create the component**

Create `frontend/src/lib/components/document-refinement/RefinementSidebar.svelte`:

```svelte
<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import { documentSourcePageUrl } from '$lib/api/documents';
    import { ChevronLeft, ChevronRight, Check } from 'lucide-svelte';

    interface Props {
        documentId: string;
        mimeType: string;
        pageCount: number | null | undefined;
        status: string;
        sourceFormat: string | null | undefined;
        ocrEngine: string | null | undefined;
    }

    let {
        documentId,
        mimeType,
        pageCount,
        status,
        sourceFormat,
        ocrEngine,
    }: Props = $props();

    const isPdf = $derived(mimeType === 'application/pdf');
    const totalPages = $derived(Math.max(1, pageCount ?? 1));

    let currentPage = $state(1);

    const thumbnailUrl = $derived(
        isPdf ? documentSourcePageUrl(documentId, currentPage) : null,
    );

    function prevPage(): void {
        if (currentPage > 1) currentPage -= 1;
    }
    function nextPage(): void {
        if (currentPage < totalPages) currentPage += 1;
    }

    /** Ordered pipeline; index of `status` decides what is done / active / pending. */
    const STEPS: { key: string; label: string }[] = [
        { key: 'UPLOADED', label: 'Uploaded' },
        { key: 'EXTRACTING', label: 'Extracting' },
        { key: 'AWAITING_REFINEMENT', label: 'Awaiting refinement' },
        { key: 'INDEXING', label: 'Indexing' },
        { key: 'READY', label: 'Ready' },
    ];

    /** Treat QUEUED like UPLOADED for pipeline display. */
    const normalizedStatus = $derived(status === 'QUEUED' ? 'UPLOADED' : status);
    const activeIndex = $derived(
        STEPS.findIndex((s) => s.key === normalizedStatus),
    );
</script>

<aside class="space-y-4">
    {#if isPdf && thumbnailUrl}
        <div class="rounded-lg border border-border bg-card p-3 shadow-sm">
            <div class="aspect-[3/4] w-full overflow-hidden rounded-md bg-muted">
                <img
                    src={thumbnailUrl}
                    alt="Source page {currentPage}"
                    class="h-full w-full object-contain"
                />
            </div>
            {#if totalPages > 1}
                <div class="mt-2 flex items-center justify-between">
                    <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Previous page"
                        disabled={currentPage <= 1}
                        onclick={prevPage}
                    >
                        <ChevronLeft class="h-4 w-4" />
                    </Button>
                    <span class="text-xs text-muted-foreground">
                        Page {currentPage} / {totalPages}
                    </span>
                    <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Next page"
                        disabled={currentPage >= totalPages}
                        onclick={nextPage}
                    >
                        <ChevronRight class="h-4 w-4" />
                    </Button>
                </div>
            {/if}
        </div>
    {/if}

    <div class="rounded-lg border border-border bg-card p-3 shadow-sm">
        <h2 class="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Extraction
        </h2>
        <ul class="space-y-1.5">
            {#each STEPS as step, i (step.key)}
                {@const isDone = activeIndex >= 0 && i < activeIndex}
                {@const isActive = i === activeIndex}
                <li
                    data-active={isActive}
                    class="flex items-center gap-2 text-sm {isActive
                        ? 'font-medium text-foreground'
                        : isDone
                          ? 'text-muted-foreground'
                          : 'text-muted-foreground/50'}"
                >
                    <span
                        class="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border {isActive
                            ? 'border-primary'
                            : isDone
                              ? 'border-primary bg-primary text-primary-foreground'
                              : 'border-border'}"
                    >
                        {#if isDone}
                            <Check class="h-3 w-3" />
                        {:else if isActive}
                            <span class="h-1.5 w-1.5 rounded-full bg-primary"></span>
                        {/if}
                    </span>
                    {step.label}
                </li>
            {/each}
        </ul>
        <dl class="mt-3 space-y-1 border-t border-border pt-2 text-xs text-muted-foreground">
            {#if sourceFormat}
                <div class="flex justify-between">
                    <dt>Format</dt>
                    <dd class="font-medium text-foreground">{sourceFormat}</dd>
                </div>
            {/if}
            {#if ocrEngine}
                <div class="flex justify-between">
                    <dt>OCR engine</dt>
                    <dd class="font-medium text-foreground">{ocrEngine}</dd>
                </div>
            {/if}
        </dl>
    </div>
</aside>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- src/lib/components/document-refinement/RefinementSidebar.test.ts`
Expected: PASS — 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/document-refinement/RefinementSidebar.svelte frontend/src/lib/components/document-refinement/RefinementSidebar.test.ts
git commit -m "feat(library): add RefinementSidebar — source thumbnail + status pipeline"
```

---

## Task 7: RefinementQueue — right rail flag list

Renders one item per `refinement_flags` entry; clicking a flag calls `onFlagClick`. Phase 1 always supplies `[]`, so the empty state is the common path.

**Files:**
- Create: `frontend/src/lib/components/document-refinement/RefinementQueue.svelte`
- Create: `frontend/src/lib/components/document-refinement/RefinementQueue.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/components/document-refinement/RefinementQueue.test.ts`:

```typescript
import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import type { RefinementFlag } from '$lib/schemas/documents';
import RefinementQueue from './RefinementQueue.svelte';

const FLAGS: RefinementFlag[] = [
    {
        id: 'flag-001',
        kind: 'low_confidence_ocr',
        confidence: 0.31,
        block_anchor: 'table-1.row-1.col-2',
        source_text: 'NaHzPO4119.98',
        page: 1,
    },
    {
        id: 'flag-002',
        kind: 'low_confidence_ocr',
        confidence: 0.48,
        source_text: 'Prepare0.8Lofwater',
        page: 2,
    },
];

describe('RefinementQueue', () => {
    it('renders the empty state when there are no flags', () => {
        render(RefinementQueue, {
            props: { flags: [], activeFlagId: null, onFlagClick: vi.fn() },
        });
        expect(screen.getByText(/no flags/i)).toBeTruthy();
    });

    it('renders one item per flag with the flag count', () => {
        render(RefinementQueue, {
            props: { flags: FLAGS, activeFlagId: null, onFlagClick: vi.fn() },
        });
        expect(screen.getByText('2')).toBeTruthy();
        expect(screen.getByText('NaHzPO4119.98')).toBeTruthy();
        expect(screen.getByText('Prepare0.8Lofwater')).toBeTruthy();
    });

    it('calls onFlagClick with the flag when an item is clicked', async () => {
        const onFlagClick = vi.fn();
        render(RefinementQueue, {
            props: { flags: FLAGS, activeFlagId: null, onFlagClick },
        });
        await fireEvent.click(screen.getByText('NaHzPO4119.98'));
        expect(onFlagClick).toHaveBeenCalledWith(FLAGS[0]);
    });

    it('marks the active flag', () => {
        render(RefinementQueue, {
            props: { flags: FLAGS, activeFlagId: 'flag-002', onFlagClick: vi.fn() },
        });
        const active = screen.getByText('Prepare0.8Lofwater').closest('button');
        expect(active?.getAttribute('data-active')).toBe('true');
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/lib/components/document-refinement/RefinementQueue.test.ts`
Expected: FAIL — cannot resolve `./RefinementQueue.svelte`.

- [ ] **Step 3: Create the component**

Create `frontend/src/lib/components/document-refinement/RefinementQueue.svelte`:

```svelte
<script lang="ts">
    import { Badge } from '$lib/components/ui/badge';
    import { CheckCircle2 } from 'lucide-svelte';
    import type { RefinementFlag } from '$lib/schemas/documents';

    interface Props {
        flags: RefinementFlag[];
        activeFlagId: string | null;
        onFlagClick: (flag: RefinementFlag) => void;
    }

    let { flags, activeFlagId, onFlagClick }: Props = $props();

    function confidencePercent(flag: RefinementFlag): string | null {
        if (flag.confidence == null) return null;
        return `${Math.round(flag.confidence * 100)}%`;
    }
</script>

<div class="rounded-lg border border-border bg-card shadow-sm">
    <div class="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 class="text-sm font-semibold">Refinement queue</h2>
        {#if flags.length > 0}
            <Badge variant="secondary">{flags.length}</Badge>
        {/if}
    </div>

    {#if flags.length === 0}
        <div class="flex flex-col items-center gap-2 px-3 py-8 text-center">
            <CheckCircle2 class="h-6 w-6 text-muted-foreground/60" />
            <p class="text-sm text-muted-foreground">
                No flags — extraction looks clean.
            </p>
        </div>
    {:else}
        <ul class="divide-y divide-border">
            {#each flags as flag (flag.id)}
                <li>
                    <button
                        type="button"
                        data-active={flag.id === activeFlagId}
                        class="w-full cursor-pointer px-3 py-2 text-left transition-colors duration-150 hover:bg-muted/60 {flag.id ===
                        activeFlagId
                            ? 'bg-amber-50'
                            : ''}"
                        onclick={() => onFlagClick(flag)}
                    >
                        <div class="flex items-center justify-between gap-2">
                            <span class="text-xs font-medium text-muted-foreground">
                                {flag.kind.replace(/_/g, ' ')}
                            </span>
                            <span class="flex items-center gap-1.5 text-xs text-muted-foreground">
                                {#if confidencePercent(flag)}
                                    <span>{confidencePercent(flag)}</span>
                                {/if}
                                {#if flag.page != null}
                                    <span>p.{flag.page}</span>
                                {/if}
                            </span>
                        </div>
                        {#if flag.source_text}
                            <p class="mt-1 break-words font-mono text-sm text-foreground">
                                {flag.source_text}
                            </p>
                        {/if}
                    </button>
                </li>
            {/each}
        </ul>
    {/if}
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- src/lib/components/document-refinement/RefinementQueue.test.ts`
Expected: PASS — 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/document-refinement/RefinementQueue.svelte frontend/src/lib/components/document-refinement/RefinementQueue.test.ts
git commit -m "feat(library): add RefinementQueue flag list component"
```

---

## Task 8: RefinementAiPanel — selection-scoped AI fix

Prompt area + scope chip + submit → side-by-side diff → Accept/Reject. Calls `refineDocumentWithAi`.

**Files:**
- Create: `frontend/src/lib/components/document-refinement/RefinementAiPanel.svelte`
- Create: `frontend/src/lib/components/document-refinement/RefinementAiPanel.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/components/document-refinement/RefinementAiPanel.test.ts`:

```typescript
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

import RefinementAiPanel from './RefinementAiPanel.svelte';
import * as documentsApi from '$lib/api/documents';

const SELECTION = {
    scope: 'selection' as const,
    markdown: 'NaHzPO4119.98',
    context: 'Add NaHzPO4119.98 to the buffer',
};

describe('RefinementAiPanel', () => {
    afterEach(() => vi.restoreAllMocks());

    it('shows a hint when there is no selection', () => {
        render(RefinementAiPanel, {
            props: {
                documentId: 'doc-1',
                selection: null,
                onAccept: vi.fn(),
                onCancel: vi.fn(),
            },
        });
        expect(screen.getByText(/select text/i)).toBeTruthy();
    });

    it('submits the instruction and renders the suggested diff', async () => {
        const spy = vi
            .spyOn(documentsApi, 'refineDocumentWithAi')
            .mockResolvedValue({
                suggested_markdown: 'NaH2PO4 119.98',
                model_used: 'claude-sonnet-4-6',
            });
        render(RefinementAiPanel, {
            props: {
                documentId: 'doc-1',
                selection: SELECTION,
                onAccept: vi.fn(),
                onCancel: vi.fn(),
            },
        });
        await fireEvent.input(screen.getByPlaceholderText(/how should/i), {
            target: { value: 'fix the formula spacing' },
        });
        await fireEvent.click(screen.getByRole('button', { name: /ask ai/i }));

        await waitFor(() => expect(screen.getByText('NaH2PO4 119.98')).toBeTruthy());
        expect(spy).toHaveBeenCalledWith('doc-1', {
            scope: 'selection',
            selectionMarkdown: 'NaHzPO4119.98',
            instruction: 'fix the formula spacing',
            surroundingContextMarkdown: 'Add NaHzPO4119.98 to the buffer',
        });
    });

    it('calls onAccept with the suggestion when Accept is clicked', async () => {
        vi.spyOn(documentsApi, 'refineDocumentWithAi').mockResolvedValue({
            suggested_markdown: 'NaH2PO4 119.98',
            model_used: 'claude-sonnet-4-6',
        });
        const onAccept = vi.fn();
        render(RefinementAiPanel, {
            props: { documentId: 'doc-1', selection: SELECTION, onAccept, onCancel: vi.fn() },
        });
        await fireEvent.input(screen.getByPlaceholderText(/how should/i), {
            target: { value: 'fix it' },
        });
        await fireEvent.click(screen.getByRole('button', { name: /ask ai/i }));
        await waitFor(() => screen.getByText('NaH2PO4 119.98'));
        await fireEvent.click(screen.getByRole('button', { name: /accept/i }));
        expect(onAccept).toHaveBeenCalledWith('NaH2PO4 119.98');
    });

    it('surfaces an error when the AI call fails', async () => {
        vi.spyOn(documentsApi, 'refineDocumentWithAi').mockRejectedValue(
            new Error('model unavailable'),
        );
        render(RefinementAiPanel, {
            props: {
                documentId: 'doc-1',
                selection: SELECTION,
                onAccept: vi.fn(),
                onCancel: vi.fn(),
            },
        });
        await fireEvent.input(screen.getByPlaceholderText(/how should/i), {
            target: { value: 'fix it' },
        });
        await fireEvent.click(screen.getByRole('button', { name: /ask ai/i }));
        await waitFor(() => expect(screen.getByText(/model unavailable/i)).toBeTruthy());
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/lib/components/document-refinement/RefinementAiPanel.test.ts`
Expected: FAIL — cannot resolve `./RefinementAiPanel.svelte`.

- [ ] **Step 3: Create the component**

Create `frontend/src/lib/components/document-refinement/RefinementAiPanel.svelte`:

```svelte
<script lang="ts">
    import { Button } from '$lib/components/ui/button';
    import { Sparkles } from 'lucide-svelte';
    import { refineDocumentWithAi } from '$lib/api/documents';

    /** A region the user wants the AI to fix. */
    export interface AiSelection {
        scope: 'selection' | 'block' | 'document';
        markdown: string;
        context: string;
        page?: number;
        bbox?: [number, number, number, number];
    }

    interface Props {
        documentId: string;
        selection: AiSelection | null;
        onAccept: (suggestedMarkdown: string) => void;
        onCancel: () => void;
    }

    let { documentId, selection, onAccept, onCancel }: Props = $props();

    let instruction = $state('');
    let loading = $state(false);
    let error = $state<string | null>(null);
    let suggestion = $state<string | null>(null);

    const SCOPES: AiSelection['scope'][] = ['selection', 'block', 'document'];
    // Scope chip mirrors the incoming selection but stays user-overridable.
    let scope = $state<AiSelection['scope']>('selection');
    $effect(() => {
        if (selection) scope = selection.scope;
    });

    async function submit(): Promise<void> {
        if (!selection || !instruction.trim()) return;
        loading = true;
        error = null;
        suggestion = null;
        try {
            const res = await refineDocumentWithAi(documentId, {
                scope,
                selectionMarkdown: selection.markdown,
                instruction: instruction.trim(),
                surroundingContextMarkdown: selection.context || undefined,
                page: selection.page,
                bbox: selection.bbox,
            });
            suggestion = res.suggested_markdown;
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'AI request failed';
        } finally {
            loading = false;
        }
    }

    function accept(): void {
        if (suggestion != null) onAccept(suggestion);
        reset();
    }

    function reject(): void {
        reset();
        onCancel();
    }

    function reset(): void {
        instruction = '';
        suggestion = null;
        error = null;
    }
</script>

<div class="rounded-lg border border-border bg-card shadow-sm">
    <div class="flex items-center gap-2 border-b border-border px-3 py-2">
        <Sparkles class="h-4 w-4 text-violet-500" />
        <h2 class="text-sm font-semibold">AI fix</h2>
    </div>

    <div class="space-y-3 p-3">
        {#if !selection}
            <p class="text-sm text-muted-foreground">
                Select text in the document or click a flag to target an AI fix.
            </p>
        {:else}
            <div class="flex gap-1.5">
                {#each SCOPES as s (s)}
                    <button
                        type="button"
                        class="cursor-pointer rounded-full px-2.5 py-0.5 text-xs capitalize transition-colors duration-150 {scope ===
                        s
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-muted text-muted-foreground hover:bg-muted/70'}"
                        onclick={() => (scope = s)}
                    >
                        {s}
                    </button>
                {/each}
            </div>

            <div class="rounded-md bg-muted/60 p-2">
                <p class="break-words font-mono text-xs text-foreground">
                    {selection.markdown}
                </p>
            </div>

            <textarea
                class="w-full resize-none rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                rows="2"
                placeholder="How should the AI fix this?"
                bind:value={instruction}
            ></textarea>

            <Button
                size="sm"
                class="w-full"
                disabled={loading || !instruction.trim()}
                onclick={submit}
            >
                {loading ? 'Asking AI…' : 'Ask AI'}
            </Button>

            {#if error}
                <p class="text-sm text-destructive">{error}</p>
            {/if}

            {#if suggestion != null}
                <div class="space-y-2 rounded-md border border-violet-200 bg-violet-50 p-2">
                    <div>
                        <p class="text-xs font-medium text-muted-foreground">Original</p>
                        <p class="break-words font-mono text-xs text-foreground line-through decoration-destructive/60">
                            {selection.markdown}
                        </p>
                    </div>
                    <div>
                        <p class="text-xs font-medium text-muted-foreground">Suggested</p>
                        <p class="break-words font-mono text-xs text-foreground">
                            {suggestion}
                        </p>
                    </div>
                    <div class="flex gap-2 pt-1">
                        <Button size="sm" class="flex-1" onclick={accept}>Accept</Button>
                        <Button
                            size="sm"
                            variant="outline"
                            class="flex-1"
                            onclick={reject}
                        >
                            Reject
                        </Button>
                    </div>
                </div>
            {/if}
        {/if}
    </div>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- src/lib/components/document-refinement/RefinementAiPanel.test.ts`
Expected: PASS — 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/document-refinement/RefinementAiPanel.svelte frontend/src/lib/components/document-refinement/RefinementAiPanel.test.ts
git commit -m "feat(library): add RefinementAiPanel selection-scoped AI fix panel"
```

---

## Task 9: RefinementEditor — center Tiptap wrapper

A thin wrapper around `edra`'s `EdraEditor` + `EdraToolBar`. It feeds display-markdown in, exposes `getMarkdown()` / `applyToSelection()` / `scrollToAnchor()` as bindable functions, and emits `onUpdate` + `onSelectionChange`. `edra` is dynamically imported (matching `experiments/[id]/+page.svelte`), which also keeps it out of the jsdom test path — the test mocks the module.

**Files:**
- Create: `frontend/src/lib/components/document-refinement/RefinementEditor.svelte`
- Create: `frontend/src/lib/components/document-refinement/RefinementEditor.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/components/document-refinement/RefinementEditor.test.ts`:

```typescript
import { render, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

// Mock the edra barrel so the component mounts without a real Tiptap instance.
vi.mock('$lib/components/edra/shadcn', () => ({
    EdraEditor: (() => {}) as unknown,
    EdraToolBar: (() => {}) as unknown,
}));

import RefinementEditor from './RefinementEditor.svelte';

describe('RefinementEditor', () => {
    it('renders a container and loads the edra module', async () => {
        const { container } = render(RefinementEditor, {
            props: {
                documentId: 'doc-1',
                initialMarkdown: '# Hello\n\n![f](images/1.png)',
            },
        });
        await waitFor(() =>
            expect(container.querySelector('.refinement-editor')).not.toBeNull(),
        );
    });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- src/lib/components/document-refinement/RefinementEditor.test.ts`
Expected: FAIL — cannot resolve `./RefinementEditor.svelte`.

- [ ] **Step 3: Create the component**

Create `frontend/src/lib/components/document-refinement/RefinementEditor.svelte`:

```svelte
<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import type { Editor } from '@tiptap/core';
    import { getToken } from '$lib/auth.svelte';
    import { toDisplayMarkdown } from '$lib/utils/document-markdown';

    interface SelectionPayload {
        markdown: string;
        context: string;
    }

    interface Props {
        documentId: string;
        /** Stored markdown (relative image refs) — rewritten to display form on mount. */
        initialMarkdown: string;
        editable?: boolean;
        /** Fired on every editor change. */
        onUpdate?: () => void;
        /** Fired when the user changes the text selection. */
        onSelectionChange?: (payload: SelectionPayload) => void;
        /** Bindable: returns current editor markdown in DISPLAY form (absolute image URLs). */
        getMarkdown?: () => string;
        /** Bindable: replaces the current selection with the given markdown. */
        applyToSelection?: (markdown: string) => void;
        /** Bindable: best-effort scroll to a flagged block by anchor. */
        scrollToAnchor?: (anchor: string) => void;
    }

    let {
        documentId,
        initialMarkdown,
        editable = true,
        onUpdate,
        onSelectionChange,
        getMarkdown = $bindable(),
        applyToSelection = $bindable(),
        scrollToAnchor = $bindable(),
    }: Props = $props();

    // Dynamically imported edra components (kept out of the base bundle / jsdom).
    let EdraEditor = $state<unknown>(null);
    let EdraToolBar = $state<unknown>(null);
    let editor = $state<Editor>();

    const displayMarkdown = toDisplayMarkdown(
        initialMarkdown,
        documentId,
        getToken(),
    );

    onMount(async () => {
        const edra = await import('$lib/components/edra/shadcn');
        EdraEditor = edra.EdraEditor;
        EdraToolBar = edra.EdraToolBar;
    });

    // Wire the bindable bridge + selection listener once the editor exists.
    $effect(() => {
        if (!editor) return;
        const ed = editor;

        getMarkdown = () => ed.storage.markdown.getMarkdown() as string;

        applyToSelection = (markdown: string) => {
            // AI suggestions may carry relative image refs — normalise to display form.
            const display = toDisplayMarkdown(markdown, documentId, getToken());
            ed.chain().focus().insertContent(display).run();
        };

        scrollToAnchor = (anchor: string) => {
            // Forward-compat: Phase 1 emits no flags, so no anchored nodes exist yet.
            const el = ed.view.dom.querySelector(`[data-anchor="${anchor}"]`);
            if (el instanceof HTMLElement) {
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        };

        const handleSelection = () => {
            const { from, to } = ed.state.selection;
            const markdown = ed.state.doc.textBetween(from, to, '\n');
            const before = ed.state.doc.textBetween(Math.max(0, from - 200), from, '\n');
            const after = ed.state.doc.textBetween(
                to,
                Math.min(ed.state.doc.content.size, to + 200),
                '\n',
            );
            onSelectionChange?.({ markdown, context: `${before}${markdown}${after}` });
        };
        ed.on('selectionUpdate', handleSelection);
        return () => ed.off('selectionUpdate', handleSelection);
    });

    onDestroy(() => {
        if (editor && !editor.isDestroyed) editor.destroy();
    });
</script>

<div class="refinement-editor flex h-full flex-col rounded-lg border border-border bg-card shadow-sm">
    {#if EdraEditor && EdraToolBar}
        <svelte:component
            this={EdraToolBar}
            {editor}
            class="border-b border-border"
        />
        <div class="min-h-0 flex-1 overflow-y-auto">
            <svelte:component
                this={EdraEditor}
                bind:editor
                content={displayMarkdown}
                {editable}
                {onUpdate}
                class="p-6"
            />
        </div>
    {:else}
        <div class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            Loading editor…
        </div>
    {/if}
</div>
```

Note on `content={displayMarkdown}`: `edra` configures the `tiptap-markdown` extension, which parses a plain string `content` as markdown when the editor initialises. `getMarkdown()` reads it back via `editor.storage.markdown.getMarkdown()`. `insertContent` with a markdown string is likewise parsed by `tiptap-markdown`. If, during integration in Task 10, the editor renders the raw markdown string verbatim instead of parsed HTML, the fix is to parse explicitly before mount — `edra.EdraEditor` accepts Tiptap JSON too — but verify the string path first; it is the documented `tiptap-markdown` behaviour.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- src/lib/components/document-refinement/RefinementEditor.test.ts`
Expected: PASS — 1 test. (The mocked edra components never become truthy in the way the real ones do, but the `.refinement-editor` container always renders, which is what the test asserts.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/document-refinement/RefinementEditor.svelte frontend/src/lib/components/document-refinement/RefinementEditor.test.ts
git commit -m "feat(library): add RefinementEditor Tiptap wrapper with markdown round-trip"
```

---

## Task 10: The refinement route

`/library/documents/[id]/refine` — orchestrates the three columns, save (explicit + 8 s idle autosave), the "saved N sec ago" indicator, the `beforeunload` guard, the EXTRACTING wait state, and the "Mark refinement complete" dialog.

**Files:**
- Create: `frontend/src/routes/library/documents/[id]/refine/+page.svelte`

- [ ] **Step 1: Create the route page**

Create `frontend/src/routes/library/documents/[id]/refine/+page.svelte`:

```svelte
<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { fade } from 'svelte/transition';
    import { toast } from 'svelte-sonner';
    import { ArrowLeft, Check, Save } from 'lucide-svelte';
    import { api } from '$lib/api';
    import { Button } from '$lib/components/ui/button';
    import * as Dialog from '$lib/components/ui/dialog';
    import LoadingSpinner from '$lib/components/ui/loading-spinner.svelte';
    import ErrorAlert from '$lib/components/ui/error-alert.svelte';
    import { blockDuration } from '$lib/transitions';
    import {
        DocumentResponseSchema,
        type DocumentResponse,
        type RefinementFlag,
    } from '$lib/schemas/documents';
    import {
        completeDocumentRefinement,
        getDocumentMarkdown,
        updateDocumentMarkdown,
    } from '$lib/api/documents';
    import { toStoredMarkdown } from '$lib/utils/document-markdown';
    import RefinementSidebar from '$lib/components/document-refinement/RefinementSidebar.svelte';
    import RefinementQueue from '$lib/components/document-refinement/RefinementQueue.svelte';
    import RefinementAiPanel, {
        type AiSelection,
    } from '$lib/components/document-refinement/RefinementAiPanel.svelte';
    import RefinementEditor from '$lib/components/document-refinement/RefinementEditor.svelte';

    const documentId = $derived($page.params.id);

    let doc = $state<DocumentResponse | null>(null);
    let initialMarkdown = $state('');
    let loading = $state(true);
    let error = $state<string | null>(null);
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    // Editor bridge (bound from RefinementEditor).
    let getMarkdown = $state<(() => string) | undefined>(undefined);
    let applyToSelection = $state<((md: string) => void) | undefined>(undefined);
    let scrollToAnchor = $state<((anchor: string) => void) | undefined>(undefined);

    // Save state.
    let saving = $state(false);
    let hasUnsavedChanges = $state(false);
    let lastSavedAt = $state<Date | null>(null);
    let savedAgoLabel = $state('');
    let autosaveTimer: ReturnType<typeof setTimeout> | null = null;
    let agoTimer: ReturnType<typeof setInterval> | null = null;

    // Right rail state.
    let aiSelection = $state<AiSelection | null>(null);
    let activeFlagId = $state<string | null>(null);

    // Complete dialog.
    let completeDialogOpen = $state(false);
    let completing = $state(false);

    const flags = $derived<RefinementFlag[]>(doc?.refinement_flags ?? []);
    const isExtracting = $derived(
        doc != null &&
            ['UPLOADED', 'QUEUED', 'EXTRACTING'].includes(doc.status),
    );
    const isFailed = $derived(doc?.status === 'FAILED');
    const alreadyDone = $derived(
        doc != null &&
            (doc.refinement_status === 'COMPLETE' ||
                ['INDEXING', 'READY', 'INDEXED', 'ENRICHED'].includes(doc.status)),
    );

    async function load(): Promise<void> {
        try {
            const fetched = await api.get(`/library/documents/${documentId}`, {
                schema: DocumentResponseSchema,
            });
            doc = fetched;

            if (
                fetched.status === 'AWAITING_REFINEMENT' &&
                initialMarkdown === ''
            ) {
                const md = await getDocumentMarkdown(documentId);
                initialMarkdown = md.markdown;
            }

            // Refinement already finished elsewhere — send the user to the viewer.
            if (alreadyDone) {
                goto(`/library/${documentId}`);
                return;
            }

            // Poll while extraction is still running.
            const stillExtracting = ['UPLOADED', 'QUEUED', 'EXTRACTING'].includes(
                fetched.status,
            );
            if (stillExtracting && !pollTimer) {
                pollTimer = setInterval(load, 3000);
            } else if (!stillExtracting && pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Failed to load document';
        } finally {
            loading = false;
        }
    }

    async function save(): Promise<void> {
        if (!getMarkdown || saving) return;
        saving = true;
        try {
            const stored = toStoredMarkdown(getMarkdown(), documentId);
            await updateDocumentMarkdown(documentId, stored);
            hasUnsavedChanges = false;
            lastSavedAt = new Date();
            updateSavedAgo();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Save failed');
        } finally {
            saving = false;
        }
    }

    function handleEditorUpdate(): void {
        hasUnsavedChanges = true;
        if (autosaveTimer) clearTimeout(autosaveTimer);
        autosaveTimer = setTimeout(() => {
            void save();
        }, 8000);
    }

    function updateSavedAgo(): void {
        if (!lastSavedAt) {
            savedAgoLabel = '';
            return;
        }
        const secs = Math.round((Date.now() - lastSavedAt.getTime()) / 1000);
        if (secs < 5) savedAgoLabel = 'saved just now';
        else if (secs < 60) savedAgoLabel = `saved ${secs} sec ago`;
        else savedAgoLabel = `saved ${Math.round(secs / 60)} min ago`;
    }

    function handleSelectionChange(payload: {
        markdown: string;
        context: string;
    }): void {
        if (payload.markdown.trim()) {
            aiSelection = {
                scope: 'selection',
                markdown: payload.markdown,
                context: payload.context,
            };
            activeFlagId = null;
        }
    }

    function handleFlagClick(flag: RefinementFlag): void {
        activeFlagId = flag.id;
        if (flag.block_anchor) scrollToAnchor?.(flag.block_anchor);
        if (flag.source_text) {
            aiSelection = {
                scope: 'block',
                markdown: flag.source_text,
                context: flag.source_text,
                page: flag.page ?? undefined,
                bbox: (flag.bbox as [number, number, number, number]) ?? undefined,
            };
        }
    }

    function handleAiAccept(suggested: string): void {
        applyToSelection?.(suggested);
        aiSelection = null;
        activeFlagId = null;
        handleEditorUpdate();
    }

    function handleAiCancel(): void {
        aiSelection = null;
        activeFlagId = null;
    }

    async function handleComplete(): Promise<void> {
        completing = true;
        try {
            if (hasUnsavedChanges) await save();
            await completeDocumentRefinement(documentId);
            toast.success('Refinement complete — indexing started');
            completeDialogOpen = false;
            hasUnsavedChanges = false;
            goto(`/library/${documentId}`);
        } catch (e: unknown) {
            toast.error(
                e instanceof Error ? e.message : 'Could not complete refinement',
            );
        } finally {
            completing = false;
        }
    }

    function beforeUnload(e: BeforeUnloadEvent): void {
        if (hasUnsavedChanges) {
            e.preventDefault();
            e.returnValue = '';
        }
    }

    onMount(() => {
        void load();
        window.addEventListener('beforeunload', beforeUnload);
        agoTimer = setInterval(updateSavedAgo, 5000);
    });
    onDestroy(() => {
        if (pollTimer) clearInterval(pollTimer);
        if (autosaveTimer) clearTimeout(autosaveTimer);
        if (agoTimer) clearInterval(agoTimer);
        window.removeEventListener('beforeunload', beforeUnload);
    });
</script>

<div class="mx-auto max-w-[1600px] space-y-4 px-4 py-4">
    <a
        href="/library/{documentId}"
        class="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
        <ArrowLeft class="h-4 w-4" />
        Back to document
    </a>

    {#if loading}
        <div in:fade={{ duration: blockDuration() }}>
            <LoadingSpinner message="Loading document…" />
        </div>
    {:else if error}
        <div in:fade={{ duration: blockDuration() }}>
            <ErrorAlert message="Error: {error}" />
        </div>
    {:else if isFailed}
        <div in:fade={{ duration: blockDuration() }}>
            <ErrorAlert
                message="Extraction failed: {doc?.error_message ??
                    'unknown error'}"
            />
        </div>
    {:else if isExtracting}
        <div
            in:fade={{ duration: blockDuration() }}
            class="rounded-md border border-amber-200 bg-amber-50 p-6 text-amber-800"
        >
            <div class="flex items-center gap-3">
                <div
                    class="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-amber-600 border-t-transparent"
                ></div>
                <span class="text-sm font-medium">
                    Extracting document — this page will update automatically.
                </span>
            </div>
        </div>
    {:else if doc}
        <!-- Toolbar -->
        <div
            in:fade={{ duration: blockDuration() }}
            class="flex flex-wrap items-center justify-between gap-3"
        >
            <div>
                <h1 class="text-xl font-bold tracking-tight">{doc.title}</h1>
                <p class="text-xs text-muted-foreground">
                    Review the extracted text, fix any artifacts, then mark
                    refinement complete.
                </p>
            </div>
            <div class="flex items-center gap-3">
                <span class="text-xs text-muted-foreground">
                    {#if saving}
                        Saving…
                    {:else if hasUnsavedChanges}
                        Unsaved changes
                    {:else if savedAgoLabel}
                        {savedAgoLabel}
                    {/if}
                </span>
                <Button
                    variant="outline"
                    size="sm"
                    disabled={saving || !hasUnsavedChanges}
                    onclick={() => save()}
                >
                    <Save class="mr-2 h-4 w-4" />
                    Save
                </Button>
                <Button size="sm" onclick={() => (completeDialogOpen = true)}>
                    <Check class="mr-2 h-4 w-4" />
                    Mark refinement complete
                </Button>
            </div>
        </div>

        <!-- Three-column workspace -->
        <div class="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)_320px]">
            <RefinementSidebar
                documentId={doc.id}
                mimeType={doc.mime_type}
                pageCount={doc.page_count}
                status={doc.status}
                sourceFormat={doc.source_format}
                ocrEngine={doc.doc_metadata?.ocr_engine as string | undefined}
            />

            <div class="min-h-[60vh] lg:h-[calc(100vh-12rem)]">
                <RefinementEditor
                    documentId={doc.id}
                    {initialMarkdown}
                    onUpdate={handleEditorUpdate}
                    onSelectionChange={handleSelectionChange}
                    bind:getMarkdown
                    bind:applyToSelection
                    bind:scrollToAnchor
                />
            </div>

            <div class="space-y-4">
                <RefinementQueue
                    {flags}
                    {activeFlagId}
                    onFlagClick={handleFlagClick}
                />
                <RefinementAiPanel
                    documentId={doc.id}
                    selection={aiSelection}
                    onAccept={handleAiAccept}
                    onCancel={handleAiCancel}
                />
            </div>
        </div>
    {/if}
</div>

<Dialog.Root bind:open={completeDialogOpen}>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>Mark refinement complete?</Dialog.Title>
            <Dialog.Description>
                Indexing will begin and the document becomes searchable. You can
                re-open refinement later from the document page if needed.
            </Dialog.Description>
        </Dialog.Header>
        <Dialog.Footer>
            <Button
                variant="outline"
                onclick={() => (completeDialogOpen = false)}
                disabled={completing}
            >
                Cancel
            </Button>
            <Button onclick={handleComplete} disabled={completing}>
                {completing ? 'Finishing…' : 'Mark complete'}
            </Button>
        </Dialog.Footer>
    </Dialog.Footer>
</Dialog.Root>
```

Note: the `doc_metadata.ocr_engine` access — Phase 1 stores `ocr_engine` as a column on `Document`, but `DocumentResponse` does not expose it as a top-level field; it is available via `doc_metadata` only if the backend put it there. If `npm run check` in Task 13 shows `ocr_engine` is reliably absent, pass `ocrEngine={undefined}` instead — `RefinementSidebar` already treats it as optional. Do not add a backend change for this; it is cosmetic.

- [ ] **Step 2: Fix the stray closing tag**

The `Dialog.Root` block above ends with `</Dialog.Footer>` twice — the outer should be `</Dialog.Content>` then `</Dialog.Root>`. Correct the last three lines of the file so they read:

```svelte
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
```

- [ ] **Step 3: Type-check the route**

Run: `npm run check`
Expected: PASS, or only pre-existing warnings unrelated to these files. Fix any error originating in `refine/+page.svelte` or the components — common culprits: a bindable function prop typed too narrowly, or the `ocr_engine` access flagged above.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/library/documents/[id]/refine/+page.svelte
git commit -m "feat(library): add /library/documents/[id]/refine route"
```

---

## Task 11: Wire the route into the library list and detail pages

Give users a way to reach the editor: a "Needs refinement" affordance in the list and a "Refine document" button on the detail page.

**Files:**
- Modify: `frontend/src/routes/library/+page.svelte`
- Modify: `frontend/src/routes/library/[id]/+page.svelte`

- [ ] **Step 1: Add a Refine link to the list table**

In `frontend/src/routes/library/+page.svelte`, in the desktop table's Actions cell, replace this block:

```svelte
                                        <Table.Cell class="text-right">
                                            <a href="/library/{doc.id}">
                                                <Button variant="ghost" size="sm">View</Button>
                                            </a>
                                        </Table.Cell>
```

with:

```svelte
                                        <Table.Cell class="text-right">
                                            {#if doc.status === 'AWAITING_REFINEMENT'}
                                                <a href="/library/documents/{doc.id}/refine">
                                                    <Button variant="outline" size="sm">Refine</Button>
                                                </a>
                                            {:else}
                                                <a href="/library/{doc.id}">
                                                    <Button variant="ghost" size="sm">View</Button>
                                                </a>
                                            {/if}
                                        </Table.Cell>
```

- [ ] **Step 2: Poll the list while documents are extracting**

In the same file, in `loadDocuments()`, replace this line:

```typescript
            const hasProcessing = documents.some((d) => d.status === 'PROCESSING');
```

with:

```typescript
            const inFlightStatuses = ['PROCESSING', 'QUEUED', 'EXTRACTING', 'INDEXING'];
            const hasProcessing = documents.some((d) =>
                inFlightStatuses.includes(d.status),
            );
```

(The existing `getStatusLabel`/`getStatusColor` in the list's badges already render `AWAITING_REFINEMENT` correctly thanks to Task 4 — no badge change needed here.)

- [ ] **Step 3: Add a Refine button to the detail page action bar**

In `frontend/src/routes/library/[id]/+page.svelte`, in the `<!-- Action bar -->` block, add a new button as the first child of the `<div class="flex items-center gap-2">`, before the `FAILED/QUEUED` retry button:

```svelte
        <!-- Action bar -->
        <div class="flex items-center gap-2">
            {#if document.status === 'AWAITING_REFINEMENT'}
                <a href="/library/documents/{document.id}/refine">
                    <Button size="sm">
                        Refine document
                    </Button>
                </a>
            {/if}
            {#if document.status === 'FAILED' || document.status === 'QUEUED'}
```

(Leave the rest of the action bar unchanged.)

- [ ] **Step 4: Add an extraction-in-progress banner to the detail page**

In `frontend/src/routes/library/[id]/+page.svelte`, immediately after the `<!-- Queued banner -->` `{#if document.status === 'QUEUED'} … {/if}` block, add:

```svelte
        <!-- Extraction / awaiting-refinement banner -->
        {#if document.status === 'EXTRACTING'}
            <div class="bg-amber-50 border border-amber-200 text-amber-800 p-4 rounded-md">
                <div class="flex items-center gap-3">
                    <div class="w-4 h-4 border-2 border-amber-600 border-t-transparent rounded-full animate-spin shrink-0"></div>
                    <span class="text-sm font-medium">Extracting document content…</span>
                </div>
            </div>
        {:else if document.status === 'AWAITING_REFINEMENT'}
            <div class="bg-amber-50 border border-amber-200 text-amber-800 p-4 rounded-md">
                <p class="text-sm font-medium">This document needs refinement before it can be searched.</p>
                <p class="text-xs text-amber-700/70 mt-1">
                    Open the refinement editor to review the extracted text and fix any artifacts.
                </p>
            </div>
        {/if}
```

- [ ] **Step 5: Poll the detail page while extracting**

In `frontend/src/routes/library/[id]/+page.svelte`, in `loadDocument()`, replace this line:

```typescript
            const shouldPoll = doc.status === 'PROCESSING' || doc.status === 'QUEUED' || (doc.status === 'INDEXED' && hasActiveProgress);
```

with:

```typescript
            const shouldPoll =
                doc.status === 'PROCESSING' ||
                doc.status === 'QUEUED' ||
                doc.status === 'EXTRACTING' ||
                doc.status === 'INDEXING' ||
                (doc.status === 'INDEXED' && hasActiveProgress);
```

- [ ] **Step 6: Type-check**

Run: `npm run check`
Expected: PASS (or only pre-existing unrelated warnings).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/library/+page.svelte frontend/src/routes/library/[id]/+page.svelte
git commit -m "feat(library): surface the refinement editor from the library list and detail pages"
```

---

## Task 12: Document the new component bucket

**Files:**
- Modify: `.claude/rules/conventions.md`

- [ ] **Step 1: Add the bucket to the component-placement list**

In `.claude/rules/conventions.md`, in the `### Component placement` section's bucket list, add this line immediately after the `- \`ai/\` — chat and agent UX` line:

```markdown
- `document-refinement/` — the library document refinement editor (Tiptap canvas wrapper, source/status sidebar, flag queue, AI-fix panel)
```

- [ ] **Step 2: Commit**

```bash
git add .claude/rules/conventions.md
git commit -m "docs: register document-refinement/ component bucket"
```

---

## Task 13: Playwright smoke + full verification

**Files:**
- Create: `frontend/e2e/document-refinement.spec.ts`

- [ ] **Step 1: Write a resilient e2e smoke test**

A full upload→extract→refine e2e needs the docling subprocess + ML models running, which is impractical for CI. This test instead asserts the route degrades gracefully for a non-existent document — deterministic, no backend extraction needed. Create `frontend/e2e/document-refinement.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

// A syntactically valid UUID that will not exist in the seeded DB.
const MISSING_ID = '00000000-0000-0000-0000-0000000000ff';

test.describe('document refinement route', () => {
    test('renders a graceful error for a missing document', async ({ page }) => {
        // Log in first (mirrors e2e/auth.spec.ts).
        await page.goto('/login');
        await page.fill('#email', 'admin@example.com');
        await page.fill('#password', 'password');
        await page.click('button[type="submit"]');
        await expect(page).not.toHaveURL(/.*login/, { timeout: 15_000 });

        await page.goto(`/library/documents/${MISSING_ID}/refine`);

        // Either the inline ErrorAlert or the back link must be visible —
        // the page must not crash to a blank screen.
        await expect(
            page.getByText(/error/i).or(page.getByText('Back to document')),
        ).toBeVisible({ timeout: 10_000 });
    });
});
```

- [ ] **Step 2: Run the full unit suite**

Run: `npm run test -- src/lib/schemas/documents.test.ts src/lib/utils/document-markdown.test.ts src/lib/utils/document-utils.test.ts src/lib/api/documents.test.ts src/lib/components/shared/MarkdownDocument.test.ts src/lib/components/document-refinement/`
Expected: PASS — all tests from Tasks 1–9 green.

- [ ] **Step 3: Run the type-check**

Run: `npm run check`
Expected: PASS, or only pre-existing warnings unrelated to the new files.

- [ ] **Step 4: Run the e2e smoke (requires dev servers)**

Start the worktree dev stack first (separate terminals, from the worktree root):
- Backend: `cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8030`
- Frontend: `cd frontend && VITE_API_PORT=8030 npm run dev -- --port 5203`

Then: `npm run test:e2e -- e2e/document-refinement.spec.ts`
Expected: PASS — 1 test. (Playwright's `webServer`/`baseURL` config picks up the running frontend; if the project's `playwright.config.ts` pins a different port, run against that port instead.)

- [ ] **Step 5: Manual smoke against the dev stack**

With the dev stack running and a real PDF uploaded through the Library UI (it transitions `UPLOADED → EXTRACTING → AWAITING_REFINEMENT`):

1. Library list shows the document with a "Needs refinement" badge and a **Refine** button.
2. Click **Refine** → `/library/documents/{id}/refine` loads the three-column workspace. Left rail shows the source-page thumbnail; center shows the extracted markdown rendered in the editor (headings, tables, images visible — images load via the token URL); right rail shows "No flags — extraction looks clean" + the AI panel hint.
3. Edit a word in the editor → toolbar shows "Unsaved changes" → wait 8 s → it flips to "saved just now". Click **Save** explicitly → same.
4. Select a phrase → AI panel shows the selection + scope chips. Type an instruction, **Ask AI** → a suggestion diff appears. **Accept** → the editor text updates; **Reject** → it does not.
5. Click **Mark refinement complete** → confirm dialog → document transitions to `INDEXING` then `READY`; you land on `/library/{id}` and the document is searchable.
6. Re-visiting `/library/documents/{id}/refine` for the now-`READY` document redirects to `/library/{id}` (refinement is one-time).

Record the result of each step. If any step fails, fix it before the final commit; note any deferred issue explicitly.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e/document-refinement.spec.ts
git commit -m "test(library): add refinement route e2e smoke"
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-05-12-td-0085-docling-integration-design.md`, Phase 2 sections):

| Spec requirement | Task |
| --- | --- |
| New route `/library/documents/[id]/refine` | Task 10 |
| `RefinementEditor.svelte` — edra wrapper, markdown serialization, image src rewriting | Tasks 2, 9 |
| `RefinementSidebar.svelte` — source-page thumbnail + status pipeline | Task 6 |
| `RefinementQueue.svelte` — flags, click-to-scroll | Task 7 |
| `RefinementAiPanel.svelte` — prompt, scope chip, suggestions, apply/cancel | Task 8 |
| Shared `MarkdownDocument.svelte` (markdown→HTML, image rewrite) | Task 5 |
| API client + Zod schemas | Tasks 1, 3 |
| Round-trip: markdown in, edit, serialize markdown out; image refs relative in storage | Tasks 2, 9, 10 |
| Save semantics — explicit button + 8 s idle autosave + "saved N sec ago" | Task 10 |
| `beforeunload` guard for unsaved changes | Task 10 |
| Refinement complete — confirm dialog, redirect, one-time (re-visit redirects) | Task 10 |
| Flag → block mapping (`block_anchor` scroll, `source_text` highlight) | Tasks 7, 9, 10 |
| AI panel selection-awareness (scope auto-switches) | Tasks 8, 10 |
| `document-refinement/` registered in conventions.md | Task 12 |
| Library list "Needs refinement" badge | Tasks 4, 11 |

Deferred / out of scope (consistent with the spec's own deferrals): re-open refinement is permission-gated on the backend and the spec says it "lives on the document detail page … not exposed in the editor UI" — a re-open button is **not** built here because `RefinementStatus` is `NOT_REQUIRED` in Phase 1 (the backend `_collect_flags` stub never produces a `COMPLETE`-then-reopen flow worth a UI yet); add it when flag-derived refinement statuses land. `MarkdownDocument.svelte` is created and unit-tested but not yet swapped into the legacy chunk-based viewer at `/library/[id]` — that viewer still works because the chunker runs on refined markdown post-indexing; rewiring it is a low-risk follow-up, not a Phase 2 blocker.

**Placeholder scan:** No `TBD`/`TODO`/"implement later". Every code step shows complete code. Two steps carry explicit verify-and-fallback notes (`getStatusColor` `warning` variant in Task 4; `doc_metadata.ocr_engine` access in Task 10) — these are real, bounded decisions with a stated fallback, not placeholders.

**Type consistency:** `DocumentResponse`, `RefinementFlag`, `MarkdownResponse`, `RefineAiResponse` defined in Task 1, imported unchanged everywhere. `RefineAiParams` (camelCase) defined in Task 3, used by `RefinementAiPanel` (Task 8). `AiSelection` exported from `RefinementAiPanel.svelte` (Task 8), imported by the route (Task 10). The editor bridge functions `getMarkdown` / `applyToSelection` / `scrollToAnchor` have identical signatures in `RefinementEditor.svelte` (Task 9) and the route's `$state` declarations (Task 10). `toDisplayMarkdown` / `toStoredMarkdown` (Task 2) consumed by Tasks 5, 9, 10 with matching signatures.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-14-td-0085-phase-2-frontend.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
