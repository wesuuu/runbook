"""Unified review queue: run + protocol sign-off requests for a user (F-0080)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import OrganizationMember, OrgRole, User
from app.models.projects import Project
from app.models.runs import Run
from app.models.signoffs import GlpSignoffRequest
from app.services.approvals.awaiting import list_awaiting_for_user

_QUEUE_CAP = 200


def _actor(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
    }


def _protocol_actor(submitted_by: Any) -> dict[str, Any] | None:
    """Normalise `list_awaiting_for_user`'s `submitted_by` dict to the queue
    actor shape.

    `list_awaiting_for_user` returns the submitter `id` as a `UUID` object,
    but `QueueActorRef.id` (and the run path's `_actor`) is a `str`. Pydantic
    will not coerce a `UUID` into a `str` field, so `SignoffRequestItem(**item)`
    in the endpoint would 500 on a protocol item. Coerce here.
    """
    if not isinstance(submitted_by, dict):
        return None
    actor = dict(submitted_by)
    if actor.get("id") is not None:
        actor["id"] = str(actor["id"])
    return actor


def _run_item(req: GlpSignoffRequest, run: Run, requester: User | None) -> dict:
    return {
        "type": "run",
        "request_id": req.id,
        "target_id": run.id,
        "target_name": run.name,
        "role": req.role,
        "project_id": run.project_id,
        "assigned": req.requested_user_id is not None,
        "requested_by": _actor(requester),
        "created_at": req.created_at,
    }


async def list_review_queue_for_user(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Return pending review items (run + protocol), oldest-first, deduped.

    Run items: OPEN run-scoped requests assigned to the user, OR unassigned QAU
    requests for runs in an organization where the user holds OrgRole.QAU. The
    org match is the tenant boundary. Project ACLs are intentionally bypassed —
    QAU oversight is org-wide under §58.35.
    """
    # Orgs where the user is a QAU.
    qau_org_rows = await db.execute(
        select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.roles.contains([OrgRole.QAU.value]),
        )
    )
    qau_orgs: set[uuid.UUID] = set(qau_org_rows.scalars().all())

    items: dict[uuid.UUID, dict[str, Any]] = {}

    # Assigned run requests.
    assigned_rows = await db.execute(
        select(GlpSignoffRequest, Run, User)
        .join(Run, GlpSignoffRequest.run_id == Run.id)
        .join(User, GlpSignoffRequest.requested_by_id == User.id, isouter=True)
        .where(
            GlpSignoffRequest.run_id.isnot(None),
            GlpSignoffRequest.status == "OPEN",
            GlpSignoffRequest.requested_user_id == user_id,
        )
    )
    for req, run, requester in assigned_rows.all():
        items[req.id] = _run_item(req, run, requester)

    # Unassigned QAU pool requests, scoped to the user's QAU orgs.
    if qau_orgs:
        pool_rows = await db.execute(
            select(GlpSignoffRequest, Run, User)
            .join(Run, GlpSignoffRequest.run_id == Run.id)
            .join(Project, Run.project_id == Project.id)
            .join(User, GlpSignoffRequest.requested_by_id == User.id, isouter=True)
            .where(
                GlpSignoffRequest.run_id.isnot(None),
                GlpSignoffRequest.status == "OPEN",
                GlpSignoffRequest.role == "QAU",
                GlpSignoffRequest.requested_user_id.is_(None),
                Project.organization_id.in_(qau_orgs),
            )
        )
        for req, run, requester in pool_rows.all():
            items.setdefault(req.id, _run_item(req, run, requester))

    # Protocol items (existing service).
    protocol_items: list[dict[str, Any]] = []
    for p in await list_awaiting_for_user(db, user_id):
        protocol_items.append(
            {
                "type": "protocol",
                "request_id": None,
                "target_id": p["protocol_id"],
                "target_name": p["name"],
                "role": None,
                "project_id": p.get("project_id"),
                "assigned": True,
                "requested_by": _protocol_actor(p.get("submitted_by")),
                "created_at": p.get("submitted_at"),
            }
        )

    combined = list(items.values()) + protocol_items
    # Oldest-first; None-dated items sort first. str() keeps the key total-order
    # safe across tz-aware/naive datetimes and avoids None < None TypeErrors.
    combined.sort(key=lambda i: (i["created_at"] is None, str(i["created_at"])))
    return combined[:_QUEUE_CAP]
