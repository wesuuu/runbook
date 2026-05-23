# BUG-0007 — SOP / Batch Record Template Overhaul (Design)

Bundles four QA-reported defects against the SOP / Batch Record preview generated from a Protocol. All four touch the same template-renderer surface, so they ship together.

- **Sub-issue 1.** Empty document number field — no input, no default.
- **Sub-issue 2.** Squished Instruction column.
- **Sub-issue 3.** No time markers in the preview when time is enabled in the editor.
- **Sub-issue 4.** No way to attach figures to a unit op.

> **Revision note.** Updated after a 5-agent review panel pass (adversarial-risk, db-scalability, dry-reuse, production-ops, ui-ux). Key changes from the first draft: attachments moved from `Protocol.attachments` JSONB to a new `protocol_attachments` child table to eliminate a lost-update race and an IDOR vector; partial unique index switched to `owner_org_id` (the always-non-null column); doc_number inline edit moved from the canvas header to `ProtocolSidebar.svelte`; migration split into a transactional backfill + a `CONCURRENTLY` index build; audit-log calls added to attachment endpoints; magic-byte / pixel-cap validation added; `render_to_docx()` figure swap extended to per-step nested lists.

---

## Sub-issue 1 — Document number

### Decision

Auto-generate `SOP-NNNN` per organization on Protocol creation, with the user free to override. Generator runs only when the caller passes no `doc_number`.

### Schema

`Protocol.doc_number` (String(64), nullable) already exists. Add a partial unique index keyed on the **always-non-null** `owner_org_id` column (project-scoped protocols have `organization_id IS NULL`; `owner_org_id` is always set):

```
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ix_protocols_owner_org_doc_number
  ON protocols (owner_org_id, doc_number)
  WHERE doc_number IS NOT NULL;
```

### Service

New module `backend/app/services/protocols/doc_number.py`:

```
async def generate_default_doc_number(db, owner_org_id) -> str
```

Algorithm:

1. Acquire a per-org Postgres advisory transaction lock: `SELECT pg_advisory_xact_lock(hashtext('sop_seq:' || owner_org_id))`. Released automatically at commit/rollback. Serializes concurrent creates within an org without blocking other orgs.
2. `SELECT max(numeric_suffix) FROM protocols WHERE owner_org_id = :org AND doc_number ~ '^SOP-\d+$'` where `numeric_suffix` is parsed via `regexp_replace(doc_number, '^SOP-0*', '')` cast to integer. The composite index `(owner_org_id, doc_number)` covers this scan.
3. Compute next = `(max or 0) + 1`. Format `SOP-{n:04d}`.
4. On a unique-index conflict (defensive, should be unreachable inside the advisory lock), retry the whole sequence up to 5 times with jittered backoff, then surface 409 with the conflicting value.

The lock-then-pick pattern is the existing convention; cross-reference `suggest_lot_number()` in `runs.py:314-354`. Document the failure mode in the module docstring.

### API

- `ProtocolCreate.doc_number` is optional. If absent/null, the service calls `generate_default_doc_number()` before insert.
- `ProtocolUpdate.doc_number` is editable.
- Unique-index violation surfaces as `409 Conflict` with body `{"detail": "doc_number_in_use", "conflicting_doc_number": "...", "conflicting_protocol_name": "..."}` so the UI can render a useful inline error.

### Migration

Single Alembic migration, split into two steps:

