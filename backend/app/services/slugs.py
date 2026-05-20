"""Slug assignment with per-scope uniqueness enforcement (F-0091)."""

import secrets
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slug import slugify


async def assign_slug(
    db: AsyncSession,
    model: type,
    scope_attr,
    scope_value,
    name: str,
    exclude_id: Optional[object] = None,
) -> str:
    """Return a unique slug for `name` within a scope, or raise.

    `scope_attr` is the mapped column the slug is unique against
    (e.g. `Project.organization_id`, `Run.project_id`). On rename, pass
    `exclude_id` so the row does not collide with itself.

    Raises `ValueError("SLUG_CONFLICT")` when the slugified name is
    already taken by another row in the same scope.
    """
    base = slugify(name) or f"untitled-{secrets.token_hex(3)}"
    stmt = select(model.id).where(scope_attr == scope_value, model.slug == base)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if (await db.execute(stmt)).first() is not None:
        raise ValueError("SLUG_CONFLICT")
    return base


async def assign_slug_or_422(
    db: AsyncSession,
    model: type,
    scope_attr,
    scope_value,
    name: str,
    entity_label: str,
    exclude_id: Optional[object] = None,
) -> str:
    """Assign a unique slug, raising the standard HTTP 422 on collision.

    Wraps assign_slug: on a SLUG_CONFLICT ValueError, raises
    slug_conflict_error(entity_label, name); any other ValueError propagates.
    """
    try:
        return await assign_slug(
            db, model, scope_attr, scope_value, name, exclude_id=exclude_id
        )
    except ValueError as exc:
        if str(exc) == "SLUG_CONFLICT":
            raise slug_conflict_error(entity_label, name)
        raise


def slug_conflict_error(entity_label: str, name: str | None = None) -> HTTPException:
    """Build the standard HTTP 422 for a slug-uniqueness collision.

    entity_label is the lowercase singular noun ("protocol", "project", ...).
    """
    if name:
        message = (
            f"A {entity_label} named '{name}' already exists in this organization."
        )
    else:
        message = (
            f"A {entity_label} with that name already exists in this organization."
        )
    return HTTPException(
        status_code=422,
        detail={"code": "SLUG_CONFLICT", "message": message},
    )
