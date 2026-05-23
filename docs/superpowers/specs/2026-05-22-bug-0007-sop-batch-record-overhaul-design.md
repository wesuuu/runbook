# BUG-0007 — SOP / Batch Record Template Overhaul (Design)

Bundles four QA-reported defects against the SOP / Batch Record preview generated from a Protocol. All four touch the same template-renderer surface, so they ship together.

- **Sub-issue 1.** Empty document number field — no input, no default.
- **Sub-issue 2.** Squished Instruction column.
- **Sub-issue 3.** No time markers in the preview when time is enabled in the editor.
- **Sub-issue 4.** No way to attach figures to a unit op.

---

## Sub-issue 1 — Document number

### Decision

Auto-generate `SOP-NNNN` per organization on Protocol creation, with the user free to override.

### Schema

`Protocol.doc_number` (String(64), nullable) already exists. Add a partial unique index:

```
CREATE UNIQUE INDEX ix_protocols_org_doc_number
  ON protocols (organization_id, doc_number)
  WHERE doc_number IS NOT NULL;
```

### Service

New module `backend/app/services/protocols/doc_number.py`:

```
async def generate_default_doc_number(db, organization_id) -> str
```

Algorithm:
1. Select existing `doc_number` values for that org that match the regex `^SOP-\d+$`.
2. Pick `max(numeric_suffix) + 1`, default 1 if none.
3. Format `SOP-{n:04d}` (zero-padded to 4 digits; grows past 9999 cleanly).
4. On a unique-index conflict (race), retry once with `max + 1` recomputed.

### API

- `ProtocolCreate` accepts an optional `doc_number`. If omitted/null, the protocol service calls `generate_default_doc_number()` before insert.
- `ProtocolUpdate` keeps `doc_number` editable.
- Unique-index violation surfaces as a 409 with a clear message.

### Migration

Alembic migration:
1. Backfill: for each org, assign `SOP-{i:04d}` to NULL `doc_number` rows in creation-time order. Skips rows that already have a doc_number.
2. Create the partial unique index.

### UI

`ProtocolEditor` header gains an inline-editable label for `doc_number` next to the protocol name. Click → input → blur/Enter saves via debounced PATCH. 409 responses render an inline error.

### Template wire-up

`build_context()` adds `doc_number` to the context dict. Both `.docx` templates reference `{{ doc_number }}` where the empty placeholder currently sits in the header block.

---

## Sub-issue 2 — Merge Name + Instruction column

### Decision

Drop the separate Name column. Render each step as a single "Step" cell with the name in bold on line 1 and the description (plus param sentence) on subsequent lines.

### Templates

Edit both `.docx` templates in LibreOffice:

- `backend/app/services/documents/templates/sop_default.docx`
- `backend/app/services/documents/templates/batch_record_default.docx`
- Plus their seeded copies in `backend/uploads/system/document_templates/`.

Column structure (Batch Record, with time enabled):

| Time (8%) | # (5%) | Step (60%) | Value (17%) | Initials (10%) |

Without time:

| # (5%) | Step (65%) | Value (20%) | Initials (10%) |

The "Step" cell content uses the existing `step.name` and `step.description` fields — no template engine change required for this sub-issue.

---

## Sub-issue 3 — Cumulative time offsets

### Decision

Render a "Time" column on the left showing each step's cumulative offset (`T=0`, `T=15m`, `T=4h 30m`) when `graph.timeEnabled = true`. Column is hidden when time is off.

### Algorithm — `compute_time_offsets(graph) -> dict[node_id, int_minutes]`

Located in `backend/app/services/data/graph_processing.py`. Topological earliest-start (CPM):

