# F-0080 Custom Drawn Signatures — Design

## Goal

Let users draw a personal signature (DocuSign-style, finger/stylus on a canvas)
once in Settings and have it replace the auto-generated cursive initials
wherever a signature is rendered. Two distinct images are captured:

- **Initials signature** — small squiggle that replaces inline step sign-off
  initials (e.g., "J.S.") in batch records, run sign-offs, and any other
  surface that renders `step.initials`.
- **Full signature** — full DocuSign-style signature for document-level
  approval blocks. Captured + stored + previewed in this task; rendered into
  approval surfaces by the future approval flow (F-0066).

If a user has not drawn a particular signature image, the system continues to
use the existing text fallback unchanged.

## Scope

**In scope**

- New `signature_initials_path` and `signature_full_path` columns on `User`
- Upload / delete / serve endpoints for both signatures
- Settings UI: a "Signature" card in the Profile tab with two pads
  (Initials + Full) and per-pad save/clear/preview
- Backend wiring: `template_engine.build_context` sets `step.initials` to an
  `InlineImage` when the completing/editing user has a registered initials
  signature, else passes the existing plain-text initials string. Templates
  keep using `{{ step.initials }}` — no template changes needed
- Audit log entries on signature create / replace / delete
- Storage at `{org_id}/signatures/{user_id}.png` (mirrors avatar layout)

**Out of scope**

- The deprecated fpdf2 path (`_draw_cursive_initials` in `pdf_base.py`,
  `batch_record_generator.py`). It's dead code only invoked by tests; it will
  be removed by the broader fpdf2 cleanup. Leave untouched.
- Any docx rendering for `signature_full` — there's no template variable for
  it yet. F-0066 owns wiring it into approval blocks.
- Offline / PWA caching of signatures.

## Architecture

### Data model

Add two nullable columns to `User`:

```python
signature_initials_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
signature_full_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
```

Both store relative paths under the file storage root, in the form
`{org_id}/signatures/{user_id}-initials.png` and
`{org_id}/signatures/{user_id}-full.png`. PNG with transparent background.

Migration: single Alembic revision adding both columns. No backfill needed —
nullable.

### Storage

Reuse `FileStorageService` (no new abstraction). Layout mirrors avatars:

```
storage_root/{org_id}/signatures/{user_id}-initials.png
storage_root/{org_id}/signatures/{user_id}-full.png
```

Limits:

- Max upload size: **500 KB** (per task description)
- Allowed MIME: `image/png` only (we always normalize on the client to PNG
  with transparent background; the server validates and rejects other types)
- No further server-side resizing — frontend exports the canvas at a sensible
  fixed pixel ratio

### Endpoints

Mirror the avatar pattern in `backend/app/api/endpoints/auth.py`. A single
"kind" path segment selects which signature (`initials` or `full`):

```
POST   /auth/me/signature/{kind}    multipart upload
DELETE /auth/me/signature/{kind}    clear stored signature
GET    /auth/signatures/{user_id}/{kind}    serve PNG (org-scoped, token via header or ?token=)
```

`kind ∈ {"initials", "full"}`. Each upload writes to the correct path,
overwrites any existing file for that kind, updates the user column,
and emits an audit log. `DELETE` removes the file and nulls the column.

`UserResponse` gains two computed URL fields (`signature_initials_url`,
`signature_full_url`) — populated when the corresponding `*_path` is set,
mirroring `avatar_url`.

### Audit log

Use existing `log_audit` (module function). Entity type
`"user_signature"`, entity_id = the user's `id`. Action one of
`"signature_created"`, `"signature_replaced"`, `"signature_deleted"`. Details
payload includes `kind` (`"initials"` or `"full"`).

### Render path (docx)

The single integration point is `template_engine.build_context` (and the
helper functions it calls when iterating step rows / role rows). Today they
do:

```python
initials = _get_initials(name) if name else ""
# step["initials"] = initials  (a string)
```

After this change, builders gain a `_resolve_initials` helper:

```python
def _resolve_initials(
    *,
    user_id: str,
    name: str,
    user_signatures: dict[str, str],   # user_id -> resolved abs path
    docx: DocxTemplate,
) -> Union[RichText, InlineImage]:
    """Return InlineImage when the user has a registered initials signature,
    else fall back to cursive-styled text initials."""
    path = user_signatures.get(user_id)
    if path and Path(path).exists():
        return InlineImage(docx, path, width=Mm(20))  # narrow inline cell
    return RichText(_get_initials(name), font="Dancing Script")
```

`build_context` callers gather all relevant user IDs (`completed_by_user_id`,
`edited_by_user_id`, `started_by_id`) and bulk-load their
`signature_initials_path` once at the top, resolve to absolute paths via
`FileStorageService`, and pass the dict into the resolver. No N+1 queries.