```python
def upgrade() -> None:
    # Step 1 — preflight: detect existing same-org collisions among user-typed values.
    # If any exist, abort with a clear error; the migration is a no-op until ops resolves.
    conn = op.get_bind()
    dups = conn.execute(text(
        "SELECT owner_org_id, doc_number, count(*) c FROM protocols "
        "WHERE doc_number IS NOT NULL "
        "GROUP BY owner_org_id, doc_number HAVING count(*) > 1"
    )).fetchall()
    if dups:
        raise RuntimeError(
            f"Cannot migrate: {len(dups)} existing duplicate doc_number rows. "
            "Resolve manually before re-running."
        )

    # Step 2 — backfill in one window-function statement (single atomic UPDATE,
    # row-locks for the duration of the statement only, no per-row Python loop).
    op.execute(text("""
        WITH numbered AS (
            SELECT id,
                   'SOP-' || lpad(row_number() OVER (
                       PARTITION BY owner_org_id ORDER BY created_at, id
                   )::text, 4, '0') AS new_doc_number
            FROM protocols
            WHERE doc_number IS NULL
        )
        UPDATE protocols p
        SET doc_number = n.new_doc_number
        FROM numbered n
        WHERE p.id = n.id
    """))

    # Step 3 — create the partial unique index without locking writes.
    with op.get_context().autocommit_block():
        op.execute(text(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_protocols_owner_org_doc_number "
            "ON protocols (owner_org_id, doc_number) "
            "WHERE doc_number IS NOT NULL"
        ))
```

Downgrade uses `DROP INDEX CONCURRENTLY` inside `autocommit_block()`. Pattern matches Alembic revision `acc00af3cd19`.

### UI

`doc_number` inline edit lives in `ProtocolSidebar.svelte`, **not** the canvas header. Place it below the `protocol.description` block, alongside `protocol.name`, following the existing ghost-Button → input swap pattern.

- Save via debounced PATCH on blur/Enter.
- Render 409 inline using the `save-as-new-error` span style from `Inspector.svelte` (small text, `color: hsl(0, 84.2%, 60.2%)`). Do **not** use `toast.error` — user must correct the value in-place; a toast auto-dismisses.
- 409 body includes the conflicting protocol's name; surface it in the error message.

### Template wire-up

`build_context()` keeps its existing signature; the function now reads `protocol.doc_number` from the protocol object it already receives and adds `doc_number` to the returned context dict. Both `.docx` templates reference `{{ doc_number }}` where the empty placeholder currently sits in the header block.

---

## Sub-issue 2 — Merge Name + Instruction column

### Decision

Drop the separate Name column. Render each step as a single "Step" cell with the step name bold on line 1 and the description (plus param sentence) on subsequent lines.

### Templates

Edit both `.docx` templates in LibreOffice:

- `backend/app/services/documents/templates/sop_default.docx`
- `backend/app/services/documents/templates/batch_record_default.docx`
- Plus their seeded copies under `backend/uploads/system/document_templates/`.

Add a `.gitattributes` line for `.docx` LFS tracking before committing the new binaries:

```
*.docx filter=lfs diff=lfs merge=lfs -text
```

Column structure (Batch Record, time enabled):

| Time (8%) | # (5%) | Step (60%) | Value (17%) | Initials (10%) |

Without time:

| # (5%) | Step (65%) | Value (20%) | Initials (10%) |

Step cell uses the existing `step.name` (bold) and `step.description` fields — no backend code change for this sub-issue.

---

## Sub-issue 3 — Cumulative time offsets

### Decision

Render a "Time" column **on the left** showing each step's cumulative offset (`T=0`, `T=15m`, `T=4h 30m`) when `graph.timeEnabled = true`. Left-side placement is intentional: this is a **reference offset** column (printed at design time), not a **record time** column (filled in by the operator on execution). Document this in a header comment in `template_engine.py` so future template editors don't move it.

### Algorithm — `compute_time_offsets(graph) -> dict[node_id, int_minutes]`

In `backend/app/services/data/graph_processing.py`. Topological earliest-start (CPM):

1. Collect all `unitOp` nodes into a set `unit_op_ids`. Coerce each `node.data.duration_min` via `int(value or 0)` and clamp to `[0, 60*24*365]` (one year) to guard against bad data.
2. Build adjacency: for each edge, **only include edges where both endpoints are in `unit_op_ids`**. This drops swimlane-container edges and orphan edges pointing at deleted nodes.
3. Kahn's algorithm topological sort.
4. For each node in order: `start[node] = max(start[p] + duration_min[p] for p in predecessors[node])`, defaulting to 0 when no predecessors.
5. Cycle detection: if Kahn's algorithm exits with unprocessed nodes, set `time_warning = "cycle_detected"`, return `{}` for offsets, AND signal the warning to the template context.

