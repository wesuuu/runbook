# BUG-0007 — SOP / Batch Record Template Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the four BUG-0007 sub-issues (empty doc_number, squished Instruction column, missing time markers, no per-unit-op figures) by overhauling the SOP/Batch-Record render pipeline — section-per-step layout, cumulative time offsets, doc_number generator, and a `protocol_attachments` child table — together with the visual-verification gates that keep the rendered preview honest.

**Architecture:** Backend gets a new `protocol_attachments` child table (mirroring `equipment_attachments`), an org-scoped `doc_number` generator using a Postgres advisory transaction lock, a `compute_time_offsets()` CPM walker over the graph, and a unified `_swap_file_path_to_inline_image()` helper. The two `.docx` templates are rewritten **once** via a checked-in idempotent script that replaces step-tables with section-per-step paragraphs and restyles role headings. The render endpoint pre-fetches attachments in a single bulk query to avoid N+1 and the sync/async boundary. Frontend adds an inline `doc_number` editor in `ProtocolSidebar` and a collapsible `InspectorFigures` panel. A `scripts/render_sample_sop.py` renderer + checked-in baseline PDFs/PNGs serve as the visual specification, backed by XML-level pytest assertions.

**Tech Stack:** FastAPI async + SQLAlchemy 2.0 (async/asyncpg), Alembic with `autocommit_block()` for CONCURRENTLY index, python-docx + docxtpl + Pillow, PostgreSQL JSONB graphs + child tables, Svelte 5 runes + shadcn-svelte, pytest with async/integration suites, LibreOffice headless for `.docx` → PDF.

**Spec:** `docs/superpowers/specs/2026-05-22-bug-0007-sop-batch-record-overhaul-design.md`

---

## Review-Panel Addendum (read first — supersedes original task text where it conflicts)

The 5-agent panel (adversarial-risk, db-scalability, dry-reuse, production-ops, ui-ux) reviewed this plan after drafting. The corrections below are **mandatory** and override the original task text where they conflict. Each entry cites the task number, severity, and the exact code/text to use.

### Verified facts (confirmed by reading the codebase)

- `build_context()` is **keyword-only** (`*,` separator, `backend/app/services/protocols/template_engine.py:182-213`); returns `tuple[dict, list[str]]`. **Every parameter added by this plan MUST have a default value.** Tests must call it with kwargs: `build_context(protocol_name="X", roles_with_steps=[...], ...)`, not positionally.
- `FileStorageService.store_file()` exists (`backend/app/services/core/file_storage.py:37`) and already validates MIME type, size, and uses `resolve_path()` (which has a path-traversal guard at lines 89-92). **There is no `store_bytes` method.**
- `IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/tiff", "image/webp"}` (file_storage.py:8) — SVG is already excluded; the new explicit SVG reject is belt-and-suspenders.
- `delete_file()` is **synchronous** (uses `path.unlink()`). Streaming reads must wrap `path.open("rb")` with `asyncio.to_thread`.
- `Protocol.doc_number` exists on the model. The Jinja `{{ doc_number }}` placeholder does **not** yet exist in the docx templates — Task 13 adds it. Between Task 6 and Task 13, the rendered SOP still has an empty doc-number area; this is acceptable (no regression).

### Per-task corrections

#### Task 2 — `compute_time_offsets` [HIGH]

Cycle handling must emit offsets for the acyclic portion and only flag cycle-participating nodes. Original "return ({}, 'cycle_detected') on any cycle" is wrong — it loses correct data for unrelated branches.

```python
# Replace cycle handling: after Kahn's algorithm, if remaining = unvisited nodes
# is non-empty, that set IS the cycle. Return offsets for the topologically
# processed nodes and a warning identifying the cycle nodes.
if remaining:
    logger.warning("compute_time_offsets cycle_detected nodes=%s", sorted(remaining))
    return offsets, "cycle_detected"  # offsets contains the acyclic portion only
return offsets, None
```

Update `test_cycle_logs_warning_and_returns_partial`: graph `a→b→a` + disconnected `c` should yield `offsets["c"] == 0` AND warning emitted.

#### Task 3 — `generate_default_doc_number` [MEDIUM, ops]

Add a structured success log line before return:

```python
logger.info(
    "doc_number_generated",
    extra={"org_id": str(owner_org_id), "doc_number": result},
)
```

Also rewrite the MAX query to use indexable ordering (`ORDER BY length(doc_number) DESC, doc_number DESC LIMIT 1` and parse the int in Python) for forward-scalability. The advisory-lock + partial-unique-index guarantee correctness; the query is a perf nit.

#### Task 4 — `validate_image_file` [HIGH]

PIL's `Image.verify()` invalidates the instance and must be called on a freshly-opened image; the original "open → check size → verify" order is broken. Also reject animated/multi-frame formats.

```python
def validate_image_file(path: Path, content_type: str) -> None:
    """Magic-byte + pixel-cap + multi-frame guard for image uploads.

    Raises HTTPException(422, "ATTACHMENT_INVALID_IMAGE") on any failure.
    """
    if content_type == "image/svg+xml":
        raise HTTPException(415, "ATTACHMENT_UNSUPPORTED_TYPE")
    expected = _MIME_TO_PIL_FORMAT.get(content_type)
    if expected is None:
        raise HTTPException(415, "ATTACHMENT_UNSUPPORTED_TYPE")
    # First pass: verify on a fresh open. verify() invalidates the instance.
    try:
        with Image.open(path) as img:
            img.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as e:
        raise HTTPException(422, "ATTACHMENT_INVALID_IMAGE") from e
    # Second pass: reopen for header inspection (verify did not give us size).
    try:
        with Image.open(path) as img:
            if img.format != expected:
                raise HTTPException(422, "ATTACHMENT_INVALID_IMAGE")
            w, h = img.size
            if w * h > _MAX_PIXELS:
                raise HTTPException(422, "ATTACHMENT_INVALID_IMAGE")
            # Reject animated WebP / multi-frame TIFF (each frame bypasses pixel cap).
            if getattr(img, "n_frames", 1) > 1:
                raise HTTPException(422, "ATTACHMENT_INVALID_IMAGE")
    except (UnidentifiedImageError, OSError) as e:
        raise HTTPException(422, "ATTACHMENT_INVALID_IMAGE") from e
```

Add a test fixture `truncated.png` (PNG header + 100 bytes garbage body) to verify the `Image.verify()` guard actually catches partial corruption.

#### Task 6 — Migration [BLOCKER + HIGH]

**BLOCKER — Add a runbook comment at the top of the migration file:**

```python
"""Add protocol_attachments + doc_number partial unique index + backfill.

OPERATOR RUNBOOK — read before running in production:

1. Preflight aborts if duplicate (owner_org_id, doc_number) pairs exist.
   To find them:
       SELECT owner_org_id, doc_number, count(*)
       FROM protocols
       WHERE doc_number IS NOT NULL
       GROUP BY owner_org_id, doc_number HAVING count(*) > 1;
2. Resolving a duplicate is a regulated-data mutation. Per 21 CFR §58.130(e),
   it requires Study Director or QAU sign-off on which protocol keeps the
   original number. Log the resolution decision in the audit_log BEFORE
   re-running the migration.
3. Large-table backfill: if SELECT count(*) FROM protocols WHERE doc_number
   IS NULL exceeds 5000, batch the UPDATE in 500-row chunks to avoid a
   minutes-long table-wide lock. The single-statement form below is safe
   for &le; 5000 rows.
4. CONCURRENTLY index creation can leave an INVALID index on partial failure.
   Detect with: SELECT indexname FROM pg_index JOIN pg_class ON
   pg_class.oid = pg_index.indexrelid WHERE NOT indisvalid;
   If found, DROP the invalid index manually before re-running.
"""
```

**HIGH — Lock the table before preflight, and detect invalid indexes:**

```python
# In upgrade(), BEFORE the duplicate-check query:
op.execute(sa.text("LOCK TABLE protocols IN SHARE MODE"))

# AFTER backfill, before CONCURRENTLY block:
op.execute(sa.text("""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            WHERE c.relname = 'ix_protocols_owner_org_doc_number' AND NOT i.indisvalid
        ) THEN
            DROP INDEX ix_protocols_owner_org_doc_number;
        END IF;
    END $$;
"""))

# Then the CONCURRENTLY create in autocommit_block as before.
```

#### Task 7 — Attachment upload endpoint [BLOCKER × 4 + HIGH × 2]

**BLOCKER B2 — Reuse `FileStorageService.store_file` instead of inventing `store_bytes`:**

```python
# Wrap incoming raw bytes in an UploadFile-compatible object or read directly.
# Simplest: validate Content-Length first, then delegate to store_file().
content_length = request.headers.get("Content-Length")
if content_length and int(content_length) > MAX_FIGURE_SIZE_BYTES:
    raise HTTPException(413, "ATTACHMENT_TOO_LARGE")

storage = FileStorageService()
try:
    stored = await storage.store_file(
        file,
        base_dir="protocol_attachments",
        org_id=protocol.owner_org_id,
        path_segments=[str(protocol_id)],
        allowed_types=IMAGE_MIME_TYPES,
        max_size_bytes=MAX_FIGURE_SIZE_BYTES,
    )
except HTTPException:
    raise  # store_file already raises 413/422 with correct details
```

Convert `store_file`'s generic 422 unsupported-type into the stable `ATTACHMENT_UNSUPPORTED_TYPE` 415 / `ATTACHMENT_TOO_LARGE` 413 codes by re-mapping. Easier: don't use store_file's allowlist and do MIME check before calling.

**BLOCKER B3 — Sanitize filename before persist:**

```python
from pathlib import PurePosixPath
safe_filename = PurePosixPath(file.filename or "upload").name  # strips ../, /etc/, etc.
# persist safe_filename into ProtocolAttachment.filename, NOT file.filename
```

**BLOCKER B4 — Atomic 50-cap via per-protocol advisory lock:**

```python
# After permission check, before count:
await db.execute(
    sa.text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
    {"k": f"proto_attach:{protocol_id}"},
)
count = await db.scalar(
    sa.select(sa.func.count()).select_from(ProtocolAttachment).where(
        ProtocolAttachment.protocol_id == protocol_id,
        ProtocolAttachment.deleted == False,  # noqa: E712
    )
)
if count >= MAX_FIGURES_PER_PROTOCOL:
    raise HTTPException(422, "ATTACHMENT_LIMIT_REACHED")
# Insert happens within the same transaction → cap is enforced atomically.
```

**BLOCKER B5 — Already addressed by the Content-Length pre-check above (B2).**

**HIGH H5 — Explicit SVG reject (defense in depth):** the MIME allowlist already excludes SVG, but add an explicit `if content_type == "image/svg+xml": raise 415` line BEFORE delegating, so the test for SVG is unambiguous.

**HIGH — Cleanup on validation failure:**

```python
# Validate AFTER store (we need the path), but wrap in try/except to delete on fail:
try:
    validate_image_file(storage.resolve_path(stored.relative_path), content_type)
except HTTPException:
    storage.delete_file(stored.relative_path)
    raise
```

**LOW — Use `detail="ATTACHMENT_NOT_FOUND"` (uppercase, matches namespace) in `_get_attachment_or_404`.**

#### Task 8 — PATCH/DELETE/GET endpoints [HIGH × 3]

**HIGH H7 — Commit before file delete:**

```python
# Change order in DELETE:
row.deleted = True
await db.flush()
await log_audit(...)
await db.commit()         # 1. Commit first; if this fails, file is intact
storage.delete_file(row.file_path)  # 2. Then delete; if this fails, file orphaned (recoverable)
```

**HIGH H8 — Async file open in StreamingResponse:**

```python
import asyncio

async def _iter():
    path = storage.resolve_path(row.file_path)
    # storage.resolve_path already includes path-traversal guard (lines 89-92);
    # additional belt-and-suspenders check:
    if not path.resolve().is_relative_to(storage.storage_root.resolve()):
        raise HTTPException(403, "ATTACHMENT_FORBIDDEN")
    # Wrap sync file IO so it doesn't block the event loop:
    def _read_all() -> bytes:
        return path.read_bytes()
    data = await asyncio.to_thread(_read_all)
    yield data
```

(Plain `read_bytes` is acceptable given the 10MB cap; if larger files become possible, switch to `aiofiles` with chunked yield.)

#### Task 9 — Create wiring + 409 surfacing [BLOCKER + HIGH × 2]

**BLOCKER B6 — Apply the same 409 handler to UPDATE endpoint:** the protocol PATCH/PUT endpoint must catch `IntegrityError` for `doc_number` conflicts identically.

**HIGH H9 — Use pgcode instead of error-message string match:**

```python
from asyncpg.exceptions import UniqueViolationError

try:
    await db.commit()
except IntegrityError as exc:
    await db.rollback()
    orig = getattr(exc, "orig", None)
    if isinstance(orig, UniqueViolationError) and orig.constraint_name == "ix_protocols_owner_org_doc_number":
        # 409 path
        ...
    raise
```

**HIGH H10 — Don't leak `existing.name` across permission boundary:**

```python
# Before returning the conflicting protocol's name, check viewer's permission:
has_view = await check_permission(db, current_user.id, ObjectType.PROTOCOL, existing.id, PermissionLevel.VIEW)
existing_name = existing.name if has_view else None
raise HTTPException(409, {"error": "DOC_NUMBER_TAKEN", "by_protocol_name": existing_name})
```

#### Task 10 — Template rewriter [HIGH × 3]

**HIGH H11 — `or` → `and` in idempotency test:**

```python
# Replace:
assert "Instruction" not in body or "{%tr for step" not in body  # WRONG
# With:
assert "Instruction" not in body and "{%tr for step" not in body  # both must be absent
```

**HIGH H12 — LFS pointer-as-docx sentinel test:**

```python
def test_templates_are_real_binaries_not_lfs_pointers():
    for tpl in ("sop_default.docx", "batch_record_default.docx"):
        p = TEMPLATES_DIR / tpl
        assert p.stat().st_size > 10_000, (
            f"{tpl} is {p.stat().st_size} bytes — likely an LFS pointer file. "
            f"Run `git lfs install && git lfs pull` and re-check."
        )
```

**MEDIUM — Rollback path:** in the Task 10 commit message, document the recovery command:

```
git show <commit-parent>:backend/app/templates/protocols/sop_default.docx > /tmp/rollback.docx
```

#### Task 12 — Unified figure swap [WARNING from dry-reuse]

Add an explicit step to the task: **"Delete lines 733-741 of template_engine.py (the old top-level figure-swap loop)."** Without this, both old and new helpers run, double-processing context.

#### Task 13 — `build_context` enhancements [BLOCKER + HIGH × 3]

**BLOCKER B7 — Test signature MUST use kwargs:** `build_context()` is keyword-only. Every test in this task must call it as:

```python
def test_doc_number_threaded_into_context():
    ctx, _ = build_context(
        protocol_name="X",
        roles_with_steps=[...],  # or flat_steps=
        # ... all kwargs only, never positional
    )
    assert ctx["doc_number"] == "SOP-0042"
```

**HIGH — Every new parameter to `build_context` MUST have a default** (`doc_number: str | None = None`, `time_enabled: bool = False`, `attachments_by_node: dict | None = None`, etc.). Required by 7 existing callers (`protocol_pdfs.py` ×4, `runs.py` ×2, internal ×1).

**HIGH H13 — Deepcopy step data + deterministic figure ordering:**

```python
import copy

def _step_ctx(step_node, *, time_offset, figures):
    step = copy.deepcopy(step_node)
    step["time_offset"] = time_offset
    step["figures"] = figures
    return step
```

For the attachment pre-fetch query, use `ORDER BY created_at, id` (id as tiebreaker for same-millisecond uploads).

#### Task 14 — N+1 fix + Batch Record parity [HIGH × 3]

**HIGH H14 — N+1 guard test must work with asyncpg.** The `sync_engine` event listener is a no-op on async engines. Replace with:

```python
# Capture queries by overriding the engine's _connection_cls.execute, or use
# the more reliable pattern: count entries in asyncpg's query log via the
# 'do_execute' event on the sync_engine of the AsyncEngine pool adapter.
# Simplest reliable approach: use a sqlalchemy LoggingConnection / engine.echo
# and grep, OR assert via the application-level query-counter middleware
# (see backend/app/core/instrumentation.py — verify it exists; if not, use
# session_factory's `before_cursor_execute` on the test-only sync engine).

# Acceptable alternative: assert renderer behavior end-to-end via psql
# log_statement = 'all' + reading the postgres log in a docker-compose CI rig.
```

If a reliable async query-counter doesn't exist in the codebase, the test must instead use an `AsyncMock` on `db.execute` and count call sites. **Do not commit a `sync_engine` listener test — it will silently pass.**

**HIGH H16 — Apply the bulk pre-fetch to ALL render paths.** Verify `protocol_pdfs.py` ×4 + `runs.py` ×2 + any batch-record handler — every site that calls `build_context()` must use the same pre-fetched `attachments_by_node` dict.

**HIGH H15 — Structured render-duration log:**

```python
import time
start = time.monotonic()
try:
    pdf_bytes = await run_in_threadpool(render_to_docx, ...)
    logger.info(
        "sop_render_complete",
        extra={"protocol_id": str(protocol_id), "duration_ms": int((time.monotonic() - start) * 1000)},
    )
except Exception:
    logger.error("sop_render_failed", extra={"protocol_id": str(protocol_id)}, exc_info=True)
    raise
```

#### Task 15 — Sample renderer + baselines [MEDIUM × 2]

- Pin LibreOffice version in CI (or document in test docstring), since `pdftoppm` output varies across versions.
- Add `@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")` on tests that invoke PDF conversion. Structural docx XML asserts do not need this skip.
- Strengthen the visual gate with coarse automated checks: `assert pdf_pages >= 2` and `assert pdf.stat().st_size > 50_000` — catches catastrophic template regressions without env sensitivity.

#### Task 17 — `ProtocolSidebar` doc_number editor [BLOCKER + HIGH × 2]

**BLOCKER B8 — Explicit field label:**

```svelte
<div class="flex flex-col gap-1">
  <label class="text-xs text-muted-foreground">Doc #</label>
  <!-- existing ghost-button → input swap pattern below -->
</div>
```

**HIGH H17 — Remove the word "debounced":** blur fires once, debounce on blur is a no-op. Use plain blur/Enter, matching `saveName` / `saveDescription` verbatim.

**HIGH — Empty-state placeholder:** when `doc_number` is null on existing protocols, render `SOP-NNNN (auto on save)` as muted placeholder text (`text-muted-foreground`). Avoid showing a blank ghost-button.

#### Task 18 — `InspectorFigures` panel [BLOCKER + HIGH × 2 + MEDIUM × 3]

**BLOCKER B9 — Wrap delete in `ConfirmDialog`:**

```svelte
<script lang="ts">
  import ConfirmDialog from "$lib/components/shared/ConfirmDialog.svelte";
  let confirmDeleteId = $state<string | null>(null);
</script>

<button onclick={() => (confirmDeleteId = att.id)}>×</button>

{#if confirmDeleteId}
  <ConfirmDialog
    title="Delete this figure?"
    description="This permanently removes the image and its caption. Cannot be undone."
    confirmLabel="Delete"
    destructive
    onconfirm={() => { deleteFigure(confirmDeleteId!); confirmDeleteId = null; }}
    oncancel={() => (confirmDeleteId = null)}
  />
{/if}
```

**HIGH — Empty-state copy:**

```svelte
{#if attachments.length === 0}
  <div class="rounded border-2 border-dashed border-muted p-6 text-center text-sm text-muted-foreground">
    Drop an image here or click to attach<br />
    <span class="text-xs">PNG / JPEG / WebP up to 10MB</span>
  </div>
{/if}
```

**HIGH — Surface `ATTACHMENT_LIMIT_REACHED`:** count badge in the panel header (`FIGURES ({count} / 50)`) and toast on 422 with copy "Figure limit reached (50). Remove an existing figure to add more."

**MEDIUM — Caption placement:** move caption input below the grid, not per-thumbnail (80px width truncates copy). One caption row for the selected thumbnail.

**MEDIUM — Touch target size:** delete overlay button must be ≥ 44×44px (gloved-hand minimum), not 24×24.

**MEDIUM — Revoke blob URLs in `$effect` cleanup** to prevent memory leak across long editor sessions:

```svelte
$effect(() => {
  return () => {
    for (const url of Object.values(thumbUrls)) URL.revokeObjectURL(url);
  };
});
```

#### Task 19 — End-to-end smoke test [MEDIUM]

The Jinja-in-caption test must actually assert the literal text:

```python
def test_caption_with_jinja_braces_is_literal():
    # Upload an attachment with caption "{{ pwn }}".
    # Render the SOP, extract text from the docx.
    # Assert: the literal string "{{ pwn }}" appears verbatim in the rendered output.
    rendered_text = extract_docx_text(pdf_or_docx_path)
    assert "{{ pwn }}" in rendered_text
```

### TECH_DEBT follow-up ClickUp tickets to create before merge

The implementer must `clickup_create_task` for each of these (list `TECH_DEBT`) and reference the IDs in comments next to the relevant code:

1. **Streaming upload** — replace in-memory `await file.read()` in `FileStorageService.store_file`; bounded by current 10MB cap but multiplies under concurrency.
2. **Soft-delete purge job for `protocol_attachments`** — evaluate retention window per 21 CFR §58.195.
3. **Per-org / per-protocol storage quota** — total-bytes ceiling beyond the per-file cap.
4. **Orphaned attachment cleanup on graph-node delete** — attachments referencing a node_id no longer in the graph.
5. **Rate-limit middleware on `POST /protocols/{id}/attachments`** — prevent rapid-fire upload abuse.
6. **Perceptual-hash CI gate for preview PNGs** — Layer 3 of the visual verification scheme; pinned LibreOffice version + pHash threshold.

---

## Pre-flight (one-time, in the worktree)

Before Task 1, in the worktree shell:

```bash
cd backend && source .venv/bin/activate
# verify Pillow + docxtpl present (already pinned in pyproject.toml)
python -c "import docxtpl, PIL; print(docxtpl.__version__, PIL.__version__)"
```

Expected: `0.18.0 11.x` or similar. If imports fail, run `poetry install --no-root` first.

---

## Task 1: `format_time_offset()` — minutes → display string

**Files:**
- Modify: `backend/app/services/data/graph_processing.py` (append a new public function)
- Test: `backend/tests/unit/services/data/test_graph_processing_time.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/services/data/test_graph_processing_time.py`:

```python
import pytest

from app.services.data.graph_processing import format_time_offset


@pytest.mark.parametrize(
    "minutes, expected",
    [
        (0, "T=0"),
        (1, "T=1m"),
        (15, "T=15m"),
        (59, "T=59m"),
        (60, "T=1h"),
        (75, "T=1h 15m"),
        (120, "T=2h"),
        (270, "T=4h 30m"),
        (24 * 60, "T=24h"),
        (24 * 60 + 30, "T=24h 30m"),
    ],
)
def test_format_time_offset_canonical_cases(minutes, expected):
    assert format_time_offset(minutes) == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/unit/services/data/test_graph_processing_time.py -v`
Expected: ImportError — `format_time_offset` not found.

- [ ] **Step 3: Implement `format_time_offset()`**

Append to `backend/app/services/data/graph_processing.py`:

```python
def format_time_offset(minutes: int) -> str:
    """Render a non-negative minute count as 'T=0' / 'T=15m' / 'T=4h 30m'.

    Reference offset only — computed at design time, not a record time
    captured on execution.
    """
    if minutes <= 0:
        return "T=0"
    if minutes < 60:
        return f"T={minutes}m"
    hours, mins = divmod(minutes, 60)
    if mins == 0:
        return f"T={hours}h"
    return f"T={hours}h {mins}m"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest backend/tests/unit/services/data/test_graph_processing_time.py -v`
Expected: PASS (10 cases).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/data/graph_processing.py backend/tests/unit/services/data/test_graph_processing_time.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): add format_time_offset minutes → display helper

Reference offset formatter for the SOP/Batch-Record step heading time
marker. Pure function; no graph traversal yet.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `compute_time_offsets()` — CPM over the protocol graph

**Files:**
- Modify: `backend/app/services/data/graph_processing.py`
- Test: `backend/tests/unit/services/data/test_graph_processing_time.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/services/data/test_graph_processing_time.py`:

```python
from app.services.data.graph_processing import compute_time_offsets


def _g(nodes, edges):
    return {"nodes": nodes, "edges": edges}


def _uo(node_id, dur):
    return {"id": node_id, "type": "unitOp", "data": {"duration_min": dur}}


def _e(src, tgt):
    return {"id": f"{src}->{tgt}", "source": src, "target": tgt}


def test_linear_chain_cumulative():
    g = _g([_uo("a", 10), _uo("b", 20), _uo("c", 5)],
           [_e("a", "b"), _e("b", "c")])
    offsets, warning = compute_time_offsets(g)
    assert warning is None
    assert offsets == {"a": 0, "b": 10, "c": 30}


def test_fan_out_shares_offset():
    g = _g([_uo("a", 10), _uo("b", 5), _uo("c", 5)],
           [_e("a", "b"), _e("a", "c")])
    offsets, _ = compute_time_offsets(g)
    assert offsets["b"] == 10
    assert offsets["c"] == 10


def test_fan_in_takes_max_predecessor():
    g = _g([_uo("a", 30), _uo("b", 10), _uo("c", 0)],
           [_e("a", "c"), _e("b", "c")])
    offsets, _ = compute_time_offsets(g)
    assert offsets["c"] == 30  # max(30, 10)


def test_disconnected_node_starts_at_zero():
    g = _g([_uo("a", 10), _uo("b", 5)], [])
    offsets, _ = compute_time_offsets(g)
    assert offsets == {"a": 0, "b": 0}


def test_cycle_returns_empty_with_warning():
    g = _g([_uo("a", 10), _uo("b", 5)],
           [_e("a", "b"), _e("b", "a")])
    offsets, warning = compute_time_offsets(g)
    assert offsets == {}
    assert warning == "cycle_detected"


def test_orphan_edge_ignored():
    g = _g([_uo("a", 10), _uo("b", 5)],
           [_e("a", "b"), _e("a", "ghost"), _e("ghost2", "b")])
    offsets, warning = compute_time_offsets(g)
    assert warning is None
    assert offsets == {"a": 0, "b": 10}


def test_negative_duration_coerced_to_zero():
    g = _g([_uo("a", -50), _uo("b", 5)], [_e("a", "b")])
    offsets, _ = compute_time_offsets(g)
    assert offsets == {"a": 0, "b": 0}


def test_absurd_duration_clamped_to_one_year():
    g = _g([_uo("a", 10**12), _uo("b", 0)], [_e("a", "b")])
    offsets, _ = compute_time_offsets(g)
    assert offsets["b"] == 60 * 24 * 365


def test_non_unitop_nodes_excluded():
    g = _g(
        [
            _uo("a", 10),
            {"id": "lane-1", "type": "swimLane", "data": {}},
            _uo("b", 5),
        ],
        [_e("a", "lane-1"), _e("lane-1", "b"), _e("a", "b")],
    )
    offsets, _ = compute_time_offsets(g)
    assert "lane-1" not in offsets
    assert offsets == {"a": 0, "b": 10}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/unit/services/data/test_graph_processing_time.py -v`
Expected: ImportError — `compute_time_offsets` not found.

- [ ] **Step 3: Implement `compute_time_offsets()`**

Append to `backend/app/services/data/graph_processing.py`:

```python
from collections import defaultdict, deque
import logging

logger = logging.getLogger(__name__)

_MAX_MINUTES = 60 * 24 * 365  # one year, decompression-style guard


def _coerce_duration(value: object) -> int:
    try:
        m = int(value or 0)
    except (TypeError, ValueError):
        return 0
    if m < 0:
        return 0
    if m > _MAX_MINUTES:
        return _MAX_MINUTES
    return m


def compute_time_offsets(graph: dict) -> tuple[dict[str, int], str | None]:
    """Earliest-start cumulative offsets for unitOp nodes (CPM).

    Returns ({node_id: minutes_from_start}, warning_or_None). Warning is
    ``"cycle_detected"`` when Kahn's algorithm cannot drain — the caller
    should render placeholders rather than silently falling back to 0.
    """
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    unit_op_ids: set[str] = set()
    duration: dict[str, int] = {}
    for n in nodes:
        if n.get("type") == "unitOp":
            nid = n.get("id")
            if not nid:
                continue
            unit_op_ids.add(nid)
            duration[nid] = _coerce_duration((n.get("data") or {}).get("duration_min"))

    predecessors: dict[str, list[str]] = defaultdict(list)
    successors: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {nid: 0 for nid in unit_op_ids}
    for e in edges:
        src = e.get("source")
        tgt = e.get("target")
        if src not in unit_op_ids or tgt not in unit_op_ids:
            continue
        predecessors[tgt].append(src)
        successors[src].append(tgt)
        in_degree[tgt] += 1

    queue: deque[str] = deque(nid for nid, d in in_degree.items() if d == 0)
    order: list[str] = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for s in successors[n]:
            in_degree[s] -= 1
            if in_degree[s] == 0:
                queue.append(s)

    if len(order) != len(unit_op_ids):
        unprocessed = [nid for nid, d in in_degree.items() if d > 0]
        logger.warning(
            "protocol_graph_cycle",
            extra={"cycle_nodes": unprocessed[:8]},
        )
        return ({}, "cycle_detected")

    offsets: dict[str, int] = {}
    for nid in order:
        preds = predecessors[nid]
        if not preds:
            offsets[nid] = 0
        else:
            offsets[nid] = max(offsets[p] + duration[p] for p in preds)
    return (offsets, None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/unit/services/data/test_graph_processing_time.py -v`
Expected: PASS (19 cases — 10 from Task 1, 9 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/data/graph_processing.py backend/tests/unit/services/data/test_graph_processing_time.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): add compute_time_offsets CPM walker

Topological earliest-start over unitOp nodes. Drops swimlane edges and
orphan endpoints. Clamps duration to [0, 1y] to guard against bad data.
Returns ('cycle_detected', {}) on cycles so the renderer prints T=? rather
than silently falling back to T=0.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `generate_default_doc_number()` — org-scoped SOP-NNNN

**Files:**
- Create: `backend/app/services/protocols/doc_number.py`
- Test: `backend/tests/integration/services/test_doc_number.py` (new — needs a real DB session)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/services/test_doc_number.py`:

```python
import asyncio
import uuid

import pytest

from app.models.protocols import Protocol
from app.services.protocols.doc_number import generate_default_doc_number


@pytest.mark.asyncio
async def test_first_protocol_in_org_gets_sop_0001(db_session, factory):
    org = await factory.organization()
    n = await generate_default_doc_number(db_session, org.id)
    assert n == "SOP-0001"


@pytest.mark.asyncio
async def test_sequence_increments_across_existing_protocols(db_session, factory):
    org = await factory.organization()
    await factory.protocol(owner_org_id=org.id, doc_number="SOP-0001")
    await factory.protocol(owner_org_id=org.id, doc_number="SOP-0002")
    n = await generate_default_doc_number(db_session, org.id)
    assert n == "SOP-0003"


@pytest.mark.asyncio
async def test_ignores_non_canonical_doc_numbers(db_session, factory):
    org = await factory.organization()
    await factory.protocol(owner_org_id=org.id, doc_number="CUSTOM-42")
    await factory.protocol(owner_org_id=org.id, doc_number="SOP-0007")
    n = await generate_default_doc_number(db_session, org.id)
    assert n == "SOP-0008"


@pytest.mark.asyncio
async def test_scope_is_per_org(db_session, factory):
    org_a = await factory.organization()
    org_b = await factory.organization()
    await factory.protocol(owner_org_id=org_a.id, doc_number="SOP-0005")
    n = await generate_default_doc_number(db_session, org_b.id)
    assert n == "SOP-0001"


@pytest.mark.asyncio
async def test_padding_holds_past_9999(db_session, factory):
    org = await factory.organization()
    await factory.protocol(owner_org_id=org.id, doc_number="SOP-9999")
    n = await generate_default_doc_number(db_session, org.id)
    assert n == "SOP-10000"  # natural overflow, no truncation
```

> **Note for the implementer:** if `factory.protocol` / `factory.organization` fixtures don't exist yet, check `backend/tests/conftest.py` for the actual fixture names. The convention in this repo is async factory fixtures returning the inserted ORM row. If the helper is named differently (e.g., `make_protocol`), adapt the test names — keep the assertions.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/integration/services/test_doc_number.py -v`
Expected: ImportError — `doc_number` module not found.

- [ ] **Step 3: Implement `generate_default_doc_number()`**

Create `backend/app/services/protocols/doc_number.py`:

```python
"""Auto-generate SOP-NNNN document numbers per organization.

Pattern mirrors the lock-then-pick approach we use elsewhere for monotonic
identifiers (cf. ``suggest_lot_number`` in ``api/endpoints/runs.py``). A
per-org Postgres advisory transaction lock serializes concurrent inserts
inside the same org without blocking other orgs; the lock releases at
commit/rollback automatically.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DOC_PATTERN = re.compile(r"^SOP-(\d+)$")


async def generate_default_doc_number(
    db: AsyncSession, owner_org_id: UUID
) -> str:
    """Return the next SOP-NNNN doc_number for the org.

    Caller is expected to be inside an open transaction so the advisory
    lock releases at commit. Run on Protocol create when the request body
    omits doc_number.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"sop_seq:{owner_org_id}"},
    )

    row = await db.execute(
        text(
            "SELECT max((regexp_replace(doc_number, '^SOP-0*', ''))::bigint) "
            "FROM protocols "
            "WHERE owner_org_id = :org "
            "AND doc_number ~ '^SOP-\\d+$'"
        ),
        {"org": owner_org_id},
    )
    current_max = row.scalar() or 0
    nxt = int(current_max) + 1
    return f"SOP-{nxt:04d}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/integration/services/test_doc_number.py -v`
Expected: PASS (5 cases).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/doc_number.py backend/tests/integration/services/test_doc_number.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): add per-org SOP-NNNN doc_number generator

Acquires a per-org advisory transaction lock, scans for the max numeric
suffix among canonical SOP-NNNN values, returns the next. Padding stays
4-wide up to 9999 and overflows naturally past that.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `validate_image_file()` — magic-byte + pixel-cap helper

**Files:**
- Modify: `backend/app/services/core/file_storage.py`
- Test: `backend/tests/unit/services/core/test_file_storage_validate.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/services/core/test_file_storage_validate.py`:

```python
import io
from pathlib import Path

import pytest
from PIL import Image

from app.services.core.file_storage import InvalidImage, validate_image_file


def _write_png(path: Path, w=10, h=10):
    Image.new("RGB", (w, h), color=(255, 0, 0)).save(path, format="PNG")


def _write_jpeg(path: Path, w=10, h=10):
    Image.new("RGB", (w, h), color=(0, 255, 0)).save(path, format="JPEG")


def test_valid_png_passes(tmp_path):
    p = tmp_path / "ok.png"
    _write_png(p)
    validate_image_file(p, "image/png")  # no raise


def test_valid_jpeg_passes(tmp_path):
    p = tmp_path / "ok.jpg"
    _write_jpeg(p)
    validate_image_file(p, "image/jpeg")  # no raise


def test_magic_byte_mismatch_rejected(tmp_path):
    p = tmp_path / "lies.jpg"
    _write_png(p)  # PNG bytes on disk
    with pytest.raises(InvalidImage):
        validate_image_file(p, "image/jpeg")


def test_corrupt_image_rejected(tmp_path):
    p = tmp_path / "corrupt.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nnotreallyapng")
    with pytest.raises(InvalidImage):
        validate_image_file(p, "image/png")


def test_pixel_cap_rejected(tmp_path):
    p = tmp_path / "huge.png"
    _write_png(p, w=10, h=10)
    with pytest.raises(InvalidImage):
        validate_image_file(p, "image/png", max_pixels=50)  # 100 > 50
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/unit/services/core/test_file_storage_validate.py -v`
Expected: ImportError — `validate_image_file` / `InvalidImage` not exported.

- [ ] **Step 3: Implement `validate_image_file()` and `InvalidImage`**

Append to `backend/app/services/core/file_storage.py`:

```python
class InvalidImage(Exception):
    """Raised when an uploaded file is not a usable image."""


_MIME_TO_PIL_FORMAT = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/tiff": "TIFF",
    "image/webp": "WEBP",
}


def validate_image_file(
    path: Path,
    declared_content_type: str,
    *,
    max_pixels: int = 25_000_000,
) -> None:
    """Confirm the file is an image of the declared type within pixel cap.

    Raises ``InvalidImage`` on magic-byte / declared-type mismatch, on a
    corrupt file PIL can't open, or when ``width * height`` exceeds
    ``max_pixels`` (decompression-bomb guard).
    """
    from PIL import Image, UnidentifiedImageError

    expected = _MIME_TO_PIL_FORMAT.get(declared_content_type)
    if expected is None:
        raise InvalidImage(f"Unsupported content type: {declared_content_type}")

    try:
        with Image.open(path) as img:
            if img.format != expected:
                raise InvalidImage(
                    f"Magic bytes report {img.format}, declared {expected}"
                )
            w, h = img.size
            if w * h > max_pixels:
                raise InvalidImage(
                    f"Image exceeds pixel cap: {w * h} > {max_pixels}"
                )
            img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImage(f"Unreadable image: {exc}") from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/unit/services/core/test_file_storage_validate.py -v`
Expected: PASS (5 cases).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core/file_storage.py backend/tests/unit/services/core/test_file_storage_validate.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): add validate_image_file magic-byte + pixel-cap guard

Re-usable helper for any future attachment surface (protocols today, runs
later). Catches PNG-pretending-to-be-JPEG, corrupt headers, and
decompression bombs over 25 MP.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `ProtocolAttachment` SQLAlchemy model + Pydantic schemas

**Files:**
- Modify: `backend/app/models/protocols.py` (append model)
- Modify: `backend/app/schemas/protocols.py` (append schemas)
- Test: `backend/tests/unit/models/test_protocol_attachment_model.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/models/test_protocol_attachment_model.py`:

```python
from app.models.protocols import ProtocolAttachment


def test_model_has_required_columns():
    cols = {c.name for c in ProtocolAttachment.__table__.columns}
    assert {
        "id", "protocol_id", "node_id", "filename", "file_path",
        "content_type", "size_bytes", "caption", "deleted",
        "uploaded_by_id", "created_at", "updated_at",
    }.issubset(cols)


def test_composite_index_on_protocol_id_node_id():
    idxs = ProtocolAttachment.__table__.indexes
    composite = [
        ix for ix in idxs
        if {c.name for c in ix.columns} == {"protocol_id", "node_id"}
    ]
    assert len(composite) == 1, "expected exactly one (protocol_id, node_id) index"


def test_no_standalone_protocol_id_index():
    """Composite covers leading column; standalone would be redundant."""
    idxs = ProtocolAttachment.__table__.indexes
    standalone = [
        ix for ix in idxs
        if {c.name for c in ix.columns} == {"protocol_id"}
    ]
    assert standalone == [], "composite index already covers protocol_id"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/unit/models/test_protocol_attachment_model.py -v`
Expected: ImportError — `ProtocolAttachment` not in `app.models.protocols`.

- [ ] **Step 3: Add the model**

Append to `backend/app/models/protocols.py`:

```python
class ProtocolAttachment(Base, UUIDMixin, TimestampMixin):
    """Per-unit-op figure attached to a Protocol. Renders inline under the
    matching step in the SOP / Batch Record."""

    __tablename__ = "protocol_attachments"

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("protocols.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    caption: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_protocol_attachments_protocol_node",
            "protocol_id",
            "node_id",
        ),
    )
```

Ensure `Boolean`, `Integer`, `String`, `Index`, `Optional`, `PG_UUID`, `ForeignKey`, `Mapped`, `mapped_column`, `UUIDMixin`, `TimestampMixin` are already imported at the top of the file (they are — check the existing `Protocol` model for proof).

- [ ] **Step 4: Add the Pydantic schemas**

Append to `backend/app/schemas/protocols.py`:

```python
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from uuid import UUID


class ProtocolAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    protocol_id: UUID
    node_id: str
    filename: str
    content_type: str
    size_bytes: int
    caption: str | None
    uploaded_by_id: UUID
    created_at: datetime


class ProtocolAttachmentCaptionPatch(BaseModel):
    caption: str | None = Field(default=None, max_length=500)
```

