# F-0080 Custom Drawn Signatures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users draw a personal initials signature and a full DocuSign-style signature in Settings; render the drawn initials as an embedded image in PDF batch records, with a cursive (Dancing Script) text fallback when no signature is registered.

**Architecture:** Mirror the existing avatar pattern for storage/endpoints (`User` columns + `FileStorageService` + `/auth/me/...` routes). Render integration is a single new helper (`_resolve_initials`) that swaps `step.initials` from plain text into either an `InlineImage` (registered) or `RichText(font="Dancing Script")` (fallback) at docx-render time. A startup hook copies the bundled `DancingScript-Regular.ttf` into `~/.fonts` and runs `fc-cache` so LibreOffice can resolve the font.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, docxtpl + LibreOffice (existing), `signature_pad` (new npm dep, ~13kB), Svelte 5 runes + shadcn-svelte, `RichText`/`InlineImage` from `docxtpl`.

**Spec:** `docs/superpowers/specs/2026-04-29-f-0080-custom-drawn-signatures-design.md`

---

## File Structure

**New files:**

- `backend/app/data/fonts/DancingScript-Regular.ttf` (moved from `backend/app/services/documents/fonts/`)
- `backend/app/services/documents/font_setup.py` — `ensure_cursive_font_registered()` startup helper
- `backend/tests/unit/test_font_setup.py`
- `backend/tests/unit/test_template_engine_signatures.py`
- `backend/tests/integration/test_user_signatures.py`
- `frontend/src/lib/components/ui/signature-pad/signature-pad.svelte`
- `frontend/src/lib/components/ui/signature-pad/index.ts`
- `frontend/src/lib/components/settings/SignatureCard.svelte` — domain settings card
- `backend/alembic/versions/<timestamp>_add_user_signature_paths.py` — migration

**Modified files:**

- `backend/app/services/documents/fonts/__init__.py` — re-point `FONTS_DIR` to new location
- `backend/app/main.py` — call `ensure_cursive_font_registered()` in `lifespan`
- `backend/app/models/iam.py` — two new `User` columns
- `backend/app/schemas/auth.py` — two new `UserResponse` URL fields
- `backend/app/api/endpoints/auth.py` — three new routes; helper for kind validation; UserResponse builder updates
- `backend/app/services/protocols/template_engine.py` — `_resolve_initials` helper, bulk-load signature paths in `build_context`, swap `step.initials` in `render_to_docx`
- `frontend/package.json` — add `signature_pad`
- `frontend/src/lib/auth.svelte.ts` — surface new URL fields on the user store (if not auto-passed)
- `frontend/src/routes/settings/+page.svelte` — embed `<SignatureCard />` in Profile tab

---

## Phase A — Backend storage + endpoints

### Task 1: Relocate the cursive font

**Files:**
- Move: `backend/app/services/documents/fonts/DancingScript-Regular.ttf` → `backend/app/data/fonts/DancingScript-Regular.ttf`
- Modify: `backend/app/services/documents/fonts/__init__.py`
- Modify: `backend/app/services/documents/pdf_base.py:155`

- [ ] **Step 1: Move the font file**

```bash
mkdir -p backend/app/data/fonts
git mv backend/app/services/documents/fonts/DancingScript-Regular.ttf backend/app/data/fonts/DancingScript-Regular.ttf
```

- [ ] **Step 2: Repoint `FONTS_DIR` to the new location**

Replace `backend/app/services/documents/fonts/__init__.py` with:

```python
from pathlib import Path

# Cursive font now lives under app/data/fonts (used by both the
# deprecated fpdf2 path and the new font-registration helper for
# LibreOffice).
FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fonts"
```

- [ ] **Step 3: Verify the existing import in `pdf_base.py` still resolves**

Read `backend/app/services/documents/pdf_base.py` line 155 (`_CURSIVE_FONT_PATH = str(FONTS_DIR / "DancingScript-Regular.ttf")`). No code change needed — just confirm the file exists at `FONTS_DIR / "DancingScript-Regular.ttf"`:

```bash
python -c "from backend.app.services.documents.fonts import FONTS_DIR; print((FONTS_DIR / 'DancingScript-Regular.ttf').exists())"
```

Expected output: `True`

- [ ] **Step 4: Run the existing fpdf2 tests to confirm the move did not break anything**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_batch_record.py -v
```

Expected: all tests pass (the deprecated fpdf2 path still resolves the cursive font from its new location).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/fonts backend/app/services/documents/fonts/__init__.py
git commit -m "refactor(fonts): move DancingScript to app/data/fonts"
```

---

### Task 2: Add `ensure_cursive_font_registered` helper

**Files:**
- Create: `backend/app/services/documents/font_setup.py`
- Test: `backend/tests/unit/test_font_setup.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_font_setup.py`:

```python
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.documents.font_setup import ensure_cursive_font_registered


def test_copies_font_into_user_fonts_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    fake_run = patch("subprocess.run").start()
    try:
        ensure_cursive_font_registered()
    finally:
        patch.stopall()

    dest = tmp_path / ".fonts" / "DancingScript-Regular.ttf"
    assert dest.exists(), "font should be copied into ~/.fonts"
    fake_run.assert_called_once()
    args = fake_run.call_args.args[0]
    assert args[0] == "fc-cache"


def test_idempotent_when_dest_already_current(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    dest_dir = tmp_path / ".fonts"
    dest_dir.mkdir()
    # Pre-populate dest with a copy that has a NEWER mtime than the source
    from app.services.documents.fonts import FONTS_DIR
    src = FONTS_DIR / "DancingScript-Regular.ttf"
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    # Bump dest mtime to "now + 1 day" so it's strictly newer than src
    future = src.stat().st_mtime + 86400
    import os
    os.utime(dest, (future, future))

    fake_run = patch("subprocess.run").start()
    try:
        ensure_cursive_font_registered()
    finally:
        patch.stopall()

    fake_run.assert_not_called()


def test_swallow_fc_cache_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HOME", str(tmp_path))
    fake_run = patch(
        "subprocess.run",
        side_effect=subprocess.SubprocessError("simulated"),
    ).start()
    try:
        # Must not raise
        ensure_cursive_font_registered()
    finally:
        patch.stopall()

    assert any("fc-cache" in r.getMessage().lower() for r in caplog.records)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_font_setup.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.documents.font_setup'` — fails because the module does not exist yet.

- [ ] **Step 3: Implement the helper**

Create `backend/app/services/documents/font_setup.py`:

