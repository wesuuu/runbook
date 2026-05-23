"""Shared org-URL-slug disambiguation.

The frontend ``disambiguatedOrgSlug`` rule (F-0091): every org gets
``slugify(name)``; if two orgs in the user's membership set collide on
that base, both get a ``-{id-prefix}`` suffix. Backend code that emits
URLs to be opened in the SvelteKit app must apply the same rule.
"""

from __future__ import annotations

from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slug import slugify
from app.models.iam import Organization, OrganizationMember


def disambiguate_org_slugs(
    orgs: Sequence[tuple[UUID, str]],
) -> dict[UUID, str]:
    """Map org id -> URL slug. Call this when you already hold the
    membership rows; prefer ``disambiguated_org_slug_for_user`` otherwise.

    Returns ``""`` for any org whose name has no alphanumeric content
    (slugifies to empty). Callers should treat empty-string slugs as
    "no valid URL" and degrade — never emit ``/-acme/...`` paths.
    """
    base: dict[UUID, str] = {oid: slugify(name) for oid, name in orgs}
    counts: dict[str, int] = {}
    for slug in base.values():
        counts[slug] = counts.get(slug, 0) + 1
    return {
        oid: ("" if slug == "" else slug if counts[slug] == 1 else f"{slug}-{str(oid)[:8]}")
        for oid, slug in base.items()
    }


async def disambiguated_org_slug_for_user(
    db: AsyncSession, user_id: UUID, org_id: UUID
) -> str | None:
    """Resolve the URL slug for ``org_id`` in the context of ``user_id``'s
    org memberships.

    Returns ``None`` if the user is not a member of ``org_id`` or if the
    resolved slug is blank / hyphen-leading (meaning the org name has no
    alphanumeric content and the URL has no valid form).
    """
    rows = await db.execute(
        select(Organization.id, Organization.name)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Organization.id,
        )
        .where(OrganizationMember.user_id == user_id)
    )
    slugs = disambiguate_org_slugs(list(rows.all()))
    slug = slugs.get(org_id)
    if not slug or slug.startswith("-"):
        return None
    return slug