If imports are already present at the top of the file, skip the duplicate import lines.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest backend/tests/unit/models/test_protocol_attachment_model.py -v`
Expected: PASS (3 cases).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/protocols.py backend/app/schemas/protocols.py backend/tests/unit/models/test_protocol_attachment_model.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): add ProtocolAttachment model + caption schemas

Child table mirroring equipment_attachments. Composite (protocol_id,
node_id) index covers both the per-step render lookup and the per-protocol
list. Caption capped at 500 chars at the schema layer.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Alembic migration — `protocol_attachments` + doc_number index + backfill

**Files:**
- Create: `backend/alembic/versions/<rev>_bug0007_protocol_attachments_and_doc_number.py`

- [ ] **Step 1: Generate a fresh migration scaffold**

```bash
cd backend && source .venv/bin/activate
alembic revision -m "bug0007 protocol attachments and doc number"
```

Expected: a new file in `backend/alembic/versions/` with a generated revision id. Note the path and revision id.

- [ ] **Step 2: Author the upgrade — table + composite index + doc_number backfill + partial unique index**

Replace the generated file body with:

```python
"""bug0007 protocol attachments and doc number

Revision ID: <leave the generated id here>
Revises: <leave the generated down_revision here>
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "<generated>"
down_revision = "<generated>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1 — Create protocol_attachments.
    op.create_table(
        "protocol_attachments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "protocol_id",
            UUID(as_uuid=True),
            sa.ForeignKey("protocols.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("caption", sa.String(500), nullable=True),
        sa.Column(
            "deleted",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "uploaded_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_protocol_attachments_protocol_node",
        "protocol_attachments",
        ["protocol_id", "node_id"],
    )

    # Step 2 — Preflight existing duplicate doc_numbers per org.
    conn = op.get_bind()
    dups = conn.execute(
        sa.text(
            "SELECT owner_org_id, doc_number, count(*) c FROM protocols "
            "WHERE doc_number IS NOT NULL "
            "GROUP BY owner_org_id, doc_number HAVING count(*) > 1"
        )
    ).fetchall()
    if dups:
        raise RuntimeError(
            f"Cannot migrate: {len(dups)} existing duplicate (owner_org_id, "
            "doc_number) rows. Resolve manually before re-running this migration."
        )

    # Step 3 — Backfill NULL doc_numbers per-org in one atomic UPDATE.
    op.execute(
        sa.text(
            """
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
            """
        )
    )

    # Step 4 — Partial unique index, CONCURRENTLY so writes aren't blocked.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_protocols_owner_org_doc_number "
                "ON protocols (owner_org_id, doc_number) "
                "WHERE doc_number IS NOT NULL"
            )
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                "DROP INDEX CONCURRENTLY IF EXISTS "
                "ix_protocols_owner_org_doc_number"
            )
        )
    op.drop_index(
        "ix_protocol_attachments_protocol_node",
        table_name="protocol_attachments",
    )
    op.drop_table("protocol_attachments")
```

Leave `revision` / `down_revision` exactly as Alembic generated them.

- [ ] **Step 3: Apply the migration locally**

```bash
alembic upgrade head
```

Expected: `Running upgrade <prev_rev> -> <this_rev>, bug0007 protocol attachments and doc number`. No errors.

- [ ] **Step 4: Sanity-check the schema**

```bash
psql -U postgres -d batchrite -c "\d protocol_attachments" -c "\di ix_protocols_owner_org_doc_number"
```

Expected: table listing showing the columns and composite index; partial unique index reported with `WHERE (doc_number IS NOT NULL)`.

- [ ] **Step 5: Verify downgrade is clean (then re-upgrade)**

```bash
alembic downgrade -1 && alembic upgrade head
```

Expected: both succeed with no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/<your_new_rev>_*.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): migrate protocol_attachments + doc_number partial unique

Creates the protocol_attachments child table with the composite
(protocol_id, node_id) index. Backfills NULL doc_numbers per-org via a
single window-function UPDATE, then builds the partial unique index
CONCURRENTLY inside an autocommit block. Preflight aborts cleanly on any
existing same-org doc_number duplicate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Attachment endpoints — POST upload + `_get_attachment_or_404`

**Files:**
- Create: `backend/app/api/endpoints/protocol_attachments.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/integration/api/test_protocol_attachments_upload.py` (new)

- [ ] **Step 1: Write the failing upload tests**

Create `backend/tests/integration/api/test_protocol_attachments_upload.py`:

```python
import io

import pytest
from PIL import Image


def _png_bytes(w=10, h=10):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color=(0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_succeeds(client, auth_user, protocol):
    files = {"file": ("ok.png", _png_bytes(), "image/png")}
    data = {"node_id": "step-1"}
    r = await client.post(
        f"/protocols/{protocol.id}/attachments", files=files, data=data
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "ok.png"
    assert body["node_id"] == "step-1"
    assert body["content_type"] == "image/png"


@pytest.mark.asyncio
async def test_rejects_svg(client, auth_user, protocol):
    files = {"file": ("x.svg", b"<svg/>", "image/svg+xml")}
    r = await client.post(
        f"/protocols/{protocol.id}/attachments",
        files=files,
        data={"node_id": "step-1"},
    )
    assert r.status_code == 415
    assert r.json()["detail"] == "ATTACHMENT_UNSUPPORTED_TYPE"


@pytest.mark.asyncio
async def test_rejects_magic_byte_mismatch(client, auth_user, protocol):
    files = {"file": ("lies.jpg", _png_bytes(), "image/jpeg")}
    r = await client.post(
        f"/protocols/{protocol.id}/attachments",
        files=files,
        data={"node_id": "step-1"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "ATTACHMENT_INVALID_IMAGE"


@pytest.mark.asyncio
async def test_rejects_oversize(client, auth_user, protocol, monkeypatch):
    import app.api.endpoints.protocol_attachments as mod
    monkeypatch.setattr(mod, "MAX_FIGURE_SIZE_BYTES", 100)
    files = {"file": ("big.png", _png_bytes(w=200, h=200), "image/png")}
    r = await client.post(
        f"/protocols/{protocol.id}/attachments",
        files=files,
        data={"node_id": "step-1"},
    )
    assert r.status_code == 413
    assert r.json()["detail"] == "ATTACHMENT_TOO_LARGE"


@pytest.mark.asyncio
async def test_per_protocol_50_cap(client, auth_user, protocol, factory):
    for _ in range(50):
        await factory.protocol_attachment(protocol_id=protocol.id)
    files = {"file": ("late.png", _png_bytes(), "image/png")}
    r = await client.post(
        f"/protocols/{protocol.id}/attachments",
        files=files,
        data={"node_id": "step-1"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "ATTACHMENT_LIMIT_REACHED"
```

> **Note for the implementer:** if `factory.protocol_attachment` doesn't exist yet, add a fixture to `backend/tests/conftest.py` that inserts a minimal `ProtocolAttachment` row.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/integration/api/test_protocol_attachments_upload.py -v`
Expected: 404 on every test — router not mounted.

- [ ] **Step 3: Implement the POST endpoint + `_get_attachment_or_404`**

Create `backend/app/api/endpoints/protocol_attachments.py`:

```python
"""Protocol-level figure attachments — upload / patch / delete / stream."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.core.permissions import (
    ObjectType,
    PermissionLevel,
    require_permission,
)
from app.models.protocols import ProtocolAttachment
from app.models.users import User
from app.schemas.protocols import ProtocolAttachmentResponse
from app.services.core.audit import log_audit
from app.services.core.file_storage import (
    IMAGE_MIME_TYPES,
    InvalidImage,
    file_storage_service,
    validate_image_file,
)

router = APIRouter(prefix="/protocols/{protocol_id}/attachments")
logger = logging.getLogger(__name__)

MAX_FIGURE_SIZE_BYTES = 10 * 1024 * 1024
PER_PROTOCOL_LIMIT = 50


async def _get_attachment_or_404(
    db: AsyncSession, protocol_id: UUID, attachment_id: UUID
) -> ProtocolAttachment:
    row = await db.scalar(
        select(ProtocolAttachment).where(
            ProtocolAttachment.id == attachment_id,
            ProtocolAttachment.protocol_id == protocol_id,
            ProtocolAttachment.deleted.is_(False),
        )
    )
    if row is None:
        raise HTTPException(404, detail="attachment_not_found")
    return row


@router.post("", response_model=ProtocolAttachmentResponse)
async def upload_attachment(
    protocol_id: UUID,
    file: UploadFile = File(...),
    node_id: str = Form(...),
    caption: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(
        require_permission(ObjectType.PROTOCOL, "protocol_id", PermissionLevel.EDIT)
    ),
) -> ProtocolAttachmentResponse:
    if file.content_type not in IMAGE_MIME_TYPES:
        raise HTTPException(415, detail="ATTACHMENT_UNSUPPORTED_TYPE")

    payload = await file.read()
    if len(payload) > MAX_FIGURE_SIZE_BYTES:
        raise HTTPException(413, detail="ATTACHMENT_TOO_LARGE")

    if caption is not None and len(caption) > 500:
        raise HTTPException(422, detail="ATTACHMENT_CAPTION_TOO_LONG")

    count = await db.scalar(
        select(func.count())
        .select_from(ProtocolAttachment)
        .where(
            ProtocolAttachment.protocol_id == protocol_id,
            ProtocolAttachment.deleted.is_(False),
        )
    )
    if (count or 0) >= PER_PROTOCOL_LIMIT:
        raise HTTPException(422, detail="ATTACHMENT_LIMIT_REACHED")

    stored = await file_storage_service.store_bytes(
        payload,
        filename=file.filename or "upload",
        base_dir="protocols",
        org_id=user.organization_id,
        path_segments=[str(protocol_id), "attachments", uuid4().hex],
    )

    try:
        validate_image_file(stored.absolute_path, file.content_type)
    except InvalidImage as exc:
        file_storage_service.delete_file(stored.relative_path)
        logger.warning("attachment_invalid_image", extra={"reason": str(exc)})
        raise HTTPException(422, detail="ATTACHMENT_INVALID_IMAGE") from exc

    row = ProtocolAttachment(
        protocol_id=protocol_id,
        node_id=node_id,
        filename=file.filename or "upload",
        file_path=stored.relative_path,
        content_type=file.content_type,
        size_bytes=len(payload),
        caption=caption,
        uploaded_by_id=user.id,
    )
    db.add(row)
    await db.flush()

    await log_audit(
        db,
        actor_id=user.id,
        action="attachment.upload",
        entity_type="protocol",
        entity_id=protocol_id,
        changes={
            "attachment_id": str(row.id),
            "filename": row.filename,
            "size_bytes": row.size_bytes,
            "node_id": row.node_id,
        },
    )
    await db.commit()
    await db.refresh(row)
    return ProtocolAttachmentResponse.model_validate(row)
```

> **Note for the implementer:** if `file_storage_service.store_bytes(...)` does not exist, check the actual signature exported from `core/file_storage.py`. The repo's existing `store_file(UploadFile, ...)` reads `await file.read()` internally — adapt the call to whichever signature is on disk, preserving the same final structure (`base_dir`, `org_id`, `path_segments`).

- [ ] **Step 4: Wire the router**

Edit `backend/app/main.py` near the existing `app.include_router(protocol_pdfs.router, ...)` line:

```python
from app.api.endpoints import protocol_attachments
...
app.include_router(protocol_attachments.router, tags=["protocol-attachments"])
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest backend/tests/integration/api/test_protocol_attachments_upload.py -v`
Expected: PASS (5 cases).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/protocol_attachments.py backend/app/main.py backend/tests/integration/api/test_protocol_attachments_upload.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): add protocol attachment upload endpoint

POST /protocols/{id}/attachments. Reject svg+xml explicitly, magic-byte
verify after write, hard cap 10MB / 50-per-protocol / 500-char caption.
Stable error codes for the UI to branch on. Shared
_get_attachment_or_404 helper added for the PATCH/DELETE/stream paths.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: PATCH caption + DELETE + GET-stream endpoints

**Files:**
- Modify: `backend/app/api/endpoints/protocol_attachments.py`
- Test: `backend/tests/integration/api/test_protocol_attachments_lifecycle.py` (new)

- [ ] **Step 1: Write the failing lifecycle tests**

Create `backend/tests/integration/api/test_protocol_attachments_lifecycle.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_patch_caption_updates_row(client, auth_user, protocol, factory):
    att = await factory.protocol_attachment(protocol_id=protocol.id, caption=None)
    r = await client.patch(
        f"/protocols/{protocol.id}/attachments/{att.id}",
        json={"caption": "Vessel A — pre-stir"},
    )
    assert r.status_code == 200
    assert r.json()["caption"] == "Vessel A — pre-stir"


@pytest.mark.asyncio
async def test_patch_caption_over_500_rejected(client, auth_user, protocol, factory):
    att = await factory.protocol_attachment(protocol_id=protocol.id)
    r = await client.patch(
        f"/protocols/{protocol.id}/attachments/{att.id}",
        json={"caption": "x" * 501},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_soft_deletes_and_removes_file(
    client, auth_user, protocol, factory, storage_root
):
    att = await factory.protocol_attachment(protocol_id=protocol.id)
    on_disk = storage_root / att.file_path
    assert on_disk.exists()
    r = await client.delete(f"/protocols/{protocol.id}/attachments/{att.id}")
    assert r.status_code == 204
    assert not on_disk.exists()
    # Subsequent stream returns 404
    r2 = await client.get(f"/protocols/{protocol.id}/attachments/{att.id}/file")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_stream_returns_image(client, auth_user, protocol, factory):
    att = await factory.protocol_attachment(protocol_id=protocol.id)
    r = await client.get(f"/protocols/{protocol.id}/attachments/{att.id}/file")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert "filename*=UTF-8''" in r.headers["content-disposition"]


@pytest.mark.asyncio
async def test_idor_cross_protocol_returns_404(
    client, auth_user, factory
):
    p_a = await factory.protocol()
    p_b = await factory.protocol()
    att_b = await factory.protocol_attachment(protocol_id=p_b.id)
    r = await client.get(f"/protocols/{p_a.id}/attachments/{att_b.id}/file")
    assert r.status_code == 404
    r2 = await client.patch(
        f"/protocols/{p_a.id}/attachments/{att_b.id}", json={"caption": "x"}
    )
    assert r2.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/integration/api/test_protocol_attachments_lifecycle.py -v`
Expected: 404/405 across the board — endpoints not yet implemented.

- [ ] **Step 3: Implement PATCH / DELETE / GET-stream**

Append to `backend/app/api/endpoints/protocol_attachments.py`:

```python
from urllib.parse import quote

from fastapi import Response
from fastapi.responses import StreamingResponse

from app.schemas.protocols import ProtocolAttachmentCaptionPatch


@router.patch("/{attachment_id}", response_model=ProtocolAttachmentResponse)
async def patch_attachment_caption(
    protocol_id: UUID,
    attachment_id: UUID,
    body: ProtocolAttachmentCaptionPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(
        require_permission(ObjectType.PROTOCOL, "protocol_id", PermissionLevel.EDIT)
    ),
) -> ProtocolAttachmentResponse:
    if body.caption is not None and len(body.caption) > 500:
        raise HTTPException(422, detail="ATTACHMENT_CAPTION_TOO_LONG")

    row = await _get_attachment_or_404(db, protocol_id, attachment_id)
    before = row.caption
    row.caption = body.caption
    await db.flush()

    await log_audit(
        db,
        actor_id=user.id,
        action="attachment.caption_edit",
        entity_type="protocol",
        entity_id=protocol_id,
        changes={
            "attachment_id": str(row.id),
            "before": before,
            "after": row.caption,
        },
    )
    await db.commit()
    await db.refresh(row)
    return ProtocolAttachmentResponse.model_validate(row)


@router.delete("/{attachment_id}", status_code=204)
async def delete_attachment(
    protocol_id: UUID,
    attachment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(
        require_permission(ObjectType.PROTOCOL, "protocol_id", PermissionLevel.EDIT)
    ),
) -> Response:
    row = await _get_attachment_or_404(db, protocol_id, attachment_id)
    row.deleted = True
    file_storage_service.delete_file(row.file_path)
    await db.flush()
    await log_audit(
        db,
        actor_id=user.id,
        action="attachment.delete",
        entity_type="protocol",
        entity_id=protocol_id,
        changes={"attachment_id": str(row.id), "filename": row.filename},
    )
    await db.commit()
    return Response(status_code=204)


@router.get("/{attachment_id}/file")
async def stream_attachment(
    protocol_id: UUID,
    attachment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(
        require_permission(ObjectType.PROTOCOL, "protocol_id", PermissionLevel.VIEW)
    ),
) -> StreamingResponse:
    row = await _get_attachment_or_404(db, protocol_id, attachment_id)
    path = file_storage_service.resolve_path(row.file_path)
    quoted = quote(row.filename, safe="")
    headers = {
        "Content-Disposition": (
            f"inline; filename*=UTF-8''{quoted}"
        )
    }

    def _iter():
        with path.open("rb") as fh:
            while chunk := fh.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        _iter(), media_type=row.content_type, headers=headers
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/integration/api/test_protocol_attachments_lifecycle.py -v`
Expected: PASS (5 cases).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/protocol_attachments.py backend/tests/integration/api/test_protocol_attachments_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): add PATCH/DELETE/stream for protocol attachments

All three route through _get_attachment_or_404 — (protocol_id,
attachment_id) scoped lookups make IDOR-by-shared-UUID impossible. DELETE
hard-removes the underlying file in addition to flipping deleted=True so
upload+delete loops can't fill disk. Caption PATCH audit records
before/after to keep the regulated trail intact.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Wire `doc_number` into Protocol create + 409 surfacing

**Files:**
- Modify: `backend/app/api/endpoints/protocols.py`
- Modify: `backend/app/schemas/protocols.py`
- Test: `backend/tests/integration/api/test_protocol_doc_number_create.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/api/test_protocol_doc_number_create.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_create_without_doc_number_auto_generates(client, auth_user, project):
    r = await client.post(
        "/protocols",
        json={"name": "Auto-numbered", "project_id": str(project.id)},
    )
    assert r.status_code == 201
    assert r.json()["doc_number"] == "SOP-0001"


@pytest.mark.asyncio
async def test_create_with_doc_number_preserved(client, auth_user, project):
    r = await client.post(
        "/protocols",
        json={
            "name": "Custom-numbered",
            "project_id": str(project.id),
            "doc_number": "CUSTOM-42",
        },
    )
    assert r.status_code == 201
    assert r.json()["doc_number"] == "CUSTOM-42"


@pytest.mark.asyncio
async def test_create_duplicate_returns_409(client, auth_user, project, factory):
    await factory.protocol(
        owner_org_id=auth_user.organization_id, doc_number="DUP-1", name="First"
    )
    r = await client.post(
        "/protocols",
        json={
            "name": "Second",
            "project_id": str(project.id),
            "doc_number": "DUP-1",
        },
    )
    assert r.status_code == 409
    body = r.json()
    assert body["detail"] == "doc_number_in_use"
    assert body["conflicting_doc_number"] == "DUP-1"
    assert body["conflicting_protocol_name"] == "First"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/integration/api/test_protocol_doc_number_create.py -v`
Expected: third test 500 (IntegrityError leak) or first/second wrong shape.

- [ ] **Step 3: Update `ProtocolCreate` to allow optional doc_number**

In `backend/app/schemas/protocols.py`, the existing `ProtocolCreate` model — confirm `doc_number: str | None = None` is present; if not, add it.

- [ ] **Step 4: Wire generator into the create endpoint**

In `backend/app/api/endpoints/protocols.py`, inside the existing `create_protocol`:

```python
from sqlalchemy.exc import IntegrityError
from app.services.protocols.doc_number import generate_default_doc_number

# ... after resolving owner_org_id but before db.add(new_protocol):
if not protocol_in.doc_number:
    protocol_in_doc_number = await generate_default_doc_number(db, owner_org_id)
else:
    protocol_in_doc_number = protocol_in.doc_number

# ... when constructing the Protocol row, use protocol_in_doc_number for doc_number=

try:
    await db.commit()
except IntegrityError as exc:
    await db.rollback()
    if "ix_protocols_owner_org_doc_number" in str(exc.orig):
        existing = await db.scalar(
            select(Protocol).where(
                Protocol.owner_org_id == owner_org_id,
                Protocol.doc_number == protocol_in_doc_number,
            )
        )
        raise HTTPException(
            status_code=409,
            detail={
                "detail": "doc_number_in_use",
                "conflicting_doc_number": protocol_in_doc_number,
                "conflicting_protocol_name": existing.name if existing else None,
            },
        ) from exc
    raise
```

> **Note for the implementer:** the existing `create_protocol` function in `protocols.py` will already commit and refresh. Restructure to (a) generate the default *before* commit, (b) wrap the commit in the IntegrityError try/except. Don't duplicate the existing commit.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest backend/tests/integration/api/test_protocol_doc_number_create.py -v`
Expected: PASS (3 cases).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/endpoints/protocols.py backend/app/schemas/protocols.py backend/tests/integration/api/test_protocol_doc_number_create.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): auto-generate doc_number on Protocol create

Generator runs only when the caller omits doc_number. IntegrityError on
the partial unique index converts to 409 with the conflicting
protocol_name so the UI can render an actionable inline error.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: One-time template rewriter — `scripts/rewrite_sop_step_tables.py`

**Files:**
- Create: `backend/scripts/rewrite_sop_step_tables.py`
- Test: `backend/tests/integration/test_rewrite_sop_idempotent.py` (new)
- Modify: `.gitattributes` (add `.docx` LFS line)