```python
"""Register the bundled DancingScript font with the OS so LibreOffice
can render the cursive initials fallback when converting docx → PDF.

Idempotent. Safe to call from FastAPI startup. Failures are logged at
WARN level — the document still renders, just in the document's body
font instead of cursive.
"""

import logging
import shutil
import subprocess
from pathlib import Path

from app.services.documents.fonts import FONTS_DIR

logger = logging.getLogger(__name__)

_FONT_FILENAME = "DancingScript-Regular.ttf"


def ensure_cursive_font_registered() -> None:
    """Copy DancingScript into ~/.fonts and refresh fontconfig cache."""
    src = FONTS_DIR / _FONT_FILENAME
    if not src.exists():
        logger.warning("Cursive font missing from %s; skipping", src)
        return

    dest_dir = Path.home() / ".fonts"
    dest = dest_dir / _FONT_FILENAME

    needs_install = (
        not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime
    )
    if not needs_install:
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)

    try:
        subprocess.run(
            ["fc-cache", "-f", str(dest_dir)],
            check=True,
            timeout=10,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        logger.warning(
            "fc-cache failed; cursive fallback may not render: %s", e
        )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && source .venv/bin/activate && pytest tests/unit/test_font_setup.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/documents/font_setup.py backend/tests/unit/test_font_setup.py
git commit -m "feat(fonts): register DancingScript with fontconfig at startup"
```

---

### Task 3: Wire `ensure_cursive_font_registered` into FastAPI startup

**Files:**
- Modify: `backend/app/main.py:267-310`

- [ ] **Step 1: Add the call inside `lifespan`**

In `backend/app/main.py`, locate `seed_system_templates()` inside `lifespan` and add the font registration call directly above it:

```python
    # Seed system document templates into file storage
    from app.services.protocols.template_seeder import seed_system_templates

    seed_system_templates()

    # Make the cursive fallback font visible to LibreOffice for PDF
    # rendering (F-0080)
    from app.services.documents.font_setup import \
        ensure_cursive_font_registered

    ensure_cursive_font_registered()
```

- [ ] **Step 2: Boot the dev server and verify the log line on startup**

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8010 --log-level info &
sleep 3
curl -sf http://localhost:8010/health
kill %1 2>/dev/null
```

Expected: `/health` returns 200; no exception in the startup logs from the font helper. If `fc-cache` is not installed locally, you should see a single WARN line — that's fine.

- [ ] **Step 3: Confirm the font is now registered**

```bash
fc-list | grep -i "Dancing Script" || echo "MISSING"
```

Expected: at least one line containing `Dancing Script` (not `MISSING`). If `fc-list` is not installed, skip this verification — the unit tests cover the logic.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(startup): register cursive font on app boot"
```

---

### Task 4: Add `signature_initials_path` and `signature_full_path` columns to `User`

**Files:**
- Modify: `backend/app/models/iam.py:143-186`
- Create: `backend/alembic/versions/<timestamp>_add_user_signature_paths.py`

- [ ] **Step 1: Add the two columns to the `User` model**

In `backend/app/models/iam.py`, just below the existing `avatar_path` line (line 155):

```python
    avatar_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    signature_initials_path: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    signature_full_path: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
```

- [ ] **Step 2: Generate the migration**

```bash
cd backend && source .venv/bin/activate && \
  alembic revision --autogenerate -m "add user signature paths"
```

- [ ] **Step 3: Review the generated migration**

Open the new file under `backend/alembic/versions/`. Confirm the `upgrade()` function adds two `op.add_column` calls and `downgrade()` drops them. Strip any unrelated noise (Alembic sometimes picks up index reorderings — leave only the two add_column / drop_column pairs).

Example shape:

```python
def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("signature_initials_path", sa.String(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("signature_full_path", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "signature_full_path")
    op.drop_column("users", "signature_initials_path")
```

- [ ] **Step 4: Apply the migration**

```bash
cd backend && source .venv/bin/activate && alembic upgrade head
```

Expected: no errors. `psql -U postgres -d batchrite -c "\d users"` should show both new columns.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/iam.py backend/alembic/versions
git commit -m "feat(model): add user signature paths"
```

---

### Task 5: Add signature URLs to `UserResponse`

**Files:**
- Modify: `backend/app/schemas/auth.py:56-69`
- Modify: `backend/app/api/endpoints/auth.py:65-82`

- [ ] **Step 1: Add the new URL fields to the schema**

In `backend/app/schemas/auth.py`, update `UserResponse`:

```python
class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    job_title: Optional[str] = None
    avatar_url: Optional[str] = None
    signature_initials_url: Optional[str] = None
    signature_full_url: Optional[str] = None
    preferences: dict[str, Any] = {}
    is_active: bool
    email_verified: bool
    tos_accepted_at: Optional[datetime] = None
    tos_version: Optional[str] = None
    tos_current: bool

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Update `_user_response` to populate them**

In `backend/app/api/endpoints/auth.py`, replace `_user_response`:

```python
def _user_response(user: User) -> UserResponse:
    """Build UserResponse with computed avatar/signature URLs and tos_current."""
    avatar_url = None
    if user.avatar_path:
        avatar_url = f"/auth/avatars/{user.id}"
    signature_initials_url = None
    if user.signature_initials_path:
        signature_initials_url = f"/auth/signatures/{user.id}/initials"
    signature_full_url = None
    if user.signature_full_path:
        signature_full_url = f"/auth/signatures/{user.id}/full"
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        job_title=user.job_title,
        avatar_url=avatar_url,
        signature_initials_url=signature_initials_url,
        signature_full_url=signature_full_url,
        preferences=user.preferences or {},
        is_active=user.is_active,
        email_verified=user.email_verified,
        tos_accepted_at=user.tos_accepted_at,
        tos_version=user.tos_version,
        tos_current=compute_tos_current(user),
    )
```

- [ ] **Step 3: Verify the existing auth tests still pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/integration/test_auth.py -v
```

Expected: all auth tests still pass (new optional fields default to `None`).

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/auth.py backend/app/api/endpoints/auth.py
git commit -m "feat(auth): expose signature URLs on UserResponse"
```

---

### Task 6: Add the signature upload/delete/get endpoints (with audit log)

**Files:**
- Modify: `backend/app/api/endpoints/auth.py` (add module-level constants + three routes near the existing avatar routes around line 625-770)
- Test: `backend/tests/integration/test_user_signatures.py`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_user_signatures.py`:

```python
"""Integration tests for /auth/me/signature/{kind} endpoints."""

import io
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

from app.models.iam import User
from app.services.core.file_storage import FileStorageService

# Reuse the existing async test fixtures (db, client, auth_user_token)
# from conftest.py.


def _png_bytes(size_px: int = 200) -> bytes:
    """Build a tiny in-memory PNG (transparent background)."""
    img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["initials", "full"])
