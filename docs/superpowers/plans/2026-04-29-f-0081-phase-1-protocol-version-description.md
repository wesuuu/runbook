# F-0081 Phase 1 — Surface ProtocolVersion Description Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users write a description and one-line change summary when publishing a new protocol version, and surface those fields in the version list so they're useful in the run-creator's version picker (Phase 3).

**Architecture:** `ProtocolVersion.description` and `ProtocolVersion.change_summary` columns already exist in the model. This phase only wires them up: extend `POST /protocols/{id}/publish-draft` to accept a body with both fields, add `description` to the version list response (currently only `change_summary` is returned), and add a `PublishVersionDialog.svelte` component that the protocol editor opens before publishing.

**Tech Stack:** FastAPI / SQLAlchemy 2.0 (async) / Pydantic; Svelte 5 (runes) / shadcn-svelte / Vitest. Backend tests use pytest-asyncio against a real Postgres test DB (`batchrite_test`). Frontend tests use Vitest with jsdom.

**Spec:** `docs/superpowers/specs/2026-04-29-f-0081-run-parameter-overrides-design.md` (Phase 1 section)

---

## File map

**Modify:**
- `backend/app/schemas/science.py:115-126` — add `description` field to `ProtocolVersionListItem`; add new `PublishDraftRequest` schema.
- `backend/app/api/endpoints/protocol_versions.py:32-65` — pass `description` to the list response.
- `backend/app/api/endpoints/protocol_versions.py:380-438` — accept optional `PublishDraftRequest` body; persist `description` and `change_summary` onto the draft when present.
- `backend/tests/integration/test_science_api.py` — add four new integration tests near the existing `test_publish_draft_*` tests (around line 800-905).
- `frontend/src/routes/protocols/[id]/+page.svelte:508-552` — replace direct publish in `saveAndPublish()` with a dialog-mediated flow.

**Create:**
- `frontend/src/lib/components/protocol/PublishVersionDialog.svelte` — small dialog: textarea + single-line input + Cancel / Publish.
- `frontend/src/lib/components/protocol/PublishVersionDialog.test.ts` — Vitest unit tests for the dialog.

---

## Task 1 — Backend: include `description` in version list response

The version list endpoint `GET /science/protocols/{id}/versions` returns `ProtocolVersionListItem`, which today exposes `change_summary` but not `description`. Add it so the Phase 3 wizard's version picker can display descriptions.

**Files:**
- Modify: `backend/app/schemas/science.py:115-126`
- Modify: `backend/app/api/endpoints/protocol_versions.py:52-65`
- Test: `backend/tests/integration/test_science_api.py` (append a new test)

- [ ] **Step 1: Write the failing test**

Append this test at the end of `backend/tests/integration/test_science_api.py`:

```python
@pytest.mark.asyncio
async def test_list_versions_returns_description(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """List endpoint exposes the version description field."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    # Create a published version directly with a description
    from app.models.science import ProtocolVersion
    version = ProtocolVersion(
        protocol_id=protocol.id,
        version_number=1,
        name=protocol.name,
        graph={"nodes": [], "edges": []},
        description="Tightened DO range",
        change_summary="DO 30 -> 25",
        is_draft=False,
    )
    db_session.add(version)
    await db_session.flush()

    resp = await client.get(
        f"/science/protocols/{protocol.id}/versions",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 1
    assert versions[0]["description"] == "Tightened DO range"
    assert versions[0]["change_summary"] == "DO 30 -> 25"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && source .venv/bin/activate
pytest tests/integration/test_science_api.py::test_list_versions_returns_description -v
```

Expected: FAIL with `KeyError: 'description'` (the field is not in the response).

- [ ] **Step 3: Add `description` to `ProtocolVersionListItem`**

Edit `backend/app/schemas/science.py:115-126`:

```python
class ProtocolVersionListItem(BaseModel):
    id: UUID
    version_number: int
    name: str
    description: Optional[str] = None
    change_summary: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    is_draft: bool = False

    class Config:
        from_attributes = True
```

- [ ] **Step 4: Pass `description` in the list endpoint**

Edit `backend/app/api/endpoints/protocol_versions.py:52-65` — inside the list comprehension, add `description=v.description`:

```python
    return [
        ProtocolVersionListItem(
            id=v.id,
            version_number=v.version_number,
            name=v.name,
            description=v.description,
            change_summary=v.change_summary,
            created_by_name=(
                v.created_by.full_name or v.created_by.email
                if v.created_by else None
            ),
            created_at=v.created_at,
            is_draft=v.is_draft,
        )
        for v in versions
    ]
```

(Also adding `is_draft=v.is_draft` since the schema declares it but the endpoint wasn't passing it — drive-by fix; the field defaults to `False` so it never failed but the explicit value is correct.)

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/integration/test_science_api.py::test_list_versions_returns_description -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/science.py backend/app/api/endpoints/protocol_versions.py backend/tests/integration/test_science_api.py
git commit -m "feat(F-0081): expose description in protocol version list response"
```

---

## Task 2 — Backend: `PublishDraftRequest` schema

Define the request body for `publish-draft`. Keeping it in `schemas/science.py` next to the other protocol schemas.

**Files:**
- Modify: `backend/app/schemas/science.py` (add new class near `ProtocolVersionResponse` at line 128)

- [ ] **Step 1: Add the schema**

Edit `backend/app/schemas/science.py` — add this class right after `ProtocolVersionResponse` (around line 137):

```python
class PublishDraftRequest(BaseModel):
    """Optional metadata captured when promoting a draft version to published."""
    description: Optional[str] = None
    change_summary: Optional[str] = None
```

- [ ] **Step 2: No test yet** — schema is exercised by Task 3's tests. Don't commit; combine with Task 3.

---

## Task 3 — Backend: `publish-draft` endpoint accepts body

Wire the new request schema into the endpoint and persist its fields on the draft before flipping `is_draft = False`.

**Files:**
- Modify: `backend/app/api/endpoints/protocol_versions.py:380-438`
- Modify: `backend/app/api/endpoints/protocol_versions.py:14-16` (import the new schema)
- Test: `backend/tests/integration/test_science_api.py` (append three tests)

- [ ] **Step 1: Write the failing test for `description` persistence**

Append to `backend/tests/integration/test_science_api.py`:

```python
@pytest.mark.asyncio
async def test_publish_draft_persists_description(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """publish-draft accepts an optional body with description; the value is
    written onto the published version."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    # Save as draft (creates draft v1)
    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "n1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Publish with a description body
    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number=1",
        json={"description": "Switched buffer from PBS to TBS"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Confirm description was written to the version row
    resp = await client.get(
        f"/science/protocols/{protocol.id}/versions/1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Switched buffer from PBS to TBS"
```

- [ ] **Step 2: Run the test — expect failure**

```bash
pytest tests/integration/test_science_api.py::test_publish_draft_persists_description -v
```

Expected: FAIL — assertion `description == "Switched buffer..."` fails because the endpoint ignores the body. (Or 422 if Pydantic strict validation rejects extra fields; in either case it doesn't pass yet.)

- [ ] **Step 3: Update the endpoint signature + import**

Edit `backend/app/api/endpoints/protocol_versions.py`:

At line 14-16, change the schema import to include `PublishDraftRequest`:

```python
from app.schemas.science import (ProtocolApprovalAction,
                                 ProtocolResponse,
                                 ProtocolVersionListItem,
                                 ProtocolVersionResponse,
                                 PublishDraftRequest)
```

Then update the `publish_draft_version` function signature (line 384-390):

```python
@router.post(
    "/protocols/{protocol_id}/publish-draft",
    response_model=ProtocolResponse,
)
async def publish_draft_version(
    protocol_id: UUID,
    version_number: int = Query(...),
    body: Optional[PublishDraftRequest] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
```

You'll also need to add `Optional` to the imports at the top:

```python
from typing import List, Optional
```

- [ ] **Step 4: Persist body fields onto the draft**

In the same function, just after `draft.is_draft = False` (line 422), add:

```python
    # Mark as published (not a draft) and update main protocol
    draft.is_draft = False
    if body is not None:
        if body.description is not None:
            draft.description = body.description
        if body.change_summary is not None:
            draft.change_summary = body.change_summary
    protocol.graph = draft.graph
    protocol.version_number = version_number
```

(The `is not None` check matters: passing an empty string is treated as "set it to empty", while not passing the field at all leaves the existing value untouched.)

- [ ] **Step 5: Run the test — expect pass**

```bash
pytest tests/integration/test_science_api.py::test_publish_draft_persists_description -v
```

Expected: PASS.

- [ ] **Step 6: Add the change_summary persistence test**

Append:

```python
@pytest.mark.asyncio
async def test_publish_draft_persists_change_summary(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """publish-draft writes change_summary from the body."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "n1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number=1",
        json={"change_summary": "DO range tightened"},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = await client.get(
        f"/science/protocols/{protocol.id}/versions/1",
        headers=auth_headers,
    )
    assert resp.json()["change_summary"] == "DO range tightened"
```

Run it:

```bash
pytest tests/integration/test_science_api.py::test_publish_draft_persists_change_summary -v
```

Expected: PASS (the same code path covers it).

- [ ] **Step 7: Add the regression test (no body still works)**

Append:

```python
@pytest.mark.asyncio
async def test_publish_draft_without_body_still_works(
    client: AsyncClient,
    auth_headers: dict,
    test_project: Project,
    db_session: AsyncSession,
):
    """Existing callers that don't send a body must continue to work.
    Backward-compatibility regression guard."""
    protocol = Protocol(
        name="Test Protocol",
        project_id=test_project.id,
        status="DRAFT",
        version_number=0,
        graph={"nodes": [], "edges": []},
    )
    db_session.add(protocol)
    await db_session.flush()

    resp = await client.put(
        f"/science/protocols/{protocol.id}?save_as_draft=true",
        json={"graph": {"nodes": [{"id": "n1"}], "edges": []}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # No JSON body, no Content-Type — same call shape as the existing client.
    resp = await client.post(
        f"/science/protocols/{protocol.id}/publish-draft?version_number=1",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["version_number"] == 1
```

Run it:

```bash
pytest tests/integration/test_science_api.py::test_publish_draft_without_body_still_works -v
```

Expected: PASS.

- [ ] **Step 8: Run the full module to catch regressions**

```bash
pytest tests/integration/test_science_api.py -v
```

Expected: all tests pass (the four existing `test_publish_draft_*` tests plus the four new ones).

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/science.py backend/app/api/endpoints/protocol_versions.py backend/tests/integration/test_science_api.py
git commit -m "feat(F-0081): publish-draft accepts description + change_summary"
```

---

## Task 4 — Frontend: `PublishVersionDialog` component

A small modal shown before publishing. The protocol editor's "Publish" button opens it; submitting it triggers the existing publish flow with the user's description and change summary.

**Files:**
- Create: `frontend/src/lib/components/protocol/PublishVersionDialog.svelte`
- Create: `frontend/src/lib/components/protocol/PublishVersionDialog.test.ts`

- [ ] **Step 1: Create the failing Vitest test**

Create `frontend/src/lib/components/protocol/PublishVersionDialog.test.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import PublishVersionDialog from './PublishVersionDialog.svelte';

describe('PublishVersionDialog', () => {
    it('renders with empty fields when opened', () => {
        const { getByLabelText, getByText } = render(PublishVersionDialog, {
            open: true,
            versionNumber: 4,
            onConfirm: vi.fn(),
        });

        expect(getByText(/Publish version 4/i)).toBeTruthy();
        const desc = getByLabelText(/Description/i) as HTMLTextAreaElement;
        const summary = getByLabelText(/Change summary/i) as HTMLInputElement;
        expect(desc.value).toBe('');
        expect(summary.value).toBe('');
    });

    it('calls onConfirm with trimmed values when Publish is clicked', async () => {
        const onConfirm = vi.fn();
        const { getByLabelText, getByRole } = render(PublishVersionDialog, {
            open: true,
            versionNumber: 4,
            onConfirm,
        });

        const desc = getByLabelText(/Description/i) as HTMLTextAreaElement;
        const summary = getByLabelText(/Change summary/i) as HTMLInputElement;

        await fireEvent.input(desc, { target: { value: '  Switched to TBS\n' } });
        await fireEvent.input(summary, { target: { value: '  TBS swap  ' } });

        const publishBtn = getByRole('button', { name: /^Publish$/i });
        await fireEvent.click(publishBtn);

        expect(onConfirm).toHaveBeenCalledTimes(1);
        expect(onConfirm).toHaveBeenCalledWith({
            description: 'Switched to TBS',
            change_summary: 'TBS swap',
        });
    });

    it('passes undefined for empty fields rather than empty strings', async () => {
        const onConfirm = vi.fn();
        const { getByRole } = render(PublishVersionDialog, {
            open: true,
            versionNumber: 4,
            onConfirm,
        });

        const publishBtn = getByRole('button', { name: /^Publish$/i });
        await fireEvent.click(publishBtn);

        expect(onConfirm).toHaveBeenCalledWith({
            description: undefined,
            change_summary: undefined,
        });
    });
});
```

- [ ] **Step 2: Run the test — expect failure (component does not exist)**

```bash
cd frontend
CI=true npm run test -- PublishVersionDialog
```

Expected: FAIL with module-not-found for `./PublishVersionDialog.svelte`.

- [ ] **Step 3: Implement the component**

Create `frontend/src/lib/components/protocol/PublishVersionDialog.svelte`:

```svelte
<script lang="ts">
    import * as Dialog from '$lib/components/ui/dialog';
    import { Button } from '$lib/components/ui/button';

    type ConfirmPayload = {
        description: string | undefined;
        change_summary: string | undefined;
    };

    interface Props {
        open: boolean;
        versionNumber: number;
        onConfirm: (payload: ConfirmPayload) => void;
        onCancel?: () => void;
    }

    let {
        open = $bindable(false),
        versionNumber,
        onConfirm,
        onCancel,
    }: Props = $props();

    let description = $state('');
    let changeSummary = $state('');

    function reset() {
        description = '';
        changeSummary = '';
    }

    function handleCancel() {
        reset();
        open = false;
        onCancel?.();
    }

    function handlePublish() {
        const trimmedDesc = description.trim();
        const trimmedSummary = changeSummary.trim();
        onConfirm({
            description: trimmedDesc || undefined,
            change_summary: trimmedSummary || undefined,
        });
        reset();
        open = false;
    }
</script>

<Dialog.Root bind:open>
    <Dialog.Content class="sm:max-w-md">
        <Dialog.Header>
            <Dialog.Title>Publish version {versionNumber}</Dialog.Title>
            <Dialog.Description>
                Optional metadata so future-you (and your team) know what changed.
            </Dialog.Description>
        </Dialog.Header>

        <div class="space-y-3">
            <div>
                <label
                    for="version-description"
                    class="block text-sm font-medium text-foreground mb-1"
                >
                    Description <span class="text-muted-foreground font-normal">(optional)</span>
                </label>
                <textarea
                    id="version-description"
                    bind:value={description}
                    rows="3"
                    placeholder="What changed in this version?"
                    class="w-full px-3 py-2 border border-border rounded-md text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent resize-y"
                ></textarea>
            </div>

            <div>
                <label
                    for="version-change-summary"
                    class="block text-sm font-medium text-foreground mb-1"
                >
                    Change summary <span class="text-muted-foreground font-normal">(one line, optional)</span>
                </label>
                <input
                    id="version-change-summary"
                    type="text"
                    bind:value={changeSummary}
                    placeholder="e.g. Reduced agitation cap from 100 → 80 rpm"
                    class="w-full px-3 py-2 border border-border rounded-md text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
                />
            </div>
        </div>

        <Dialog.Footer>
            <Button variant="secondary" onclick={handleCancel}>Cancel</Button>
            <Button onclick={handlePublish}>Publish</Button>
        </Dialog.Footer>
    </Dialog.Content>
</Dialog.Root>
```

- [ ] **Step 4: Run the tests — expect pass**

```bash
cd frontend
CI=true npm run test -- PublishVersionDialog
```

Expected: 3 passing tests.

- [ ] **Step 5: Run frontend type-check to make sure nothing broke**

```bash
cd frontend
npm run check
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/protocol/PublishVersionDialog.svelte frontend/src/lib/components/protocol/PublishVersionDialog.test.ts
git commit -m "feat(F-0081): PublishVersionDialog component"
```

---

## Task 5 — Frontend: wire dialog into the protocol editor

The protocol editor's `saveAndPublish()` function (`frontend/src/routes/protocols/[id]/+page.svelte:508`) currently saves the draft and immediately publishes it. We split it: clicking Publish now opens `PublishVersionDialog`; the dialog's `onConfirm` callback runs the existing save-then-publish logic with the description + change_summary fields included in the body.

**Files:**
- Modify: `frontend/src/routes/protocols/[id]/+page.svelte:508-552`

- [ ] **Step 1: Read the existing function**

```bash
sed -n '508,552p' frontend/src/routes/protocols/[id]/+page.svelte
```

Confirm the current shape: `async function saveAndPublish() { ... await api.put(... save_as_draft); await api.post(... publish-draft?version_number=...); ... toast.success('Published'); ... }`.

- [ ] **Step 2: Add dialog state and import at the top of the `<script>` block**

Find the import block (lines ~1-30 of the file) and add the dialog component:

```typescript
import PublishVersionDialog from '$lib/components/protocol/PublishVersionDialog.svelte';
```

Then in the `<script>` body where `let saving = $state(false);` etc. live, add:

```typescript
let publishDialogOpen = $state(false);
```

- [ ] **Step 3: Split `saveAndPublish` into `requestPublish` (opens dialog) + `performPublish` (does the work)**

Replace the existing `saveAndPublish` function (lines 508-552) with:

```typescript
    async function saveAndPublish() {
        if (!protocol) return;

        // Block save while previewing old version
        if (previewingVersion !== null) {
            toast.warning("Exit version preview before saving");
            return;
        }

        // Block if already approved, pending, or archived
        if (protocolStatus === "PENDING_APPROVAL" || protocolStatus === "APPROVED" || protocolStatus === "ARCHIVED") {
            toast.warning(protocolStatus === "ARCHIVED" ? "Cannot save an archived protocol" : protocolStatus === "APPROVED" ? "Already published" : "Cannot save while pending approval");
            return;
        }

        // Open the dialog; actual publish happens in performPublish via onConfirm
        publishDialogOpen = true;
    }

    async function performPublish(payload: { description: string | undefined; change_summary: string | undefined }) {
        if (!protocol) return;

        saving = true;

        try {
            const graphData = serializeGraphData(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);

            // Save as draft first
            const draftResponse: any = await api.put(`/science/protocols/${protocol.id}?save_as_draft=true`, {
                graph: graphData,
            });
            const draftVersionNumber = versionNumber + 1;

            // Then publish the draft (with optional metadata from the dialog)
            const publishResponse: any = await api.post(
                `/science/protocols/${protocol.id}/publish-draft?version_number=${draftVersionNumber}`,
                payload,
            );

            protocolStatus = publishResponse.status || "APPROVED";
            versionNumber = publishResponse.version_number || draftVersionNumber;
            toast.success("Published");

            // Mark as saved and reset undo/redo
            lastSavedState = buildStateSnapshot(nodes, edges, layout, handleOrientation, timeEnabled, pixelsPerHour);
            hasUnsavedChanges = false;
            undoRedoState = createUndoRedoState();
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'An error occurred');
        } finally {
            saving = false;
        }
    }
```

- [ ] **Step 4: Mount the dialog in the template**

Locate the `<ProtocolSidebar ...>` element in the template (around line 1018-1037 of `frontend/src/routes/protocols/[id]/+page.svelte`). Add the new dialog component immediately after the closing `/>` of `<ProtocolSidebar>`:

```svelte
<ProtocolSidebar
    {/* ...existing props unchanged... */}
    onSaveAndPublish={saveAndPublish}
/>

<PublishVersionDialog
    bind:open={publishDialogOpen}
    versionNumber={versionNumber + 1}
    onConfirm={performPublish}
/>
```

`versionNumber` is the currently-published version on the protocol; the new version being published is `versionNumber + 1`, matching the `draftVersionNumber` arithmetic in `performPublish` (and matching the `version_number` query-param value sent to the backend).

- [ ] **Step 5: Run the type-checker**

```bash
cd frontend
npm run check
```

Expected: 0 errors. Address any type errors that appear (most likely missing field on the api.post payload since it's typed loose; the payload type matches).

- [ ] **Step 6: Run the full Vitest suite**

```bash
cd frontend
CI=true npm run test
```

Expected: all tests pass; the new `PublishVersionDialog.test.ts` tests pass; no existing tests break.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/protocols/[id]/+page.svelte
git commit -m "feat(F-0081): protocol editor opens PublishVersionDialog on publish"
```

---

## Task 6 — qa-verify session

Run the qa-verify agent end-to-end on Phase 1. Per the spec's verification strategy: open the protocol editor, publish with metadata, confirm it persists.

**Files:** none (browser verification only).

- [ ] **Step 1: Start the dev servers in the worktree**

In one terminal:

```bash
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8010
```

In another terminal:

```bash
cd frontend
VITE_API_PORT=8010 npm run dev -- --port 5183
```

- [ ] **Step 2: Reset the local DB so the run is on clean data**

```bash
./scripts/reset.sh
```

(Wipes DB and re-seeds. Local-only; won't affect anything shared.)

- [ ] **Step 3: Launch the qa-verify agent with these instructions:**

```
Phase 1 verification for F-0081 — adding description + change_summary to protocol version publish flow.

Login: any seeded user works. Default test user from scripts/reset.sh
seed is wesley@trellis.bio with any password (auth is permissive in dev).

Pages affected:
- Protocol editor (/protocols/{id}) — Publish button now opens a
  metadata dialog before publishing.
- Version history drawer accessible from the protocol editor —
  shows the description + change_summary on each version row.

What to test:

GOLDEN PATH
1. Open any seeded protocol's editor.
2. Make a small graph edit (drag a unit op, or just toggle layout).
3. Click "Publish".
4. The PublishVersionDialog should appear with a Description
   textarea and a Change summary input, both empty, plus
   Cancel / Publish buttons.
5. Type a description ("Tightened DO range for high-density runs")
   and a change summary ("DO 30 -> 25").
6. Click Publish. The toast "Published" should appear, the dialog
   should close, and unsaved changes indicator should clear.
7. Open Version History (drawer/sidebar). The newly-published
   version row should show the description and the change summary.

EDGE CASES
- Publish with both fields empty -> still publishes (the fields
  are optional). Confirm via version history that the new version
  exists with no description.
- Click Cancel from the dialog -> dialog closes, no version is
  created, unsaved changes still present.
- Try with previewing=true (preview an older version) -> Publish
  button should warn "Exit version preview before saving" and
  not open the dialog.

UI / UX AUDIT
- Dialog width and spacing match other dialogs in the app
  (CreateRunModal at sm:max-w-md is the right reference).
- Textarea is resize-y and a sensible default height (~3 rows).
- Inputs use the app's focus-ring style (teal primary).
- Buttons: secondary "Cancel", primary "Publish", same as other
  modals.
- No oversized inputs/buttons on tablet width (test at 1024x768).
- Description and Change summary are clearly distinguished
  (label "(optional)" on both, "(one line, optional)" on summary).

Fix any FAIL or POLISH issues found before returning.
```

- [ ] **Step 4: Address findings inline**

If the qa-verify agent surfaces FAIL or POLISH issues, fix them. Re-run the full Vitest suite to confirm no regressions:

```bash
cd frontend && CI=true npm run test
```

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(F-0081): qa-verify findings on Phase 1"
```

(Skip if no fixes needed.)

---

## Phase 1 done — completion checklist

- [ ] All four new backend integration tests pass
- [ ] All three new frontend Vitest tests pass
- [ ] `npm run check` returns 0 errors
- [ ] `pytest tests/integration/test_science_api.py` returns all-pass
- [ ] qa-verify agent returned PASS with no outstanding FAIL or POLISH issues
- [ ] Worktree branch has clean commits matching the conventional-commit format above

When this phase is complete, write a short ClickUp comment summarizing the changes (files modified, tests added, qa-verify outcome) and mark Phase 1 as shipped before moving on to Phase 2.

---

## Out of scope (do NOT do here)

- Editing descriptions on already-published versions (separate task if ever needed).
- Backfilling descriptions on existing version rows.
- Markdown rendering of the description (plain text only for Phase 1).
- Surfacing the description in `RunHistory.svelte` or anywhere outside the protocol editor's version drawer (that wiring lands in Phase 3 with the wizard's version picker).
- Any wizard / run-creator changes — those are Phases 2-4.