- [ ] **Step 1: Add the `.docx` LFS line**

Edit (or create) the repo root `.gitattributes`:

```
*.docx filter=lfs diff=lfs merge=lfs -text
*.pdf  filter=lfs diff=lfs merge=lfs -text
*.png  filter=lfs diff=lfs merge=lfs -text
```

```bash
git lfs install
git add .gitattributes
git commit -m "chore(BUG-0007): track .docx/.pdf/.png via git LFS for templates and previews"
```

- [ ] **Step 2: Write the failing idempotency test**

Create `backend/tests/integration/test_rewrite_sop_idempotent.py`:

```python
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "rewrite_sop_step_tables.py"
TEMPLATE = REPO / "app" / "services" / "documents" / "templates" / "sop_default.docx"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_rewrite_script_is_idempotent(tmp_path):
    # Copy the post-rewrite template into a sandbox and run the script twice.
    sandbox = tmp_path / "sop_default.docx"
    shutil.copyfile(TEMPLATE, sandbox)
    subprocess.run(
        ["python", str(SCRIPT), str(sandbox)], check=True, capture_output=True
    )
    after_first = _sha(sandbox)
    subprocess.run(
        ["python", str(SCRIPT), str(sandbox)], check=True, capture_output=True
    )
    after_second = _sha(sandbox)
    assert after_first == after_second, "second run must be a no-op"


def test_rewrite_drops_step_tables():
    """The committed template should have no <w:tbl> with the Step/Name/
    Instruction/Duration header signature."""
    import zipfile
    with zipfile.ZipFile(TEMPLATE) as z:
        body = z.read("word/document.xml").decode("utf-8")
    assert "Instruction" not in body or "{%tr for step" not in body, (
        "step-table signature still present in committed template"
    )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest backend/tests/integration/test_rewrite_sop_idempotent.py -v`
Expected: FileNotFoundError for the script.

- [ ] **Step 4: Author the rewrite script**

Create `backend/scripts/rewrite_sop_step_tables.py`. Use the derisked source at `/tmp/rewrite_template_to_sections.py` as the starting point (it is the proven version that produced the user-approved preview). Required behaviors, in addition to the derisked source:

1. Accept the target `.docx` path as `sys.argv[1]`.
2. Before applying changes, detect whether the file is already rewritten by checking that **no** `<w:tbl>` in the body has a first-row header signature matching either `("Step", "Name", "Instruction", "Duration")` or `("Time Target", "Action", "Expected Output / Log")`. If both are absent, print `no-op: template already in section-per-step form` and `sys.exit(0)`.
3. After the rewrite, count the paragraphs whose text contains `{{ role.process_name or role.name }}` or `{{ tp.name }}`. If the count is zero, print an error and `sys.exit(1)`.
4. Save the rewritten doc back to the same path.

```python
"""Rewrite SOP/Batch-Record step-tables into section-per-step paragraphs.

Idempotent — running twice in a row is a no-op the second time.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


# (Copy verbatim from /tmp/rewrite_template_to_sections.py:)
# - insert_paragraph_before_element(...)
# - build_capture_table_before(...) [you can drop this — capture rows aren't used]
# - remove_table(...)
# - replace_step_table_with_sections(...)
# - ROLE_HEADING_MARKERS
# - restyle_role_headings_and_unify_spacing(...)


def _is_already_rewritten(doc) -> bool:
    for t in doc.tables:
        headers = tuple(c.text.strip() for c in t.rows[0].cells)
        if headers == ("Step", "Name", "Instruction", "Duration"):
            return False
        if headers[:3] == ("Time Target", "Action", "Expected Output / Log"):
            return False
    return True


def _count_marker_paragraphs(doc) -> int:
    body = doc.element.body
    count = 0
    for p in body.iter(qn("w:p")):
        text = "".join(
            (t.text or "") for t in p.findall(".//" + qn("w:t"))
        )
        if any(m in text for m in ROLE_HEADING_MARKERS):
            count += 1
    return count


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: rewrite_sop_step_tables.py <path-to-docx>", file=sys.stderr)
        return 2
    target = Path(sys.argv[1])
    doc = Document(target)
    if _is_already_rewritten(doc):
        print(f"no-op: template already in section-per-step form: {target}")
        return 0

    # (rewrite tables and restyle, verbatim from the derisked source)

    if _count_marker_paragraphs(doc) == 0:
        print(
            "ERROR: rewritten template has zero role/time-point marker "
            "paragraphs — restyle will silently no-op at render time.",
            file=sys.stderr,
        )
        return 1

    doc.save(target)
    print(f"rewrote: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The derisked source is the authoritative reference for the body of `replace_step_table_with_sections` and `restyle_role_headings_and_unify_spacing` — drop in those functions byte-for-byte from `/tmp/rewrite_template_to_sections.py`.

- [ ] **Step 5: Run the script on the four committed templates**

```bash
cd backend
python scripts/rewrite_sop_step_tables.py app/services/documents/templates/sop_default.docx
python scripts/rewrite_sop_step_tables.py app/services/documents/templates/batch_record_default.docx
python scripts/rewrite_sop_step_tables.py uploads/system/document_templates/sop_default.docx
python scripts/rewrite_sop_step_tables.py uploads/system/document_templates/batch_record_default.docx
```

Expected: each prints `rewrote: …`. Re-running prints `no-op: template already in section-per-step form: …`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest backend/tests/integration/test_rewrite_sop_idempotent.py -v`
Expected: PASS (2 cases).

- [ ] **Step 7: Commit script + rewritten binaries together**

```bash
git add backend/scripts/rewrite_sop_step_tables.py \
        backend/tests/integration/test_rewrite_sop_idempotent.py \
        backend/app/services/documents/templates/sop_default.docx \
        backend/app/services/documents/templates/batch_record_default.docx \
        backend/uploads/system/document_templates/sop_default.docx \
        backend/uploads/system/document_templates/batch_record_default.docx
git commit -m "$(cat <<'EOF'
feat(BUG-0007): section-per-step .docx templates + idempotent rewriter

The four SOP/Batch-Record templates are rewritten in place: step-tables
become bold-heading + body-text paragraphs with optional inline figures;
role headings restyled to 16pt bold black; double line spacing across the
body. The script is checked in for reproducibility and is idempotent —
running it again on a rewritten template is a no-op. Templates tracked
via git LFS.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Template-pair hash parity test

**Files:**
- Create: `backend/tests/integration/test_template_parity.py`

- [ ] **Step 1: Write the test**

Create `backend/tests/integration/test_template_parity.py`:

```python
import hashlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO / "app" / "services" / "documents" / "templates"
SEEDED_DIR = REPO / "uploads" / "system" / "document_templates"


@pytest.mark.parametrize("name", ["sop_default.docx", "batch_record_default.docx"])
def test_template_pairs_identical(name):
    a = hashlib.sha256((TEMPLATES_DIR / name).read_bytes()).hexdigest()
    b = hashlib.sha256((SEEDED_DIR / name).read_bytes()).hexdigest()
    assert a == b, f"{name}: templates/ ({a[:8]}) != uploads/ ({b[:8]})"
```

- [ ] **Step 2: Run the test**

Run: `pytest backend/tests/integration/test_template_parity.py -v`
Expected: PASS (2 cases — Task 10 produced identical pairs).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_template_parity.py
git commit -m "$(cat <<'EOF'
test(BUG-0007): SHA-256 parity gate across .docx template pairs

Catches the failure mode where a contributor edits one copy (templates/
or uploads/system/document_templates/) and forgets the other — production
serves the seeded copy, dev defaults serve the template copy, so silent
drift would skew the rendered output by environment.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Unified `_swap_file_path_to_inline_image()` helper

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py`
- Test: `backend/tests/unit/services/protocols/test_swap_file_path.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/services/protocols/test_swap_file_path.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.protocols.template_engine import _swap_file_path_to_inline_image


def test_missing_file_sets_image_ok_false(tmp_path):
    figs = [{"_file_path": str(tmp_path / "nope.png"), "filename": "nope.png"}]
    doc = MagicMock()
    _swap_file_path_to_inline_image(figs, doc, width=MagicMock())
    assert figs[0]["image_ok"] is False
    assert "missing" in figs[0]["image"].lower()


def test_no_file_path_key_skips_silently():
    figs = [{"filename": "x.png"}]
    _swap_file_path_to_inline_image(figs, MagicMock(), width=MagicMock())
    assert "image" not in figs[0]


def test_empty_list_is_noop():
    _swap_file_path_to_inline_image([], MagicMock(), width=MagicMock())


def test_real_image_sets_image_ok_true(tmp_path):
    from PIL import Image
    p = tmp_path / "ok.png"
    Image.new("RGB", (10, 10)).save(p, format="PNG")
    figs = [{"_file_path": str(p), "filename": "ok.png"}]
    doc = MagicMock()
    # Replace docxtpl.InlineImage with a sentinel so we don't need a real DocxTemplate
    from app.services.protocols import template_engine as te
    sentinel = object()
    monkey_patcher = te.InlineImage  # save
    te.InlineImage = lambda d, p, width: sentinel
    try:
        _swap_file_path_to_inline_image(figs, doc, width=MagicMock())
    finally:
        te.InlineImage = monkey_patcher
    assert figs[0]["image"] is sentinel
    assert figs[0]["image_ok"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/unit/services/protocols/test_swap_file_path.py -v`
Expected: ImportError — `_swap_file_path_to_inline_image` not exported.

- [ ] **Step 3: Replace the existing swap with the unified helper**

In `backend/app/services/protocols/template_engine.py`, find the existing figure swap loop (around lines 726–741) inside `render_to_docx()` and replace its body with calls to a new module-level helper. Add the helper above `render_to_docx`:

```python
def _swap_file_path_to_inline_image(
    figs: list[dict],
    doc: "DocxTemplate",
    *,
    width,
) -> None:
    """Swap each ``_file_path`` placeholder for an InlineImage.

    On a missing file or unreadable image, set ``image_ok=False`` and put
    a text placeholder in ``image`` so the template renders a graceful
    fallback caption.
    """
    for fig in figs or []:
        fpath_str = fig.pop("_file_path", None)
        if not fpath_str:
            continue
        fpath = Path(fpath_str)
        try:
            fig["image"] = InlineImage(doc, str(fpath), width=width)
            fig["image_ok"] = True
        except FileNotFoundError:
            fig["image"] = f"[Figure file missing: {fig.get('filename', 'unknown')}]"
            fig["image_ok"] = False
            logger.warning("inline_image_missing", extra={"file_path": str(fpath)})
        except Exception as exc:
            fig["image"] = f"[Figure unreadable: {fig.get('filename', 'unknown')}]"
            fig["image_ok"] = False
            logger.warning(
                "inline_image_failed",
                extra={"file_path": str(fpath), "error": str(exc)},
            )
```

Replace the existing inline swap block at the end of `render_to_docx()` with:

```python
from docx.shared import Inches, Mm

_swap_file_path_to_inline_image(
    context.get("figures") or [], doc, width=Mm(150)
)
_swap_file_path_to_inline_image(
    context.get("non_image_attachments") or [], doc, width=Mm(150)
)
for step in (context.get("steps") or []):
    _swap_file_path_to_inline_image(
        step.get("figures") or [], doc, width=Inches(5.5)
    )
for role in (context.get("roles") or []):
    for step in (role.get("steps") or []):
        _swap_file_path_to_inline_image(
            step.get("figures") or [], doc, width=Inches(5.5)
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/unit/services/protocols/test_swap_file_path.py -v`
Expected: PASS (4 cases).

Also run the existing template_engine test suite to confirm no regression:

Run: `pytest backend/tests/unit/services/protocols/ -v`
Expected: PASS (existing tests stay green).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/template_engine.py backend/tests/unit/services/protocols/test_swap_file_path.py
git commit -m "$(cat <<'EOF'
refactor(BUG-0007): unify figure file-path → InlineImage swap

One helper, called for top-level figures (Mm(150)), non-image attachments
(Mm(150)), and per-step inline figures (Inches(5.5)). Missing files /
unreadable images set image_ok=False so the template renders 'Figure N —
unavailable' rather than a misleading placeholder caption.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: `build_context()` — doc_number, time_enabled, time_offset, per-step figures

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py`
- Test: `backend/tests/unit/services/protocols/test_build_context_bug0007.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/services/protocols/test_build_context_bug0007.py`:

```python
from types import SimpleNamespace

import pytest

from app.services.protocols.template_engine import build_context


def _protocol(*, doc_number="SOP-0042", graph=None):
    return SimpleNamespace(
        id="proto-1",
        name="P",
        description="",
        doc_number=doc_number,
        graph=graph or {"nodes": [], "edges": [], "timeEnabled": False},
        owner_org_id="org-1",
    )


def _step(node_id, name, dur):
    return {
        "id": node_id, "type": "unitOp",
        "data": {"label": name, "duration_min": dur},
    }


def test_doc_number_threaded_into_context():
    ctx, _ = build_context(_protocol(doc_number="SOP-0099"))
    assert ctx["doc_number"] == "SOP-0099"


def test_time_enabled_false_by_default():
    ctx, _ = build_context(_protocol())
    assert ctx["time_enabled"] is False


def test_time_enabled_threaded_when_graph_says_so():
    g = {
        "nodes": [_step("a", "Buffer Prep", 30), _step("b", "Thaw", 15)],
        "edges": [{"id": "e", "source": "a", "target": "b"}],
        "timeEnabled": True,
    }
    ctx, _ = build_context(_protocol(graph=g))
    assert ctx["time_enabled"] is True
    # step_a is T=0, step_b is T=30m
    steps = ctx["steps"]
    assert {s.get("time_offset") for s in steps} == {"T=0", "T=30m"}


def test_attachments_grouped_by_node_id():
    g = {
        "nodes": [_step("a", "S1", 10), _step("b", "S2", 5)],
        "edges": [],
        "timeEnabled": False,
    }
    attachments_by_node = {
        "a": [
            SimpleNamespace(
                id="att-1", filename="f1.png", caption=None, file_path="x/1"
            ),
            SimpleNamespace(
                id="att-2", filename="f2.png", caption="caption2",
                file_path="x/2",
            ),
        ],
        "b": [
            SimpleNamespace(
                id="att-3", filename="f3.png", caption=None, file_path="x/3"
            ),
        ],
    }
    ctx, _ = build_context(
        _protocol(graph=g), attachments_by_node=attachments_by_node
    )
    figs_a = next(s["figures"] for s in ctx["steps"] if s["data"]["label"] == "S1")
    figs_b = next(s["figures"] for s in ctx["steps"] if s["data"]["label"] == "S2")
    assert [f["number"] for f in figs_a] == [1, 2]
    assert [f["number"] for f in figs_b] == [3]
    assert figs_a[0]["caption"] == "f1.png"  # filename fallback
    assert figs_a[1]["caption"] == "caption2"


def test_cycle_in_graph_sets_time_warning():
    g = {
        "nodes": [_step("a", "S1", 10), _step("b", "S2", 5)],
        "edges": [
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "a"},
        ],
        "timeEnabled": True,
    }
    ctx, _ = build_context(_protocol(graph=g))
    assert ctx["time_warning"] == "cycle_detected"
    assert all(s.get("time_offset") == "T=?" for s in ctx["steps"])
```

> **Note for the implementer:** `build_context` already exists with a specific signature. Find it in `template_engine.py` and read its current shape. Extend it to:
> 1. Accept an optional keyword arg `attachments_by_node: dict[str, list] | None = None`.
> 2. Read `protocol.doc_number` and inject into the context.
> 3. Read `protocol.graph.timeEnabled`, call `compute_time_offsets`, format each step's `time_offset`.
> 4. On cycle, set `time_warning="cycle_detected"` and stamp every step's `time_offset = "T=?"`.
> 5. Walk steps in stable order (role.steps in role iteration order; bare `steps` otherwise) and attach `figures: [{number, filename, caption, _file_path}, ...]` using a single document-global `itertools.count(1)`.
> 6. Caption fallback: `caption = attachment.caption or attachment.filename`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/unit/services/protocols/test_build_context_bug0007.py -v`
Expected: KeyError / AttributeError on `doc_number`, `time_enabled`, `figures`.

- [ ] **Step 3: Extend `build_context()`**

In `backend/app/services/protocols/template_engine.py`, modify `build_context` per the implementer note above. Key code to add (adapt names to the actual existing function shape):

```python
import itertools
from app.services.data.graph_processing import (
    compute_time_offsets,
    format_time_offset,
)
from app.services.core.file_storage import file_storage_service

def build_context(
    protocol,
    ...,
    attachments_by_node: dict[str, list] | None = None,
):
    attachments_by_node = attachments_by_node or {}
    graph = protocol.graph or {}
    time_enabled = bool(graph.get("timeEnabled"))
    offsets, warning = compute_time_offsets(graph)

    fig_counter = itertools.count(1)

    def _step_ctx(step_node: dict) -> dict:
        nid = step_node["id"]
        if warning == "cycle_detected":
            tof = "T=?"
        else:
            tof = format_time_offset(offsets.get(nid, 0))
        figs = []
        for att in attachments_by_node.get(nid, []):
            figs.append({
                "number": next(fig_counter),
                "filename": att.filename,
                "caption": att.caption or att.filename,
                "_file_path": str(
                    file_storage_service.resolve_path(att.file_path)
                ),
            })
        step = {
            **step_node,
            "time_offset": tof,
            "figures": figs,
        }
        return step

    # (Inside the existing steps/roles assembly, replace step dicts with _step_ctx(node).)

    ctx = {
        # ... existing keys ...
        "doc_number": protocol.doc_number,
        "time_enabled": time_enabled,
    }
    if warning:
        ctx["time_warning"] = warning
    return ctx, unresolved  # preserve existing return shape
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/unit/services/protocols/test_build_context_bug0007.py -v`
Expected: PASS (5 cases).

Also re-run all of `tests/unit/services/protocols/` to catch regressions:

Run: `pytest backend/tests/unit/services/protocols/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/template_engine.py backend/tests/unit/services/protocols/test_build_context_bug0007.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): thread doc_number, time markers, per-step figures into context

build_context now injects doc_number, time_enabled, per-step time_offset
(or 'T=?' on cycle), and a per-step figures list with a single
document-global figure counter. Captions fall back to filename when the
upload didn't supply one. Render pipeline reads attachments via the
existing pre-fetch dict keyed by node_id — no DB access inside the sync
build_context call.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: `protocol_pdfs.py` — bulk attachment pre-fetch (eliminate N+1)

**Files:**
- Modify: `backend/app/api/endpoints/protocol_pdfs.py`
- Test: `backend/tests/integration/api/test_protocol_pdfs_n_plus_one.py` (new)

- [ ] **Step 1: Write the failing N+1 guard test**

Create `backend/tests/integration/api/test_protocol_pdfs_n_plus_one.py`:

```python
import pytest
from sqlalchemy import event


@pytest.mark.asyncio
async def test_render_runs_single_attachment_query(
    client, auth_user, protocol_with_steps_and_attachments, db_engine
):
    """Render a 10-step protocol with 5 attachments. Exactly one
    SELECT FROM protocol_attachments should execute (the bulk pre-fetch)."""
    queries: list[str] = []

    @event.listens_for(db_engine.sync_engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, params, context, executemany):
        if "protocol_attachments" in statement.lower():
            queries.append(statement)

    r = await client.get(
        f"/protocols/{protocol_with_steps_and_attachments.id}/sop.pdf"
    )
    assert r.status_code == 200
    attachment_selects = [
        q for q in queries
        if q.lower().lstrip().startswith("select")
        and "from protocol_attachments" in q.lower()
    ]
    assert len(attachment_selects) == 1, (
        f"expected exactly 1 attachment SELECT, got {len(attachment_selects)}"
    )