async def test_upload_signature(client: AsyncClient, auth_user_token, db, kind):
    headers = {"Authorization": f"Bearer {auth_user_token['token']}"}
    files = {"file": (f"sig.png", _png_bytes(), "image/png")}
    res = await client.post(
        f"/auth/me/signature/{kind}", headers=headers, files=files
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body[f"signature_{kind}_url"] == (
        f"/auth/signatures/{auth_user_token['user_id']}/{kind}"
    )

    # Database column populated
    user = (
        await db.execute(
            select(User).where(User.id == auth_user_token["user_id"])
        )
    ).scalar_one()
    col = "signature_initials_path" if kind == "initials" else "signature_full_path"
    assert getattr(user, col) is not None

    # File on disk
    storage = FileStorageService()
    assert storage.resolve_path(getattr(user, col)).exists()


@pytest.mark.asyncio
async def test_upload_rejects_non_png(client: AsyncClient, auth_user_token):
    headers = {"Authorization": f"Bearer {auth_user_token['token']}"}
    files = {"file": ("sig.jpg", b"not really a jpeg", "image/jpeg")}
    res = await client.post(
        "/auth/me/signature/initials", headers=headers, files=files
    )
    assert res.status_code == 400
    assert "PNG" in res.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_too_large(client: AsyncClient, auth_user_token):
    headers = {"Authorization": f"Bearer {auth_user_token['token']}"}
    big = b"\x89PNG\r\n\x1a\n" + b"A" * (600 * 1024)
    files = {"file": ("sig.png", big, "image/png")}
    res = await client.post(
        "/auth/me/signature/initials", headers=headers, files=files
    )
    assert res.status_code == 400
    assert "500" in res.json()["detail"] or "size" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_rejects_unknown_kind(client: AsyncClient, auth_user_token):
    headers = {"Authorization": f"Bearer {auth_user_token['token']}"}
    files = {"file": ("sig.png", _png_bytes(), "image/png")}
    res = await client.post(
        "/auth/me/signature/wrist", headers=headers, files=files
    )
    assert res.status_code == 422 or res.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["initials", "full"])
async def test_delete_signature(client: AsyncClient, auth_user_token, db, kind):
    headers = {"Authorization": f"Bearer {auth_user_token['token']}"}
    files = {"file": ("sig.png", _png_bytes(), "image/png")}
    await client.post(f"/auth/me/signature/{kind}", headers=headers, files=files)

    res = await client.delete(f"/auth/me/signature/{kind}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body[f"signature_{kind}_url"] is None

    user = (
        await db.execute(
            select(User).where(User.id == auth_user_token["user_id"])
        )
    ).scalar_one()
    col = "signature_initials_path" if kind == "initials" else "signature_full_path"
    assert getattr(user, col) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["initials", "full"])
async def test_get_signature_serves_png(client: AsyncClient, auth_user_token, kind):
    headers = {"Authorization": f"Bearer {auth_user_token['token']}"}
    png = _png_bytes()
    await client.post(
        f"/auth/me/signature/{kind}",
        headers=headers,
        files={"file": ("sig.png", png, "image/png")},
    )
    res = await client.get(
        f"/auth/signatures/{auth_user_token['user_id']}/{kind}", headers=headers
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_get_signature_404_when_not_set(client: AsyncClient, auth_user_token):
    headers = {"Authorization": f"Bearer {auth_user_token['token']}"}
    res = await client.get(
        f"/auth/signatures/{auth_user_token['user_id']}/initials", headers=headers
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_audit_logged_on_create_replace_delete(
    client: AsyncClient, auth_user_token, db
):
    from app.models.audit import AuditLog

    headers = {"Authorization": f"Bearer {auth_user_token['token']}"}
    files = {"file": ("sig.png", _png_bytes(), "image/png")}

    await client.post("/auth/me/signature/initials", headers=headers, files=files)
    await client.post("/auth/me/signature/initials", headers=headers, files=files)
    await client.delete("/auth/me/signature/initials", headers=headers)

    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "user_signature")
            .where(AuditLog.entity_id == auth_user_token["user_id"])
            .order_by(AuditLog.created_at)
        )
    ).scalars().all()

    actions = [r.action for r in rows]
    assert actions == [
        "signature_created",
        "signature_replaced",
        "signature_deleted",
    ]
    for r in rows:
        assert r.details.get("kind") == "initials"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && source .venv/bin/activate && \
  pytest tests/integration/test_user_signatures.py -v
```

Expected: all tests fail (404s) because the endpoints don't exist yet.

- [ ] **Step 3: Add module-level constants**

In `backend/app/api/endpoints/auth.py`, just below the existing avatar constants (line 58–59), add:

```python
ALLOWED_SIGNATURE_TYPES = {"image/png"}
MAX_SIGNATURE_SIZE = 500 * 1024  # 500 KB
SIGNATURE_KINDS = {"initials", "full"}


def _signature_path_attr(kind: str) -> str:
    return "signature_initials_path" if kind == "initials" else "signature_full_path"
```

- [ ] **Step 4: Add the upload endpoint**

Below the existing `delete_avatar` route (around line 690), add:

```python
@router.post("/me/signature/{kind}", response_model=UserResponse)
async def upload_signature(
    kind: str,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if kind not in SIGNATURE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown signature kind: {kind}",
        )
    if not user.selected_org_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    if file.content_type not in ALLOWED_SIGNATURE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type {file.content_type} not allowed. "
                "Use PNG with transparent background."
            ),
        )

    content = await file.read()
    if len(content) > MAX_SIGNATURE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="Signature must be under 500 KB.",
        )

    storage = FileStorageService()
    org_id = user.selected_org_id
    attr = _signature_path_attr(kind)
    relative_path = str(
        Path(str(org_id)) / "signatures" / f"{user.id}-{kind}.png"
    )

    previous = getattr(user, attr)
    full_path = storage.storage_root / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(content)

    setattr(user, attr, relative_path)
    await db.commit()
    await db.refresh(user)

    await log_audit(
        db,
        user_id=user.id,
        org_id=org_id,
        entity_type="user_signature",
        entity_id=user.id,
        action=("signature_replaced" if previous else "signature_created"),
        details={"kind": kind},
    )
    await db.commit()

    return _user_response(user)


@router.delete("/me/signature/{kind}", response_model=UserResponse)
async def delete_signature(
    kind: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if kind not in SIGNATURE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown signature kind: {kind}",
        )
    attr = _signature_path_attr(kind)
    previous = getattr(user, attr)
    if previous:
        try:
            FileStorageService().delete_file(previous)
        except (OSError, ValueError):
            pass
        setattr(user, attr, None)
        await db.commit()
        await db.refresh(user)

        await log_audit(
            db,
            user_id=user.id,
            org_id=user.selected_org_id,
            entity_type="user_signature",
            entity_id=user.id,
            action="signature_deleted",
            details={"kind": kind},
        )
        await db.commit()
    return _user_response(user)


