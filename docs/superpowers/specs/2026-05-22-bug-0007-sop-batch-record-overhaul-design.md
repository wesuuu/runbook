# BUG-0007 — SOP / Batch Record Template Overhaul (Design)

Bundles four QA-reported defects against the SOP / Batch Record preview generated from a Protocol. All four touch the same template-renderer surface, so they ship together.

- **Sub-issue 1.** Empty document number field — no input, no default.
- **Sub-issue 2.** Squished Instruction column.
- **Sub-issue 3.** No time markers in the preview when time is enabled in the editor.
- **Sub-issue 4.** No way to attach figures to a unit op.

> **Revision note.** Updated after a 5-agent review panel pass (adversarial-risk, db-scalability, dry-reuse, production-ops, ui-ux). Key changes from the first draft: attachments moved from `Protocol.attachments` JSONB to a new `protocol_attachments` child table to eliminate a lost-update race and an IDOR vector; partial unique index switched to `owner_org_id` (the always-non-null column); doc_number inline edit moved from the canvas header to `ProtocolSidebar.svelte`; migration split into a transactional backfill + a `CONCURRENTLY` index build; audit-log calls added to attachment endpoints; magic-byte / pixel-cap validation added; `render_to_docx()` figure swap extended to per-step nested lists.
>
> **Layout pivot (2026-05-22).** Step-tables were replaced with a **section-per-step** layout: each step renders as a bold heading paragraph followed by a description paragraph and an optional inline-figure block. Pivot was driven by a derisk test (`/tmp/derisk_tc_if.py`) which proved docxtpl's `{%tc if %}` strips the surrounding `<w:tc>` wrapper unconditionally — so a conditional single-column Time removal is not expressible. The new layout dissolves three problems at once: sub-issue 2 (squished Instruction column → full-width body text), sub-issue 3 (no structural conditional needed — plain `{% if time_enabled %}` inside the heading paragraph works), and sub-issue 4 (per-step inline figures sit naturally under the description). The two-template fallback is dropped.

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

## Sub-issue 2 — Section-per-step layout (replaces step-tables)

### Decision

Drop the four-column step-table entirely. Render each step as a sequence of paragraphs:

```
N. <step name>   [— <time_offset>]   (<duration_min> min)        ← 12pt bold black
<step description, full page width>                              ← body, double-spaced
[per-step inline figure block — see sub-issue 4]
```

This dissolves the squished Instruction column (sub-issue 2), the docxtpl single-column conditional problem (sub-issue 3), and provides a natural anchor for inline figures (sub-issue 4).

Visual hierarchy is preserved: existing role headings (`{{ role.process_name or role.name }}`) and time-point headings (`{{ tp.name }}`) are restyled to 16pt bold **black** (overriding Heading-3 blue), so the role/time-point heading visually dominates the 12pt step headings beneath it. Double line spacing (`w:line="480"`) is applied uniformly across every body paragraph for consistent rhythm.

### Template restructure (one-time)

The three step-tables in the two `.docx` templates are rewritten in-place to section-per-step paragraphs. This is a binary-asset change, performed once via a checked-in script (`scripts/rewrite_sop_step_tables.py`, derived from the derisked `/tmp/rewrite_template_to_sections.py`). The script is committed for reproducibility but the rewritten `.docx` is the authoritative artifact at render time — the script is **not** run as part of `build_context()` or render.

Tables targeted by header signature:

- `("Step", "Name", "Instruction", "Duration")` — default + role-scoped step tables
- `("Time Target", "Action", "Expected Output / Log")` — time-point action tables

For each, the script:

1. Inserts a `{%p for step in <iterable> %}` paragraph before the table (`%p` mode dissolves the surrounding `<w:p>`).
2. Inserts the heading paragraph: ``{{ loop.index }}. {{ step.name }}{% if time_enabled %}  —  {{ step.time_offset }}{% endif %}   ({{ step.duration_min }} min)`` at 12pt bold black.
3. Inserts the description paragraph: `{{ step.description }}` at body size.
4. Inserts the nested figure block (see sub-issue 4 template render).
5. Inserts a blank spacer paragraph and the `{%p endfor %}`.
6. Removes the original `<w:tbl>` element.

Then a post-pass walks every `<w:p>` in the body:

- If the paragraph text contains a role-heading marker (`{{ role.process_name or role.name }}` or `{{ tp.name }}`), rewrite each run's `<w:rPr>` to remove existing color/size/bold and append `w:color=000000`, `w:sz=32` (16pt), `w:b`. The paragraph-level `Heading3` style stays in place (for outline / TOC), but the run-level overrides win.
- For every paragraph (heading and body), drop any existing `<w:spacing>` and append `<w:spacing w:line="480" w:lineRule="auto" w:before="0" w:after="120"/>` to enforce double line spacing with a 6pt after-gap.