The variable name in the docx template stays `step.initials`. No template
change needed; the existing seeded `.docx` files continue to work, and
user-uploaded templates automatically get cursive fallbacks too because
docxtpl applies `RichText` font formatting at render time.

`signature_full` is captured + stored + serveable but is **not** added to the
docx context in this task — there's no template variable for it yet.

#### Cursive font availability

The `RichText(font="Dancing Script")` only renders cursive if LibreOffice
can find the font via fontconfig. We bundle `DancingScript-Regular.ttf` in
the repo; today it's only used by the deprecated fpdf2 path. We need
LibreOffice to see it too.

**Move the font** from `backend/app/services/documents/fonts/` to
`backend/app/data/fonts/DancingScript-Regular.ttf` so it lives alongside
other bundled app data (e.g. `backend/app/data/unit_op_libraries/`).
Update the existing fpdf2 import (`pdf_base._CURSIVE_FONT_PATH` /
`fonts.FONTS_DIR`) to the new location so the deprecated path keeps
working until cleanup.

**Register at app startup.** New helper
`backend/app/services/documents/font_setup.py::ensure_cursive_font_registered()`
called from FastAPI's startup event:

```python
def ensure_cursive_font_registered() -> None:
    """Copy DancingScript into the user font dir and refresh fontconfig
    cache so LibreOffice can find it. Idempotent — no-ops if already
    registered."""
    src = Path(__file__).parent.parent.parent / "data" / "fonts" / "DancingScript-Regular.ttf"
    dest_dir = Path.home() / ".fonts"
    dest = dest_dir / src.name
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, dest)
        try:
            subprocess.run(
                ["fc-cache", "-f", str(dest_dir)],
                check=True, timeout=10, capture_output=True,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as e:
            logger.warning("fc-cache failed; cursive fallback may not render: %s", e)
```

Failure is non-fatal — if `fc-cache` is unavailable or the copy fails, the
text initials still appear in the PDF, just in the document's body font
instead of cursive. Logged at WARN level.

For prod (Docker) we can later add a Dockerfile line that installs the
font at image-build time as belt-and-suspenders, but that's not required
for this task.

### Frontend

#### Library

`signature_pad` (npm). Wrapped in a small `SignaturePad.svelte` primitive
under `lib/components/ui/signature-pad/` (matches shadcn-svelte folder
convention). The wrapper exposes:

- `bind:isEmpty` — whether the pad currently has any strokes
- a method `toBlob(): Promise<Blob | null>` — exports a PNG blob
- a method `clear(): void`

#### Settings UI

New "Signature" card in the Profile tab (`routes/settings/+page.svelte`),
placed below the existing avatar/profile card. Shows two side-by-side
sub-sections:

1. **Initials** — narrow pad (~280×120px). Save / Clear buttons. Preview the
   currently-stored image; show the auto-generated cursive initials as the
   fallback preview when nothing is stored.
2. **Full Signature** — wider pad (~480×120px). Same Save / Clear buttons.
   Preview the stored full signature; show the user's full name in plain
   styling as the fallback preview.

A short note: "Drawn signatures replace the auto-generated cursive initials
in PDF exports. Full signatures will be used for document approvals."

Each pad uses `signature_pad` with sensible defaults
(`minWidth=0.5, maxWidth=2.5, throttle=16, velocityFilterWeight=0.7`).
Touch/stylus events are handled by the library directly. The canvas honors
`window.devicePixelRatio` for crisp output.

API client extensions:

- `api.uploadFile('/auth/me/signature/initials', blob)`
- `api.uploadFile('/auth/me/signature/full', blob)`
- `api.delete('/auth/me/signature/initials' | '/auth/me/signature/full')`

`refreshUser()` after each save / delete so the preview reacts.

## Failure modes

- **Upload too large / wrong type** → 400 with descriptive detail (matches
  avatar behavior).
- **Storage write fails** → 500; the user record is not updated. We reuse
  the existing pattern from avatar upload (try-except around delete of old
  file is best-effort).
- **Image file goes missing on disk** but `*_path` is set → renderer falls
  back to text initials (the resolver checks `Path.exists()`).
- **User leaves the org / org changes** → signatures stay in their original
  `{org_id}` path. The stored relative path on the user is the source of
  truth; no rewrite on org switch (avatars work the same way today).

## Testing

Backend:

- Unit: `_resolve_initials` returns `InlineImage` when path exists, returns
  text fallback otherwise.
- Integration: POST `/auth/me/signature/initials` with valid PNG → 200, file
  written, user row updated, audit log written.