@router.get("/signatures/{user_id}/{kind}")
async def get_signature(
    user_id: str,
    kind: str,
    request: Request,
    current_user: User = Depends(_get_user_for_file),
    db: AsyncSession = Depends(get_db),
):
    if kind not in SIGNATURE_KINDS:
        raise HTTPException(status_code=404, detail="Signature not found")
    if not current_user.selected_org_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Signature not found")

    rel = getattr(target, _signature_path_attr(kind))
    if not rel:
        raise HTTPException(status_code=404, detail="Signature not found")

    same_org = (
        await db.execute(
            select(OrganizationMember.id).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == current_user.selected_org_id,
            )
        )
    ).scalar_one_or_none()
    if same_org is None:
        raise HTTPException(status_code=404, detail="Signature not found")

    storage = FileStorageService()
    try:
        full_path = storage.resolve_path(rel)
    except ValueError:
        raise HTTPException(status_code=404, detail="Signature not found")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Signature not found")

    return FileResponse(full_path, media_type="image/png")
```

- [ ] **Step 5: Verify the `log_audit` import is correct**

Check the `from app.services.core.audit import log_audit` line near the top of `auth.py` exists. If `log_audit` is not yet imported, add it. Then read its signature in `backend/app/services/core/audit.py` and adjust the call args above to match (the example call args mirror existing avatar audit logging, but the actual function signature is the source of truth).

```bash
grep -n "def log_audit" backend/app/services/core/audit.py
```

If the signature differs from the call sites in this task, update the calls to match — keep `entity_type="user_signature"`, `entity_id=user.id`, `action=...`, and pass `kind` via `details={"kind": kind}`.

- [ ] **Step 6: Run the integration tests**

```bash
cd backend && source .venv/bin/activate && \
  pytest tests/integration/test_user_signatures.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/endpoints/auth.py backend/tests/integration/test_user_signatures.py
git commit -m "feat(auth): add signature upload/delete/get endpoints"
```

---

## Phase B — Render integration

### Task 7: Add `_resolve_initials` and bulk-load signature paths

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py`
- Test: `backend/tests/unit/test_template_engine_signatures.py`

- [ ] **Step 1: Write the failing unit test**

Create `backend/tests/unit/test_template_engine_signatures.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docxtpl import DocxTemplate, InlineImage, RichText

from app.services.protocols.template_engine import _resolve_initials


def test_returns_inline_image_when_signature_path_exists(tmp_path):
    sig = tmp_path / "sig.png"
    sig.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    docx = MagicMock(spec=DocxTemplate)

    result = _resolve_initials(
        user_id="u1",
        name="John Smith",
        user_signatures={"u1": str(sig)},
        docx=docx,
    )
    assert isinstance(result, InlineImage)


def test_falls_back_to_cursive_richtext_when_no_signature():
    docx = MagicMock(spec=DocxTemplate)

    result = _resolve_initials(
        user_id="u1",
        name="John Smith",
        user_signatures={},
        docx=docx,
    )
    assert isinstance(result, RichText)
    # docxtpl RichText stores its XML; the font name should be embedded
    assert "Dancing Script" in result.xml or "DancingScript" in result.xml


def test_falls_back_when_path_is_missing_from_disk(tmp_path):
    docx = MagicMock(spec=DocxTemplate)
    missing_path = tmp_path / "does-not-exist.png"

    result = _resolve_initials(
        user_id="u1",
        name="John Smith",
        user_signatures={"u1": str(missing_path)},
        docx=docx,
    )
    assert isinstance(result, RichText)


def test_falls_back_when_user_unknown():
    docx = MagicMock(spec=DocxTemplate)

    result = _resolve_initials(
        user_id="not-in-map",
        name="John Smith",
        user_signatures={"someone-else": "/path/that/exists"},
        docx=docx,
    )
    assert isinstance(result, RichText)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && source .venv/bin/activate && \
  pytest tests/unit/test_template_engine_signatures.py -v
```

Expected: ImportError — `_resolve_initials` does not exist yet.

- [ ] **Step 3: Add the helper to `template_engine.py`**

In `backend/app/services/protocols/template_engine.py`, just above `def build_context` (around line 72), add:

```python
def _resolve_initials(
    *,
    user_id: str,
    name: str,
    user_signatures: dict[str, str],
    docx: DocxTemplate,
):
    """Return an InlineImage of the user's drawn initials if registered,
    else a cursive RichText with the auto-generated text initials."""
    path = user_signatures.get(user_id)
    if path and Path(path).exists():
        return InlineImage(docx, path, width=Mm(20))
    return RichText(_get_initials(name), font="Dancing Script")
```

(`Path` is already imported at the top of the file. So is `RichText`. `Mm` is already imported. `InlineImage` is already imported.)

- [ ] **Step 4: Verify the unit tests pass**

```bash
cd backend && source .venv/bin/activate && \
  pytest tests/unit/test_template_engine_signatures.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/protocols/template_engine.py backend/tests/unit/test_template_engine_signatures.py
git commit -m "feat(render): add _resolve_initials with InlineImage / cursive fallback"
```

---

### Task 8: Plumb `user_signatures` map into `build_context`

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py:72-95` (signature) and `:186-194` (initials assignment)
- Modify: `backend/app/api/endpoints/protocol_pdfs.py` (one call site) — pass through if needed

- [ ] **Step 1: Add a `user_signatures` parameter to `build_context`**

In `backend/app/services/protocols/template_engine.py`, update the `build_context` signature:

```python
def build_context(
    *,
    protocol_name: str = "",
    protocol_description: str = "",
    version_number: int | None = None,
    created_at: str = "",
    run_name: str | None = None,
    run_status: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    project_name: str = "",
    organization_name: str = "",
    roles_with_steps: list[dict[str, Any]] | None = None,
    flat_steps: list[dict[str, Any]] | None = None,
    is_role_based: bool = True,
    execution_data: dict[str, Any] | None = None,
    user_map: dict[str, str] | None = None,
    user_signatures: dict[str, str] | None = None,
    started_by_id: str | None = None,
    notes: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    storage: FileStorageService | None = None,
) -> dict[str, Any]:
```

Just under the existing `umap = user_map or {}` line, add:

```python
    sigmap = user_signatures or {}
```

- [ ] **Step 2: Replace the text-only initials assignment with a deferred placeholder**

In `build_context`, find (around line 186–194):

```python
        completer_name = umap.get(completed_by_uid, "")
        if not completer_name and started_by_id:
            completer_name = umap.get(started_by_id, "")
        initials = (
            _get_initials(completer_name)
            if completer_name and sd.get("status") == "completed"
            else ""
        )
```

Replace with:

```python
        completer_uid = completed_by_uid or (
            started_by_id if not completed_by_uid else ""
        )
        completer_name = umap.get(completer_uid, "")
        # Store both the resolved name and the user_id so render_to_docx
        # can build the InlineImage / RichText against the open
        # DocxTemplate (mirrors the figure-handling pattern).
        if completer_name and sd.get("status") == "completed":
            initials_user_id = completer_uid
            initials_text_fallback = _get_initials(completer_name)
        else:
            initials_user_id = ""
            initials_text_fallback = ""
        initials = initials_text_fallback  # plain-text placeholder for now