### Formatting — `format_time_offset(minutes) -> str`

- `0` → `T=0`
- `< 60` → `T={n}m`
- `% 60 == 0` → `T={h}h`
- else → `T={h}h {m}m`

When `time_warning == "cycle_detected"`, the template renders `T=?` for every step instead of falling back to `T=0` (which would be silently wrong).

### Wire-up

- `build_context()` adds `time_enabled: bool` from `graph.timeEnabled`, optional `time_warning: str`, and per-step `time_offset_display: str`.
- `.docx` templates add a leading "Time" column wrapped in `{% if time_enabled %}…{% endif %}` for both header and body rows.

### Conditional column fallback

`docxtpl` `{% if %}` inside `<w:tc>` cells in table headers can mis-render. Acceptance test renders one PDF with time on and one off and checks both visually.

If unreliable, the fallback is **two templates per type** (`sop_default.docx` and `sop_default_with_time.docx`, same for batch record), selected by `time_enabled` in the endpoint. The codebase already has the `DocumentTemplate` table for per-org template selection; reuse it. Add a CI test that diffs cell-by-cell between the with-time and without-time variants to detect drift.

### Logging

`build_context()` emits a structured `logger.warning("protocol_graph_cycle", protocol_id=..., cycle_nodes=...)` on cycle detection so the event is queryable / alertable.

---

## Sub-issue 4 — Figure attachments per unit op

### Decision

Add a new `protocol_attachments` child table (mirroring `equipment_attachments` — see `app/services/equipment/attachments.py`). Render attached figures inline under each step's description in the SOP / Batch Record. Inspector panel manages them.

**Why a child table and not `Protocol.attachments` JSONB:**
- Concurrent uploads on the same protocol race on a JSONB read-modify-write, silently dropping entries. A child table with one-row-per-attachment avoids this.
- The streaming endpoint looks up an attachment by `id`; with JSONB this is a linear scan, with a table it's an index lookup. Also blocks IDOR-by-shared-UUID: the stream endpoint filters by `(protocol_id, attachment_id)` directly.
- Soft-delete and the per-step `node_id` filter become indexed-WHERE queries.

### Schema

```python
class ProtocolAttachment(Base, TimestampMixin):
    __tablename__ = "protocol_attachments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    protocol_id: Mapped[UUID] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        Index("ix_protocol_attachments_protocol_node", "protocol_id", "node_id"),
    )
```

Composite index `(protocol_id, node_id)` covers the render-path filter for "give me figures for this step." `protocol_id` index alone covers the per-protocol list path.

### Validation

In the upload endpoint:

- `content_type in IMAGE_MIME_TYPES` — imported from `app/services/core/file_storage.py:8`, **not redefined**. Reject `image/svg+xml` explicitly (XSS / SSRF surface).
- Stream-read with running size counter against `MAX_FIGURE_SIZE_BYTES = 10 * 1024 * 1024`. Abort early once exceeded.
- After upload, run `PIL.Image.open(path)` + `verify()` to confirm magic bytes match content_type. Reject mismatches (deletes the staged file).
- Pixel cap: reject images where `width * height > 25_000_000` (25 MP) to guard against decompression bombs.
- Stable error codes returned: `ATTACHMENT_UNSUPPORTED_TYPE` (415), `ATTACHMENT_TOO_LARGE` (413), `ATTACHMENT_INVALID_IMAGE` (422), `ATTACHMENT_LIMIT_REACHED` (422).
- Per-protocol count cap: max **50 non-deleted attachments** per protocol. Returns 422 with code `ATTACHMENT_LIMIT_REACHED`.
- Sanitize `filename` for the response `Content-Disposition` header via RFC 5987 encoding (`filename*=UTF-8''…`) on the stream endpoint.

### Endpoints (new)

