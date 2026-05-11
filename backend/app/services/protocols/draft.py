"""Draft routing for protocol mutations.

DRAFT protocols are edited in place: writes land on ``Protocol.graph``.
APPROVED protocols are frozen — edits go through a ``ProtocolVersion`` row
with ``is_draft=True``, which the user later publishes via
``/protocols/{id}/publish-draft``. Chat mutation tools and HTTP role
endpoints share this resolver so the published surface stays consistent
with what the editor does.

PENDING_APPROVAL and ARCHIVED refuse: nothing should be mutating them.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.iam import ObjectType, PermissionLevel
from app.models.science import Protocol, ProtocolVersion
from app.services.core.permissions import check_permission


@dataclass
class WorkingDraft:
    """Editable surface for one protocol's graph.

    Either points at the live ``protocol.graph`` (for DRAFT protocols) or
    at an active draft ``ProtocolVersion.graph`` (for APPROVED protocols
    with an open draft). Callers read ``graph`` and write back via
    ``set_graph``; the routing is transparent.
    """

    protocol: Protocol
    version: ProtocolVersion | None

    @property
    def graph(self) -> dict:
        if self.version is not None:
            return self.version.graph or {}
        return self.protocol.graph or {}

    @property
    def is_version_backed(self) -> bool:
        return self.version is not None

    def set_graph(self, new_graph: dict) -> None:
        if self.version is not None:
            self.version.graph = new_graph
        else:
            self.protocol.graph = new_graph


async def _find_active_draft(
    db: AsyncSession, protocol_id: UUID
) -> ProtocolVersion | None:
    """Return the highest-numbered ``is_draft=True`` version, if any."""
    result = await db.execute(
        select(ProtocolVersion)
        .where(
            ProtocolVersion.protocol_id == protocol_id,
            ProtocolVersion.is_draft.is_(True),
        )
        .order_by(ProtocolVersion.version_number.desc())
    )
    return result.scalars().first()


async def resolve_working_draft(
    db: AsyncSession, protocol: Protocol
) -> WorkingDraft:
    """Return the editable graph surface for ``protocol``.

    Raises ``ValueError`` (message contains "published" for HTTP 409
    mapping) when the protocol is APPROVED with no active draft —
    callers should surface the message and let the user call
    ``create_draft`` before retrying.
    """
    if protocol.status == "DRAFT":
        return WorkingDraft(protocol=protocol, version=None)
    if protocol.status == "PENDING_APPROVAL":
        raise ValueError(
            "Protocol is published and pending approval — cannot edit until "
            "approved or rejected."
        )
    if protocol.status == "ARCHIVED":
        raise ValueError(
            "Protocol is archived. Restore it before editing."
        )
    if protocol.status == "APPROVED":
        draft = await _find_active_draft(db, protocol.id)
        if draft is None:
            raise ValueError(
                "Protocol is published — call create_draft(protocol_id) to "
                "start a draft, then re-issue your edit."
            )
        return WorkingDraft(protocol=protocol, version=draft)
    raise ValueError(f"Protocol is in unsupported status '{protocol.status}'.")


async def create_draft_version(
    db: AsyncSession, *, user_id: UUID, protocol_id: UUID
) -> tuple[ProtocolVersion, bool]:
    """Open a draft on an APPROVED protocol.

    Returns ``(draft_version, created)`` where ``created`` is False if an
    active draft already existed (idempotent). Refuses with a ValueError
    on DRAFT (no draft needed), PENDING_APPROVAL, or ARCHIVED. The
    "published" sentinel substring is intentionally absent — callers
    expect this function to *make* a draft, not to be told the protocol
    is published.
    """
    protocol = (
        await db.execute(select(Protocol).where(Protocol.id == protocol_id))
    ).scalar_one_or_none()
    if protocol is None:
        raise ValueError(f"Protocol {protocol_id} not found")

    if protocol.project_id is not None:
        allowed = await check_permission(
            db,
            user_id,
            ObjectType.PROJECT,
            protocol.project_id,
            PermissionLevel.EDIT,
        )
        if not allowed:
            raise ValueError("You don't have edit permission on this protocol")

    if protocol.status == "DRAFT":
        raise ValueError(
            "Protocol is already a draft — edit it directly without "
            "calling create_draft."
        )
    if protocol.status == "PENDING_APPROVAL":
        raise ValueError(
            "Protocol is pending approval — wait for it to be approved or "
            "rejected before drafting changes."
        )
    if protocol.status == "ARCHIVED":
        raise ValueError("Protocol is archived. Restore it before drafting.")
    if protocol.status != "APPROVED":
        raise ValueError(
            f"Cannot create draft from status '{protocol.status}'."
        )

    existing = await _find_active_draft(db, protocol_id)
    if existing is not None:
        return existing, False

    draft = ProtocolVersion(
        protocol_id=protocol.id,
        version_number=protocol.version_number + 1,
        graph=dict(protocol.graph or {}),
        name=protocol.name,
        description=protocol.description,
        created_by_id=user_id,
        is_draft=True,
        sop_template_id=protocol.sop_template_id,
        batch_record_template_id=protocol.batch_record_template_id,
    )
    db.add(draft)
    await db.flush()
    return draft, True