```

Then in the `step_ctx` dict (around line 251–267), add two private fields alongside `initials`:

```python
        step_ctx = {
            "_step_id": step_id,
            ...
            "initials": initials,
            "_initials_user_id": initials_user_id,
            "_initials_name": completer_name,
            ...
        }
```

- [ ] **Step 3: Wire the same `user_signatures` parameter into role-iterating steps if applicable**

If `role_contexts` also produces steps with `initials` (audit by reading lines 270–end of `build_context`), apply the same `_initials_user_id` / `_initials_name` plumbing to those `step_ctx` dicts. If role-iterating code reuses `step_ctx_by_id` (line 274) for batch-record-style steps, the placeholder fields will already be present — no extra work needed. Confirm by reading the code around line 270–360.

- [ ] **Step 4: Pass `user_signatures` from `protocol_pdfs.py` callers**

In `backend/app/api/endpoints/protocol_pdfs.py`, anywhere `build_context` is called, build the signature map ahead of the call. Search for `build_context(` and for each call:

```python
# Just before build_context(...)
relevant_user_ids = [u for u in (umap.keys() if 'umap' in locals() else []) if u]
sig_rows = (
    await db.execute(
        select(User.id, User.signature_initials_path)
        .where(User.id.in_(relevant_user_ids))
        .where(User.signature_initials_path.is_not(None))
    )
).all() if relevant_user_ids else []
storage = FileStorageService()
user_signatures = {
    str(uid): str(storage.resolve_path(path))
    for uid, path in sig_rows
    if path
}

# then pass into the call
context = build_context(..., user_signatures=user_signatures, ...)
```

If `protocol_pdfs.py` is the only call site that includes user-attributed initials, this is a single edit. Read the file first and pick the exact insertion point.

- [ ] **Step 5: Re-run existing render tests to confirm they still pass**

```bash
cd backend && source .venv/bin/activate && pytest tests/ -k "template_engine or protocol_pdf" -v
```

Expected: all green. Initials still rendered as plain text in this step (we haven't touched `render_to_docx` yet) — that lands in the next task.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/protocols/template_engine.py backend/app/api/endpoints/protocol_pdfs.py
git commit -m "refactor(render): plumb user_signatures map through build_context"
```

---

### Task 9: Swap initials in `render_to_docx` after the template opens

**Files:**
- Modify: `backend/app/services/protocols/template_engine.py:469-489` (`render_to_docx`)
- Test: `backend/tests/unit/test_template_engine_signatures.py` (extend)

- [ ] **Step 1: Extend the unit tests**

Append to `backend/tests/unit/test_template_engine_signatures.py`:

```python
def test_render_to_docx_swaps_initials_to_inline_image(tmp_path):
    """Smoke: when a step has _initials_user_id and that user has a
    signature path on the user_signatures map (passed via render_to_docx),
    the rendered docx must embed the image rather than the text fallback."""
    from app.services.protocols.template_engine import render_to_docx

    sig = tmp_path / "sig.png"
    # Minimal valid PNG (1×1 transparent pixel)
    sig.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
        b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9c"
        b"c\xfa\xcf\x00\x00\x00\x02\x00\x01\xe2!\xbc\x33\x00\x00\x00\x00"
        b"IEND\xaeB`\x82"
    )

    template_path = (
        Path(__file__).resolve().parent.parent.parent
        / "app/services/documents/templates/batch_record_default.docx"
    )

    context = {
        "protocol_name": "Test",
        "steps": [
            {
                "_step_id": "s1",
                "name": "Step 1",
                "description": "Do thing",
                "initials": "J.S.",
                "_initials_user_id": "u1",
                "_initials_name": "John Smith",
                "value_display": "",
                "notes_display": "",
            }
        ],
        "_user_signatures": {"u1": str(sig)},
        # Other top-level fields the template references can be empty:
        "roles": [],
        "notes": [],
        "figures": [],
        "non_image_attachments": [],
    }

    docx_bytes = render_to_docx(template_path, context)
    # docx is a zip; embedded images appear under word/media/
    import zipfile
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert media, "expected at least one embedded media file"
```

(Add `import io` at the top of the file if not present.)

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && source .venv/bin/activate && \
  pytest tests/unit/test_template_engine_signatures.py::test_render_to_docx_swaps_initials_to_inline_image -v
```

Expected: assertion fails (`expected at least one embedded media file`) because `render_to_docx` does not yet swap initials.

- [ ] **Step 3: Update `render_to_docx` to swap initials**

In `backend/app/services/protocols/template_engine.py`, replace the existing `render_to_docx` function with:

```python
def render_to_docx(
    template_path: str | Path,
    context: dict[str, Any],
) -> bytes:
    """Render a .docx template with context, return .docx bytes."""
    doc = DocxTemplate(str(template_path))

    # Convert figure file paths to InlineImage objects
    for fig in context.get("figures", []):
        fpath_str = fig.pop("_file_path", None)
        if fpath_str:
            fpath = Path(fpath_str)
            if fpath.exists():
                fig["image"] = InlineImage(doc, str(fpath), width=Mm(150))
            else:
                fig["image"] = f"[Image not found: {fpath.name}]"

    # F-0080 — swap step.initials to an InlineImage of the user's drawn
    # signature, or a cursive RichText fallback. Mirrors the figure
    # handling above: build_context puts placeholders, render_to_docx
    # finalizes them against the open DocxTemplate.
    user_signatures = context.pop("_user_signatures", {}) or {}

    def _swap(steps_list):
        for step in steps_list or []:
            uid = step.get("_initials_user_id")
            name = step.get("_initials_name", "")
            if not uid:
                continue
            step["initials"] = _resolve_initials(
                user_id=uid,
                name=name,
                user_signatures=user_signatures,
                docx=doc,
            )

    _swap(context.get("steps"))
    for role in context.get("roles", []) or []:
        _swap(role.get("steps"))
        _swap(role.get("br_steps"))

    doc.render(context)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
```

