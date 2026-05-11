"""Service: list protocols awaiting a given user's approval."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import OrganizationMember, OrgRole, User
from app.models.science import (Project, Protocol, ProtocolApprovalEvent,
                                ProtocolApprovalRequest)


async def list_awaiting_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return a deduped list of protocols awaiting the user's approval.

    A protocol is awaiting the user if either:
      (a) there is an OPEN ProtocolApprovalRequest for the user, or
      (b) the user holds the org PROTOCOL_APPROVER role in the protocol's
          organization AND the protocol is PENDING_APPROVAL.

    Returns an empty list when the user has no relevant context.
    """
    # 1. Orgs where this user is a PROTOCOL_APPROVER
    approver_org_rows = await db.execute(
        select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.roles.contains([OrgRole.PROTOCOL_APPROVER.value]),
        )
    )
    approver_orgs: set[uuid.UUID] = set(approver_org_rows.scalars().all())

    # 2. Protocols with an OPEN approval request directly addressed to user
    open_request_rows = await db.execute(
        select(ProtocolApprovalRequest.protocol_id).where(
            ProtocolApprovalRequest.requested_user_id == user_id,
            ProtocolApprovalRequest.status == "OPEN",
        )
    )
    request_proto_ids: set[uuid.UUID] = set(open_request_rows.scalars().all())

    if not approver_orgs and not request_proto_ids:
        return []

    # 3. Pull candidate protocols + their parent project (left-join for
    #    org-scoped protocols which have no project).
    stmt = (
        select(Protocol, Project)
        .join(Project, Protocol.project_id == Project.id, isouter=True)
        .where(Protocol.status == "PENDING_APPROVAL")
    )
    result = await db.execute(stmt)
    rows = result.all()

    awaiting: dict[uuid.UUID, dict[str, Any]] = {}
    for proto, project in rows:
        if proto.id in awaiting:
            continue
        proto_org_id = (
            project.organization_id if project is not None else proto.organization_id
        )
        match_request = proto.id in request_proto_ids
        match_org = proto_org_id is not None and proto_org_id in approver_orgs
        if not (match_request or match_org):
            continue
        awaiting[proto.id] = {
            "protocol_id": proto.id,
            "name": proto.name,
            "project_id": project.id if project is not None else None,
            "project_name": project.name if project is not None else None,
            "organization_id": proto_org_id,
        }

    if not awaiting:
        return []

    # 4. Fetch the latest SUBMITTED event per protocol for actor + timestamp
    proto_ids = list(awaiting.keys())
    submit_rows = await db.execute(
        select(ProtocolApprovalEvent, User)
        .join(User, ProtocolApprovalEvent.actor_id == User.id, isouter=True)
        .where(
            ProtocolApprovalEvent.protocol_id.in_(proto_ids),
            ProtocolApprovalEvent.action == "SUBMITTED",
        )
        .order_by(
            ProtocolApprovalEvent.protocol_id,
            ProtocolApprovalEvent.created_at.desc(),
        )
    )
    seen: set[uuid.UUID] = set()
    for ev, actor in submit_rows.all():
        if ev.protocol_id in seen:
            continue
        seen.add(ev.protocol_id)
        item = awaiting.get(ev.protocol_id)
        if item is None:
            continue
        item["submitted_at"] = ev.created_at
        if actor is not None:
            item["submitted_by"] = {
                "id": actor.id,
                "name": actor.full_name or actor.email,
                "email": actor.email,
            }

    # Default missing keys for shape consistency
    for item in awaiting.values():
        item.setdefault("submitted_at", None)
        item.setdefault("submitted_by", None)

    return list(awaiting.values())