New module `backend/app/api/endpoints/protocol_attachments.py`, registered alongside `protocol_pdfs.py`. All scoped under `/protocols/{protocol_id}/attachments` with permission gates.

- `POST /protocols/{protocol_id}/attachments`
  - Multipart form: `file`, `node_id`.
  - Requires Protocol EDIT permission.
  - Validates per the rules above.
  - `FileStorageService.store_file()` writes to `{storage_root}/{org_id}/protocols/{protocol_id}/...` (verify `org_id` is passed to keep future GC tractable).
  - Inserts a `ProtocolAttachment` row.
  - Calls `log_audit(db, actor_id, action="attachment.upload", entity_type="protocol", entity_id=protocol_id, changes={"attachment_id": ..., "filename": ..., "size_bytes": ..., "node_id": ...})`.
  - Returns the attachment row as JSON.
- `DELETE /protocols/{protocol_id}/attachments/{attachment_id}`
  - Requires EDIT permission. Scopes the lookup by `(protocol_id, id)` — IDOR-safe. 404 on mismatch or unknown.
  - Sets `deleted=True` on the row **and** hard-deletes the underlying storage file (`FileStorageService.delete_file()`). This prevents an upload+delete loop from filling disk.
  - Calls `log_audit(action="attachment.delete", ...)`.
- `GET /protocols/{protocol_id}/attachments/{attachment_id}/file`
  - Requires VIEW permission. Scopes by `(protocol_id, id)`. 404 if soft-deleted or mismatched.
  - Streams raw image bytes with RFC 5987 `Content-Disposition`.

### Inspector UI

New `frontend/src/lib/components/protocol/InspectorFigures.svelte`, included from `Inspector.svelte` when a unit op is selected.

- **Collapsed by default.** Uses the chevron-toggle pattern from `Inspector.svelte`'s `showSchemaEditor` (line 454–513). Auto-opens via `$effect` when `attachments.length > 0` for the current node.
- Drag-drop zone + file-picker fallback for upload. Both `dragover` and `drop` handlers call `event.stopPropagation()` to prevent leaking file drops to the canvas drag-and-drop handler at `+page.svelte:~1569`.
- Thumbnail grid (`grid-template-columns: repeat(auto-fill, minmax(80px, 1fr))`). Tap target ≥ 80px; this is tablet-friendly.
- Each thumbnail: image preview (loaded via `api.fetchBlobUrl()` for auth), `title={filename}` tooltip, absolute-positioned delete button at top-right, minimum 24×24px (gloved-hand sizing). Pattern: `media/ImageGallery.svelte` lines 65–70.
- Click thumbnail → opens enlarge modal.

**Enlarge modal:** reuse the existing `ui/FullScreenModal.svelte` (scroll-lock, header with close, `fixed inset-0 z-50`). Do **not** create a new `media/ImageModal.svelte` — the existing primitive composes for this case.

### Soft-delete helpers (shared)

Adversarial findings called out a third duplicate of the soft-delete scan pattern. With attachments moved to a child table, this issue partially dissolves (delete is now a row-update, not a JSONB scan). However, the run-side soft-delete pattern (`runs.py:1702-1731`, `runs.py:1762-1795`) remains JSONB-based and stays as-is for this task; consolidation across the run + protocol attachment models is logged as **TECH_DEBT follow-up**, not in scope here.

### Template render

`build_context()` extends every step ctx:

```python
step_attachments = (
    db.query(ProtocolAttachment)
      .filter_by(protocol_id=protocol.id, node_id=node_id, deleted=False)
      .order_by(ProtocolAttachment.created_at)
      .all()
)
step_ctx["figures"] = [
    {"filename": a.filename, "_file_path": storage.resolve_path(a.file_path)}
    for a in step_attachments
]
```

Render the per-step figure block right under `{{ step.description }}` in both `.docx` templates:

```jinja
{% for figure in step.figures %}
{{ figure.image }}
{% endfor %}
```

### `render_to_docx()` figure swap extension

