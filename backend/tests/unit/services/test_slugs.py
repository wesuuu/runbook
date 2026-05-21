"""Tests for the assign_slug DB uniqueness helper."""

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.iam import Organization
from app.models.projects import Project
from app.services.slugs import (
    SlugConflictError,
    assign_slug,
    assign_slug_or_422,
    is_slug_conflict,
)

# ---------------------------------------------------------------------------
# Local fixtures — inline org/project factories scoped to this test module.
# We don't use `test_org` / `test_project` from conftest because those are
# shared singletons; these tests need independent orgs to test cross-scope
# isolation.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def org_factory(db_session):
    """Return an async callable that creates a fresh Organization."""

    async def _make(**kwargs):
        org = Organization(name=kwargs.get("name", f"org-{uuid.uuid4().hex[:8]}"))
        db_session.add(org)
        await db_session.flush()
        return org

    return _make


@pytest_asyncio.fixture
async def project_factory(db_session):
    """Return an async callable that creates a minimal Project row."""

    async def _make(*, organization_id, name, slug, **kwargs):
        proj = Project(
            name=name,
            slug=slug,
            organization_id=organization_id,
            settings={},
        )
        for k, v in kwargs.items():
            setattr(proj, k, v)
        db_session.add(proj)
        await db_session.flush()
        return proj

    return _make


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_slug_returns_slugified_name(db_session, org_factory):
    org = await org_factory()
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org.id, "Buffer Prep"
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_raises_on_collision(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    await project_factory(
        organization_id=org.id, name="Buffer Prep", slug="buffer-prep"
    )
    with pytest.raises(ValueError, match="SLUG_CONFLICT"):
        await assign_slug(
            db_session, Project, Project.organization_id, org.id, "buffer prep"
        )


@pytest.mark.asyncio
async def test_assign_slug_allows_same_name_in_a_different_scope(
    db_session, org_factory, project_factory
):
    org_a = await org_factory()
    org_b = await org_factory()
    await project_factory(
        organization_id=org_a.id, name="Buffer Prep", slug="buffer-prep"
    )
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org_b.id, "Buffer Prep"
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_excludes_self_on_rename(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    proj = await project_factory(
        organization_id=org.id, name="Buffer Prep", slug="buffer-prep"
    )
    # Renaming to a slug it already owns must not raise.
    slug = await assign_slug(
        db_session,
        Project,
        Project.organization_id,
        org.id,
        "Buffer Prep",
        exclude_id=proj.id,
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_falls_back_for_degenerate_name(db_session, org_factory):
    org = await org_factory()
    slug = await assign_slug(
        db_session, Project, Project.organization_id, org.id, "🎉🎉"
    )
    assert slug.startswith("untitled-")


@pytest.mark.asyncio
async def test_assign_slug_or_422_returns_slug_on_success(db_session, org_factory):
    org = await org_factory()
    slug = await assign_slug_or_422(
        db_session,
        Project,
        Project.organization_id,
        org.id,
        "Buffer Prep",
        "project",
    )
    assert slug == "buffer-prep"


@pytest.mark.asyncio
async def test_assign_slug_or_422_raises_http_422_on_collision(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    await project_factory(
        organization_id=org.id, name="Buffer Prep", slug="buffer-prep"
    )
    with pytest.raises(HTTPException) as exc_info:
        await assign_slug_or_422(
            db_session,
            Project,
            Project.organization_id,
            org.id,
            "buffer prep",
            "project",
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "SLUG_CONFLICT"


# ---------------------------------------------------------------------------
# Truncation near-collisions — two distinct long names whose 64-char slugs
# coincide. The error must name the conflicting row so the message can frame
# it as a URL collision rather than a duplicate-name error (F-0091 L1).
# ---------------------------------------------------------------------------

# Both names slugify to "x" * 64: the differing suffix falls past the
# SLUG_MAX_LENGTH=64 truncation boundary.
_LONG_NAME_A = "x" * 64 + " alpha edition"
_LONG_NAME_B = "x" * 64 + " beta edition"


@pytest.mark.asyncio
async def test_assign_slug_conflict_carries_conflicting_row_name(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    await project_factory(
        organization_id=org.id, name=_LONG_NAME_A, slug="x" * 64
    )
    with pytest.raises(SlugConflictError) as exc_info:
        await assign_slug(
            db_session, Project, Project.organization_id, org.id, _LONG_NAME_B
        )
    # The error exposes the existing row's name ...
    assert exc_info.value.conflicting_name == _LONG_NAME_A
    # ... while staying a ValueError that stringifies to the stable code.
    assert isinstance(exc_info.value, ValueError)
    assert str(exc_info.value) == "SLUG_CONFLICT"


@pytest.mark.asyncio
async def test_assign_slug_or_422_truncation_collision_message(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    await project_factory(
        organization_id=org.id, name=_LONG_NAME_A, slug="x" * 64
    )
    with pytest.raises(HTTPException) as exc_info:
        await assign_slug_or_422(
            db_session,
            Project,
            Project.organization_id,
            org.id,
            _LONG_NAME_B,
            "project",
        )
    message = exc_info.value.detail["message"]
    # Names the existing row and frames it as a shared-URL collision.
    assert _LONG_NAME_A in message
    assert "same URL" in message


@pytest.mark.asyncio
async def test_assign_slug_or_422_exact_duplicate_keeps_plain_message(
    db_session, org_factory, project_factory
):
    org = await org_factory()
    await project_factory(
        organization_id=org.id, name="Buffer Prep", slug="buffer-prep"
    )
    with pytest.raises(HTTPException) as exc_info:
        await assign_slug_or_422(
            db_session,
            Project,
            Project.organization_id,
            org.id,
            "Buffer Prep",
            "project",
        )
    # An identical name keeps the plain "already exists" wording.
    assert "already exists" in exc_info.value.detail["message"]


# ---------------------------------------------------------------------------
# is_slug_conflict — recognises a raced unique-constraint violation
# ---------------------------------------------------------------------------


class _FakeOrig:
    """Stand-in for an asyncpg driver error carried on IntegrityError.orig."""

    def __init__(self, constraint_name=None, text=""):
        if constraint_name is not None:
            self.constraint_name = constraint_name
        self._text = text

    def __str__(self):
        return self._text


def _integrity_error(constraint_name=None, text=""):
    return IntegrityError("INSERT ...", {}, _FakeOrig(constraint_name, text))


def test_is_slug_conflict_true_for_slug_constraint_name():
    for name in (
        "uq_protocols_owner_org_slug",
        "uq_projects_org_slug",
        "uq_runs_project_slug",
        "uq_experiments_project_slug",
        "uq_documents_org_slug",
    ):
        assert is_slug_conflict(_integrity_error(constraint_name=name)) is True


def test_is_slug_conflict_false_for_unrelated_constraint():
    exc = _integrity_error(constraint_name="fk_projects_organization_id")
    assert is_slug_conflict(exc) is False


def test_is_slug_conflict_falls_back_to_error_text():
    # asyncpg does not always populate constraint_name on the wrapped error.
    exc = _integrity_error(
        text='duplicate key value violates unique constraint '
        '"uq_runs_project_slug"'
    )
    assert is_slug_conflict(exc) is True


def test_is_slug_conflict_false_for_unrelated_error_text():
    exc = _integrity_error(text="null value in column violates not-null")
    assert is_slug_conflict(exc) is False


# ---------------------------------------------------------------------------
# Reserved slugs — a name slugifying to a route segment is rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_slug_rejects_a_reserved_name(db_session, org_factory):
    org = await org_factory()
    with pytest.raises(ValueError, match="SLUG_RESERVED"):
        await assign_slug(
            db_session, Project, Project.organization_id, org.id, "Projects"
        )


@pytest.mark.asyncio
async def test_assign_slug_or_422_reserved_name_returns_422(
    db_session, org_factory
):
    org = await org_factory()
    with pytest.raises(HTTPException) as exc_info:
        await assign_slug_or_422(
            db_session,
            Project,
            Project.organization_id,
            org.id,
            "New",
            "project",
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "SLUG_CONFLICT"