1. Collect all `unitOp` nodes. Build an adjacency map `predecessors[node_id] -> list[node_id]` from edges. Ignore edges to/from swimlane container nodes.
2. Topo-sort (Kahn's algorithm).
3. For each node in order: `start[node] = max(start[p] + duration_min[p] for p in predecessors[node])`, defaulting to 0 when no predecessors.
4. Cycles → log a warning and bail out (return empty dict, treat all as T=0). Should not happen for valid DAG protocols.

### Formatting — `format_time_offset(minutes) -> str`

- `0` → `T=0`
- `< 60` → `T={n}m`
- `% 60 == 0` → `T={h}h`
- else → `T={h}h {m}m`

### Wire-up

- `build_context()` adds `time_enabled: bool` from `graph.timeEnabled` and per-step `time_offset_display: str`.
- `.docx` templates add a leading column wrapped in `{% if time_enabled %}…{% endif %}` for both header and body rows.

### Fallback for conditional columns

`docxtpl` conditionals inside table headers and inside table rows can mis-render when wrapping `<w:tc>` cells. Acceptance test: render one PDF with `timeEnabled=true` and one with `timeEnabled=false` against the new templates and check both visually.

If the conditional wrapping is unreliable, fall back to **two templates per type** (`sop_default.docx` and `sop_default_with_time.docx`, same for batch record), selected by `time_enabled` in the endpoint. Spec flags this as a contingency, not the first attempt.

---

## Sub-issue 4 — Figure attachments per unit op

### Decision

Add a JSONB `attachments` array on `Protocol`, tagged per node_id. Render inline under each step's description in the SOP / Batch Record. Inspector panel manages them.

### Schema

```python
# Protocol model
attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
```

Each entry:

```json
{
  "id": "<uuid>",
  "node_id": "<unitOp node id from graph.nodes>",
  "filename": "centrifuge-position.png",
  "file_path": "<org-scoped storage path>",
  "content_type": "image/png",
  "size_bytes": 123456,
  "uploaded_at": "<ISO>",
  "uploaded_by_id": "<user id>",
  "deleted": false
}
```

`id` is a stable UUID generated server-side so URLs do not depend on filename.

### Endpoints (new)

All scoped under `/protocols/{protocol_id}/attachments`, with permission gates via the existing `require_permission` dependency.

- `POST /protocols/{protocol_id}/attachments`
  - Multipart form: `file`, `node_id`.
  - Requires Protocol EDIT permission.
  - Validates `content_type in IMAGE_MIME_TYPES` and `size_bytes <= 10 * 1024 * 1024`.
  - Stores via `FileStorageService.store_file()` under `protocols/{protocol_id}/`.
  - Appends entry to `Protocol.attachments`, persists, returns the entry.
- `DELETE /protocols/{protocol_id}/attachments/{attachment_id}`
  - Requires EDIT permission. Soft-deletes (sets `deleted: true`). 404 on unknown id.
- `GET /protocols/{protocol_id}/attachments/{attachment_id}/file`
  - Requires VIEW permission. Streams raw image bytes from storage. 404 if soft-deleted.

Endpoint module: `backend/app/api/endpoints/protocol_attachments.py` (or inline in `protocols.py` — pick whichever keeps that file under the conventions limit).

### Inspector UI

Add a "Figures" section to `Inspector.svelte`, visible when a unit op is selected:

- Drag-drop zone + file-picker fallback for upload.
- Thumbnail grid (CSS `grid-template-columns: repeat(auto-fill, minmax(80px, 1fr))`).
- Each thumbnail: image preview, filename tooltip, delete (X) button.
- Click thumbnail → opens an enlarge modal.

New components:
- `frontend/src/lib/components/protocol/InspectorFigures.svelte` — section component owned by the protocol bucket.
- `frontend/src/lib/components/media/ImageModal.svelte` — if no equivalent exists; check for a reusable image-preview modal first. Reuses shadcn-svelte `Dialog` primitive.

### Template render

`build_context()` extends each step ctx:

```python
step_ctx["figures"] = [
    {"filename": att["filename"], "_file_path": storage.resolve_path(att["file_path"])}
    for att in protocol.attachments
    if att["node_id"] == node_id and not att.get("deleted") and is_image(att["content_type"])
]
```

`render_to_docx()` already converts `_file_path` → `InlineImage`. In the `.docx` templates, add inside the step row right under `{{ step.description }}`:

```jinja
{% for figure in step.figures %}
{{ figure.image }}
{% endfor %}
```

`InlineImage` is constructed with `width=Inches(4)` so figures fit the step cell width consistently.

---

## File touchlist

### Backend

- `app/models/protocols.py` — add `attachments` JSONB column.
- `app/schemas/protocols.py` — surface `attachments` in `ProtocolResponse` (read-only; uploads go through dedicated endpoints).
- `app/services/protocols/doc_number.py` (new) — `generate_default_doc_number()`.
- `app/services/protocols/template_engine.py` — add `doc_number`, `time_enabled`, `time_offset_display`, `figures` to context.
- `app/services/data/graph_processing.py` — `compute_time_offsets()`, `format_time_offset()`.
- `app/api/endpoints/protocol_pdfs.py` — pass `protocol.doc_number` to `build_context()`.
- `app/api/endpoints/protocols.py` — call `generate_default_doc_number()` on create when `doc_number` is null.
- `app/api/endpoints/protocol_attachments.py` (new) — upload, delete, stream endpoints. Wire into the router in `app/api/__init__.py`.
- New Alembic migration: `attachments` column, partial unique index on `(organization_id, doc_number)`, backfill NULL doc_numbers.

### Frontend

- `lib/api.ts` — new client methods for protocol attachments and doc_number patch.
- `lib/components/protocol/ProtocolEditor.svelte` (or whichever owns the header) — inline-editable doc_number label.
- `lib/components/protocol/Inspector.svelte` — slot in the new `InspectorFigures` section.
- `lib/components/protocol/InspectorFigures.svelte` (new) — thumbnail grid + upload + delete.
- `lib/components/media/ImageModal.svelte` (new, if no equivalent) — enlarge modal.

### Templates (binary)

- `backend/app/services/documents/templates/sop_default.docx`
- `backend/app/services/documents/templates/batch_record_default.docx`
- `backend/uploads/system/document_templates/sop_default.docx`
- `backend/uploads/system/document_templates/batch_record_default.docx`

Tools: open in LibreOffice, edit table structure + Jinja loop syntax, save, commit. Diff visible only as binary; rely on tests + qa-verify to confirm output.

---

## Testing

### Backend unit

- `doc_number.py`:
  - First protocol in an org → `SOP-0001`.
  - Sequence increments correctly.
  - Padding stable up to and past 9999.
  - On simulated unique-index violation, retries once and succeeds.
- `compute_time_offsets()`:
  - Single linear chain → cumulative sums.
  - Fan-out: two children get same offset.
  - Fan-in (CPM): node's start is max of predecessors' ends.
  - Disconnected node → T=0.
  - Cycle → empty dict + warning, no crash.
- `format_time_offset()`:
  - `0 → 'T=0'`, `15 → 'T=15m'`, `60 → 'T=1h'`, `75 → 'T=1h 15m'`, `270 → 'T=4h 30m'`.
- Figure attachment validation:
  - Non-image rejected (415).
  - Oversize rejected (413).
  - Image accepted, returns entry with stable UUID.

### Backend integration

- Protocol create: `doc_number` populated when omitted; user-supplied value preserved.
- Unique-index conflict surfaces as 409 on user override collision.
- Attachment upload → list (in Protocol response) → delete (soft) → GET file (404 after delete).
- PDF render: protocol with figures + time enabled produces a `.docx` whose Jinja loop unrolled the figures and the Time column.

### Frontend

- `ProtocolEditor` header edits doc_number and saves on blur; renders 409 inline error.
- `InspectorFigures`: upload via file picker, thumbnail appears; delete removes it; click enlarges in modal.

### Manual / qa-verify

- Render a real SOP and Batch Record PDF with: time off, time on, figures attached. Compare against the bug-report screenshots — all four sub-issues visibly resolved.

---

## Out of scope

- Reordering figures within a step (single linear list is fine for v1).
- Captions per figure beyond the filename.
- Figures rendered in places other than SOP / Batch Record (e.g. the runtime field-mode flow).
- Migrating existing run-level attachment patterns to share code with protocol attachments.
- Per-step time markers in the visual graph editor — the editor already has `TimeAxis.svelte`; this spec only adds them to the printed document.
- Inline image rendering inside the protocol editor canvas itself.