```

> **Note for the implementer:** add a `protocol_with_steps_and_attachments` factory fixture that creates a Protocol with a 10-node `unitOp` graph and 5 attachments distributed across nodes.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest backend/tests/integration/api/test_protocol_pdfs_n_plus_one.py -v`
Expected: either the endpoint runs 0 attachment queries (figures don't render), or 10+ queries (one per step).

- [ ] **Step 3: Pre-fetch attachments in the endpoint**

Locate the existing `/protocols/{id}/sop.pdf` (or equivalent) handler in `backend/app/api/endpoints/protocol_pdfs.py`. Before the `build_context(...)` call, add:

```python
import collections

from sqlalchemy import select

from app.models.protocols import ProtocolAttachment

# ... inside the handler, after `protocol` is loaded:

rows = (await db.execute(
    select(ProtocolAttachment)
    .where(
        ProtocolAttachment.protocol_id == protocol.id,
        ProtocolAttachment.deleted.is_(False),
    )
    .order_by(ProtocolAttachment.created_at)
)).scalars().all()

attachments_by_node = collections.defaultdict(list)
for row in rows:
    attachments_by_node[row.node_id].append(row)

context, unresolved = build_context(
    protocol,
    ...,  # whatever other args the existing call passes
    attachments_by_node=attachments_by_node,
)
```

Replicate the same change in the batch-record endpoint(s) and any other render entry point that calls `build_context()`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest backend/tests/integration/api/test_protocol_pdfs_n_plus_one.py -v`
Expected: PASS (1 case).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/endpoints/protocol_pdfs.py backend/tests/integration/api/test_protocol_pdfs_n_plus_one.py
git commit -m "$(cat <<'EOF'
perf(BUG-0007): bulk-fetch protocol_attachments in render endpoint

One async SELECT before build_context() instead of an N-per-step lookup
inside the sync function. Eliminates the N+1 and the sync/async session
boundary issue: build_context never touches the DB now.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Verification-matrix sample renderer + baseline previews + visual XML assertions

> **Why this task is matrix-driven, not single-sample**: The SOP template has many conditional branches — time markers, role grouping, figures, approvals, unapproved-warning watermark, critical-requirement banner, time-cycle warning, signoff variations. A single "maximal" sample exercises everything but proves nothing about the *fallback* shape of each branch when its variable is absent or false. The matrix below produces one rendered PDF per scenario, each crafted to exercise a specific subset of conditionals so visual regressions in any branch are caught locally and in the Chrome QA pass (Task 20).

### Verification Matrix

| # | Scenario | `is_role_based` | `time_enabled` | figures | `requires_approval` | `unapproved_warning` | `critical_requirement` | `time_warning` | Targets |
|---|----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---------|
| 1 | `minimal` | F | F | none | F | F | none | none | All conditionals off — flat 3-step list, no headings, no banner, no approvals |
| 2 | `role_based_basic` | T | F | none | F | F | none | none | Role 16pt headings; step 12pt headings; no time segment in step heading |
| 3 | `time_only` | F | T | none | F | F | none | none | `T=…` appears in flat-list step headings; no role headings |
| 4 | `time_and_roles` | T | T | none | F | F | none | none | Cumulative offsets across role boundaries (Role B step 1 starts where Role A step N ended) |
| 5 | `figures_only` | F | F | mixed | F | F | none | none | Step 1: zero figures (no blank paragraph); Step 2: one figure; Step 3: two figures with monotonic numbering |
| 6 | `approval_full` | T | F | none | T | F | none | none | Approvals table renders with sponsor, study director, QAU rows — each with signature image + attestation |
| 7 | `approval_partial` | T | F | none | T | F | none | none | Only sponsor signed — study director/QAU rows show empty signature placeholder, no broken image |
| 8 | `unapproved_draft` | T | F | none | T | T | none | none | `unapproved_warning=True` → DRAFT banner/watermark visible; approvals block still rendered but marked pending |
| 9 | `critical_requirement` | T | F | none | F | F | set | none | Critical-requirement banner appears under purpose/scope, ahead of procedure body |
| 10 | `cycle_warning` | F | T | none | F | F | none | `cycle_detected` | `time_warning` banner replaces the cumulative-offset assumption; warning copy is visible |
| 11 | `maximal` | T | T | mixed | T | F | set | none | Everything on — mirrors `/tmp/render_maximal_sop.py` user-approved sample |
| 12 | `edge_long_text` | T | F | none | F | F | none | none | 5 roles, 8 steps each, multi-paragraph step descriptions ≥600 chars — exercises page-break + column-width regressions |

Each scenario is rendered to `docs/previews/sop_default/sop_<scenario>.{docx,pdf}` (+ per-page PNGs) and is the input to both the XML assertion suite (Task 15, Step 5), the end-to-end pytest suite (Task 19), and the Chrome browser pass (Task 20).

**Files:**
- Create: `backend/scripts/render_sample_sop.py`
- Create: `backend/scripts/_sop_scenarios.py` (scenario registry — split out so the test layer can import it)
- Create: `docs/previews/sop_default/README.md`
- Create: `docs/previews/sop_default/sop_minimal.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_role_based_basic.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_time_only.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_time_and_roles.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_figures_only.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_approval_full.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_approval_partial.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_unapproved_draft.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_critical_requirement.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_cycle_warning.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_maximal.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_edge_long_text.{docx,pdf}` (generated)
- Create: `docs/previews/sop_default/sop_<scenario>-{1..N}.png` per scenario (generated)
- Create: `backend/tests/integration/test_sop_render_visual.py`

- [ ] **Step 1: Write the failing XML-level assertion tests**

Create `backend/tests/integration/test_sop_render_visual.py`. The tests parametrize over `SCENARIOS` so every conditional branch is exercised structurally, then add scenario-specific assertions that lock down the *intent* of each scenario (time markers present iff time_enabled, role headings present iff is_role_based, etc.).

```python
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RENDER = REPO / "scripts" / "render_sample_sop.py"
PREVIEW_DIR = REPO.parent / "docs" / "previews" / "sop_default"

# Import the registry directly so the test list stays in sync with the
# renderer.
from scripts._sop_scenarios import SCENARIOS  # noqa: E402


@pytest.fixture(scope="module")
def rendered_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("sop_visual")
    subprocess.run(
        ["python", str(RENDER), "--out-dir", str(out),
         "--scenario", "all", "--no-pdf"],
        check=True,
    )
    return out


def _body_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8")


def _visible_text(xml: str) -> str:
    return re.sub(r"<[^>]+>", "", xml)


@pytest.fixture(scope="module")
def rendered_docx(rendered_dir):
    """Back-compat single-doc fixture, used by structural assertions below."""
    return rendered_dir / "sop_maximal.docx"


# ── Per-scenario structural assertions ───────────────────────────────

@pytest.mark.parametrize("name", list(SCENARIOS.keys()))
def test_every_scenario_renders(rendered_dir, name):
    assert (rendered_dir / f"sop_{name}.docx").exists(), (
        f"renderer did not emit sop_{name}.docx"
    )


def test_minimal_has_no_role_headings_or_time_markers(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_minimal.docx")
    visible = _visible_text(xml)
    # No `T=…` time marker anywhere.
    assert not re.search(r"T=\d", visible)
    # No 16pt-black-bold role heading (the rule we assert elsewhere for
    # role-based scenarios) — but step 12pt-bold headings are still allowed.
    role_pat = re.compile(
        r'<w:rPr>(?=.*<w:b/>)(?=.*<w:sz w:val="32"/>)'
        r'(?=.*<w:color w:val="000000"/>).*?</w:rPr>',
        re.DOTALL,
    )
    assert not role_pat.search(xml)


def test_role_based_basic_has_role_headings_but_no_time(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_role_based_basic.docx")
    visible = _visible_text(xml)
    assert "Upstream Operator" in visible
    assert "QC Analyst" in visible
    assert not re.search(r"T=\d", visible)


def test_time_only_has_time_markers_in_step_headings(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_time_only.docx")
    visible = _visible_text(xml)
    assert "T=0" in visible
    assert "T=30m" in visible


def test_time_and_roles_offsets_are_cumulative_across_roles(rendered_dir):
    """Role B step 1 should start where Role A step N ended (T=45m), not T=0."""
    xml = _body_xml(rendered_dir / "sop_time_and_roles.docx")
    visible = _visible_text(xml)
    # Role A: T=0 + T=30m. Role B: T=45m + T=55m.
    for marker in ("T=0", "T=30m", "T=45m", "T=55m"):
        assert marker in visible, f"missing time marker {marker!r}"
    # Critical: Role B does NOT restart at T=0 — only one T=0 in the doc.
    assert visible.count("T=0") == 1


def test_figures_only_has_monotonic_figure_numbers_skipping_step_with_none(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_figures_only.docx")
    fig_nums = [int(m.group(1)) for m in re.finditer(r"Figure (\d+)\.", xml)]
    # Step 1: 0 figures. Step 2: figure 1. Step 3: figures 2 and 3.
    assert fig_nums == [1, 2, 3]
    # No double-blank paragraph for the figureless step.
    assert "<w:p/><w:p/>" not in xml


def test_approval_full_has_three_signature_drawings(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_approval_full.docx")
    # Three signature images plus zero figure-block images.
    assert xml.count("<w:drawing") >= 3


def test_approval_partial_has_one_signature_drawing(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_approval_partial.docx")
    assert xml.count("<w:drawing") == 1
    visible = _visible_text(xml)
    # The other rows are still present (name lines), but no broken
    # `[InlineImage:]` placeholder text leaks through.
    assert "InlineImage" not in visible


def test_unapproved_draft_emits_draft_banner(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_unapproved_draft.docx")
    visible = _visible_text(xml).upper()
    # The template can express the warning as "DRAFT" or "UNAPPROVED" —
    # accept either, but require one.
    assert "DRAFT" in visible or "UNAPPROVED" in visible


def test_critical_requirement_banner_appears_above_procedure(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_critical_requirement.docx")
    visible = _visible_text(xml)
    crit_at = visible.find("aseptic technique")
    proc_at = visible.find("Buffer Prep")  # first procedural step
    assert 0 < crit_at < proc_at, (
        "critical_requirement banner should precede the procedure body"
    )


def test_cycle_warning_renders_warning_copy_and_no_offsets(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_cycle_warning.docx")
    visible = _visible_text(xml).lower()
    assert "cycle" in visible  # warning copy mentions the detected cycle
    # No T=… markers in step headings — the renderer should suppress them
    # when a cycle is detected.
    assert not re.search(r"T=\d", visible)


def test_maximal_contains_all_features(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_maximal.docx")
    visible = _visible_text(xml)
    # Roles
    assert "Upstream Operator" in visible and "QC Analyst" in visible
    # Time
    assert "T=0" in visible
    # Figures (2 inline + 3 signatures = 5+ drawings)
    assert xml.count("<w:drawing") >= 5
    # Critical requirement
    assert "aseptic" in visible
    # Approvals
    assert "Dana Park" in visible


def test_edge_long_text_paginates_without_text_overflow(rendered_dir):
    xml = _body_xml(rendered_dir / "sop_edge_long_text.docx")
    # 5 roles × 8 steps = 40 step headings. Confirm we got them all
    # (i.e. nothing was dropped by an off-by-one).
    visible = _visible_text(xml)
    step_count = sum(1 for _ in re.finditer(r"\bStep \d+\.\d+\b", visible))
    assert step_count == 40


def _body_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_no_wtbl_in_procedure_body(rendered_docx):
    xml = _body_xml(rendered_docx)
    # The approvals block contains a real signature table; the *procedure*
    # body (before the approval header) must be table-free.
    procedure = xml.split("Approval")[0]
    assert "<w:tbl" not in procedure


def test_role_heading_run_has_16pt_bold_black(rendered_docx):
    xml = _body_xml(rendered_docx)
    # Look for at least one run with all three: w:color=000000, w:sz=32, w:b
    pat = re.compile(
        r'<w:rPr>(?=.*<w:b/>)(?=.*<w:sz w:val="32"/>)'
        r'(?=.*<w:color w:val="000000"/>).*?</w:rPr>',
        re.DOTALL,
    )
    assert pat.search(xml), "no role-heading run with 16pt bold black found"


def test_step_heading_run_has_12pt_bold(rendered_docx):
    xml = _body_xml(rendered_docx)
    pat = re.compile(
        r'<w:rPr>(?=.*<w:b/>)(?=.*<w:sz w:val="24"/>).*?</w:rPr>',
        re.DOTALL,
    )
    assert pat.search(xml), "no step-heading run with 12pt bold found"


def test_no_double_space_in_step_headings(rendered_docx):
    xml = _body_xml(rendered_docx)
    # Step headings contain '. ' followed by the step name. Two spaces
    # between any two visible words anywhere in the procedure body is the
    # spacing-typo regression we are guarding against.
    procedure = xml.split("Approval")[0]
    visible_text = re.sub(r"<[^>]+>", "", procedure)
    assert "  " not in visible_text


def test_at_least_one_drawing_per_figure(rendered_docx):
    xml = _body_xml(rendered_docx)
    drawing_count = xml.count("<w:drawing")
    # The maximal sample has 2 inline figures.
    assert drawing_count >= 2


def test_caption_runs_at_10pt(rendered_docx):
    xml = _body_xml(rendered_docx)
    # Caption paragraphs contain 'Figure N.' or 'Figure N —'. Their runs
    # carry w:sz=20 (10pt half-points).
    pat = re.compile(
        r'<w:p[^>]*>.*?<w:sz w:val="20"/>.*?Figure \d',
        re.DOTALL,
    )
    assert pat.search(xml), "no Figure caption paragraph at 10pt"


def test_figure_numbers_monotonic(rendered_docx):
    xml = _body_xml(rendered_docx)
    fig_nums = [
        int(m.group(1))
        for m in re.finditer(r"Figure (\d+)\.", xml)
    ]
    assert fig_nums == sorted(fig_nums)
    assert fig_nums == list(range(1, len(fig_nums) + 1))


def test_baselines_checked_in():
    assert (PREVIEW_DIR / "sop_maximal_with_time.pdf").exists()
    assert (PREVIEW_DIR / "sop_maximal_without_time.pdf").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/integration/test_sop_render_visual.py -v`
Expected: FileNotFoundError for the render script.

- [ ] **Step 3: Author the scenario registry**

Create `backend/scripts/_sop_scenarios.py`. This module exposes `SCENARIOS: dict[str, Callable[[DocxTemplate], dict]]` where each value returns the context dict for that scenario. Keeping it separate from the CLI lets `test_sop_render_visual.py` (Task 15 step 1) and `test_sop_render_end_to_end.py` (Task 19) import the same scenario list and parametrize across it — single source of truth for what the matrix is.

```python
"""Scenario registry for the SOP verification matrix.

Each scenario builder receives the docxtpl `DocxTemplate` (so it can attach
`InlineImage`s) and returns a fully-formed context dict ready for
`render_to_docx()`. Adding a new branch in the template? Add a scenario
here that exercises it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from docx.shared import Inches, Mm
from docxtpl import DocxTemplate, InlineImage

# Asset paths — generated lazily by _ensure_assets(out_dir).
ASSET_DIR_ENV = "SOP_PREVIEW_ASSET_DIR"


def _ensure_assets(asset_dir: Path) -> dict[str, Path]:
    """Materialize the figure/signature PNGs the scenarios reference."""
    # Reuse the make_figure_image / make_signature_image helpers from
    # /tmp/render_maximal_sop.py — copy them verbatim into this file.
    asset_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "fig_vessel": asset_dir / "fig_vessel.png",
        "fig_hemo": asset_dir / "fig_hemo.png",
        "sig_sponsor": asset_dir / "sig_sponsor.png",
        "sig_sd": asset_dir / "sig_sd.png",
        "sig_qau": asset_dir / "sig_qau.png",
    }
    if not paths["fig_vessel"].exists():
        make_figure_image(paths["fig_vessel"], "Fig: Vessel A", (180, 210, 240))
        make_figure_image(paths["fig_hemo"], "Fig: Hemocytometer", (220, 230, 200))
        make_signature_image(paths["sig_sponsor"], "Dana Park")
        make_signature_image(paths["sig_sd"], "Dr. Lin Yao")
        make_signature_image(paths["sig_qau"], "Marcus Reid")
    return paths


def _base_metadata() -> dict:
    """Constant metadata across scenarios — only the conditional fields vary."""
    return {
        "organization_name": "Acme Bio",
        "project_name": "PD-2026-A — Cell Seeding Optimization",
        "created_at": "2026-05-22",
        "protocol_name": "Cell Seeding & QC v2.1",
        "doc_number": "SOP-0042",
        "version_number": "2.1",
        "effective_date": "2026-06-01",
        "purpose": "Reproducible cell seeding and QC procedure.",
        "scope": "Applies to all CHO-K1 cultures in the PD lab.",
        "figures": [],
        "non_image_attachments": [],
        "notes": [],
    }


def _step(name, description, *, duration_min=15, time_offset="", figures=None):
    return {
        "name": name,
        "description": description,
        "duration_min": duration_min,
        "time_offset": time_offset,
        "figures": figures or [],
        "params": {},
        "value_display": "",
        "initials": "",
        "notes_display": "",
        "role_name": "",
    }


# ── Scenario builders ────────────────────────────────────────────────

def build_minimal(tpl: DocxTemplate) -> dict:
    """All conditionals off — flat 3-step list."""
    return {
        **_base_metadata(),
        "unapproved_warning": False,
        "critical_requirement": "",
        "is_time_based": False,
        "is_role_based": False,
        "time_enabled": False,
        "time_warning": "",
        "time_points": [],
        "roles": [],
        "steps": [
            _step("Prepare Reagents", "Combine reagents A and B per SOP-001."),
            _step("Incubate", "Incubate at 37C for 30 minutes."),
            _step("Record Result", "Document outcome in the LIMS."),
        ],
        "requires_approval": False,
        "protocol_approvals": None,
    }


def build_role_based_basic(tpl: DocxTemplate) -> dict:
    """2 roles, no time, no figures."""
    ctx = build_minimal(tpl)
    ctx["is_role_based"] = True
    ctx["steps"] = []
    ctx["roles"] = [
        {
            "name": "Upstream Operator",
            "process_name": "Upstream Operator — Prep",
            "steps": [
                _step("Buffer Prep", "Prepare buffer per recipe."),
                _step("Cell Thawing", "Thaw cryovial at 37C."),
            ],
        },
        {
            "name": "QC Analyst",
            "process_name": "QC Analyst — Assay",
            "steps": [
                _step("Sample", "Withdraw 1 mL of culture."),
                _step("Stain", "Apply trypan blue 1:1."),
            ],
        },
    ]
    return ctx


def build_time_only(tpl: DocxTemplate) -> dict:
    """Flat list + time_enabled. Exercises step-heading T=... suffix."""
    ctx = build_minimal(tpl)
    ctx["time_enabled"] = True
    ctx["steps"] = [
        _step("Prep", "Step body.", duration_min=30, time_offset="T=0"),
        _step("Incubate", "Step body.", duration_min=60, time_offset="T=30m"),
        _step("Record", "Step body.", duration_min=10, time_offset="T=1h 30m"),
    ]
    return ctx


def build_time_and_roles(tpl: DocxTemplate) -> dict:
    """Roles + time. Critical check: offsets are cumulative ACROSS role boundaries."""
    ctx = build_role_based_basic(tpl)
    ctx["time_enabled"] = True
    # Role A: T=0 (30m) → T=30m (15m) = ends at T=45m
    ctx["roles"][0]["steps"] = [
        _step("Buffer Prep", "...", duration_min=30, time_offset="T=0"),
        _step("Cell Thawing", "...", duration_min=15, time_offset="T=30m"),
    ]
    # Role B: starts where Role A ended.
    ctx["roles"][1]["steps"] = [
        _step("Sample", "...", duration_min=10, time_offset="T=45m"),
        _step("Stain", "...", duration_min=20, time_offset="T=55m"),
    ]
    return ctx


def build_figures_only(tpl: DocxTemplate) -> dict:
    """Flat list, per-step figure variety: 0 / 1 / 2 figures."""
    assets = _ensure_assets(Path(_assets_dir()))
    fig1 = {
        "number": 1,
        "caption": "Vessel A — pre-stir configuration.",
        "image": InlineImage(tpl, str(assets["fig_vessel"]), width=Inches(5.5)),
        "image_ok": True,
    }
    fig2 = {
        "number": 2,
        "caption": "Hemocytometer field at 10x.",
        "image": InlineImage(tpl, str(assets["fig_hemo"]), width=Inches(5.5)),
        "image_ok": True,
    }
    fig3 = {
        "number": 3,
        "caption": "Hemocytometer reference grid.",
        "image": InlineImage(tpl, str(assets["fig_hemo"]), width=Inches(5.5)),
        "image_ok": True,
    }
    ctx = build_minimal(tpl)
    ctx["steps"] = [
        _step("Prep", "Step body — no figures attached."),
        _step("Stain", "Step body — one figure attached.", figures=[fig1]),
        _step("Count", "Step body — two figures attached.", figures=[fig2, fig3]),
    ]
    return ctx


def build_approval_full(tpl: DocxTemplate) -> dict:
    """All 3 approvals signed with signature images."""
    assets = _ensure_assets(Path(_assets_dir()))
    ctx = build_role_based_basic(tpl)
    ctx["requires_approval"] = True
    ctx["protocol_approvals"] = {
        "sponsor": {
            "name": "Dana Park",
            "email": "dana@acme.bio",
            "signed_at": "2026-05-19 14:22",
            "attestation": "I attest the study director and QAU approved per 21 CFR §58.10.",
            "signature_image": InlineImage(tpl, str(assets["sig_sponsor"]), width=Mm(45)),
        },
        "study_director": {
            "name": "Dr. Lin Yao",
            "email": "lin@acme.bio",
            "signed_at": "2026-05-20 09:05",
            "attestation": "Reviewed and conforms to 21 CFR §58.33.",
            "signature_image": InlineImage(tpl, str(assets["sig_sd"]), width=Mm(45)),
        },
        "qau": {
            "name": "Marcus Reid",
            "email": "marcus@acme.bio",
            "signed_at": "2026-05-21 16:40",
            "attestation": "Independent QA review per 21 CFR §58.35.",
            "signature_image": InlineImage(tpl, str(assets["sig_qau"]), width=Mm(45)),
        },
    }
    return ctx


def build_approval_partial(tpl: DocxTemplate) -> dict:
    """Only sponsor signed. study_director + qau are present with `signed_at=None`."""
    ctx = build_approval_full(tpl)
    ctx["protocol_approvals"]["study_director"] = {
        "name": "Dr. Lin Yao",
        "email": "lin@acme.bio",
        "signed_at": None,
        "attestation": None,
        "signature_image": None,
    }
    ctx["protocol_approvals"]["qau"] = {
        "name": "Marcus Reid",
        "email": "marcus@acme.bio",
        "signed_at": None,
        "attestation": None,
        "signature_image": None,
    }
    return ctx


def build_unapproved_draft(tpl: DocxTemplate) -> dict:
    """unapproved_warning=True → DRAFT watermark/banner visible."""
    ctx = build_approval_full(tpl)
    ctx["unapproved_warning"] = True
    # Strip the signed_at to make the draft state coherent.
    for role in ("sponsor", "study_director", "qau"):
        ctx["protocol_approvals"][role]["signed_at"] = None
        ctx["protocol_approvals"][role]["signature_image"] = None
    return ctx


def build_critical_requirement(tpl: DocxTemplate) -> dict:
    """critical_requirement banner exercise — under purpose/scope, above procedure body."""
    ctx = build_role_based_basic(tpl)
    ctx["critical_requirement"] = (
        "Maintain aseptic technique throughout. Any deviation must be logged "
        "and reviewed by the QA Unit per 21 CFR §58.81(b)."
    )
    return ctx


def build_cycle_warning(tpl: DocxTemplate) -> dict:
    """time_enabled + a graph with a cycle → renderer sets time_warning='cycle_detected'."""
    ctx = build_time_only(tpl)
    ctx["time_warning"] = "cycle_detected"
    # Step time_offsets should be empty when a cycle is detected (the renderer
    # falls back to author-specified offsets only).
    for step in ctx["steps"]:
        step["time_offset"] = ""
    return ctx


def build_maximal(tpl: DocxTemplate) -> dict:
    """Everything on — the original user-approved sample."""
    ctx = build_time_and_roles(tpl)
    assets = _ensure_assets(Path(_assets_dir()))
    fig1 = {
        "number": 1,
        "caption": "Vessel A — pre-stir configuration.",
        "image": InlineImage(tpl, str(assets["fig_vessel"]), width=Inches(5.5)),
        "image_ok": True,
    }
    fig2 = {
        "number": 2,
        "caption": "Hemocytometer field at 10x.",
        "image": InlineImage(tpl, str(assets["fig_hemo"]), width=Inches(5.5)),
        "image_ok": True,
    }
    ctx["roles"][0]["steps"][0]["figures"] = [fig1]
    ctx["roles"][1]["steps"][1]["figures"] = [fig2]
    ctx["critical_requirement"] = (
        "Maintain aseptic technique throughout. Any deviation must be logged."
    )
    full = build_approval_full(tpl)
    ctx["requires_approval"] = True
    ctx["protocol_approvals"] = full["protocol_approvals"]
    return ctx


def build_edge_long_text(tpl: DocxTemplate) -> dict:
    """5 roles, 8 steps each, ≥600-char descriptions. Page-break regression target."""
    long = (
        "This step description deliberately runs long to exercise the "
        "description column's text-wrap and the page-break behavior between "
        "step blocks. " * 6
    )
    ctx = build_role_based_basic(tpl)
    ctx["roles"] = [
        {
            "name": f"Role {chr(65 + i)}",
            "process_name": f"Role {chr(65 + i)} — Process",
            "steps": [
                _step(f"Step {i+1}.{j+1}", long, duration_min=10)
                for j in range(8)
            ],
        }
        for i in range(5)
    ]
    return ctx


SCENARIOS: dict[str, Callable[[DocxTemplate], dict]] = {
    "minimal": build_minimal,
    "role_based_basic": build_role_based_basic,
    "time_only": build_time_only,
    "time_and_roles": build_time_and_roles,
    "figures_only": build_figures_only,
    "approval_full": build_approval_full,
    "approval_partial": build_approval_partial,
    "unapproved_draft": build_unapproved_draft,
    "critical_requirement": build_critical_requirement,
    "cycle_warning": build_cycle_warning,
    "maximal": build_maximal,
    "edge_long_text": build_edge_long_text,
}


def _assets_dir() -> str:
    import os
    return os.environ.get(ASSET_DIR_ENV, "/tmp/sop_preview_assets")


# Copy make_figure_image and make_signature_image verbatim from
# /tmp/render_maximal_sop.py.
```

- [ ] **Step 3b: Author the renderer CLI**

Create `backend/scripts/render_sample_sop.py`. The CLI iterates `SCENARIOS`, renders each through the **real** `build_context()` + `render_to_docx()` pipeline (not docxtpl directly), and emits the `.docx` + `.pdf` (+ PNGs) to `--out-dir`. Required behavior:

1. CLI flags: `--out-dir <path>` (default `docs/previews/sop_default/`), `--scenario <name|all>` (default `all`), `--no-pdf` (skip LibreOffice).
2. Import `SCENARIOS` from `_sop_scenarios.py`.
3. For each scenario name, construct a `DocxTemplate`, build the context, call `render_to_docx()`, save to `sop_<name>.docx`.
4. If `not --no-pdf`: `libreoffice --headless --convert-to pdf --outdir <out_dir> <docx>`.
5. If `pdftoppm` is on PATH and pdf produced: `pdftoppm -r 110 -png <pdf> <out_dir>/sop_<name>` → `sop_<name>-1.png`, etc.
6. Print one line per scenario to stdout so a CI log clearly shows which scenarios ran.

```python
"""Render the SOP verification-matrix baselines.

For each scenario in scripts._sop_scenarios.SCENARIOS, render
docs/previews/sop_default/sop_<name>.{docx,pdf} (+ per-page PNGs).
PDFs and PNGs are committed (LFS-tracked) and serve as the visual
specification of how each conditional template branch must render.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from docxtpl import DocxTemplate

# Real render pipeline — not docxtpl directly, so the script exercises
# the same code path as production.
from app.services.protocols.template_engine import render_to_docx
from scripts._sop_scenarios import SCENARIOS

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO.parent / "docs" / "previews" / "sop_default"
TEMPLATE_PATH = (
    REPO / "app" / "services" / "documents" / "templates" / "sop_default.docx"
)


def _render_scenario(name: str, out_dir: Path, no_pdf: bool) -> None:
    tpl = DocxTemplate(str(TEMPLATE_PATH))
    ctx = SCENARIOS[name](tpl)
    docx_path = out_dir / f"sop_{name}.docx"
    render_to_docx(template_path=TEMPLATE_PATH, context=ctx, out_path=docx_path)
    print(f"[render] {name} -> {docx_path.name}")

    if no_pdf:
        return

    subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "pdf",
         "--outdir", str(out_dir), str(docx_path)],
        check=True, capture_output=True,
    )
    pdf_path = docx_path.with_suffix(".pdf")
    print(f"[pdf]    {name} -> {pdf_path.name}")

    if shutil.which("pdftoppm"):
        subprocess.run(
            ["pdftoppm", "-r", "110", "-png",
             str(pdf_path), str(out_dir / f"sop_{name}")],
            check=True, capture_output=True,
        )
        print(f"[png]    {name} -> sop_{name}-*.png")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--scenario", default="all",
                   help="Scenario name from SCENARIOS, or 'all'")
    p.add_argument("--no-pdf", action="store_true")
    args = p.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.scenario == "all":
        names = list(SCENARIOS.keys())
    else:
        if args.scenario not in SCENARIOS:
            print(f"unknown scenario: {args.scenario}", file=sys.stderr)
            return 2
        names = [args.scenario]

    for name in names:
        _render_scenario(name, args.out_dir, args.no_pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Generate baselines + check in**

```bash
cd backend
python scripts/render_sample_sop.py --scenario all
# (writes one .docx + .pdf + per-page PNGs per scenario to
#  docs/previews/sop_default/, ~12 scenarios x ~3 pages = ~36 PNGs)
```

Quickly skim each PDF to confirm the *intent* of its scenario is visible:

```bash
ls docs/previews/sop_default/*.pdf
# sop_minimal.pdf … sop_maximal.pdf … sop_edge_long_text.pdf

# Open them in a viewer or convert to a quick contact sheet:
montage docs/previews/sop_default/sop_*-1.png \
        -tile 4x3 -geometry 200x \
        /tmp/sop_matrix_contact_sheet.png && \
        xdg-open /tmp/sop_matrix_contact_sheet.png
```

Add the README:

Create `docs/previews/sop_default/README.md`:

```markdown
# SOP Verification-Matrix Baselines

These PDFs and per-page PNGs are the **visual specification** of how the
SOP renders. Each file corresponds to one scenario in
`backend/scripts/_sop_scenarios.py`. The matrix exercises every conditional
branch of the template — time markers, role grouping, figures, approvals
(full / partial), unapproved-draft warning, critical-requirement banner,
time-cycle warning, and long-text page-break behavior.

| File | Conditional branch exercised |
|------|------------------------------|
| sop_minimal.pdf | All conditionals off |
| sop_role_based_basic.pdf | is_role_based only |
| sop_time_only.pdf | time_enabled only |
| sop_time_and_roles.pdf | Cumulative offsets across role boundaries |
| sop_figures_only.pdf | Per-step figures: 0 / 1 / 2 mix |
| sop_approval_full.pdf | All 3 approvals signed |
| sop_approval_partial.pdf | Only sponsor signed |
| sop_unapproved_draft.pdf | unapproved_warning watermark |
| sop_critical_requirement.pdf | critical_requirement banner |
| sop_cycle_warning.pdf | time_warning='cycle_detected' |
| sop_maximal.pdf | Everything on (user-approved sample) |
| sop_edge_long_text.pdf | 5 roles x 8 steps, ≥600-char descriptions |

They are regenerated by `backend/scripts/render_sample_sop.py --scenario all`
and checked in via git LFS. Any change touching:

- `backend/app/services/protocols/template_engine.py`
- `backend/app/services/data/graph_processing.py`
- the `.docx` templates under `backend/app/services/documents/templates/`
- the rewrite script `backend/scripts/rewrite_sop_step_tables.py`
- `backend/scripts/_sop_scenarios.py`

MUST be followed by `python backend/scripts/render_sample_sop.py --scenario all`
and a commit of the regenerated previews alongside the code change. PR review
naturally surfaces an image diff and any unintended layout regression shows
up side-by-side in the review UI. Per-scenario PNG diffs are the fastest way
to spot a branch-specific regression.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest backend/tests/integration/test_sop_render_visual.py -v`
Expected: PASS — 12 `test_every_scenario_renders[…]` cases + ~12 per-scenario assertions.

- [ ] **Step 6: Commit script + baselines + tests together**

```bash
git add backend/scripts/render_sample_sop.py \
        backend/scripts/_sop_scenarios.py \
        backend/tests/integration/test_sop_render_visual.py \
        docs/previews/sop_default/
git commit -m "$(cat <<'EOF'
feat(BUG-0007): verification-matrix SOP sample + baseline previews + XML asserts

scripts/_sop_scenarios.py defines 12 scenarios each targeting a specific
conditional template branch (minimal / role_based_basic / time_only /
time_and_roles / figures_only / approval_full / approval_partial /
unapproved_draft / critical_requirement / cycle_warning / maximal /
edge_long_text). scripts/render_sample_sop.py iterates them through the
real build_context() + render_to_docx() pipeline. PDFs + per-page PNGs
are committed via LFS and serve as the visual spec. The pytest layer
parametrizes structural assertions across every scenario plus
scenario-specific intent checks (cumulative time offsets across role
boundaries, figure-numbering skipping empty steps, draft watermark,
critical-requirement banner ordering, cycle-warning suppresses offsets).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Frontend API client — doc_number + attachment methods

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/schemas/` (add attachment Zod schemas — pick the existing module pattern)
- Test: `frontend/src/lib/api.test.ts` (extend existing or new — match existing test convention)

- [ ] **Step 1: Add a Zod schema for `ProtocolAttachment`**

Find the existing `frontend/src/lib/schemas/protocol.ts` (or equivalent) and append:

```typescript
import {z} from 'zod';

export const protocolAttachmentSchema = z.object({
  id: z.string().uuid(),
  protocol_id: z.string().uuid(),
  node_id: z.string(),
  filename: z.string(),
  content_type: z.string(),
  size_bytes: z.number().int(),
  caption: z.string().nullable(),
  uploaded_by_id: z.string().uuid(),
  created_at: z.string(),
});

export type ProtocolAttachment = z.infer<typeof protocolAttachmentSchema>;
```

- [ ] **Step 2: Add API client methods**

Append to `frontend/src/lib/api.ts`:

```typescript
import {
  protocolAttachmentSchema,
  type ProtocolAttachment,
} from './schemas/protocol';

export async function patchProtocol(
    id: string,
    patch: {name?: string; description?: string; doc_number?: string},
): Promise<unknown> {
  return await api.patch(`/protocols/${id}`, patch);
}

export async function uploadProtocolAttachment(
    protocolId: string,
    file: File,
    nodeId: string,
    caption?: string,
): Promise<ProtocolAttachment> {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('node_id', nodeId);
  if (caption) fd.append('caption', caption);
  const res = await api.postForm(
      `/protocols/${protocolId}/attachments`,
      fd,
  );
  return protocolAttachmentSchema.parse(res);
}

export async function patchProtocolAttachment(
    protocolId: string,
    attachmentId: string,
    caption: string | null,
): Promise<ProtocolAttachment> {
  const res = await api.patch(
      `/protocols/${protocolId}/attachments/${attachmentId}`,
      {caption},
  );
  return protocolAttachmentSchema.parse(res);
}

export async function deleteProtocolAttachment(
    protocolId: string,
    attachmentId: string,
): Promise<void> {
  await api.delete(
      `/protocols/${protocolId}/attachments/${attachmentId}`,
  );
}

export async function fetchProtocolAttachmentBlobUrl(
    protocolId: string,
    attachmentId: string,
): Promise<string> {
  const blob = await api.getBlob(
      `/protocols/${protocolId}/attachments/${attachmentId}/file`,
  );
  return URL.createObjectURL(blob);
}
```

> **Note for the implementer:** the actual `api` object in this repo may expose `postForm` / `getBlob` under different names. Search `frontend/src/lib/api.ts` for an existing FormData upload (likely in equipment or run attachments) and copy that convention.

- [ ] **Step 3: Run frontend typecheck**

```bash
cd frontend && npm run check
```

Expected: no errors related to the new exports.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/schemas/
git commit -m "$(cat <<'EOF'
feat(BUG-0007): add API client methods for doc_number + attachments

patchProtocol gains doc_number; new upload/patch/delete/stream helpers
for protocol attachments. Zod schema for ProtocolAttachment matches the
backend response shape.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: `ProtocolSidebar.svelte` — inline doc_number editor

**Files:**
- Modify: `frontend/src/lib/components/protocol/ProtocolSidebar.svelte`
- Test: `frontend/src/lib/components/protocol/ProtocolSidebar.test.ts` (new or extend)

- [ ] **Step 1: Write the failing component test**

Create or extend `frontend/src/lib/components/protocol/ProtocolSidebar.test.ts`:

```typescript
import {render, screen, fireEvent} from '@testing-library/svelte';
import {expect, test, vi} from 'vitest';

import ProtocolSidebar from './ProtocolSidebar.svelte';

test('clicking doc_number row opens the input', async () => {
  const protocol = {
    id: 'p1',
    name: 'P',
    description: 'd',
    doc_number: 'SOP-0042',
  };
  render(ProtocolSidebar, {protocol});
  const btn = screen.getByRole('button', {name: /SOP-0042/});
  await fireEvent.click(btn);
  expect(screen.getByRole('textbox', {name: /doc number/i})).toBeTruthy();
});

test('409 from patch renders inline error with conflicting protocol name', async () => {
  const protocol = {
    id: 'p1', name: 'P', description: 'd', doc_number: 'SOP-0042',
  };
  vi.mock('$lib/api', () => ({
    patchProtocol: vi.fn().mockRejectedValue({
      status: 409,
      body: {
        detail: 'doc_number_in_use',
        conflicting_doc_number: 'SOP-0007',
        conflicting_protocol_name: 'Existing Protocol',
      },
    }),
  }));
  render(ProtocolSidebar, {protocol});
  // Open input, type, blur:
  await fireEvent.click(screen.getByRole('button', {name: /SOP-0042/}));
  const input = screen.getByRole('textbox', {name: /doc number/i});
  await fireEvent.input(input, {target: {value: 'SOP-0007'}});
  await fireEvent.blur(input);
  expect(
      await screen.findByText(/already in use by "Existing Protocol"/i),
  ).toBeTruthy();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm run test -- ProtocolSidebar`
Expected: doc_number control not rendered → first test fails.

- [ ] **Step 3: Add the doc_number row to `ProtocolSidebar.svelte`**

Below the existing `description` block, mirroring the existing name-edit ghost-Button pattern:

```svelte
<script lang="ts">
  // existing imports
  import {patchProtocol} from '$lib/api';

  let editingDocNumber = $state(false);
  let docNumberInput = $state('');
  let docNumberError = $state<string | null>(null);

  function startEditingDocNumber() {
    docNumberInput = protocol?.doc_number ?? '';
    editingDocNumber = true;
    docNumberError = null;
  }

  async function saveDocNumber() {
    docNumberError = null;
    if (!protocol) {
      editingDocNumber = false;
      return;
    }
    const trimmed = docNumberInput.trim();
    if (trimmed === (protocol.doc_number ?? '')) {
      editingDocNumber = false;
      return;
    }
    try {
      await patchProtocol(protocol.id, {doc_number: trimmed});
      protocol.doc_number = trimmed;
      editingDocNumber = false;
    } catch (err: any) {
      if (err?.status === 409) {
        const name = err.body?.conflicting_protocol_name ?? 'another protocol';
        docNumberError = `Doc number already in use by "${name}".`;
      } else {
        docNumberError = 'Could not save doc number.';
      }
    }
  }

  function handleDocNumberKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') saveDocNumber();
    if (e.key === 'Escape') {
      editingDocNumber = false;
      docNumberError = null;
    }
  }
</script>

<!-- inside the existing markup, beneath the description block: -->
<div class="doc-number-row">
  {#if editingDocNumber}
    <label class="text-xs text-muted-foreground">Doc number</label>
    <input
      aria-label="Doc number"
      type="text"
      bind:value={docNumberInput}
      onblur={saveDocNumber}
      onkeydown={handleDocNumberKeydown}
      class="..."
    />
    {#if docNumberError}
      <span class="save-as-new-error">{docNumberError}</span>
    {/if}
  {:else}
    <Button
      variant="ghost"
      class="w-full justify-start text-left"
      onclick={startEditingDocNumber}
    >
      {protocol?.doc_number ?? 'Add doc number…'}
    </Button>
  {/if}
</div>
```

The `.save-as-new-error` class already exists in `Inspector.svelte`; if needed, replicate the same style locally (small text, `color: hsl(0, 84.2%, 60.2%)`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm run test -- ProtocolSidebar`
Expected: PASS (2 cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/protocol/ProtocolSidebar.svelte frontend/src/lib/components/protocol/ProtocolSidebar.test.ts
git commit -m "$(cat <<'EOF'
feat(BUG-0007): inline doc_number edit row in ProtocolSidebar

Ghost-button → input swap, debounced PATCH on blur/Enter, 409 renders an
inline error citing the conflicting protocol — no toast (must correct in
place, toast would auto-dismiss).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: `InspectorFigures.svelte` — figure attachment panel

**Files:**
- Create: `frontend/src/lib/components/protocol/InspectorFigures.svelte`
- Modify: `frontend/src/lib/components/protocol/Inspector.svelte` (include the panel)
- Test: `frontend/src/lib/components/protocol/InspectorFigures.test.ts` (new)

- [ ] **Step 1: Write the failing component tests**

Create `frontend/src/lib/components/protocol/InspectorFigures.test.ts`:

```typescript
import {render, screen, fireEvent} from '@testing-library/svelte';
import {expect, test, vi} from 'vitest';

import InspectorFigures from './InspectorFigures.svelte';

test('section collapsed by default when no figures', () => {
  render(InspectorFigures, {protocolId: 'p1', nodeId: 'n1', attachments: []});
  expect(screen.queryByTestId('figures-grid')).toBeNull();
});

test('section auto-opens when figures exist', () => {
  render(InspectorFigures, {
    protocolId: 'p1',
    nodeId: 'n1',
    attachments: [{
      id: 'a1', filename: 'fig.png', content_type: 'image/png',
      caption: null, size_bytes: 100, node_id: 'n1', protocol_id: 'p1',
      uploaded_by_id: 'u1', created_at: '2026-05-22T00:00:00Z',
    }],
  });
  expect(screen.getByTestId('figures-grid')).toBeTruthy();
});

test('drag-drop event stops propagation', async () => {
  const canvasHandler = vi.fn();
  document.body.addEventListener('drop', canvasHandler);
  render(InspectorFigures, {protocolId: 'p1', nodeId: 'n1', attachments: []});
  const dropZone = screen.getByTestId('figures-dropzone');
  await fireEvent.drop(dropZone, {
    dataTransfer: {files: [], types: ['Files'], items: []},
  });
  expect(canvasHandler).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm run test -- InspectorFigures`
Expected: component not found.

- [ ] **Step 3: Implement `InspectorFigures.svelte`**

Create `frontend/src/lib/components/protocol/InspectorFigures.svelte`:

```svelte
<script lang="ts">
  import {slide} from 'svelte/transition';
  import {cubicOut} from 'svelte/easing';
  import {X} from 'lucide-svelte';

  import {
    uploadProtocolAttachment,
    deleteProtocolAttachment,
    patchProtocolAttachment,
    fetchProtocolAttachmentBlobUrl,
  } from '$lib/api';
  import {Button} from '$lib/components/ui/button';
  import FullScreenModal from '$lib/components/ui/FullScreenModal.svelte';
  import type {ProtocolAttachment} from '$lib/schemas/protocol';

  interface Props {
    protocolId: string;
    nodeId: string;
    attachments: ProtocolAttachment[];
    onChanged?: () => void;
  }
  let {protocolId, nodeId, attachments, onChanged}: Props = $props();

  let expanded = $state(false);
  let thumbUrls = $state<Record<string, string>>({});
  let enlarged = $state<ProtocolAttachment | null>(null);

  $effect(() => {
    if (attachments.length > 0 && !expanded) expanded = true;
  });

  $effect(() => {
    for (const a of attachments) {
      if (!thumbUrls[a.id]) {
        fetchProtocolAttachmentBlobUrl(protocolId, a.id)
            .then((u) => (thumbUrls = {...thumbUrls, [a.id]: u}));
      }
    }
  });

  async function uploadFile(file: File) {
    await uploadProtocolAttachment(protocolId, file, nodeId);
    onChanged?.();
  }

  async function onDrop(e: DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    const files = Array.from(e.dataTransfer?.files ?? []);
    for (const f of files) await uploadFile(f);
  }

  function onDragOver(e: DragEvent) {
    e.preventDefault();
    e.stopPropagation();
  }

  async function onPick(e: Event) {
    const target = e.target as HTMLInputElement;
    const files = Array.from(target.files ?? []);
    for (const f of files) await uploadFile(f);
    target.value = '';
  }

  async function onDelete(att: ProtocolAttachment) {
    await deleteProtocolAttachment(protocolId, att.id);
    onChanged?.();
  }

  async function saveCaption(att: ProtocolAttachment, value: string) {
    if ((att.caption ?? '') === value) return;
    await patchProtocolAttachment(protocolId, att.id, value || null);
    onChanged?.();
  }
</script>

<Button
  variant="ghost"
  class="w-full justify-between px-0 hover:bg-transparent"
  onclick={() => (expanded = !expanded)}
>
  <span class="section-label" style="margin-bottom: 0;">FIGURES</span>
  <span class="chevron" class:open={expanded}>▾</span>
</Button>

{#if expanded}
  <div
    transition:slide={{duration: 180, easing: cubicOut}}
    class="figures-section"
  >
    <div
      class="dropzone"
      data-testid="figures-dropzone"
      ondrop={onDrop}
      ondragover={onDragOver}
    >
      <label class="picker">
        Drop image or
        <input type="file" accept="image/*" multiple onchange={onPick} />
        <span>browse</span>
      </label>
    </div>

    {#if attachments.length > 0}
      <div class="figures-grid" data-testid="figures-grid">
        {#each attachments as att (att.id)}
          <div class="thumb group">
            <button
              type="button"
              class="thumb-tap"
              onclick={() => (enlarged = att)}
              title={att.filename}
            >
              {#if thumbUrls[att.id]}
                <img src={thumbUrls[att.id]} alt={att.filename} />
              {:else}
                <div class="thumb-placeholder" />
              {/if}
            </button>
            <Button
              variant="ghost"
              size="icon-sm"
              class="thumb-delete"
              onclick={() => onDelete(att)}
              aria-label="Delete figure"
            >
              <X class="w-4 h-4" />
            </Button>
            <input
              class="caption-input"
              type="text"
              value={att.caption ?? ''}
              maxlength="500"
              placeholder="Caption (filename used if blank)"
              onblur={(e) =>
                saveCaption(att, (e.target as HTMLInputElement).value)}
            />
          </div>
        {/each}
      </div>
    {/if}
  </div>
{/if}

{#if enlarged}
  <FullScreenModal
    open={true}
    title={enlarged.caption ?? enlarged.filename}
    onClose={() => (enlarged = null)}
  >
    <img
      src={thumbUrls[enlarged.id]}
      alt={enlarged.filename}
      class="max-w-full max-h-full"
    />
  </FullScreenModal>
{/if}

<style>
.figures-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
  gap: 0.5rem;
}
.thumb {
  position: relative;
  aspect-ratio: 1 / 1;
  border: 1px solid hsl(var(--border));
  border-radius: 4px;
  overflow: hidden;
}
.thumb-tap {
  width: 100%;
  height: 100%;
  background: transparent;
  border: 0;
  padding: 0;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.thumb-delete {
  position: absolute;
  top: 2px; right: 2px;
  opacity: 0;
  transition: opacity 120ms;
  min-width: 24px;
  min-height: 24px;
}
.thumb.group:hover .thumb-delete { opacity: 1; }
.caption-input {
  width: 100%;
  font-size: 0.75rem;
  margin-top: 2px;
}
.chevron { transition: transform 120ms; display: inline-block; }
.chevron.open { transform: rotate(180deg); }
.dropzone {
  border: 1px dashed hsl(var(--border));
  border-radius: 4px;
  padding: 0.75rem;
  margin-bottom: 0.5rem;
  text-align: center;
  font-size: 0.85rem;
}
.dropzone input[type=file] { display: none; }
.dropzone .picker span { text-decoration: underline; cursor: pointer; }
</style>
```

- [ ] **Step 4: Include in `Inspector.svelte`**

In `frontend/src/lib/components/protocol/Inspector.svelte`, slot in the panel for `unitOp` node selection (likely near the existing schema editor toggle around line 454):

```svelte
{#if selectedNode?.type === 'unitOp'}
  <InspectorFigures
    protocolId={protocolId}
    nodeId={selectedNode.id}
    attachments={attachmentsForNode}
    onChanged={refreshAttachments}
  />
{/if}
```

Wire `attachmentsForNode` from the protocol's attachment list (filter by `node_id === selectedNode.id`) and pass `refreshAttachments` from the parent that already fetches the protocol.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npm run test -- InspectorFigures`
Expected: PASS (3 cases).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/protocol/InspectorFigures.svelte \
        frontend/src/lib/components/protocol/InspectorFigures.test.ts \
        frontend/src/lib/components/protocol/Inspector.svelte
git commit -m "$(cat <<'EOF'
feat(BUG-0007): figure attachment panel in Inspector

Collapsed-by-default chevron section that auto-expands when figures exist.
Drop-zone calls stopPropagation so file drops don't leak to the canvas
drag handler. Per-figure delete overlay, full-screen modal on click,
caption input fires PATCH on blur only (one audit row per edit, not one
per keystroke).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: End-to-end render smoke test (matrix-parametrized) + manual verification

> **Difference from Task 15:** Task 15 invokes the *renderer script* directly with synthetic `dict` contexts. Task 19 walks a real `Protocol` row through the live FastAPI endpoint — it proves the same shape comes out when the input is a real DB graph, not a hand-built dict. We parametrize across the same scenario list so any branch that the script exercises is also covered end-to-end.

**Files:**
- Test: `backend/tests/integration/test_sop_render_end_to_end.py` (new)
- Test: `backend/tests/conftest.py` (extend fixtures)

- [ ] **Step 1: Write the matrix-parametrized end-to-end test**

Create `backend/tests/integration/test_sop_render_end_to_end.py`:

```python
"""End-to-end SOP render via the FastAPI endpoint, one assertion-set per
verification-matrix scenario. The scenarios match scripts._sop_scenarios.SCENARIOS
exactly — Task 15 exercises the renderer with synthetic context dicts; this
file exercises the same surface area through a real Protocol row + the
HTTP endpoint."""

import re
import zipfile
from pathlib import Path

import pytest

# Scenario builders that materialize a Protocol row + linked rows
# matching the named scenario from the verification matrix.
from tests.factories.sop_scenarios import build_protocol_for_scenario

SCENARIO_NAMES = [
    "minimal",
    "role_based_basic",
    "time_only",
    "time_and_roles",
    "figures_only",
    "approval_full",
    "approval_partial",
    "unapproved_draft",
    "critical_requirement",
    "cycle_warning",
    "maximal",
    "edge_long_text",
]


def _docx_text(docx_bytes: bytes) -> str:
    """Extract visible text from a docx blob for substring checks."""
    import io
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", xml)


def _docx_drawing_count(docx_bytes: bytes) -> int:
    import io
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return xml.count("<w:drawing")


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIO_NAMES)
async def test_endpoint_renders_scenario(client, auth_user, db, scenario):
    """Every scenario returns 200 from the docx endpoint."""
    protocol = await build_protocol_for_scenario(db, auth_user, scenario)
    r = await client.get(f"/protocols/{protocol.id}/sop.docx")
    assert r.status_code == 200, f"{scenario} returned {r.status_code}: {r.text}"
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml"
    )


@pytest.mark.asyncio
async def test_minimal_has_no_time_no_roles(client, auth_user, db):
    p = await build_protocol_for_scenario(db, auth_user, "minimal")
    text = _docx_text((await client.get(f"/protocols/{p.id}/sop.docx")).content)
    assert not re.search(r"T=\d", text)
    # No role process_name strings.
    assert "Upstream Operator" not in text
    assert "QC Analyst" not in text


@pytest.mark.asyncio
async def test_time_only_emits_time_offsets_in_step_headings(
    client, auth_user, db
):
    p = await build_protocol_for_scenario(db, auth_user, "time_only")
    text = _docx_text((await client.get(f"/protocols/{p.id}/sop.docx")).content)
    assert "T=0" in text
    assert "T=30m" in text


@pytest.mark.asyncio
async def test_time_and_roles_offsets_cumulative_across_role_boundary(
    client, auth_user, db
):
    """Critical: Role B's first step starts where Role A's last step ended."""
    p = await build_protocol_for_scenario(db, auth_user, "time_and_roles")
    text = _docx_text((await client.get(f"/protocols/{p.id}/sop.docx")).content)
    assert "T=0" in text and "T=45m" in text
    # Only one T=0 — Role B does not restart the clock.
    assert text.count("T=0") == 1


@pytest.mark.asyncio
async def test_figures_only_figure_numbering_skips_empty_step(
    client, auth_user, db
):
    """Step 1 has 0 figures, step 2 has 1, step 3 has 2. Numbers must be 1,2,3."""
    p = await build_protocol_for_scenario(db, auth_user, "figures_only")
    body = (await client.get(f"/protocols/{p.id}/sop.docx")).content
    text = _docx_text(body)
    fig_nums = [int(m.group(1)) for m in re.finditer(r"Figure (\d+)\.", text)]
    assert fig_nums == [1, 2, 3]


@pytest.mark.asyncio
async def test_approval_full_renders_three_signature_images(
    client, auth_user, db
):
    p = await build_protocol_for_scenario(db, auth_user, "approval_full")
    body = (await client.get(f"/protocols/{p.id}/sop.docx")).content
    assert _docx_drawing_count(body) >= 3


@pytest.mark.asyncio
async def test_approval_partial_only_signed_rows_show_image(
    client, auth_user, db
):
    p = await build_protocol_for_scenario(db, auth_user, "approval_partial")
    body = (await client.get(f"/protocols/{p.id}/sop.docx")).content
    text = _docx_text(body)
    # Sponsor signed, others not — no leaked `[InlineImage:]` placeholder.
    assert "InlineImage" not in text
    # All three names still appear in the approval block.
    for name in ("Dana Park", "Dr. Lin Yao", "Marcus Reid"):
        assert name in text


@pytest.mark.asyncio
async def test_unapproved_draft_shows_warning(client, auth_user, db):
    p = await build_protocol_for_scenario(db, auth_user, "unapproved_draft")
    text = _docx_text((await client.get(f"/protocols/{p.id}/sop.docx")).content)
    upper = text.upper()
    assert "DRAFT" in upper or "UNAPPROVED" in upper


@pytest.mark.asyncio
async def test_critical_requirement_appears_above_procedure(
    client, auth_user, db
):
    p = await build_protocol_for_scenario(db, auth_user, "critical_requirement")
    text = _docx_text((await client.get(f"/protocols/{p.id}/sop.docx")).content)
    crit_at = text.find("aseptic technique")
    proc_at = text.find("Buffer Prep")
    assert 0 < crit_at < proc_at


@pytest.mark.asyncio
async def test_cycle_warning_suppresses_time_offsets(client, auth_user, db):
    p = await build_protocol_for_scenario(db, auth_user, "cycle_warning")
    text = _docx_text((await client.get(f"/protocols/{p.id}/sop.docx")).content)
    assert "cycle" in text.lower()
    assert not re.search(r"T=\d", text)


@pytest.mark.asyncio
async def test_maximal_has_all_features(client, auth_user, db):
    p = await build_protocol_for_scenario(db, auth_user, "maximal")
    body = (await client.get(f"/protocols/{p.id}/sop.docx")).content
    text = _docx_text(body)
    assert "Upstream Operator" in text
    assert "T=0" in text
    assert _docx_drawing_count(body) >= 5
    assert "aseptic" in text


@pytest.mark.asyncio
async def test_edge_long_text_does_not_lose_steps(client, auth_user, db):
    p = await build_protocol_for_scenario(db, auth_user, "edge_long_text")
    text = _docx_text((await client.get(f"/protocols/{p.id}/sop.docx")).content)
    step_count = sum(1 for _ in re.finditer(r"\bStep \d+\.\d+\b", text))
    assert step_count == 40


@pytest.mark.asyncio
async def test_caption_with_jinja_chars_rendered_literally(
    client, auth_user, factory
):
    """Cross-cutting safety check: an attacker-controlled caption with
    Jinja-looking syntax must NOT execute as a directive."""
    p = await factory.protocol()
    await factory.protocol_attachment(
        protocol_id=p.id, caption="{{ pwn }} {% if %}",
    )
    r = await client.get(f"/protocols/{p.id}/sop.docx")
    assert r.status_code == 200
    text = _docx_text(r.content)
    assert "{{ pwn }}" in text
    assert "{% if %}" in text
```

- [ ] **Step 2: Implement the `build_protocol_for_scenario` fixture**

Create `backend/tests/factories/sop_scenarios.py`. The factory takes a scenario name and returns a `Protocol` row (with linked `unit_op_instances`, role swimlane nodes, `protocol_attachments`, `protocol_approvals`) shaped to match the scenario from the matrix. Keep the scenario shapes in **lockstep** with `scripts/_sop_scenarios.py` — every conditional that the renderer script exercises with a synthetic dict should also exist in a real row here.

```python
"""Per-scenario Protocol-row factories. Names mirror SCENARIOS in
scripts/_sop_scenarios.py one-to-one."""

from uuid import uuid4

# Reuse the existing factory helpers in tests/factories/protocol.py
# for unit_op_instance, lane node, attachment, approval rows.
from tests.factories.protocol import (
    protocol_factory, lane_node, unit_op_instance,
    attachment_factory, approval_factory,
)

async def build_minimal(db, user): ...
async def build_role_based_basic(db, user): ...
# ... one per scenario ...

BUILDERS = {
    "minimal": build_minimal,
    "role_based_basic": build_role_based_basic,
    "time_only": build_time_only,
    "time_and_roles": build_time_and_roles,
    "figures_only": build_figures_only,
    "approval_full": build_approval_full,
    "approval_partial": build_approval_partial,
    "unapproved_draft": build_unapproved_draft,
    "critical_requirement": build_critical_requirement,
    "cycle_warning": build_cycle_warning,
    "maximal": build_maximal,
    "edge_long_text": build_edge_long_text,
}


async def build_protocol_for_scenario(db, user, name):
    return await BUILDERS[name](db, user)
```

Stub bodies aside, each builder writes a real `Protocol` row whose `graph_json` and child rows reflect the scenario's intent: e.g. `time_and_roles` flips `graph_json.timeEnabled=True` and constructs lane→unit-op parent relationships so the renderer computes cumulative offsets.

- [ ] **Step 3: Run the matrix-parametrized tests**

Run: `pytest backend/tests/integration/test_sop_render_end_to_end.py -v`
Expected: PASS — 12 `test_endpoint_renders_scenario[…]` cases + 12 per-scenario intent assertions + the Jinja-injection safety check.

- [ ] **Step 4: Run the full backend suite for regression**

Run: `cd backend && pytest`
Expected: PASS across the board. Investigate any failure — Task 13 (`build_context`) and Task 14 (`protocol_pdfs.py`) are the most likely sources of incidental regressions. Any scenario in this matrix that newly fails is a load-bearing signal: it means a conditional branch in the template silently changed shape.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/integration/test_sop_render_end_to_end.py \
        backend/tests/factories/sop_scenarios.py \
        backend/tests/conftest.py
git commit -m "$(cat <<'EOF'
test(BUG-0007): end-to-end SOP render matrix across 12 scenarios

Walks a real Protocol row through the live endpoint for each scenario in
the verification matrix (mirrors scripts/_sop_scenarios.py one-to-one).
Per-scenario assertions lock down the observable consequence of each
conditional template branch: cumulative time offsets across role
boundaries, figure numbering that skips empty steps, draft watermark,
critical-requirement banner ordering, cycle-warning suppresses offsets,
partial-approval rows don't leak [InlineImage:] placeholders, etc.
Includes a Jinja-injection safety check on attachment captions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 20: qa-verify pass + per-scenario Chrome browser verification

> **Why per-scenario instead of one sweep:** Tasks 15 and 19 prove that *structurally* each conditional branch behaves correctly (right XML, right text). Browser verification proves that the final rendered PDF *looks* the way we agreed it should — for every branch. A single happy-path browser check leaves regressions in unapproved/cycle/partial-approval branches undetected until a user hits them in prod.

**Files:** (none — verification only)

- [ ] **Step 1: Bring up dev servers in the worktree**

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8010 &
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183 &
```

Confirm: `curl -s localhost:8010/health` → 200; open `localhost:5183` in Chrome → login screen.

- [ ] **Step 2: Seed one protocol per matrix scenario**

Add a dev-only seed script `backend/scripts/seed_bug0007_matrix.py` that uses the same `BUILDERS` from `tests/factories/sop_scenarios.py` to materialize 12 protocols named `BUG0007 — <scenario>` in a dedicated `BUG-0007 QA` project. The protocols must persist (no rollback) so the browser pass can navigate to each.

```bash
cd backend && source .venv/bin/activate
python scripts/seed_bug0007_matrix.py --org "Acme Bio" --user wesu07@gmail.com
# Prints the 12 protocol IDs and a per-scenario URL to open in Chrome.
```

- [ ] **Step 3: Per-scenario Chrome browser verification**

Use the `mcp__claude-in-chrome` tools. For *each* of the 12 scenarios, open the SOP preview, render the PDF, take a screenshot of every page, and verify against the agreed section-per-step mock. Stay strict on the per-scenario pass/fail criteria below — they are the precise observable consequences of each conditional template branch.

Workflow per scenario:
1. `tabs_create_mcp` → `localhost:5183/protocols/<id>` (the editor view).
2. Confirm the Protocol Sidebar shows `doc_number = SOP-NNNN` for the auto-assigned value.
3. Click "Preview SOP" → backend serves the PDF in-tab.
4. `get_page_text` to dump the visible text of the PDF (Chrome renders the PDF inline) and scroll-screenshot every page.
5. Compare visually against the corresponding `docs/previews/sop_default/sop_<scenario>-*.png` baseline. They should match — the seed protocol was built from the same scenario builder. Any drift = bug.

Per-scenario pass/fail criteria (FAIL on any miss; POLISH on visible-but-ugly):

| Scenario | Browser pass/fail criteria |
|----------|----------------------------|
| `minimal` | Flat 3-step list. No role headings. No T=… markers. No critical-requirement banner. No approvals block. No DRAFT watermark. Each step = bold 12pt heading + full-width body paragraph (no Instruction column). |
| `role_based_basic` | Role headings "Upstream Operator" / "QC Analyst" rendered 16pt black bold (visually dominant). Steps grouped under each role. Still no T=… markers. |
| `time_only` | Step headings of the form `1. Prep — T=0 (30 min)`. No role headings. |
| `time_and_roles` | Role A steps show T=0, T=30m. Role B's first step shows **T=45m** (not T=0). Visually verify the clock does NOT reset across role boundary. |
| `figures_only` | Step 1 has no figure block (no awkward empty paragraph). Step 2 shows Figure 1 inline under the description. Step 3 shows Figure 2 and Figure 3 in order. Figure caption renders below image at 10pt. |
| `approval_full` | Approvals block at end with 3 rows. Each row shows: name, date, attestation text, **signature image** (hand-drawn-looking PNG). All three signature drawings render — no broken-image icons. |
| `approval_partial` | Approvals block at end with 3 rows. Sponsor row has signature image. Study Director + QAU rows show "Pending" or empty signature line — no `[InlineImage:...]` literal text leaks through, no broken-image icon. |
| `unapproved_draft` | Visible DRAFT or UNAPPROVED banner/watermark (top of page or diagonal across body). Approvals block still rendered but with all rows pending/empty. |
| `critical_requirement` | Critical-requirement banner appears between Purpose/Scope and the first procedure step. Banner styling visually distinct (background fill or rule above/below). |
| `cycle_warning` | Warning banner referencing "cycle" appears (color/icon distinct). Step headings do **not** include T=… markers. |
| `maximal` | All of the above visible together. Mirrors `docs/previews/sop_default/sop_maximal-*.png` baseline within minor anti-aliasing differences. |
| `edge_long_text` | All 40 step headings (`Step 1.1` … `Step 5.8`) render. No text overflow off the right margin. No step heading orphaned at bottom of page from its body. Page count > 6. |

After each scenario, record one line:
```
[scenario] [PASS|FAIL|POLISH] [<one-line note if FAIL/POLISH>]
```

- [ ] **Step 4: Launch the qa-verify agent for cross-cutting + sub-issue verification**

Launch the `qa-verify` agent with this brief:

> Verify BUG-0007 SOP / Batch Record template overhaul. Dev servers at `localhost:5183` (frontend) and `localhost:8010` (backend). Login with wesu07@gmail.com / any password. The seed script `backend/scripts/seed_bug0007_matrix.py` has created 12 named protocols under "BUG-0007 QA" project, one per scenario in `scripts/_sop_scenarios.py`.
>
> **Cross-cutting sub-issue checklist** (run on the `maximal` protocol):
>
> 1. **Sub-issue 1 — doc_number.** Open Protocol Sidebar — `doc_number` visible and shows auto-generated `SOP-NNNN`. Click it → becomes editable. Enter a value already in use by another protocol in the same org → expect inline red error citing the conflicting protocol's name. No toast. Empty save → also inline error.
> 2. **Sub-issue 2 — no Instruction column.** Render the SOP preview. The old narrow Instruction column is gone — each step renders as a bold heading on its own line + a full-width body paragraph spanning the page width + (optional) figure block below.
> 3. **Sub-issue 3 — time markers.** Toggle time on/off in the editor on the `time_and_roles` protocol. Re-render. With time ON, step headings show `T=…` and cumulative offsets across roles. With time OFF, the `T=…` segment vanishes from every heading.
> 4. **Sub-issue 4 — figure attachments.** Select a unit-op node. Inspector has a collapsible FIGURES section. Expand → drop an image (or use file picker). Thumbnail appears. Click thumbnail → full-screen modal. Add a caption, blur, re-render PDF → caption renders below image inline under that step's description. Delete the figure → thumbnail gone AND figure gone from rendered PDF.
>
> **Matrix verification** (per-scenario from step 3 above): for each of the 12 scenarios, open the preview and visually confirm the pass/fail criteria in the matrix table. If any scenario diverges from its baseline at `docs/previews/sop_default/sop_<scenario>-*.png`, that's a FAIL — fix and re-render.
>
> **Cross-cutting visual hygiene** (every PDF):
> - Role headings 16pt black bold dominate step headings 12pt black bold.
> - No residual blue Heading-3 color from the old template.
> - Body double-spaced (lineRule auto, line=480 in XML).
> - No `[InlineImage:…]` literal text anywhere.
> - No double-spaces in step headings ("1.  Step" vs "1. Step").
>
> Fix anything that FAILs or needs POLISH before returning. Report the per-scenario pass/fail table and the four sub-issue results.

- [ ] **Step 5: Land qa-verify's fixes (if any)**

The qa-verify agent commits its fixes inline. After it returns, review `git log` for the new commits and confirm they look reasonable. If qa-verify edited the renderer script or `_sop_scenarios.py`, regenerate the baselines:

```bash
cd backend && python scripts/render_sample_sop.py --scenario all
git add docs/previews/sop_default/
git diff --staged --stat  # confirm only the affected scenario(s) changed
git commit -m "chore(BUG-0007): refresh preview baselines after qa-verify fixes"
```

- [ ] **Step 6: User sign-off**

Present the per-scenario verification table + the sub-issue results to the user. Wait for explicit "looks good" before moving to the cleanup step. If the user wants to spot-check, attach `docs/previews/sop_default/sop_<scenario>.pdf` for any scenario they call out.

---

## Task 21: Update `KNOWN_VARIABLES` for template-converter parity

> **Why this task exists**: `template_engine.KNOWN_VARIABLES` (line 29) is consumed by `parse_template()` (line 65) and by the LLM template-converter at `backend/app/services/protocols/template_converter.py`. Without `doc_number` in this set, `parse_template()` flags `{{ doc_number }}` as an *unrecognized* variable in any uploaded template — the settings UI then shows a scary "unknown variable" warning on a perfectly valid upload.

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py:29-62`
- Test: `backend/tests/unit/services/protocols/test_template_engine.py` (add or extend)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/services/protocols/test_template_engine.py
from app.services.protocols.template_engine import KNOWN_VARIABLES, parse_template


def test_known_variables_contains_doc_number_and_time_flags():
    """BUG-0007 added doc_number, time_enabled, time_warning to the
    render context. The converter and parse_template must recognize
    them so uploaded templates with these tokens don't flag as unknown."""
    assert "doc_number" in KNOWN_VARIABLES
    assert "time_enabled" in KNOWN_VARIABLES
    assert "time_warning" in KNOWN_VARIABLES


def test_parse_template_recognizes_step_time_offset_and_figures(tmp_path):
    """`{{ step.time_offset }}` and `{{ fig.image }}` inside a
    `{%p for step in steps %}` loop must be recognized via the
    top-level `steps` prefix already in KNOWN_VARIABLES."""
    from docx import Document
    doc = Document()
    doc.add_paragraph("{%p for step in steps %}{{ step.time_offset }}{%p endfor %}")
    doc.add_paragraph("{%p for fig in figures %}{{ fig.image }}{%p endfor %}")
    p = tmp_path / "t.docx"
    doc.save(p)
    recognized, unrecognized = parse_template(p)
    # step.time_offset → top-level "steps" is in KNOWN_VARIABLES → recognized
    assert "step.time_offset" in recognized
    assert "fig.image" in recognized
    assert unrecognized == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && source .venv/bin/activate
pytest tests/unit/services/protocols/test_template_engine.py::test_known_variables_contains_doc_number_and_time_flags -v
```

Expected: FAIL with `AssertionError: assert 'doc_number' in {…}` (set doesn't contain it).

- [ ] **Step 3: Add the new variables to `KNOWN_VARIABLES`**

```python
# backend/app/services/protocols/template_engine.py:29
KNOWN_VARIABLES = {
    # Protocol
    "protocol_name",
    "protocol_description",
    "version_number",
    "created_at",
    "doc_number",                 # BUG-0007
    # Run
    "run_name",
    "run_status",
    "started_at",
    "completed_at",
    # Project / Org
    "project_name",
    "organization_name",
    # Layout
    "is_role_based",
    "page_break",
    "time_enabled",               # BUG-0007
    "time_warning",               # BUG-0007 (set when compute_time_offsets returns cycle_detected)
    # Loops (top-level)
    "roles",
    "steps",
    "notes",
    "figures",
    "non_image_attachments",
    # Approval (F-0066)
    "approval",
    "approval_history",
    "unapproved_warning",
    "requires_approval",
    # GLP sign-offs (F-0087)
    "signoffs",
    "protocol_approvals",
    "run",
    "equipment",
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/services/protocols/test_template_engine.py -v -k "known_variables or parse_template_recognizes_step"
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/template_engine.py backend/tests/unit/services/protocols/test_template_engine.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): recognize doc_number / time flags in KNOWN_VARIABLES

parse_template() and the LLM template-converter consult this set when
deciding which Jinja tokens are valid. Without these entries the
settings/templates upload flow flags uploaded SOPs with {{ doc_number }}
as containing unknown variables.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 22: Update `get_mock_context()` for converter LLM preview parity

> **Why this task exists**: `template_converter.py` (line 31) imports `get_mock_context` and feeds it to the LLM as a "what does a populated template look like" reference. With `doc_number` empty, time markers missing, and step figures absent, the LLM has no signal to map a user-uploaded doc-number cell to `{{ doc_number }}` or a step-image cell to `{{ fig.image }}`. After BUG-0007, the mock context must mirror the new fields end-to-end.

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py:999+` (the `get_mock_context` function body)
- Test: `backend/tests/unit/services/protocols/test_template_engine.py`

- [ ] **Step 1: Write the failing test**

```python
def test_mock_context_includes_doc_number_and_time_markers():
    """The LLM converter consumes this mock as its reference. Empty
    or missing fields produce poor mappings for user-uploaded SOPs."""
    from app.services.protocols.template_engine import get_mock_context
    ctx = get_mock_context()

    assert ctx["doc_number"], "doc_number must be populated for converter preview"
    assert ctx["doc_number"].startswith("SOP-")
    assert ctx["time_enabled"] is True

    # Per-step time_offset and figures must be present on at least one step.
    role0 = ctx["roles"][0]
    step0 = role0["steps"][0]
    assert "time_offset" in step0
    assert step0["time_offset"].startswith("T="), "time_offset must format like 'T=0' / 'T=15m'"
    assert isinstance(step0.get("figures", []), list)
    # At least one step in the mock should have at least one figure attached,
    # so the LLM sees what a per-step figure looks like.
    has_any_figure = any(
        bool(s.get("figures")) for r in ctx["roles"] for s in r["steps"]
    )
    assert has_any_figure, "mock context must include at least one per-step figure"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/services/protocols/test_template_engine.py::test_mock_context_includes_doc_number_and_time_markers -v
```

Expected: FAIL — `assert ctx["doc_number"]` because `build_context` was not passed `doc_number`.

- [ ] **Step 3: Extend `get_mock_context()` to thread the new fields through**

Edit the `build_context(...)` call inside `get_mock_context()`:

```python
def get_mock_context() -> dict[str, Any]:
    """Build mock context for template preview. Lazy — only called when needed.

    BUG-0007: includes doc_number, time_enabled, per-step time_offset, and
    one per-step figure so the LLM template-converter sees what each new
    Jinja token resolves to.
    """
    ctx, _ = build_context(
        protocol_name="Example Protocol — Buffer Preparation",
        protocol_description=(
            "This protocol describes the preparation of phosphate-buffered "
            "saline (PBS) for use in downstream cell culture applications."
        ),
        version_number=3,
        created_at="January 15, 2026",
        doc_number="SOP-0042",                  # BUG-0007
        time_enabled=True,                      # BUG-0007
        run_name="Run-2026-001",
        run_status="COMPLETED",
        started_at="2026-01-20 08:00",
        completed_at="2026-01-20 14:30",
        project_name="AAV Production Campaign Q1",
        organization_name="Acme Therapeutics",
        is_role_based=True,
        roles_with_steps=[
            {
                "role_name": "Media Prep",
                "steps": [
                    {
                        "name": "Weigh Reagents",
                        "description": "Weigh out NaCl, KCl, and phosphate salts.",
                        "params": {"nacl_g": 8.0, "kcl_g": 0.2},
                        "param_schema": {
                            "properties": {
                                "nacl_g": {"title": "NaCl", "unit": "g"},
                                "kcl_g": {"title": "KCl", "unit": "g"},
                            }
                        },
                        "duration_min": 10,
                        "time_offset": "T=0",      # BUG-0007
                        "figures": [               # BUG-0007 — one figure on the first step
                            {
                                "number": 1,
                                "caption": "Reagent weighing setup (10× balance).",
                                "image_ok": True,
                                # No InlineImage in the mock — the converter only inspects
                                # caption + number text; the actual image is rendered live.
                            },
                        ],
                    },
                    {
                        "name": "Dissolve in Water",
                        "description": (
                            "Add reagents to {{volume}} mL of purified water "
                            "and stir until dissolved."
                        ),
                        "params": {"volume": 1000},
                        "param_schema": {
                            "properties": {"volume": {"title": "Volume", "unit": "mL"}}
                        },
                        "duration_min": 15,
                        "time_offset": "T=10m",    # BUG-0007
                        "figures": [],
                    },
                ],
            },
            {
                "role_name": "QC",
                "steps": [
                    {
                        "name": "Measure pH",
                        "description": "Measure pH and adjust to target.",
                        "params": {"target_ph": 7.4},
                        "param_schema": {
                            "properties": {"target_ph": {"title": "Target pH"}}
                        },
                        "duration_min": 5,
                        "time_offset": "T=25m",    # BUG-0007
                        "figures": [],
                    },
                ],
            },
        ],
        # … rest of build_context kwargs unchanged (flat_steps, etc.)
    )
    return ctx
```

**Implementer note**: only the `build_context(...)` call body changes. The function's contract and return type are unchanged. The `flat_steps=` block (line 1061+) should mirror the same `time_offset` / `figures` additions on each step entry for consistency.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/services/protocols/test_template_engine.py -v -k "mock_context"
# Plus the existing template_converter regression suite, if any:
pytest tests/unit/services/protocols/ -v -k "template_converter or get_mock_context"
```

Expected: PASS. No template_converter regressions.

- [ ] **Step 5: Visual smoke check (manual, one-shot)**

Open `/settings?tab=templates` in the running dev server, click "Upload template" on any test docx that contains a doc-number cell. Verify the converter's preview pane now shows `SOP-0042` (or whatever the mock sets) in the doc-number position, and that a step's preview shows `T=0` / `T=10m` instead of empty time fields. No code change here — just eyeball that the LLM is getting better signal.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/protocols/template_engine.py backend/tests/unit/services/protocols/test_template_engine.py
git commit -m "$(cat <<'EOF'
feat(BUG-0007): include doc_number / time / figures in get_mock_context

The LLM template-converter consumes get_mock_context() as its reference
for what a populated template looks like. Pre-BUG-0007 the mock had no
doc_number, no time markers, and no per-step figures — so the LLM had
no signal to tokenize matching content from user uploads. Threading
these fields through keeps the settings/templates upload flow honest.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 23: Cleanup — refresh project rules + ClickUp + close worktree

**Files:**
- Modify: `CLAUDE.md` (if new env var / command surface introduced)
- Modify: `.claude/rules/conventions.md` (if a new convention emerged)
- Comment + status update on the ClickUp task

- [ ] **Step 1: Sync rules**

Review `.claude/rules/conventions.md` and `CLAUDE.md`. Add lines only for genuinely new conventions:

- The `protocol_attachments` child-table-not-JSONB rule for new per-entity attachment surfaces (cross-reference `equipment_attachments` and now `protocol_attachments`).
- The `scripts/render_sample_sop.py` regenerate-on-change discipline (already documented in `docs/previews/sop_default/README.md`; cross-reference may not be necessary).

Prune any stale lines referencing the old step-table renderer if such lines exist.

- [ ] **Step 2: Update ClickUp**

```python
clickup_create_task_comment(
    task_id="BUG-0007",
    comment=(
        "Shipped:\n"
        "- doc_number auto-generates SOP-NNNN per org; inline editable in ProtocolSidebar.\n"
        "- Section-per-step layout replaces step-tables (squished column dissolved).\n"
        "- Cumulative time offsets in the rendered preview when timeEnabled.\n"
        "- protocol_attachments child table + Inspector figure panel; figures render inline.\n"
        "- Visual verification gate: scripts/render_sample_sop.py + checked-in PDF/PNG baselines + XML pytest asserts."
    ),
)
clickup_update_task(task_id="BUG-0007", status="complete")
```

- [ ] **Step 3: Exit worktree, preserving commits**

`ExitWorktree(action="keep")`.

---

## File touchlist (cross-reference)

### Backend

| File | Action |
| --- | --- |
| `backend/app/services/data/graph_processing.py` | Add `compute_time_offsets`, `format_time_offset` |
| `backend/app/services/protocols/doc_number.py` | New module |
| `backend/app/services/core/file_storage.py` | Add `validate_image_file`, `InvalidImage` |
| `backend/app/services/protocols/template_engine.py` | Add `_swap_file_path_to_inline_image`; extend `build_context`; add `doc_number` / `time_enabled` / `time_warning` to `KNOWN_VARIABLES`; thread new fields through `get_mock_context()` |
| `backend/app/models/protocols.py` | Add `ProtocolAttachment` model |
| `backend/app/schemas/protocols.py` | Add `ProtocolAttachmentResponse`, `ProtocolAttachmentCaptionPatch` |
| `backend/app/api/endpoints/protocol_attachments.py` | New module — upload/patch/delete/stream |
| `backend/app/api/endpoints/protocols.py` | Wire `generate_default_doc_number` + 409 surfacing |
| `backend/app/api/endpoints/protocol_pdfs.py` | Bulk-fetch attachments, pass to `build_context` |
| `backend/app/main.py` | Register `protocol_attachments` router |
| `backend/alembic/versions/<rev>_bug0007_…py` | New migration |
| `backend/scripts/rewrite_sop_step_tables.py` | New checked-in idempotent script |
| `backend/scripts/render_sample_sop.py` | New sample renderer |
| `backend/tests/...` | See per-task tests |

### Templates (binary, LFS-tracked)

- `backend/app/services/documents/templates/sop_default.docx`
- `backend/app/services/documents/templates/batch_record_default.docx`
- `backend/uploads/system/document_templates/sop_default.docx`
- `backend/uploads/system/document_templates/batch_record_default.docx`

### Frontend

| File | Action |
| --- | --- |
| `frontend/src/lib/api.ts` | Add `patchProtocol`, `uploadProtocolAttachment`, `patchProtocolAttachment`, `deleteProtocolAttachment`, `fetchProtocolAttachmentBlobUrl` |
| `frontend/src/lib/schemas/protocol.ts` | Add `protocolAttachmentSchema`, `ProtocolAttachment` |
| `frontend/src/lib/components/protocol/ProtocolSidebar.svelte` | Add doc_number row |
| `frontend/src/lib/components/protocol/Inspector.svelte` | Include `InspectorFigures` |
| `frontend/src/lib/components/protocol/InspectorFigures.svelte` | New component |

### Previews (LFS-tracked)

- `docs/previews/sop_default/README.md`
- `docs/previews/sop_default/sop_maximal_with_time.{pdf, png pages}`
- `docs/previews/sop_default/sop_maximal_without_time.{pdf, png pages}`

### LFS config

- `.gitattributes` — `*.docx`, `*.pdf`, `*.png` filters

---

## Out-of-scope (per spec — log as TECH_DEBT only)

- pHash CI gate (Layer 3 visual verification)
- Streaming write in `FileStorageService.store_file()`
- Reordering figures within a step
- Per-org / per-protocol storage quota
- Rate-limit middleware on upload
- Auto-cleanup of orphaned attachments on graph-node delete
- `InlineImage(width=min(Inches(5.5), natural_width))` for portrait figures
- Soft-delete helper extraction across run + protocol attachment models
- Run-side attachment migration to a child table
- `w:keepWithNext` on signature blocks
