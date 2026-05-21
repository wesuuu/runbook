"""Slug assignment with per-scope uniqueness enforcement (F-0091)."""

import secrets
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.slug import RESERVED_SLUGS, slugify

# Per-scope slug-uniqueness constraints created by the f0091_url_slugs
# migration. A violation of any of these means a slug collision raced past
# the assign_slug pre-check (see is_slug_conflict).
SLUG_UNIQUE_CONSTRAINTS: frozenset[str] = frozenset(
    {
        "uq_protocols_owner_org_slug",
        "uq_projects_org_slug",
        "uq_runs_project_slug",
        "uq_experiments_project_slug",
        "uq_documents_org_slug",
    }
)


class SlugConflictError(ValueError):
    """A slugified name collides with an existing row in the same scope.

    Subclasses ``ValueError`` and stringifies to the stable
    ``"SLUG_CONFLICT"`` code, so callers that match on
    ``str(exc) == "SLUG_CONFLICT"`` keep working. ``conflicting_name`` is
    the display name of the row that already holds the slug; it differs
    from the requested name when two distinct, long names truncate to the
    same 64-character slug (or differ only in case/punctuation).
    """

    def __init__(self, conflicting_name: str | None = None) -> None:
        super().__init__("SLUG_CONFLICT")
        self.conflicting_name = conflicting_name


def _label_column(model: type):
    """Return the human-readable name column for a routed model.

    Protocols/projects/runs/experiments expose ``name``; documents use
    ``title``. Returns ``None`` when neither exists, in which case the
    conflict message simply omits the existing row's name.
    """
    for attr in ("name", "title"):
        col = getattr(model, attr, None)
        if col is not None:
            return col
    return None


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

    Raises `SlugConflictError` (a `ValueError` stringifying to
    `"SLUG_CONFLICT"`) when the slugified name is already taken by another
    row in the same scope, or `ValueError("SLUG_RESERVED")` when it would
    shadow a route segment.
    """
    base = slugify(name) or f"untitled-{secrets.token_hex(3)}"
    if base in RESERVED_SLUGS:
        raise ValueError("SLUG_RESERVED")
    label_col = _label_column(model)
    columns = [model.id]
    if label_col is not None:
        columns.append(label_col.label("conflict_name"))
    stmt = select(*columns).where(scope_attr == scope_value, model.slug == base)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    row = (await db.execute(stmt)).first()
    if row is not None:
        raise SlugConflictError(
            conflicting_name=getattr(row, "conflict_name", None)
        )
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

    Wraps assign_slug: on a SLUG_CONFLICT or SLUG_RESERVED ValueError,
    raises the standard HTTP 422; any other ValueError propagates.
    """
    try:
        return await assign_slug(
            db, model, scope_attr, scope_value, name, exclude_id=exclude_id
        )
    except SlugConflictError as exc:
        raise slug_conflict_error(
            entity_label, name, conflicting_name=exc.conflicting_name
        )
    except ValueError as exc:
        if str(exc) == "SLUG_RESERVED":
            raise slug_conflict_error(entity_label, name, reserved=True)
        raise


def slug_conflict_error(
    entity_label: str,
    name: str | None = None,
    *,
    reserved: bool = False,
    conflicting_name: str | None = None,
) -> HTTPException:
    """Build the standard HTTP 422 for a slug collision or reserved name.

    entity_label is the lowercase singular noun ("protocol", "project", ...).
    Set `reserved=True` when the name slugifies to a reserved route segment
    rather than colliding with an existing row.
    `conflicting_name`, when supplied and different from `name`, means two
    distinct names reduced to the same URL slug (e.g. long names sharing a
    64-char prefix, or names differing only in case/punctuation); the
    message then names the existing row so the user understands it is a
    URL collision, not a duplicate name.
    The error code stays SLUG_CONFLICT in every case so the frontend
    matches on one code.
    """
    if reserved:
        if name:
            message = (
                f"'{name}' is a reserved name — please choose a different "
                f"name for this {entity_label}."
            )
        else:
            message = (
                f"That name is reserved — please choose a different name "
                f"for this {entity_label}."
            )
    elif conflicting_name and name and conflicting_name != name:
        message = (
            f"The name '{name}' produces the same URL as the existing "
            f"{entity_label} '{conflicting_name}'. Please choose a more "
            f"distinct name."
        )
    elif name:
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


def is_slug_conflict(exc: IntegrityError) -> bool:
    """True when an IntegrityError is a per-scope slug-uniqueness violation.

    The asyncpg driver error is carried on `exc.orig`. We prefer the
    structured `constraint_name` when present and fall back to scanning the
    error text, since the driver does not always populate the attribute.
    """
    orig = getattr(exc, "orig", None)
    constraint = getattr(orig, "constraint_name", None)
    if constraint in SLUG_UNIQUE_CONSTRAINTS:
        return True
    text = str(orig) if orig is not None else str(exc)
    return any(name in text for name in SLUG_UNIQUE_CONSTRAINTS)
