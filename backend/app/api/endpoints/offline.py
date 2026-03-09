"""Offline field mode endpoints: session creation, prefetch, and token revocation."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, get_db
from app.core.security import verify_password, create_offline_token
from app.models.iam import User
from app.models.offline import RevokedOfflineToken
from app.models.science import Run, RunRoleAssignment, UnitOpDefinition
from app.schemas.offline import (
    OfflineSessionRequest,
    OfflineSessionResponse,
    RunPrefetchResponse,
    RoleAssignmentPrefetch,
    RevokeTokenRequest,
    RevokedTokenResponse,
)
from app.services.audit import log_audit
from app.services.notifications import send_notification

router = APIRouter()


@router.post("/auth/offline-session", response_model=OfflineSessionResponse)
async def create_offline_session(
    body: OfflineSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a scoped offline JWT for field mode execution."""
    # Verify password
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    # Verify run exists and is ACTIVE
    result = await db.execute(select(Run).where(Run.id == body.run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    run_status = run.status.value if hasattr(run.status, "value") else str(run.status)
    if run_status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run must be ACTIVE to create offline session (current: {run_status})",
        )

    # Verify user has a role assignment on this run
    assignment_result = await db.execute(
        select(RunRoleAssignment).where(
            RunRoleAssignment.run_id == body.run_id,
            RunRoleAssignment.user_id == user.id,
        )
    )
    if assignment_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be assigned to a role on this run",
        )

    # Issue offline token
    token, jti, expires_at = create_offline_token(user.id, body.run_id)

    # Audit log
    await log_audit(
        db,
        actor_id=user.id,
        action="OFFLINE_SESSION_CREATED",
        entity_type="Run",
        entity_id=body.run_id,
        changes={"jti": jti, "expires_at": expires_at.isoformat()},
    )

    # Send sync reminder notification
    run_result = await db.execute(select(Run).where(Run.id == body.run_id))
    run_obj = run_result.scalar_one()
    project_result = await db.execute(
        select(Run.project_id).where(Run.id == body.run_id)
    )
    from app.models.science import Project
    proj_result = await db.execute(
        select(Project.organization_id).where(Project.id == run_obj.project_id)
    )
    org_id = proj_result.scalar_one()

    await send_notification(
        db=db,
        event_type="OFFLINE_SYNC_PENDING",
        org_id=org_id,
        entity_type="run",
        entity_id=body.run_id,
        recipients=[user.id],
        context={
            "run_name": run_obj.name,
            "user_name": user.full_name or user.email,
        },
    )

    await db.commit()

    return OfflineSessionResponse(
        offline_token=token,
        expires_at=expires_at,
        run_id=body.run_id,
    )


@router.get("/offline/runs/{run_id}/prefetch", response_model=RunPrefetchResponse)
async def prefetch_run_data(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return everything needed for offline run execution."""
    # Load run with role assignments
    result = await db.execute(
        select(Run)
        .options(selectinload(Run.role_assignments).selectinload(RunRoleAssignment.user))
        .where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    # Build role assignments
    assignments = [
        RoleAssignmentPrefetch(
            id=ra.id,
            lane_node_id=ra.lane_node_id,
            role_name=ra.role_name,
            user_id=ra.user_id,
            user_name=ra.user.full_name if ra.user else None,
        )
        for ra in run.role_assignments
    ]

    # Collect unit op IDs from the graph and fetch definitions
    unit_op_defs = {}
    graph = run.graph or {}
    nodes = graph.get("nodes", [])
    unit_op_ids = set()
    for node in nodes:
        data = node.get("data", {})
        uid = data.get("unitOpId")
        if uid:
            unit_op_ids.add(uid)

    if unit_op_ids:
        defs_result = await db.execute(
            select(UnitOpDefinition).where(
                UnitOpDefinition.id.in_(unit_op_ids)
            )
        )
        for uod in defs_result.scalars():
            unit_op_defs[str(uod.id)] = {
                "name": uod.name,
                "category": uod.category,
                "param_schema": uod.param_schema,
            }

    return RunPrefetchResponse(
        run_id=run.id,
        run_name=run.name,
        run_status=run.status.value if hasattr(run.status, "value") else str(run.status),
        graph=graph,
        execution_data=run.execution_data or {},
        role_assignments=assignments,
        unit_op_definitions=unit_op_defs,
    )


@router.delete("/auth/offline-session/{jti}", response_model=RevokedTokenResponse)
async def revoke_offline_token(
    jti: str,
    body: RevokeTokenRequest = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an offline token by its JTI. Admin override."""
    # Check if already revoked
    existing = await db.execute(
        select(RevokedOfflineToken).where(RevokedOfflineToken.jti == jti)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Token already revoked",
        )

    # Decode the JTI from known tokens — we don't have the token itself,
    # so we trust the admin is providing a valid JTI. We store the revocation
    # and the blacklist check happens at auth time.
    # For audit, we need user_id and run_id — but we can't decode without
    # the token. Store with the revoking user's context.
    revoked = RevokedOfflineToken(
        jti=jti,
        user_id=user.id,  # Will be updated if we can identify the token owner
        run_id=None,  # Unknown without the token itself
        revoked_by=user.id,
        reason=body.reason if body else None,
    )
    db.add(revoked)
    await db.flush()

    await log_audit(
        db,
        actor_id=user.id,
        action="OFFLINE_TOKEN_REVOKED",
        entity_type="RevokedOfflineToken",
        entity_id=revoked.id,
        changes={"jti": jti, "reason": body.reason if body else None},
    )

    await db.commit()
    await db.refresh(revoked)

    return RevokedTokenResponse(
        jti=revoked.jti,
        user_id=revoked.user_id,
        run_id=revoked.run_id,
        revoked_by=revoked.revoked_by,
        reason=revoked.reason,
        created_at=revoked.created_at,
    )