The existing `_file_path` → `InlineImage` swap (`template_engine.py:733-741`) only walks the top-level `figures` list. Extend it to also walk nested per-step `figures` lists, in both `context["steps"]` (no-role variant) and `context["roles"][...]["steps"]` (role variant):

```python
def _swap_step_figures(steps, doc):
    for step in steps or []:
        for fig in step.get("figures", []) or []:
            fpath_str = fig.pop("_file_path", None)
            if not fpath_str:
                continue
            try:
                fig["image"] = InlineImage(doc, str(fpath_str), width=Inches(4))
            except Exception as exc:
                logger.warning(
                    "inline_image_failed",
                    file_path=fpath_str,
                    error=str(exc),
                )
                fig["image"] = f"[Figure unavailable: {fig.get('filename', 'unknown')}]"

_swap_step_figures(context.get("steps"), doc)
for role in context.get("roles", []) or []:
    _swap_step_figures(role.get("steps"), doc)
```

Per-figure try/except prevents one corrupt upload from aborting the entire PDF render.

Sizing: spec uses `width=Inches(4)`. A future refinement to use `min(Inches(4), natural_width_inches)` would render narrow / portrait figures more gracefully — logged as **TECH_DEBT follow-up**.

---

## File touchlist

### Backend

- `app/models/protocols.py` — add `ProtocolAttachment` model.
- `app/schemas/protocols.py` — add `ProtocolAttachmentResponse`; surface attachments in `ProtocolResponse` as a list of those.
- `app/services/protocols/doc_number.py` (new) — `generate_default_doc_number()` with advisory-lock pattern.
- `app/services/protocols/template_engine.py` — add `doc_number`, `time_enabled`, `time_warning`, `time_offset_display`, per-step `figures` to context; extend `render_to_docx()` figure swap to per-step lists; per-figure try/except.
- `app/services/data/graph_processing.py` — `compute_time_offsets()`, `format_time_offset()`, with bounded `duration_min` coercion and orphan-edge filtering.
- `app/api/endpoints/protocol_pdfs.py` — pass `protocol.doc_number` and time offsets / attachments to `build_context()`.
- `app/api/endpoints/protocols.py` — call `generate_default_doc_number()` on create when `doc_number` is null.
- `app/api/endpoints/protocol_attachments.py` (new) — upload, delete, stream endpoints with audit logging, IDOR-safe lookups, magic-byte + pixel-cap validation, per-protocol count cap, RFC 5987 filenames. Wire into the router in `app/api/__init__.py`.
- New Alembic migration: `protocol_attachments` table (+ indexes), partial unique index on `(owner_org_id, doc_number)` (CONCURRENTLY in autocommit_block), backfill NULL doc_numbers with a preflight duplicate check.

### Frontend

- `lib/api.ts` — client methods: `patchProtocol` (doc_number), `uploadProtocolAttachment`, `deleteProtocolAttachment`, `fetchProtocolAttachmentBlobUrl`.
- `lib/components/protocol/ProtocolSidebar.svelte` — inline-editable `doc_number` row beneath `protocol.description`, using the existing ghost-Button → input swap; renders inline error from 409 body.
- `lib/components/protocol/Inspector.svelte` — slot in `InspectorFigures` section; collapsed by default with chevron toggle; auto-open when attachments exist.
- `lib/components/protocol/InspectorFigures.svelte` (new) — drag-drop + file-picker, thumbnail grid, delete button overlay, `stopPropagation()` on drag events.

### Templates (binary)

- `backend/app/services/documents/templates/sop_default.docx`
- `backend/app/services/documents/templates/batch_record_default.docx`
- `backend/uploads/system/document_templates/sop_default.docx`
- `backend/uploads/system/document_templates/batch_record_default.docx`
- `.gitattributes` — add `*.docx filter=lfs diff=lfs merge=lfs -text` before committing new binaries.

---

## Testing

### Backend unit

- `doc_number.py`:
  - First protocol in an org → `SOP-0001`.
  - Sequence increments correctly across both org-level and project-scoped protocols (uses `owner_org_id`).
  - Padding stable up to and past 9999.
  - Bounded retry on unique-index violation eventually surfaces 409 with conflicting protocol info.
