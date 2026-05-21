"""Onboarding tour API — state and sample artifact lifecycle."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_active_subscription
from app.db.session import get_db
from app.models.iam import Organization, User
from app.schemas.onboarding import (
    TourProjectStartResponse,
    TourProtocolStartResponse,
    TourRunStartResponse,
    TourStateResponse,
    TourStateUpdate,
)
from app.services.core.onboarding import (
    delete_sample_run,
    find_or_create_sample_project,
    find_or_create_sample_protocol,
    find_or_create_sample_run,
)

router = APIRouter()


async def _get_current_org(db: AsyncSession, user: User) -> Organization:
    if user.selected_org_id is None:
        raise HTTPException(status_code=400, detail="No org selected")
    org = await db.get(Organization, user.selected_org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Org not found")
    return org


@router.get("/state", response_model=TourStateResponse)
async def get_tour_state(
    user: User = Depends(get_current_user),
):
    state = user.tour_state or {}
    return TourStateResponse(
        completed=state.get("completed", []),
        dismissed=state.get("dismissed", []),
    )


@router.patch("/state", response_model=TourStateResponse)
async def patch_tour_state(
    body: TourStateUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    state = dict(user.tour_state or {})
    completed = list(state.get("completed", []))
    dismissed = list(state.get("dismissed", []))

    completed = [s for s in completed if s != body.segment]
    dismissed = [s for s in dismissed if s != body.segment]
    if body.status == "completed":
        completed.append(body.segment)
    else:
        dismissed.append(body.segment)

    user.tour_state = {"completed": completed, "dismissed": dismissed}
    await db.commit()
    await db.refresh(user)
    return TourStateResponse(completed=completed, dismissed=dismissed)


@router.post("/tour/project/start", response_model=TourProjectStartResponse)
async def tour_project_start(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    org = await _get_current_org(db, user)
    project = await find_or_create_sample_project(db, user, org)
    return TourProjectStartResponse(
        project_id=project.id, project_slug=project.slug
    )


def _clear_segment_from_tour_state(user: User, segment: str) -> None:
    """Remove segment from both completed and dismissed lists so its dot re-appears."""
    state = dict(user.tour_state or {})
    completed = [s for s in state.get("completed", []) if s != segment]
    dismissed = [s for s in state.get("dismissed", []) if s != segment]
    user.tour_state = {"completed": completed, "dismissed": dismissed}


@router.post("/tour/protocol/start", response_model=TourProtocolStartResponse)
async def tour_protocol_start(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    org = await _get_current_org(db, user)
    protocol = await find_or_create_sample_protocol(db, user, org)
    # Clicking "Load sample protocol" is an explicit re-invitation: reset the
    # protocol segment so the HelpMenu dot pulses again on arrival.
    _clear_segment_from_tour_state(user, "protocol")
    await db.commit()
    return TourProtocolStartResponse(
        project_id=protocol.project_id,
        protocol_id=protocol.id,
        protocol_slug=protocol.slug,
    )


@router.post("/tour/run/start", response_model=TourRunStartResponse)
async def tour_run_start(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    org = await _get_current_org(db, user)
    protocol = await find_or_create_sample_protocol(db, user, org)
    run = await find_or_create_sample_run(db, user, protocol)
    return TourRunStartResponse(
        run_id=run.id,
        protocol_id=protocol.id,
        project_id=run.project_id,
    )


@router.post("/tour/run/end")
async def tour_run_end(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_active_subscription()),
):
    await delete_sample_run(db, user)
    return {"ok": True}
