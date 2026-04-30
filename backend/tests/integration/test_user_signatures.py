"""Integration tests for /auth/me/signature/{kind} endpoints."""

import io

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

from app.models.execution import AuditLog
from app.models.iam import User
from app.services.core.file_storage import FileStorageService


def _png_bytes(size_px: int = 200) -> bytes:
    """Build a tiny in-memory PNG (transparent background)."""
    img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["initials", "full"])
async def test_upload_signature(
    client: AsyncClient, auth_headers, db_session, test_user, kind
):
    files = {"file": ("sig.png", _png_bytes(), "image/png")}
    res = await client.post(
        f"/auth/me/signature/{kind}", headers=auth_headers, files=files
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body[f"signature_{kind}_url"] == (f"/auth/signatures/{test_user.id}/{kind}")

    # Database column populated
    user = (
        await db_session.execute(select(User).where(User.id == test_user.id))
    ).scalar_one()
    col = "signature_initials_path" if kind == "initials" else "signature_full_path"
    assert getattr(user, col) is not None

    # File on disk
    storage = FileStorageService()
    assert storage.resolve_path(getattr(user, col)).exists()


@pytest.mark.asyncio
async def test_upload_rejects_non_png(client: AsyncClient, auth_headers):
    files = {"file": ("sig.jpg", b"not really a jpeg", "image/jpeg")}
    res = await client.post(
        "/auth/me/signature/initials", headers=auth_headers, files=files
    )
    assert res.status_code == 400
    assert "PNG" in res.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejects_too_large(client: AsyncClient, auth_headers):
    big = b"\x89PNG\r\n\x1a\n" + b"A" * (600 * 1024)
    files = {"file": ("sig.png", big, "image/png")}
    res = await client.post(
        "/auth/me/signature/initials", headers=auth_headers, files=files
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "500" in detail or "size" in detail.lower()


@pytest.mark.asyncio
async def test_upload_rejects_unknown_kind(client: AsyncClient, auth_headers):
    files = {"file": ("sig.png", _png_bytes(), "image/png")}
    res = await client.post(
        "/auth/me/signature/wrist", headers=auth_headers, files=files
    )
    assert res.status_code in (400, 422)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["initials", "full"])
async def test_delete_signature(
    client: AsyncClient, auth_headers, db_session, test_user, kind
):
    files = {"file": ("sig.png", _png_bytes(), "image/png")}
    await client.post(f"/auth/me/signature/{kind}", headers=auth_headers, files=files)

    res = await client.delete(f"/auth/me/signature/{kind}", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body[f"signature_{kind}_url"] is None

    user = (
        await db_session.execute(select(User).where(User.id == test_user.id))
    ).scalar_one()
    col = "signature_initials_path" if kind == "initials" else "signature_full_path"
    assert getattr(user, col) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["initials", "full"])
async def test_get_signature_serves_png(
    client: AsyncClient, auth_headers, kind, test_user
):
    png = _png_bytes()
    await client.post(
        f"/auth/me/signature/{kind}",
        headers=auth_headers,
        files={"file": ("sig.png", png, "image/png")},
    )
    res = await client.get(
        f"/auth/signatures/{test_user.id}/{kind}", headers=auth_headers
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_get_signature_404_when_not_set(
    client: AsyncClient, auth_headers, test_user
):
    res = await client.get(
        f"/auth/signatures/{test_user.id}/initials", headers=auth_headers
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_audit_logged_on_create_replace_delete(
    client: AsyncClient, auth_headers, db_session, test_user
):
    files = {"file": ("sig.png", _png_bytes(), "image/png")}

    await client.post("/auth/me/signature/initials", headers=auth_headers, files=files)
    await client.post("/auth/me/signature/initials", headers=auth_headers, files=files)
    await client.delete("/auth/me/signature/initials", headers=auth_headers)

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.entity_type == "user_signature")
                .where(AuditLog.entity_id == test_user.id)
                .order_by(AuditLog.created_at)
            )
        )
        .scalars()
        .all()
    )

    actions = [r.action for r in rows]
    assert actions == [
        "signature_created",
        "signature_replaced",
        "signature_deleted",
    ]
    for r in rows:
        assert r.changes.get("kind") == "initials"
