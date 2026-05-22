"""Resolve notification deep-link URLs.

A ``Notification`` row stores only ``entity_type`` + ``entity_id``; the
in-app inbox needs a navigable, org-scoped, slug-based path to deep-link
to. This module resolves a batch of notifications to their canonical
front-end routes at read time.

Routes mirror the SvelteKit URL scheme (F-0091): every routed object lives
under ``/{org-slug}/...`` and runs/experiments nest under their project.
The org slug is ``slugify(org.name)``, disambiguated with an id-prefix
suffix when the recipient belongs to two orgs whose names slugify
identically — the same rule the frontend ``disambiguatedOrgSlug`` applies.
"""

from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slug import slugify
from app.models.iam import Organization, OrganizationMember
from app.models.notifications import Notification
from app.models.projects import Project
from app.models.protocols import Protocol
from app.models.runs import Experiment, Run

# Lower-cased ``entity_type`` values that resolve to a routed page. Any
# other type (e.g. "RevokedOfflineToken") has no in-app destination.
_ROUTABLE = frozenset({"run", "experiment", "protocol", "project"})


def _disambiguated_org_slugs(
    orgs: Sequence[tuple[UUID, str]],
) -> dict[UUID, str]:
    """Map org id -> URL slug, mirroring frontend ``disambiguatedOrgSlug``.

    When two orgs in ``orgs`` slugify to the same base, every colliding org
    gets a ``-{id-prefix}`` suffix so the deep link stays unambiguous.
    """
    base: dict[UUID, str] = {oid: slugify(name) for oid, name in orgs}
    counts: dict[str, int] = {}
    for slug in base.values():
        counts[slug] = counts.get(slug, 0) + 1
    return {
        oid: slug if counts[slug] == 1 else f"{slug}-{str(oid)[:8]}"
        for oid, slug in base.items()
    }


async def resolve_notification_urls(
    db: AsyncSession,
    notifications: Sequence[Notification],
    recipient_id: UUID,
) -> dict[UUID, Optional[str]]:
    """Resolve each notification to an in-app deep-link URL.

    Returns a ``{notification.id: url-or-None}`` map. A notification
    resolves to ``None`` when its entity type is not routable, the target
    row no longer exists, or the target's org is not one the recipient
    belongs to (a 403 dead-end is worse than no link at all).
    """
    if not notifications:
        return {}

    # Group entity ids by lower-cased type so each table is queried once.
    ids_by_type: dict[str, set[UUID]] = {}
    for n in notifications:
        etype = (n.entity_type or "").lower()
        if etype in _ROUTABLE and n.entity_id is not None:
            ids_by_type.setdefault(etype, set()).add(n.entity_id)

    # (entity_type, entity id) -> (org_id, path below the org segment)
    targets: dict[tuple[str, UUID], tuple[UUID, str]] = {}

    run_ids = ids_by_type.get("run")
    if run_ids:
        rows = await db.execute(
            select(Run).where(Run.id.in_(run_ids))
        )
        for run in rows.scalars():
            if run.project is not None:  # project_id is NOT NULL; purely defensive
                targets[("run", run.id)] = (
                    run.project.organization_id,
                    f"/projects/{run.project.slug}/runs/{run.slug}",
                )

    exp_ids = ids_by_type.get("experiment")
    if exp_ids:
        rows = await db.execute(
            select(Experiment).where(Experiment.id.in_(exp_ids))
        )
        for exp in rows.scalars():
            if exp.project is not None:  # project_id is NOT NULL; purely defensive
                targets[("experiment", exp.id)] = (
                    exp.project.organization_id,
                    f"/projects/{exp.project.slug}/experiments/{exp.slug}",
                )

    protocol_ids = ids_by_type.get("protocol")
    if protocol_ids:
        rows = await db.execute(
            select(Protocol).where(Protocol.id.in_(protocol_ids))
        )
        for protocol in rows.scalars():
            targets[("protocol", protocol.id)] = (
                protocol.owner_org_id,
                f"/protocols/{protocol.slug}",
            )

    project_ids = ids_by_type.get("project")
    if project_ids:
        rows = await db.execute(
            select(Project).where(Project.id.in_(project_ids))
        )
        for project in rows.scalars():
            targets[("project", project.id)] = (
                project.organization_id,
                f"/projects/{project.slug}",
            )

    if not targets:
        return {n.id: None for n in notifications}

    # Org slugs are computed only over the recipient's own memberships:
    # disambiguation must match the membership set the frontend nav uses,
    # which is exactly the recipient's orgs. A target in an org the
    # recipient does not belong to therefore resolves to None.
    member_orgs = await db.execute(
        select(Organization.id, Organization.name)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Organization.id,
        )
        .where(OrganizationMember.user_id == recipient_id)
    )
    org_slugs = _disambiguated_org_slugs(list(member_orgs.all()))

    result: dict[UUID, Optional[str]] = {}
    for n in notifications:
        target = targets.get(((n.entity_type or "").lower(), n.entity_id))
        if target is None:
            result[n.id] = None
            continue
        org_id, path = target
        org_slug = org_slugs.get(org_id)
        # A blank or hyphen-leading slug means the org name had no
        # alphanumeric content — there is no valid route, so degrade.
        if org_slug and not org_slug.startswith("-"):
            result[n.id] = f"/{org_slug}{path}"
        else:
            result[n.id] = None
    return result