### Templates affected

- `backend/app/services/documents/templates/sop_default.docx`
- `backend/app/services/documents/templates/batch_record_default.docx`
- Plus their seeded copies under `backend/uploads/system/document_templates/`.

Add a `.gitattributes` line for `.docx` LFS tracking before committing the rewritten binaries:

```
*.docx filter=lfs diff=lfs merge=lfs -text
```

### Backend changes

No new context keys for this sub-issue. The rewritten templates reference `step.name`, `step.description`, `step.duration_min`, `step.time_offset` — all of which `build_context()` already supplies on each step ctx. The only addition is `time_enabled` (covered under sub-issue 3) and `time_offset` (covered under sub-issue 3).

---

## Sub-issue 3 — Cumulative time offsets

### Decision

When `graph.timeEnabled = true`, append each step's cumulative offset (`T=0`, `T=15m`, `T=4h 30m`) to the step-heading line, between the step name and the duration. The offset is a **reference offset** (computed at design time), not a **record time** (filled in by the operator on execution). Document this distinction in a header comment in `template_engine.py` so future template editors don't repurpose it.

With the section-per-step layout (sub-issue 2), the structural docxtpl problem dissolves: `{% if time_enabled %}` is a plain Jinja conditional inside a single paragraph run, not the `{%tc if %}` cell-structural variant. No dual-template fallback is needed.

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

- `build_context()` adds `time_enabled: bool` from `graph.timeEnabled`, optional `time_warning: str`, and per-step `time_offset: str` (rendered by `format_time_offset()` from the computed minutes).
- The rewritten templates (sub-issue 2) reference `{{ step.time_offset }}` inside an inline `{% if time_enabled %}…{% endif %}` in the step heading paragraph. No `{%tc if %}`, no separate Time column.

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
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
  - Multipart form: `file`, `node_id`, optional `caption`.
  - Requires Protocol EDIT permission.
  - Validates per the rules above.
  - `FileStorageService.store_file()` writes to `{storage_root}/{org_id}/protocols/{protocol_id}/...` (verify `org_id` is passed to keep future GC tractable).
  - Inserts a `ProtocolAttachment` row.
  - Calls `log_audit(db, actor_id, action="attachment.upload", entity_type="protocol", entity_id=protocol_id, changes={"attachment_id": ..., "filename": ..., "size_bytes": ..., "node_id": ...})`.
  - Returns the attachment row as JSON.
- `PATCH /protocols/{protocol_id}/attachments/{attachment_id}`
  - Requires EDIT permission. Scopes lookup by `(protocol_id, id)`. Body: `{"caption": str | null}` (max 500 chars). 404 on mismatch.
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
- Below each thumbnail: inline-editable caption input (placeholder = filename). Debounced PATCH on blur via `PATCH /protocols/{protocol_id}/attachments/{attachment_id}` body `{"caption": "..."}`. Empty / unset captions fall back to the filename at render time (see `caption or filename` in `build_context()`).

**Enlarge modal:** reuse the existing `ui/FullScreenModal.svelte` (scroll-lock, header with close, `fixed inset-0 z-50`). Do **not** create a new `media/ImageModal.svelte` — the existing primitive composes for this case.

### Soft-delete helpers (shared)

Adversarial findings called out a third duplicate of the soft-delete scan pattern. With attachments moved to a child table, this issue partially dissolves (delete is now a row-update, not a JSONB scan). However, the run-side soft-delete pattern (`runs.py:1702-1731`, `runs.py:1762-1795`) remains JSONB-based and stays as-is for this task; consolidation across the run + protocol attachment models is logged as **TECH_DEBT follow-up**, not in scope here.

### Template render

`build_context()` extends every step ctx. A single counter is threaded through step iteration order so figure numbers are document-global (Figure 1, 2, 3, …) rather than per-step:

```python
fig_counter = itertools.count(1)
for step_ctx, node_id in steps_in_render_order:
    step_attachments = (
        db.query(ProtocolAttachment)
          .filter_by(protocol_id=protocol.id, node_id=node_id, deleted=False)
          .order_by(ProtocolAttachment.created_at)
          .all()
    )
    step_ctx["figures"] = [
        {
            "number": next(fig_counter),
            "filename": a.filename,
            "caption": a.caption or a.filename,
            "_file_path": storage.resolve_path(a.file_path),
        }
        for a in step_attachments
    ]
```