- Integration: POST with an unsupported type (image/jpeg) → 400.
- Integration: POST when over 500 KB → 400.
- Integration: DELETE clears file + column + writes audit log.
- Integration: GET `/auth/signatures/{user_id}/initials` requires same-org
  auth (mirrors avatar test).
- Smoke: render a docx batch record for a run where one user has a stored
  initials signature and another does not — assert the first row contains
  an embedded image and the second row contains the text initials.

Frontend:

- Vitest: `SignaturePad.svelte` `clear()` empties the canvas, `toBlob()`
  resolves to a non-null blob after a stroke and null when empty.
- Manual / Playwright: draw → save → reload → preview shows stored image;
  clear → save with empty pad is rejected; delete restores fallback.

## Browser verification (qa-verify)

After implementation passes the unit + integration suites, launch the
`qa-verify` agent to validate the feature end-to-end in a browser. The agent
must check both functional correctness and UI/UX polish. Brief it with:

**Login**: dev creds `localhost:5432` / `postgres` / `postgres` / `batchrite`;
any password works.

**Functional checks** (must all pass):

- Settings → Profile tab shows a new "Signature" card with two pads
  (Initials + Full)
- Drawing on the initials pad and clicking Save persists the signature;
  reload shows the stored image preview, not the cursive fallback
- Clicking Clear empties the pad without saving
- Clicking Delete removes the stored signature; preview reverts to the
  cursive auto-generated initials
- Same flow for the Full Signature pad
- Saving an empty pad is rejected with a visible error
- Uploading >500 KB or non-PNG via direct API → 400 (sanity check)
- Generate a batch record PDF for a run where the current user has a
  saved initials signature: open the rendered PDF and confirm the
  initials cells contain the drawn image rather than text
- Generate the same PDF for a user with NO saved signature: confirm the
  cells contain cursive text initials (Dancing Script font)

**UI/UX audit** (qa-verify must catch and fix any of these):

- The Signature card matches the visual style of the surrounding Profile
  cards (same `Card` / `CardHeader` / `CardContent` primitives, spacing,
  typography)
- The two pads sit side-by-side on desktop and stack cleanly on tablet /
  narrow viewports
- Pad canvases have a clear border, visible "Sign here" baseline or
  placeholder, and obvious affordance (cursor-crosshair, hover state)
- Save / Clear / Delete buttons follow project button conventions
  (shadcn-svelte primitives, correct variants, `cursor-pointer`,
  `hover:` transitions)
- Touch / stylus drawing works smoothly on a tablet viewport (qa-verify
  should resize the browser to a tablet width and try drawing)
- Loading spinner appears during upload (mirrors avatar pattern)
- Toast notifications fire on success / failure (uses existing `toast`)
- No layout shifts, oversized inputs, overflow, or spacing inconsistencies
- Strokes are smooth (signature_pad's bezier interpolation is enabled,
  not jagged segments)

The qa-verify agent must fix any FAIL or POLISH issues it finds before
returning. Report back with a confirmation that all checks pass and a
short note on anything that was adjusted.

## Migration / rollout

- Single Alembic migration adding both columns. No data backfill.
- No feature flag — feature is additive; the fallback exactly matches today's
  behavior.

## File touch list (rough)

Backend:

- `backend/app/models/iam.py` — add two columns
- `backend/alembic/versions/<new>_add_user_signatures.py` — migration
- `backend/app/schemas/auth.py` — add `signature_initials_url`,
  `signature_full_url` to `UserResponse`
- `backend/app/api/endpoints/auth.py` — three new routes (POST/DELETE/GET)
- `backend/app/services/protocols/template_engine.py` — `_resolve_initials`
  helper; bulk preload signature paths in `build_context`
- `backend/app/data/fonts/DancingScript-Regular.ttf` (move from
  `backend/app/services/documents/fonts/`)
- `backend/app/services/documents/fonts/__init__.py` — update
  `FONTS_DIR` to point at the new location (or remove if no longer
  needed)
- `backend/app/services/documents/font_setup.py` (new) —
  `ensure_cursive_font_registered()` helper
- `backend/app/main.py` — call the helper from FastAPI startup
- `backend/tests/integration/test_user_signatures.py` (new)
- `backend/tests/unit/test_template_engine_signatures.py` (new)
- `backend/tests/unit/test_font_setup.py` (new)

Frontend:

- `frontend/src/lib/components/ui/signature-pad/signature-pad.svelte` (new)
- `frontend/src/lib/components/ui/signature-pad/index.ts` (new)
- `frontend/src/routes/settings/+page.svelte` — new Signature card under
  Profile tab; signature state + handlers
- `frontend/src/lib/auth.svelte.ts` — surface
  `signature_initials_url`/`signature_full_url` on the user store
- `frontend/package.json` — add `signature_pad`