(Add `_resolve_initials` to the imports at the top of `render_to_docx` only if it lives in another module — in this plan it's defined in the same file, so no import change needed.)

- [ ] **Step 4: Push `_user_signatures` into `context` from `build_context`**

In `build_context`, near the bottom (just before `return` of the assembled context dict), add the line:

```python
    context["_user_signatures"] = sigmap
```

(Find the existing `return` statement of `build_context` and place the assignment one line above it. If the function builds the context dict in pieces, drop the line into whichever dict is returned.)

- [ ] **Step 5: Run the unit + render tests**

```bash
cd backend && source .venv/bin/activate && \
  pytest tests/unit/test_template_engine_signatures.py -v && \
  pytest tests/ -k "template_engine or protocol_pdf" -v
```

Expected: all green, including the new `test_render_to_docx_swaps_initials_to_inline_image` smoke test.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/protocols/template_engine.py backend/tests/unit/test_template_engine_signatures.py
git commit -m "feat(render): swap step.initials to InlineImage at docx render"
```

---

## Phase C — Frontend

### Task 10: Add `signature_pad` dependency

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install the library**

```bash
cd frontend && npm install signature_pad
```

- [ ] **Step 2: Confirm the version is pinned**

Open `frontend/package.json` and verify a new `"signature_pad"` entry under `dependencies` — should be roughly `^5.x` or `^4.x` (whatever npm picks up). Pin to a single major version:

```json
    "signature_pad": "^5.0.4"
```

(Use whatever version `npm install` picked up — don't downgrade arbitrarily.)

- [ ] **Step 3: Run `npm run check` to confirm types resolve**

```bash
cd frontend && npm run check
```

Expected: 0 errors. (`signature_pad` ships its own types.)

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add signature_pad dep"
```

---

### Task 11: Build `<SignaturePad />` UI primitive

**Files:**
- Create: `frontend/src/lib/components/ui/signature-pad/signature-pad.svelte`
- Create: `frontend/src/lib/components/ui/signature-pad/index.ts`

- [ ] **Step 1: Create the index re-export**

Create `frontend/src/lib/components/ui/signature-pad/index.ts`:

```typescript
import Root from './signature-pad.svelte';

export { Root as SignaturePad };
export type { SignaturePadHandle } from './signature-pad.svelte';
```

- [ ] **Step 2: Implement the component**

Create `frontend/src/lib/components/ui/signature-pad/signature-pad.svelte`:

```svelte
<script lang="ts" context="module">
    export interface SignaturePadHandle {
        clear(): void;
        toBlob(): Promise<Blob | null>;
        isEmpty(): boolean;
    }
</script>

<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import SignaturePad from 'signature_pad';
    import { cn } from '$lib/utils';

    interface Props {
        width?: number;
        height?: number;
        class?: string;
        ariaLabel?: string;
        onChange?: (isEmpty: boolean) => void;
    }

    let {
        width = 480,
        height = 160,
        class: className = '',
        ariaLabel = 'Signature pad',
        onChange,
    }: Props = $props();

    let canvas: HTMLCanvasElement | null = $state(null);
    let pad: SignaturePad | null = null;

    function resizeCanvas() {
        if (!canvas) return;
        const ratio = Math.max(window.devicePixelRatio || 1, 1);
        canvas.width = canvas.offsetWidth * ratio;
        canvas.height = canvas.offsetHeight * ratio;
        canvas.getContext('2d')?.scale(ratio, ratio);
        pad?.clear();
    }

    onMount(() => {
        if (!canvas) return;
        pad = new SignaturePad(canvas, {
            minWidth: 0.5,
            maxWidth: 2.5,
            throttle: 16,
            velocityFilterWeight: 0.7,
            backgroundColor: 'rgba(0,0,0,0)',
            penColor: '#0f172a',
        });
        pad.addEventListener('endStroke', () => onChange?.(pad?.isEmpty() ?? true));
        resizeCanvas();
        window.addEventListener('resize', resizeCanvas);
    });

    onDestroy(() => {
        window.removeEventListener('resize', resizeCanvas);
        pad?.off();
    });

    export function clear(): void {
        pad?.clear();
        onChange?.(true);
    }

    export function isEmpty(): boolean {
        return pad?.isEmpty() ?? true;
    }

    export async function toBlob(): Promise<Blob | null> {
        if (!canvas || !pad || pad.isEmpty()) return null;
        return await new Promise<Blob | null>((resolve) => {
            canvas!.toBlob((b) => resolve(b), 'image/png');
        });
    }
</script>

<div
    class={cn(
        'relative rounded-md border border-border bg-background overflow-hidden',
        className,
    )}
    style="width: {width}px; height: {height}px;"
>
    <canvas
        bind:this={canvas}
        class="block w-full h-full cursor-crosshair touch-none"
        aria-label={ariaLabel}
    ></canvas>
    <span
        class="pointer-events-none absolute inset-x-3 bottom-2 border-t border-dashed border-muted-foreground/40"
    ></span>
    <span
        class="pointer-events-none absolute left-3 bottom-3 text-[11px] text-muted-foreground/60"
    >
        Sign here
    </span>
</div>
```

- [ ] **Step 3: Smoke-build the frontend**

```bash
cd frontend && npm run check
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/ui/signature-pad
git commit -m "feat(ui): add SignaturePad primitive (signature_pad wrapper)"
```

---

### Task 12: Build the Signature settings card

**Files:**
- Create: `frontend/src/lib/components/settings/SignatureCard.svelte`

- [ ] **Step 1: Implement `SignatureCard.svelte`**

Create `frontend/src/lib/components/settings/SignatureCard.svelte`:

```svelte
<script lang="ts">
    import { api } from '$lib/api';
    import { toast } from '$lib/toast';
    import { getUser, refreshUser, getToken } from '$lib/auth.svelte';
    import { API_BASE } from '$lib/config';
    import { Button } from '$lib/components/ui/button';
    import {
        Card,
        CardContent,
        CardHeader,
        CardTitle,
        CardDescription,
    } from '$lib/components/ui/card';
    import { SignaturePad, type SignaturePadHandle } from '$lib/components/ui/signature-pad';
    import { fade } from 'svelte/transition';
    import { blockDuration } from '$lib/transitions';

    let initialsPad: SignaturePadHandle | null = $state(null);
    let fullPad: SignaturePadHandle | null = $state(null);
    let initialsEmpty = $state(true);
    let fullEmpty = $state(true);
    let initialsBusy = $state(false);
    let fullBusy = $state(false);

    const user = $derived(getUser());

    function urlFor(suffix: 'initials' | 'full'): string | null {
        const u = user;
        const key = suffix === 'initials' ? 'signature_initials_url' : 'signature_full_url';
        const path = u?.[key];
        return path ? `${API_BASE}${path}?token=${getToken()}` : null;
    }

    const initialsUrl = $derived(urlFor('initials'));
    const fullUrl = $derived(urlFor('full'));

    async function save(kind: 'initials' | 'full', pad: SignaturePadHandle | null) {
        if (!pad) return;
        if (pad.isEmpty()) {
            toast.error('Please draw a signature before saving.');
            return;
        }
        const blob = await pad.toBlob();
        if (!blob) {
            toast.error('Could not export signature.');
            return;
        }
        const setBusy = (b: boolean) => (kind === 'initials' ? (initialsBusy = b) : (fullBusy = b));
        setBusy(true);
        try {
            const file = new File([blob], `${kind}.png`, { type: 'image/png' });
            await api.uploadFile(`/auth/me/signature/${kind}`, file);
            await refreshUser();
            pad.clear();
            toast.success(kind === 'initials' ? 'Initials saved.' : 'Signature saved.');
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to save signature.');
        } finally {
            setBusy(false);
        }
    }

    async function remove(kind: 'initials' | 'full') {
        const setBusy = (b: boolean) => (kind === 'initials' ? (initialsBusy = b) : (fullBusy = b));
        setBusy(true);
        try {
            await api.delete(`/auth/me/signature/${kind}`);
            await refreshUser();
            toast.success('Removed.');
        } catch (e: unknown) {
            toast.error(e instanceof Error ? e.message : 'Failed to remove signature.');
        } finally {
            setBusy(false);
        }
    }
</script>

<Card>
    <CardHeader>
        <CardTitle>Signature</CardTitle>
        <CardDescription>
            Drawn signatures replace the auto-generated cursive initials in PDF exports.
            Full signatures will be used for document approvals.
        </CardDescription>
    </CardHeader>
    <CardContent>
        <div class="grid gap-6 md:grid-cols-2">
            <!-- Initials -->
            <div class="space-y-3">
                <div class="flex items-center justify-between">
                    <h3 class="text-sm font-medium">Initials</h3>
                    {#if initialsBusy}
                        <span in:fade={{ duration: blockDuration() }} class="text-xs text-muted-foreground">Saving...</span>
                    {/if}
                </div>
                {#if initialsUrl}
                    <div class="flex items-center gap-3">
                        <img src={initialsUrl} alt="Saved initials" class="h-16 w-32 object-contain border border-dashed border-border rounded-md bg-background" />
                        <Button size="sm" variant="ghost" class="text-destructive" disabled={initialsBusy} onclick={() => remove('initials')}>
                            Delete
                        </Button>
                    </div>
                {/if}
                <SignaturePad
                    bind:this={initialsPad}
                    width={280}
                    height={120}
                    ariaLabel="Initials signature pad"
                    onChange={(empty) => (initialsEmpty = empty)}
                />
                <div class="flex items-center gap-2">
                    <Button size="sm" disabled={initialsBusy || initialsEmpty} onclick={() => save('initials', initialsPad)}>
                        Save Initials
                    </Button>
                    <Button size="sm" variant="outline" disabled={initialsBusy} onclick={() => initialsPad?.clear()}>
                        Clear
                    </Button>
                </div>
            </div>

            <!-- Full Signature -->
            <div class="space-y-3">
                <div class="flex items-center justify-between">
                    <h3 class="text-sm font-medium">Full Signature</h3>
                    {#if fullBusy}
                        <span in:fade={{ duration: blockDuration() }} class="text-xs text-muted-foreground">Saving...</span>
                    {/if}
                </div>
                {#if fullUrl}
                    <div class="flex items-center gap-3">
                        <img src={fullUrl} alt="Saved signature" class="h-16 w-56 object-contain border border-dashed border-border rounded-md bg-background" />
                        <Button size="sm" variant="ghost" class="text-destructive" disabled={fullBusy} onclick={() => remove('full')}>
                            Delete
                        </Button>
                    </div>
                {/if}
                <SignaturePad
                    bind:this={fullPad}
                    width={480}
                    height={120}
                    ariaLabel="Full signature pad"
                    onChange={(empty) => (fullEmpty = empty)}
                />
                <div class="flex items-center gap-2">
                    <Button size="sm" disabled={fullBusy || fullEmpty} onclick={() => save('full', fullPad)}>
                        Save Signature
                    </Button>
                    <Button size="sm" variant="outline" disabled={fullBusy} onclick={() => fullPad?.clear()}>
                        Clear
                    </Button>
                </div>
            </div>
        </div>
    </CardContent>
</Card>
```

- [ ] **Step 2: Verify `auth.svelte.ts` exposes the new URL fields**

```bash
grep -n "signature_initials_url\|signature_full_url" frontend/src/lib/auth.svelte.ts
```

If the grep returns nothing, open `frontend/src/lib/auth.svelte.ts` and confirm the user object is typed as `Record<string, any>` (or similar) and that `refreshUser()` overwrites the local store with the API response. If the user type is strictly typed, add the two optional fields:

```typescript
signature_initials_url?: string | null;
signature_full_url?: string | null;
```

- [ ] **Step 3: Smoke-build**

```bash
cd frontend && npm run check
```

Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/settings/SignatureCard.svelte frontend/src/lib/auth.svelte.ts
git commit -m "feat(settings): add SignatureCard with initials + full pads"
```

---

### Task 13: Embed `<SignatureCard />` in the Profile tab

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte` (Profile tab section, around line 994–1068)

- [ ] **Step 1: Import the card**

Near the other settings imports (around line 20–23):

```typescript
import SignatureCard from '$lib/components/settings/SignatureCard.svelte';
```

- [ ] **Step 2: Embed the card under the Profile tab**

Just below the closing `</Card>` of the existing Profile card (the avatar/profile-info card around line 1068), add:

```svelte
<SignatureCard />
```

Place it before the Password card for visual grouping (the order becomes: Profile → Signature → Password → Preferences).

- [ ] **Step 3: Verify the dev server renders the card**

Start the dev server:

```bash
cd frontend && npm run dev -- --port 5183 &
sleep 4
```

Visit `http://localhost:5183/settings?tab=profile` in a browser. Expected: a new "Signature" card appears under the Profile card with two pads.

Stop the dev server when done:

```bash
kill %1 2>/dev/null
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "feat(settings): embed SignatureCard under Profile tab"
```

---

## Phase D — Verification

### Task 14: Manual browser smoke test via Chrome MCP

**Files:** none — verification only. Catches startup / wiring problems before delegating to qa-verify, while servers are still warm.

- [ ] **Step 1: Start dev servers on worktree ports**

```bash
# Backend (port 8010 — worktree convention)
cd backend && source .venv/bin/activate && \
  uvicorn app.main:app --reload --port 8010 &

# Frontend (port 5183 — worktree convention)
cd frontend && VITE_API_PORT=8010 npm run dev -- --port 5183 &

sleep 6
curl -sf http://localhost:8010/health  # confirm backend up
curl -sf http://localhost:5183/        # confirm frontend up
```

If either curl fails, tail the server stderr (the background processes log inline) and fix before continuing.

- [ ] **Step 2: Drive the feature through Chrome MCP**

Load the chrome MCP tools as needed (they are deferred — use ToolSearch with `select:mcp__claude-in-chrome__<name>`). Then perform this scripted walkthrough:

1. `tabs_context_mcp` — capture current tab state.
2. `tabs_create_mcp` to `http://localhost:5183/` — log in (use a seeded dev account, or register one if needed).
3. Navigate to `http://localhost:5183/settings?tab=profile` and `read_page`. Confirm the **Signature** card is rendered between Profile and Password, with two pads ("Initials", "Full Signature") side-by-side on desktop width.
4. **Initials happy path:** drive a pen stroke onto the initials canvas. Use `javascript_tool` to dispatch synthetic `pointerdown`/`pointermove`/`pointerup` events on the canvas (signature_pad listens for pointer events), tracing a short curve. Click **Save Initials** via `find` + a click. Confirm a success toast appears and the saved-image preview shows up after `read_page` reload.
5. **Persistence:** reload the page. Confirm the preview is still rendered and is served from `/auth/signatures/{user_id}/initials`. Use `read_network_requests` to confirm the GET returned 200 with `content-type: image/png`.
6. **Empty-pad guard:** click **Save Initials** without drawing. Confirm an error toast fires and no network call is made.
7. **Clear:** draw, then click **Clear**. Pad should empty, save button should disable.
8. **Delete:** click the destructive **Delete** button on the preview. Confirm DELETE request fires, preview disappears, and `refreshUser` re-renders the card with no preview.
9. **Full signature:** repeat steps 4–8 for the Full Signature pad.
10. **Backend rendering smoke:** with initials saved, open `http://localhost:5183/api/science/protocols/<any-protocol-with-completed-steps>/pdf/sop` (or whichever protocol PDF endpoint exists — check `backend/app/api/endpoints/protocol_pdfs.py` for the exact path). Use `read_network_requests` to confirm 200 + `application/pdf`. Save the PDF locally via `javascript_tool` (`fetch` → blob → download) and inspect with `pdftotext`/`pdfimages` to confirm the drawn signature image is embedded for the current user's completed steps. Then delete the saved signature, re-render the same PDF, and confirm the cursive (Dancing Script) text fallback now appears instead of an embedded image.
11. **Console / network sweep:** call `read_console_messages` with pattern `"error|warning"`. No new errors from this feature should appear. Call `read_network_requests` and confirm no 4xx/5xx other than the intentional empty-pad rejection.
12. Optional: `gif_creator` capture of the initials draw → save → preview flow, named `f-0080-initials-flow.gif`, for the ClickUp comment.

If anything in steps 1–11 fails, fix it now (while the servers are warm) before the qa-verify dispatch. Re-run the failing leg only.

- [ ] **Step 3: Leave dev servers running**

Do **not** kill the servers — Task 15 (qa-verify) needs them. Note the bash job IDs so they can be cleaned up after qa-verify finishes.

---

### Task 15: Browser verification via qa-verify agent

**Files:** none — verification only. Servers are already running from Task 14.

- [ ] **Step 1: Confirm servers are still up**

```bash
curl -sf http://localhost:8010/health && curl -sf http://localhost:5183/
```

If either is down, restart them as in Task 14, Step 1.

- [ ] **Step 2: Launch the qa-verify agent**

Use the `Agent` tool with `subagent_type: "qa-verify"` and the following prompt:

```
Verify F-0080 Custom Drawn Signatures feature.

App: http://localhost:5183 (frontend), backend at http://localhost:8010
Login: any seeded user works in dev. If unsure, register a new user via the
  Sign-Up flow on the homepage and then re-login.

Functional checks (all must pass):
- Settings → Profile shows a new "Signature" card with two pads (Initials,
  Full Signature)
- Drawing on the initials pad and clicking "Save Initials" persists the
  signature; reloading the page shows the stored image preview, not a
  cursive fallback
- "Clear" empties the pad without saving
- "Delete" on the saved preview removes the stored signature; preview
  reverts to absent (and the cursive fallback would only appear in PDFs)
- Same flow for the Full Signature pad
- Trying to save with an empty pad is rejected with a visible error toast
- Open `/science/protocols/<any-protocol>/pdf/sop` in a tab logged in as a
  user who has saved drawn initials — confirm the rendered PDF embeds the
  drawn image in the initials column for steps that user completed
- Open the same PDF as a user with NO saved signature — confirm the
  initials column shows cursive (Dancing Script) text initials

UI/UX audit (must catch and fix any of these):
- Signature card matches surrounding Profile cards: same Card / CardHeader /
  CardContent primitives, spacing, typography
- Two pads sit side-by-side on desktop (md:grid-cols-2) and stack cleanly on
  tablet / narrow viewports
- Pad canvas has clear border, baseline, and "Sign here" affordance;
  cursor-crosshair shows on hover
- Save / Clear / Delete buttons follow project conventions: shadcn-svelte
  primitives, correct variants, cursor-pointer, hover transitions
- Touch / stylus drawing works smoothly when the browser is resized to a
  tablet viewport (~768×1024). Resize and try drawing.
- Loading spinner / "Saving..." indicator shows during upload
- Toast notifications fire on success / failure
- No layout shifts, oversized inputs, overflow, or spacing inconsistencies
- Strokes are smooth (signature_pad's bezier interpolation) — not jagged

Fix any FAIL or POLISH issues you find before returning. Report back with
"ALL CHECKS PASS" plus a short note on anything you adjusted.
```

- [ ] **Step 3: Apply any qa-verify-suggested fixes**

If the agent returns FAIL or POLISH issues, apply the fixes (the agent does this itself per its skill definition) and re-run the verification once.

- [ ] **Step 4: Stop the dev servers**

```bash
kill %1 %2 2>/dev/null
```

- [ ] **Step 5: Commit any qa-verify polish**

```bash
git add -A
git diff --staged --quiet || git commit -m "polish(F-0080): qa-verify fixes"
```

(If there are no changes, the `git commit` is skipped by the `||`.)

---

## Self-Review

Spec coverage:

- ✅ Two `User` columns + migration → Task 4
- ✅ Three endpoints (POST/DELETE/GET) → Task 6
- ✅ Audit log → Task 6
- ✅ `_resolve_initials` helper → Task 7
- ✅ Bulk-load signature paths in `build_context` → Task 8
- ✅ Swap initials at `render_to_docx` → Task 9
- ✅ Cursive `RichText` fallback → Task 7 (RichText) + Task 1–3 (font registration so LibreOffice resolves it)
- ✅ Font moved to `backend/app/data/fonts/` → Task 1
- ✅ `ensure_cursive_font_registered` helper → Task 2
- ✅ Wired into FastAPI startup → Task 3
- ✅ `signature_pad` dependency → Task 10
- ✅ `<SignaturePad />` UI primitive → Task 11
- ✅ Signature card in Settings → Tasks 12–13
- ✅ Manual Chrome MCP smoke test → Task 14
- ✅ qa-verify browser verification → Task 15

No placeholders, types are consistent (`SignaturePadHandle` interface used in both `signature-pad.svelte` and `SignatureCard.svelte`; `_initials_user_id` / `_initials_name` used identically in `build_context` and `render_to_docx`).

---

## Execution Handoff

Plan complete and saved to:
`/home/wesuuu/Code/trellisbio/.claude/worktrees/F-0080-custom-signatures/docs/superpowers/plans/2026-04-29-f-0080-custom-drawn-signatures.md`

Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — execute tasks in this session using executing-plans, batch with checkpoints

Which approach?
