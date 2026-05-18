"""Cross-context validators for GLP sign-offs.

Used by both POST /protocols/{id}/signoffs and POST /runs/{id}/signoffs.
Follows the validate_X / assert_no_X_errors pattern from
.claude/rules/backend-services.md.

Grilling decision #5 (lines 4240-4269): QAU independence is broadened to check
all run actors — operator (started_by_id), creator (created_by_id), per-step
actors in execution_data, lane assignments, and any active Study Director
sign-off on the run/protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.science import GlpSignoff, Protocol, Run, RunRoleAssignment
from app.services.core.permissions import check_permission


@dataclass
class SignoffPayload:
    role: str
    action: str
    attestation: Optional[str]
    signature_image_path: Optional[str]


def assert_attestation_and_image_present(payload: SignoffPayload) -> None:
    """K2/K4: APPROVED sign-offs must carry both attestation text and a
    record-scoped signature image path.

    Non-APPROVED actions (REJECTED, REQUESTED_CHANGES) are allowed without
    either field.
    """
    if payload.action != "APPROVED":
        return
    if not payload.attestation or not payload.signature_image_path:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "ATTESTATION_REQUIRED",
                "role": payload.role,
                "action": payload.action,
            },
        )


async def assert_qau_independent(
    db: AsyncSession,
    entity_type: Literal["protocol", "run"],
    entity_id: UUID,
    signer_id: UUID,
    role: str,
) -> None:
    """§58.35: QAU must be independent of every actor who touched the study.

    For a run, "touched" means any of:
    - started_by_id (OPERATOR conflict)
    - created_by_id (CREATED_BY conflict)
    - per-step started_by_user_id / reviewed_by_user_id in execution_data
      (STEP_ACTOR conflict)
    - RunRoleAssignment.user_id for any lane on the run (LANE_ASSIGNMENT conflict)
    - active STUDY_DIRECTOR sign-off on the run (STUDY_DIRECTOR conflict)

    For a protocol, only the active STUDY_DIRECTOR sign-off is checked
    (no operator/step concepts on protocols).

    Raises HTTPException(400) with error="QAU_NOT_INDEPENDENT" and
    conflict_role=<role> if any condition is violated.
    """
    if role != "QAU":
        return

    signer_str = str(signer_id)

    if entity_type == "run":
        result = await db.execute(select(Run).where(Run.id == entity_id))
        run = result.scalar_one()

        # 1. Operator (started_by_id)
        if run.started_by_id == signer_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "QAU_NOT_INDEPENDENT",
                    "conflict_role": "OPERATOR",
                },
            )

        # 2. Creator (created_by_id)
        if run.created_by_id is not None and run.created_by_id == signer_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "QAU_NOT_INDEPENDENT",
                    "conflict_role": "CREATED_BY",
                },
            )

        # 3. Per-step actors in execution_data (JSONB stores strings; also allow
        #    UUID objects for resilience against in-memory test data).
        if run.execution_data:
            for step_data in run.execution_data.values():
                if not isinstance(step_data, dict):
                    continue
                for field in ("started_by_user_id", "reviewed_by_user_id"):
                    raw = step_data.get(field)
                    if raw is None:
                        continue
                    # Compare as strings to handle UUID vs str heterogeneity.
                    if str(raw) == signer_str:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "error": "QAU_NOT_INDEPENDENT",
                                "conflict_role": "STEP_ACTOR",
                            },
                        )

        # 4. Lane (RunRoleAssignment) actors
        assignments_result = await db.execute(
            select(RunRoleAssignment).where(RunRoleAssignment.run_id == entity_id)
        )
        for assignment in assignments_result.scalars().all():
            if assignment.user_id == signer_id:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "QAU_NOT_INDEPENDENT",
                        "conflict_role": "LANE_ASSIGNMENT",
                    },
                )

        # 5. Active Study Director sign-off on the protocol the run executes.
        # GLP §58.35: QAU must be independent of the SD who APPROVED THE
        # PROTOCOL (pre-execution approval), not a per-run SD sign-off.
        # Grilling decision #5 (plan lines 4262-4263).
        if run.protocol_id is not None:
            sd_result = await db.execute(
                select(GlpSignoff).where(
                    GlpSignoff.protocol_id == run.protocol_id,
                    GlpSignoff.role == "STUDY_DIRECTOR",
                    GlpSignoff.action == "APPROVED",
                    GlpSignoff.invalidated_at.is_(None),
                )
            )
            sd_row = sd_result.scalar_one_or_none()
            if sd_row is not None and sd_row.signer_id == signer_id:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "QAU_NOT_INDEPENDENT",
                        "conflict_role": "STUDY_DIRECTOR",
                    },
                )

    else:
        # entity_type == "protocol"
        # Only check active Study Director sign-off on the protocol itself.
        sd_result = await db.execute(
            select(GlpSignoff).where(
                GlpSignoff.protocol_id == entity_id,
                GlpSignoff.role == "STUDY_DIRECTOR",
                GlpSignoff.action == "APPROVED",
                GlpSignoff.invalidated_at.is_(None),
            )
        )
        sd_row = sd_result.scalar_one_or_none()
        if sd_row is not None and sd_row.signer_id == signer_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "QAU_NOT_INDEPENDENT",
                    "conflict_role": "STUDY_DIRECTOR",
                },
            )


async def validate_signoff_role_assignable(
    db: AsyncSession,
    entity_type: Literal["protocol", "run"],
    entity_id: UUID,
    user_id: UUID,
    role: str,
) -> None:
    """Verify the signer has the project-level permission required to act in
    ``role``.  Raises HTTPException(403) on failure.

    Role → required permission mapping (grilling plan lines 1098-1138):
        OPERATOR        → WRITE  (EDIT) on the run
        STUDY_DIRECTOR  → APPROVE on the protocol (or the run's protocol)
        QAU             → APPROVE on the protocol (or the run's protocol)
        SPONSOR         → ADMIN on the project owning the protocol

    For roles that check the protocol (STUDY_DIRECTOR, QAU, SPONSOR) when the
    entity is a run, the check is performed against the run's ``protocol_id``.
    If ``protocol_id`` is None the run is not linked to a protocol and only
    OPERATOR/EDIT-level checks apply (protocol-scoped roles pass through).
    """
    # Resolve the protocol_id we need for SD/QAU/SPONSOR checks.
    protocol_id: Optional[UUID] = None
    if entity_type == "run":
        run_result = await db.execute(select(Run).where(Run.id == entity_id))
        run = run_result.scalar_one()
        protocol_id = run.protocol_id
    else:
        protocol_id = entity_id

    # Determine the (object_type, object_id, level) triple for check_permission.
    if role == "OPERATOR":
        # OPERATOR signs the run directly; requires EDIT on the run.
        obj_type = ObjectType.RUN
        obj_id = entity_id
        required = PermissionLevel.EDIT

    elif role in ("STUDY_DIRECTOR", "QAU"):
        # These roles sign the protocol (or the run's protocol).
        if protocol_id is None:
            # Run not linked to a protocol — no protocol permission to check.
            return
        obj_type = ObjectType.PROTOCOL
        obj_id = protocol_id
        required = PermissionLevel.APPROVE

    elif role == "SPONSOR":
        # SPONSOR requires ADMIN on the project owning the protocol.
        if protocol_id is None:
            return
        proto_result = await db.execute(
            select(Protocol.project_id).where(Protocol.id == protocol_id)
        )
        proj_id: Optional[UUID] = proto_result.scalar_one_or_none()
        if proj_id is None:
            # Protocol is org-scoped (no project) — fall back to APPROVE on
            # the protocol itself.
            # TODO: revisit when org-scoped protocols get a proper SPONSOR flow.
            obj_type = ObjectType.PROTOCOL
            obj_id = protocol_id
            required = PermissionLevel.APPROVE
        else:
            obj_type = ObjectType.PROJECT
            obj_id = proj_id
            required = PermissionLevel.ADMIN

    else:
        # Unknown role — no specific permission mapping; allow through.
        return

    allowed = await check_permission(
        db=db,
        user_id=user_id,
        object_type=obj_type,
        object_id=obj_id,
        required_level=required,
    )
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "ROLE_NOT_AUTHORIZED",
                "role": role,
                "entity_type": entity_type,
            },
        )
