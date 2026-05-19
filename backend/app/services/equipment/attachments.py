from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.science import Equipment, EquipmentAttachment
from app.services.core.audit import log_audit
from app.services.core.file_storage import FileStorageService

ALLOWED_MIMES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_BYTES = 25 * 1024 * 1024


def _assert_writable(equipment: Equipment) -> None:
    if equipment.archived_at is not None:
        raise HTTPException(400, detail={"code": "EQUIPMENT_ARCHIVED"})


async def add_attachment(
    db: AsyncSession, equipment: Equipment, file: UploadFile, *, actor_id: UUID
) -> EquipmentAttachment:
    _assert_writable(equipment)
    storage = FileStorageService()
    stored = await storage.store_file(
        file,
        base_dir="equipment",
        org_id=equipment.organization_id,
        path_segments=[str(equipment.id)],
        allowed_types=ALLOWED_MIMES,
        max_size_bytes=MAX_BYTES,
    )
    att = EquipmentAttachment(
        equipment_id=equipment.id,
        file_path=stored.relative_path,
        original_filename=stored.original_filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        uploaded_by_id=actor_id,
    )
    db.add(att)
    await db.flush()
    await log_audit(
        db,
        actor_id=actor_id,
        action="CREATE",
        entity_type="equipment_attachment",
        entity_id=att.id,
        changes={
            "equipment_id": str(equipment.id),
            "filename": att.original_filename,
        },
    )
    await db.commit()
    await db.refresh(att)
    return att


async def remove_attachment(
    db: AsyncSession,
    attachment: EquipmentAttachment,
    *,
    actor_id: UUID,
) -> None:
    equipment = await db.get(Equipment, attachment.equipment_id)
    if equipment is not None:
        _assert_writable(equipment)
    storage = FileStorageService()
    try:
        storage.delete_file(attachment.file_path)
    except (
        Exception
    ):  # noqa: BLE001 — file may already be gone; row delete still proceeds
        pass
    await db.delete(attachment)
    await log_audit(
        db,
        actor_id=actor_id,
        action="DELETE",
        entity_type="equipment_attachment",
        entity_id=attachment.id,
        changes={},
    )
    await db.commit()
