import io

import pytest
from fastapi import UploadFile

from app.services.equipment.attachments import (
    ALLOWED_MIMES,
    MAX_BYTES,
    add_attachment,
    remove_attachment,
)


def _upload(name: str, content_type: str, content: bytes) -> UploadFile:
    return UploadFile(
        filename=name,
        file=io.BytesIO(content),
        headers={"content-type": content_type},
    )


@pytest.mark.asyncio
async def test_add_attachment_pdf(db_session, sample_equipment, test_user):
    f = _upload("manual.pdf", "application/pdf", b"%PDF-1.4 hello")
    att = await add_attachment(db_session, sample_equipment, f, actor_id=test_user.id)
    assert att.mime_type == "application/pdf"
    assert att.size_bytes > 0


@pytest.mark.asyncio
async def test_add_attachment_rejects_exe(db_session, sample_equipment, test_user):
    from fastapi import HTTPException

    f = _upload("bad.exe", "application/x-msdownload", b"MZ\x90\x00")
    with pytest.raises(HTTPException) as exc:
        await add_attachment(db_session, sample_equipment, f, actor_id=test_user.id)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_add_attachment_blocked_when_equipment_archived(
    db_session, sample_equipment, test_user
):
    from datetime import datetime, timezone

    from fastapi import HTTPException

    sample_equipment.archived_at = datetime.now(timezone.utc)
    await db_session.commit()
    f = _upload("manual.pdf", "application/pdf", b"%PDF-1.4")
    with pytest.raises(HTTPException) as exc:
        await add_attachment(db_session, sample_equipment, f, actor_id=test_user.id)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "EQUIPMENT_ARCHIVED"


@pytest.mark.asyncio
async def test_remove_attachment_blocked_when_equipment_archived(
    db_session, sample_equipment, sample_equipment_attachment, test_user
):
    from datetime import datetime, timezone

    from fastapi import HTTPException

    sample_equipment.archived_at = datetime.now(timezone.utc)
    await db_session.commit()
    with pytest.raises(HTTPException) as exc:
        await remove_attachment(
            db_session, sample_equipment_attachment, actor_id=test_user.id
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "EQUIPMENT_ARCHIVED"


def test_max_bytes_is_25mb():
    assert MAX_BYTES == 25 * 1024 * 1024


def test_allowed_mimes_includes_pdf_docx_images():
    for m in [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/png",
        "image/jpeg",
    ]:
        assert m in ALLOWED_MIMES