- `compute_time_offsets()`:
  - Linear chain → cumulative sums.
  - Fan-out: two children share same offset.
  - Fan-in (CPM): node's start = max of predecessors' ends.
  - Disconnected node → T=0.
  - Cycle → empty dict, `time_warning` set, no crash, warning logged.
  - Orphan edge (endpoint not in unitOp set) → ignored cleanly.
  - Missing / non-numeric / negative `duration_min` → coerced to 0.
  - Absurd `duration_min` (e.g. 10⁹ minutes) → clamped to one year.
- `format_time_offset()`:
  - `0 → 'T=0'`, `15 → 'T=15m'`, `60 → 'T=1h'`, `75 → 'T=1h 15m'`, `270 → 'T=4h 30m'`.
- Attachment validation:
  - Non-image → 415 with `ATTACHMENT_UNSUPPORTED_TYPE`.
  - `image/svg+xml` → 415 explicitly.
  - Oversize → 413 with `ATTACHMENT_TOO_LARGE` (early abort, not full read).
  - Magic-byte mismatch (PNG header, declared JPEG) → 422 with `ATTACHMENT_INVALID_IMAGE`.
  - 25 MP pixel bomb → 422 (decompression-bomb guard).
  - 50th attachment uploads; 51st → 422 with `ATTACHMENT_LIMIT_REACHED`.

### Backend integration

- Protocol create: `doc_number` populated when omitted; user-supplied value preserved.
- Unique-index conflict surfaces 409 with conflicting protocol info.
- Attachment lifecycle: upload → list (in Protocol response) → stream → soft-delete → underlying file removed from storage; subsequent GET → 404.
- IDOR test: protocol A's user requests `/protocols/A/attachments/{B-attachment-id}/file` → 404.
- Concurrent attachment uploads (10 parallel) → all 10 rows present.
- PDF render with figures + time enabled → docx Jinja loop unrolls per-step figures AND inserts the Time column.
- PDF render where one attachment file is missing from disk → still renders, with `[Figure unavailable: ...]` placeholder.
- Migration preflight aborts cleanly on existing duplicate doc_numbers.
- Audit-log entries written for upload and delete.

### Frontend

- `ProtocolSidebar` edits `doc_number` and saves on blur; 409 renders inline error with the conflicting protocol's name; toast NOT shown.
- `InspectorFigures`: section collapsed by default; auto-opens when figures exist; upload via file picker; drag-drop file does not leak to canvas (verified via spy on canvas drop handler); thumbnail click opens `FullScreenModal`; delete removes thumbnail.

### Manual / qa-verify

- Render real SOP and Batch Record PDF with: time off, time on, figures attached. Compare against bug-report screenshots — all four sub-issues visibly resolved.
- Visual diff of with-time vs without-time templates if the dual-template fallback is chosen.

---

## Out of scope (logged as TECH_DEBT follow-ups)

- Reordering figures within a step.
- Per-figure captions beyond the filename.
- Figures rendered outside SOP / Batch Record (e.g. field-mode runtime, canvas inline).
- Migrating the existing `Run.attachments` JSONB pattern to a child table for consistency with `protocol_attachments`.
- Per-step time markers in the visual canvas editor (canvas already has `TimeAxis.svelte`; this spec only adds them to the printed document).
- Per-org / per-protocol total-bytes storage quota.
- Rate-limit middleware on the upload endpoint.
- Auto-cleanup of orphaned attachments when a graph node is deleted (today: orphans survive silently; not rendered because no matching step). Follow-up: surface "node X has N attachments; delete them?" preflight on graph save.
- `InlineImage(width=min(Inches(4), natural_width))` for narrow / portrait figures.
- Streaming write in `FileStorageService.store_file()` (currently reads full file into memory; bounded by the 10 MB cap).
- Soft-delete helper extraction across run + protocol attachment models.
- `ProtocolSidebar.saveName()` silent error swallowing (pre-existing bug).
