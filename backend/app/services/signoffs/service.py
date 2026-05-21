"""Shared sign-off creation.

Single entry point used by both ``POST /protocols/{id}/signoffs`` and
``POST /runs/{id}/signoffs`` (Task 11 of F-0087 GLP Gap Fixes).

Responsibilities, in order:

1. Resolve org_id (from explicit kwarg or the signer).
2. Pre-generate a UUID so it can appear in the record-scoped signature path.
3. If ``action == "APPROVED"`` and the signer has ``signature_full_path``,
   copy the source file to ``{org_id}/signoffs/{signoff_id}{ext}`` under the
   FileStorageService storage root and store the relative path on the row
   (§11.70: pin the signature at sign time so future re-uploads can't
   retroactively change past records).
4. Run validators in order:
   ``validate_signoff_role_assignable`` → ``assert_qau_independent``
   → ``assert_attestation_and_image_present``.
5. INSERT the ``GlpSignoff`` row, ``flush``.
6. ``log_audit`` with ``action=f"signoff.{action.lower()}"`` and
   ``entity_type=f"{entity_type}_signoff"``.
7. ``commit`` and ``refresh``, then return.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import User
from app.models.signoffs import GlpSignoff
from app.services.core.audit import log_audit
from app.services.core.file_storage import FileStorageService
from app.services.signoffs.validation import (
    SignoffPayload,
    assert_attestation_and_image_present,
    assert_qau_independent,
    validate_signoff_role_assignable,
)


def _record_scoped_signature_path(org_id: UUID, signoff_id: UUID, source: str) -> str:
    """Return ``{org_id}/signoffs/{signoff_id}{ext}`` (relative)."""
    ext = Path(source).suffix or ".png"
    return f"{org_id}/signoffs/{signoff_id}{ext}"


async def create_signoff(
    db: AsyncSession,
    *,
    entity_type: Literal["protocol", "run"],
    entity_id: UUID,
    role: str,
    action: str,
    signer: User,
    attestation: Optional[str],
    signoff_request_id: Optional[UUID],
    organization_id: Optional[UUID] = None,
) -> GlpSignoff:
    """Run all validators, copy signature image, INSERT row, write AuditLog."""

    # 1. Resolve org_id (needed for the record-scoped signature path).
    if organization_id is None:
        organization_id = signer.selected_org_id  # type: ignore[assignment]
    if organization_id is None:
        raise ValueError(
            "create_signoff: organization_id could not be resolved from signer"
        )

    # 2. Pre-generate id so it can be embedded in the signature path.
    new_id = uuid4()

    # 3. Copy signature image (APPROVED + signer has a source path).
    signature_image_path: Optional[str] = None
    if action == "APPROVED" and signer.signature_full_path:
        relative = _record_scoped_signature_path(
            organization_id, new_id, signer.signature_full_path
        )
        storage = FileStorageService()
        # signature_full_path is stored relative to the storage root (see
        # auth.upload_signature); resolve it before copying so the source
        # isn't looked up against the process CWD.
        src = storage.resolve_path(signer.signature_full_path)
        dest = storage.storage_root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        signature_image_path = relative

    payload = SignoffPayload(
        role=role,
        action=action,
        attestation=attestation,
        signature_image_path=signature_image_path,
    )

    # 4. Validators (order matters: role assignability → QAU independence
    #    → presence of attestation+image).
    await validate_signoff_role_assignable(db, entity_type, entity_id, signer.id, role)
    await assert_qau_independent(db, entity_type, entity_id, signer.id, role)
    assert_attestation_and_image_present(payload)

    # 5. INSERT.
    signoff = GlpSignoff(
        id=new_id,
        protocol_id=entity_id if entity_type == "protocol" else None,
        run_id=entity_id if entity_type == "run" else None,
        role=role,
        action=action,
        signer_id=signer.id,
        attestation=attestation,
        signed_at=datetime.now(timezone.utc),
        signature_image_path=signature_image_path,
        signoff_request_id=signoff_request_id,
    )
    db.add(signoff)
    await db.flush()

    # 6. Audit log.
    await log_audit(
        db,
        actor_id=signer.id,
        action=f"signoff.{action.lower()}",
        entity_type=f"{entity_type}_signoff",
        entity_id=signoff.id,
        changes={"role": role, "entity_id": str(entity_id)},
    )

    # 7. Commit and refresh.
    await db.commit()
    await db.refresh(signoff)
    return signoff