Render order matches the document order: bare `steps` list first (for no-role protocols), or `roles[i].steps` walked role-by-role. Time-point action lists do not carry figures (no `node_id` mapping).

Render the per-step figure block right under `{{ step.description }}` in both `.docx` templates, inside the section-per-step paragraph sequence:

```jinja
{%p for fig in step.figures %}
{{ fig.image }}
Figure {{ fig.number }}. {{ fig.caption }}
{%p endfor %}
```

The `%p` mode dissolves the surrounding `<w:p>` wrappers so the loop expands to one image paragraph + one caption paragraph per attachment. Caption text is rendered at 9pt; `fig.number` is the per-document sequence (assigned in `build_context()` by enumerating attachments across all steps in render order). When a step has no attachments the loop emits zero paragraphs, leaving no visual gap.

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
- `app/services/protocols/template_engine.py` — add `doc_number`, `time_enabled`, `time_warning`, per-step `time_offset` (string), per-step `figures` (with `number`, `caption`, `_file_path`) to context; thread a document-global figure counter through render order; extend `render_to_docx()` figure swap to per-step lists; per-figure try/except.
- `app/services/data/graph_processing.py` — `compute_time_offsets()`, `format_time_offset()`, with bounded `duration_min` coercion and orphan-edge filtering.
- `app/api/endpoints/protocol_pdfs.py` — pass `protocol.doc_number` and time offsets / attachments to `build_context()`.
- `app/api/endpoints/protocols.py` — call `generate_default_doc_number()` on create when `doc_number` is null.
- `app/api/endpoints/protocol_attachments.py` (new) — upload, patch (caption), delete, stream endpoints with audit logging, IDOR-safe lookups, magic-byte + pixel-cap validation, per-protocol count cap, RFC 5987 filenames. Wire into the router in `app/api/__init__.py`.
- New Alembic migration: `protocol_attachments` table (with `caption` column + indexes), partial unique index on `(owner_org_id, doc_number)` (CONCURRENTLY in autocommit_block), backfill NULL doc_numbers with a preflight duplicate check.
- `scripts/rewrite_sop_step_tables.py` (new, checked-in but not run at request time) — the one-time step-table → section-per-step + role-heading restyle + double-spacing post-pass script. Used to regenerate the seeded `.docx` templates from source-controlled originals if they ever need to be re-derived. Includes a regression test that asserts the rewritten templates contain no `<w:tbl>` elements between the procedure heading and the approvals block.

### Frontend

- `lib/api.ts` — client methods: `patchProtocol` (doc_number), `uploadProtocolAttachment`, `patchProtocolAttachment` (caption), `deleteProtocolAttachment`, `fetchProtocolAttachmentBlobUrl`.
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
- PDF render with figures + time enabled → docx Jinja loop unrolls per-step figures inline under each step heading, and each step heading shows `T=…` between the step name and the duration parens.
- PDF render with figures + time disabled → step heading omits the `T=…` segment but the figure block still renders.
- PDF render with no figures attached → step description is followed directly by the next step heading; no stray blank paragraph.
- Figure numbers are document-global and increase monotonically across roles (Role A step 1 has Figure 1; Role B step 2 has Figure 2, not Figure 1 again).
- Caption fallback: attachment with `caption IS NULL` renders the filename in the caption line; attachment with a non-empty caption renders that text instead.
- PDF render where one attachment file is missing from disk → still renders, with `[Figure unavailable: ...]` placeholder.
- Rewritten templates contain zero `<w:tbl>` elements in the procedure body (regression guard against accidentally re-introducing a step-table).
- Migration preflight aborts cleanly on existing duplicate doc_numbers.
- Audit-log entries written for upload, caption-patch, and delete.

### Frontend

- `ProtocolSidebar` edits `doc_number` and saves on blur; 409 renders inline error with the conflicting protocol's name; toast NOT shown.
- `InspectorFigures`: section collapsed by default; auto-opens when figures exist; upload via file picker; drag-drop file does not leak to canvas (verified via spy on canvas drop handler); thumbnail click opens `FullScreenModal`; delete removes thumbnail.

### Manual / qa-verify

- Render real SOP and Batch Record PDF with: time off, time on, figures attached, multi-role, single role-less, and a time-points variant. Compare against bug-report screenshots — all four sub-issues visibly resolved.
- Verify visual hierarchy in the rendered PDF: role / time-point headings (16pt black bold) dominate step headings (12pt black bold); body text is double-spaced throughout; no blue Heading-3 color remains.

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
